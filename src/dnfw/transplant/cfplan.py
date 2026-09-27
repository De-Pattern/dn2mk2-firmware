"""Check two user-supplied MAIN OS images against a `CfSpec`, and compose the pieces.

    plan = build(SPEC, donor_main_os, recipient_main_os)
    plan.ok, plan.refusals
    plan.report()                         # addresses, digests, twins: no donor bytes
    plan.strings()                        # [(key, text)]: donor strings, in memory only
    plan.records(page=..., ordinals=..., string_va=...)   # the recipient's records
    plan.descriptor(entry_of=..., rep_va=...)             # the page, as the recipient builds it

`build` refuses -- it never patches around a mismatch -- when the donor is not
the MAIN OS the spec was measured on (SHA-256 of the whole section), when a
record run, the page initializer or the name row does not hash or read as
recorded, or when a formatter twin is not the same function in both images
(bytes equal outside the named operands; each operand checked on its terms).

Only `strings()`, `records()` and the descriptor carry donor-derived bytes, and
they exist only in memory, at apply time.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field

from . import cfspec as C

BASE = 0x40000400
MAX_STRING = 64


@dataclass
class CfPlan:
    spec: C.CfSpec
    donor: bytes
    recipient: bytes
    refusals: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.refusals

    # -- reading ----------------------------------------------------------------------------
    def _d(self, va: int, n: int) -> bytes:
        return _read(self.donor, va, n)

    def _r(self, va: int, n: int) -> bytes:
        return _read(self.recipient, va, n)

    def donor_record(self, k: int) -> bytes:
        run = self.spec.records
        return self._d(run.donor + C.RECORD * k, C.RECORD)

    def donor_string(self, va: int) -> str:
        return _string(self.donor, va)

    # -- what the recipient receives --------------------------------------------------------
    def strings(self) -> list[tuple[str, str]]:
        """Every donor string the records, the page and the name row point at, keyed by
        where it is used. In memory only: these are the donor's bytes."""
        self._require()
        out, seen = [], set()

        def add(key: str, va: int) -> None:
            if key not in seen:
                seen.add(key)
                out.append((key, self.donor_string(va)))

        for k in range(self.spec.records.count):
            rec = self.donor_record(k)
            for off, what in ((C.LONG_NAME, "long"), (C.PAGE_LABEL, "page"), (C.SHORT_NAME, "short")):
                add(f"record{k}.{what}", _u32(rec, off))
        add("page.title", self.spec.page.title)
        add("page.subtitle", self.spec.page.subtitle)
        row = self.spec.machine_name.donor_row
        add("machine.long", _u32(self._d(row, 4), 0))
        add("machine.short", _u32(self._d(row + 4, 4), 0))
        return out

    def records(self, *, page: int, ordinals: list[int], string_va: dict[str, int]) -> bytes:
        """The donor's records, relocated for the recipient: its page id, fresh ordinals,
        the recipient's twin formatters, copied strings, no CC or NRPN."""
        self._require()
        run = self.spec.records
        if len(ordinals) != run.count:
            raise ValueError(f"{run.count} ordinals wanted, {len(ordinals)} given")
        fixed = {f.donor: f.recipient for f in self.spec.fixed}
        out = b""
        for k in range(run.count):
            rec = bytearray(self.donor_record(k))
            struct.pack_into(">I", rec, C.PAGE, page)
            struct.pack_into(">I", rec, C.CC, C.UNSET)
            struct.pack_into(">I", rec, C.NRPN, C.UNSET)
            struct.pack_into(">I", rec, C.ORDINAL, ordinals[k])
            for off, what in ((C.LONG_NAME, "long"), (C.PAGE_LABEL, "page"), (C.SHORT_NAME, "short")):
                struct.pack_into(">I", rec, off, string_va[f"record{k}.{what}"])
            twin = self.spec.formatter(self.spec.record_formatters[k])
            struct.pack_into(">I", rec, C.FORMATTER, twin.recipient)
            struct.pack_into(">I", rec, C.SUFFIX, fixed[_u32(rec, C.SUFFIX)])
            out += bytes(rec)
        return out

    def page_entries(self, entry_of: dict[int, int]) -> list[int]:
        """The page's eight knob entries in the recipient's numbering (0 stays 0)."""
        return [entry_of[e] if e else 0 for e in self.spec.page.entries]

    def report(self) -> dict:
        s = self.spec
        return {
            "spec": s.name, "ok": self.ok, "refusals": list(self.refusals),
            "checks": list(self.checks),
            "donor_guard": vars(s.donor) if hasattr(s.donor, "__dict__") else str(s.donor),
            "records": {"donor": f"{s.records.donor:#010x}", "count": s.records.count,
                        "donor_entries": [s.records.donor_entry + k for k in range(s.records.count)],
                        "sha256": s.records.sha256, "labels": list(s.records.labels),
                        "whose": "the user's donor file, read at apply time; never committed"},
            "formatters": [{"name": f.name, "donor": f"{f.donor:#010x}",
                            "recipient": f"{f.recipient:#010x}", "length": f.length,
                            "operands": [list(o) for o in f.operands]} for f in s.formatters],
            "page": {"initializer": f"{s.page.init_start:#010x}+{s.page.init_length:#x}",
                     "sha256": s.page.sha256, "donor_entries": list(s.page.entries), "tag": s.page.tag},
            "machine_name": {"row": f"{s.machine_name.donor_row:#010x}",
                             "names_sha256": s.machine_name.names_sha256},
            "notes": list(s.notes),
        }

    def _require(self) -> None:
        if not self.ok:
            raise ValueError("refused: " + "; ".join(self.refusals))


