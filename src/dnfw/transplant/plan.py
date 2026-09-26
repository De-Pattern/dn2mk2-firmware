"""Check two user-supplied images against a `Spec` and produce the transplant.

    plan = build(SPEC, donor_raw, recipient_raw)
    plan.ok, plan.refusals        # why not, if not
    plan.report()                 # hashes, guards, relocations: no donor bytes
    plan.blocks()                 # the relocated spans, for the recipient's stream

`build` refuses -- it never patches around a mismatch -- when:

- the donor or the recipient is not the device, product code and OS version
  the spec was measured on, or its section 7 does not hash to the recorded
  SHA-256 (a different OS build, a modified file, the wrong file);
- a span of the donor does not hash to its recorded digest;
- a relocation site does not hold the address the spec says it holds;
- a relocated relative transfer no longer fits its field;
- the recipient's boot stream loads any byte a span would land on.

`report()` is safe to write anywhere: it carries addresses, sizes, digests and
relocated field values, never a donor byte. `blocks()` carries donor bytes
and exists only in memory, at apply time.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from ..firmware.load import load
from ..image import bootstream
from . import sharc
from .spec import Guard, Spec


@dataclass
class Plan:
    spec: Spec
    refusals: list[str] = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    relocations: list[dict] = field(default_factory=list)
    _payloads: dict[str, bytes] = field(default_factory=dict, repr=False)

    @property
    def ok(self) -> bool:
        return not self.refusals

    def report(self) -> dict:
        """Everything about the plan except the donor's bytes."""
        s = self.spec
        return {
            "spec": s.name,
            "ok": self.ok,
            "refusals": list(self.refusals),
            "donor_guard": _guard_dict(s.donor),
            "recipient_guard": _guard_dict(s.recipient),
            "images": self.facts,
            "spans": [{
                "name": sp.name, "kind": sp.kind, "what": sp.what,
                "donor": _addr(sp.kind, sp.donor), "donor_window": sp.window if sp.kind == "code" else None,
                "size": sp.size, "unit": "parcels" if sp.kind == "code" else "bytes", "bytes": sp.nbytes,
                "recipient": _addr(sp.kind, sp.recipient),
                "sha256": sp.sha256,
                "whose": "the user's donor file, read at apply time; never committed",
            } for sp in s.spans],
            "relocations": list(self.relocations),
            "donor_bytes_moved": sum(sp.nbytes for sp in s.spans),
            "notes": list(s.notes),
        }

    def blocks(self) -> list[tuple[int, bytes]]:
        """(recipient loader address, relocated bytes) per span. Donor bytes: in memory only."""
        if not self.ok:
            raise ValueError("refused: " + "; ".join(self.refusals))
        out = []
        for sp in self.spec.spans:
            at = (sharc.code_address(sp.recipient) if sp.kind == "code"
                  else sharc.data_address(sp.recipient))
            out.append((at, self._payloads[sp.name]))
        return out

    def recipient_sw(self, donor_sw: int, span: str | None = None) -> int:
        """Where a donor code address lands (for callers and tests)."""
        for sp in self.spec.spans:
            if sp.kind == "code" and (span is None or sp.name == span) and sp.contains(donor_sw):
                return sp.moved(donor_sw)
        raise ValueError(f"{donor_sw:#x} is not inside a moved code span")


def build(spec: Spec, donor_raw: bytes, recipient_raw: bytes) -> Plan:
    """Check both images against SPEC and relocate every span (in memory)."""
    plan = Plan(spec)
    donor7 = _section7(plan, "donor", spec.donor, donor_raw)
    recip7 = _section7(plan, "recipient", spec.recipient, recipient_raw)
    if donor7 is None or recip7 is None:
        return plan

    for sp in spec.spans:
        try:
            data = bootstream.read_span(donor7, _donor_address(sp), sp.nbytes)
        except bootstream.SpanError as error:
            plan.refusals.append(f"donor span {sp.name}: {error}")
            continue
        digest = hashlib.sha256(data).hexdigest()
        if digest != sp.sha256:
            plan.refusals.append(f"donor span {sp.name} at {_addr(sp.kind, sp.donor)} hashes to "
                                 f"{digest[:12]}..., not {sp.sha256[:12]}...")
            continue
        plan._payloads[sp.name] = data
        at = sharc.code_address(sp.recipient) if sp.kind == "code" else sharc.data_address(sp.recipient)
        loaded = loaded_bytes(recip7, at, sp.nbytes)
        if loaded:
            plan.refusals.append(f"recipient span for {sp.name} at {at:#x}+{sp.nbytes:#x} "
                                 f"is loaded by the recipient's boot stream ({loaded} bytes)")
    if plan.refusals:
        return plan

    for site in spec.sites:
        _relocate(plan, site)
    return plan


def loaded_bytes(stream: bytes, address: int, length: int) -> int:
    """How many bytes of [address, address+length) any block of STREAM loads (fills included)."""
    total = 0
    for blk in bootstream.walk(stream).blocks:
        if not blk.count:
            continue
        lo, hi = max(address, blk.target), min(address + length, blk.target + blk.count)
        total += max(0, hi - lo)
    return total


def _relocate(plan: Plan, site) -> None:
    spec = plan.spec
    span = spec.span(site.span)
    if span.kind != "code" or not span.contains(site.sw):
        plan.refusals.append(f"site {site.sw:#x} is not inside code span {site.span}")
        return
    target = spec.span(site.refers_to)
    payload = bytearray(plan._payloads[span.name])
    off = 2 * (site.sw - span.donor)
    value = sharc.to_value(bytes(payload[off:off + sharc.INSTRUCTION_BYTES]))
    held = sharc.target_of(value, site.field, site.sw)
    if held != site.donor_target:
        plan.refusals.append(f"site {site.sw:#x} ({site.form}) holds {held:#x}, "
                             f"not {site.donor_target:#x}")
        return
    new_sw = span.moved(site.sw)
    new_target = target.moved(site.donor_target)
    try:
        new_value = sharc.retarget(value, site.field, new_sw, new_target)
    except ValueError as error:
        plan.refusals.append(f"site {site.sw:#x}: {error}")
        return
    payload[off:off + sharc.INSTRUCTION_BYTES] = sharc.to_bytes(new_value)
    plan._payloads[span.name] = bytes(payload)
    plan.relocations.append({
        "span": span.name, "donor_sw": f"{site.sw:#x}", "recipient_sw": f"{new_sw:#x}",
        "form": site.form, "field": site.field, "what": site.what,
        "donor_target": _addr(target.kind, site.donor_target),
        "recipient_target": _addr(target.kind, new_target),
        "field_before": f"{sharc.get_field(value, site.field) & 0xFFFFFFFF:#x}",
        "field_after": f"{sharc.get_field(new_value, site.field) & 0xFFFFFFFF:#x}",
    })


def _section7(plan: Plan, role: str, guard: Guard, raw: bytes) -> bytes | None:
    try:
        fw = load(raw)
    except (ValueError, KeyError) as error:
        plan.refusals.append(f"{role}: not a firmware image dnfw can read ({error})")
        return None
    c = fw.container
    section = c.find(7)
    data = (section.unpack() or section.raw_payload) if section is not None else None
    digest = hashlib.sha256(data).hexdigest() if data is not None else None
    plan.facts[role] = {"product": c.product, "version": c.version, "section7_sha256": digest}
    if c.product != guard.product:
        plan.refusals.append(f"{role}: product code {c.product}, not {guard.product} ({guard.device})")
    if c.version != guard.version:
        plan.refusals.append(f"{role}: OS {c.version}, not {guard.version}; this transplant was "
                             f"measured on {guard.device} {guard.version} only")
    if digest != guard.section7_sha256:
        plan.refusals.append(f"{role}: section 7 hashes to {str(digest)[:12]}..., not "
                             f"{guard.section7_sha256[:12]}...")
    return data if not plan.refusals else None


def _donor_address(sp) -> int:
    return sharc.code_address(sp.donor, sp.window) if sp.kind == "code" else sharc.data_address(sp.donor)


def _addr(kind: str, value: int) -> str:
    return f"sw {value:#x}" if kind == "code" else f"DM {value:#x}"


def _guard_dict(g: Guard) -> dict:
    return {"device": g.device, "product": g.product, "version": g.version,
            "section7_sha256": g.section7_sha256}