def build(spec: C.CfSpec, donor_main_os: bytes, recipient_main_os: bytes) -> CfPlan:
    plan = CfPlan(spec, donor_main_os, recipient_main_os)
    digest = hashlib.sha256(donor_main_os).hexdigest()
    if digest != spec.donor.section3_sha256:
        plan.refusals.append(f"donor MAIN OS hashes to {digest[:12]}..., not "
                             f"{spec.donor.section3_sha256[:12]}... ({spec.donor.device} "
                             f"{spec.donor.version} only)")
        return plan
    plan.checks.append(f"donor MAIN OS is {spec.donor.device} {spec.donor.version}")
    _check_records(plan)
    _check_page(plan)
    _check_name_row(plan)
    for f in spec.formatters:
        _check_twin(plan, f)
    for f in spec.fixed:
        a, b = _string(plan.donor, f.donor), _string(plan.recipient, f.recipient)
        if a != f.text or b != f.text:
            plan.refusals.append(f"{f.name}: donor {a!r} / recipient {b!r}, not {f.text!r}")
    return plan


def _check_records(plan: CfPlan) -> None:
    run = plan.spec.records
    data = plan._d(run.donor, C.RECORD * run.count)
    digest = hashlib.sha256(data).hexdigest()
    if digest != run.sha256:
        plan.refusals.append(f"records {run.name}: {digest[:12]}..., not {run.sha256[:12]}...")
        return
    shorts = tuple(_string(plan.donor, _u32(data, C.RECORD * k + C.SHORT_NAME))
                   for k in range(run.count))
    if _names_sha(shorts) != run.shorts_sha256:
        plan.refusals.append(f"records {run.name}: their short names are not the recorded ones")
        return
    if len(plan.spec.record_formatters) != run.count:
        plan.refusals.append("one formatter per record is wanted")
        return
    for k in range(run.count):
        fmt = _u32(data, C.RECORD * k + C.FORMATTER)
        want = plan.spec.formatter(plan.spec.record_formatters[k]).donor
        if fmt != want:
            plan.refusals.append(f"record {run.labels[k]}: formatter {fmt:#010x}, not {want:#010x}")
    plan.checks.append(f"{run.count} records {run.name} ({', '.join(run.labels)}) hash as recorded")


def _check_page(plan: CfPlan) -> None:
    p = plan.spec.page
    digest = hashlib.sha256(plan._d(p.init_start, p.init_length)).hexdigest()
    if digest != p.sha256:
        plan.refusals.append(f"page {p.name}: its initializer hashes {digest[:12]}..., not {p.sha256[:12]}...")
        return
    if _names_sha((_string(plan.donor, p.title), _string(plan.donor, p.subtitle))) != p.names_sha256:
        plan.refusals.append(f"page {p.name}: its title strings are not the recorded ones")
        return
    plan.checks.append(f"page {p.name}: initializer and title strings as recorded "
                       f"(entries {list(p.entries)}, tag {p.tag})")


def _check_name_row(plan: CfPlan) -> None:
    n = plan.spec.machine_name
    row = plan._d(n.donor_row, 8)
    got = (_string(plan.donor, _u32(row, 0)), _string(plan.donor, _u32(row, 4)))
    if _names_sha(got) != n.names_sha256:
        plan.refusals.append(f"machine name row {n.donor_row:#010x}: not the recorded names")
    else:
        plan.checks.append(f"machine name row {n.donor_row:#010x}: as recorded")


def _check_twin(plan: CfPlan, f: C.FormatterTwin) -> None:
    a, b = plan._d(f.donor, f.length), plan._r(f.recipient, f.length)
    covered = set()
    for off, kind in f.operands:
        width = 2 if kind == "rel16" else 4
        covered.update(range(off, off + width))
        va, vb = struct.unpack_from(">I", a, off)[0], struct.unpack_from(">I", b, off)[0]
        if kind == "str32":
            sa, sb = _string(plan.donor, va), _string(plan.recipient, vb)
            if sa is None or sa != sb:
                plan.refusals.append(f"formatter {f.name} +{off}: donor {sa!r}, recipient {sb!r}")
                return
        elif kind == "code32":
            if va != vb:
                plan.refusals.append(f"formatter {f.name} +{off}: calls {va:#x} and {vb:#x}")
                return
        elif kind.startswith("call32:"):
            n = int(kind.split(":")[1])
            if plan._d(va, n) != plan._r(vb, n):
                plan.refusals.append(f"formatter {f.name} +{off}: its callees {va:#x} / {vb:#x} differ")
                return
        else:
            plan.refusals.append(f"formatter {f.name}: unknown operand kind {kind!r}")
            return
    for i in range(f.length):
        if i not in covered and a[i] != b[i]:
            plan.refusals.append(f"formatter {f.name}: {f.donor:#010x} and {f.recipient:#010x} "
                                 f"differ at +{i} outside the named operands")
            return
    plan.checks.append(f"formatter {f.name}: donor {f.donor:#010x} == recipient {f.recipient:#010x} "
                       f"({f.length} B, {len(f.operands)} operand(s))")


def _names_sha(names) -> str:
    return hashlib.sha256("\0".join(n or "" for n in names).encode()).hexdigest()


def _read(image: bytes, va: int, n: int) -> bytes:
    at = va - BASE
    if at < 0 or at + n > len(image):
        raise ValueError(f"{va:#010x}+{n} is outside the image")
    return bytes(image[at:at + n])


def _u32(blob: bytes, off: int) -> int:
    return struct.unpack_from(">I", blob, off)[0]


def _string(image: bytes, va: int) -> str | None:
    at = va - BASE
    if at < 0 or at >= len(image):
        return None
    end = image.find(b"\0", at, at + MAX_STRING)
    if end < 0:
        return None
    text = image[at:end]
    if any(c < 0x20 or c > 0x7E for c in text):
        return None
    return text.decode("ascii")
