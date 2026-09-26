"""Which mods combine: every pair, tried rather than argued.

For each pair, in both orders, three questions with checkable answers:

1. **Bytes** -- do the extents the two mods declare overlap (`check_compatible`)?
2. **Apply** -- does the second mod accept the image the first one produced?
   Every mod guards the stock bytes it replaces and the section length it
   expects, so a mod that would silently land on another's work refuses here.
3. **Order** -- if one order applies and the other does not, the pair combines
   only in the order the CLI uses (`APPLY_LAST`). A mod that copies part of
   the image (`COPIES`, lfo4's parameter table) also makes a pair order-only
   when the other mod edits what it copies: applied after it, that edit still
   finds its stock bytes, applies cleanly, and lands on a copy nothing reads.

What this cannot see is a **functional** clash: two mods that write disjoint
bytes and still fight over one feature. Those are recorded by hand in
`NOTES`, each with its evidence, and a pair carries its note alongside
whatever the tooling says. Nor is any of this a hardware result -- no combined
image has been flashed -- which `docs/mods-compatibility.md` states beside the
table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from . import ModError, check_compatible

# Functional findings the byte check cannot make, by unordered pair.
NOTES: dict[frozenset, str] = {
    frozenset(("arpplocks", "bootscreen")):
        "bootscreen reserves 0x380 bytes at 0x402dfa1c for its code and refuses if any is "
        "used; its code is 366 bytes and ends 2 bytes before arpplocks' cave at 0x402dfb8c, "
        "so bootscreen first then arpplocks writes disjoint bytes. Whether bootscreen uses "
        "the rest of its reservation at run time is not measured.",
    frozenset(("fxmod", "lfo4")):
        "emulator, 2026-09-26: the LFO4 slot harness and a turn of all eight LFO4 dials match "
        "lfo4 alone; fxmod's DEST checks and names match fxmod alone; every LFO page, LFO4's "
        "included, gains the same 24 FX destinations. The hooks are on different paths "
        "(fxmod's slot lookup at 0x400dc02a is asked above slot 100 only while the DEST list "
        "is built). Not exercised: LFO4 aimed at an FX destination. fxmod's own helper at "
        "0x4028ea02 keeps the stock table bounds, so it would answer LFO4's own entries with "
        "-1; it is only ever called with destination entries.",
    frozenset(("lfo4", "moddest")):
        "measured: with moddest applied first, all 13 masks it opens are in lfo4's "
        "relocated table (test/test_lfo4_mod.py).",
}


@dataclass
class Pair:
    a: str
    b: str
    overlaps: list[str] = field(default_factory=list)
    refused: dict[str, str] = field(default_factory=dict)     # "a+b" -> why
    note: str = ""
    must_precede: str = ""                                    # "x before y", from COPIES

    @property
    def combines(self) -> bool:
        return not self.overlaps and len(self.refused) < 2

    @property
    def order_only(self) -> bool:
        return not self.overlaps and (len(self.refused) == 1 or bool(self.must_precede))

    def reason(self) -> str:
        if self.overlaps:
            return self.overlaps[0]
        if len(self.refused) == 2:
            return next(iter(self.refused.values()))
        if self.refused:
            return next(iter(self.refused.values()))
        return self.must_precede


def _extents(mod, firmware):
    try:
        return list(mod.extents(firmware))
    except TypeError:
        return list(mod.extents())


def pairs(firmware, registry: dict, apply_one, stage) -> list[Pair]:
    """-> one `Pair` per unordered pair of `registry`.

    `apply_one(mod, firmware) -> Result` supplies each mod's inputs (samples,
    images) -- the caller's business, since it may touch files. `stage(firmware,
    payloads)` returns the image with earlier payloads standing in.
    """
    out = []
    for a_id, b_id in combinations(sorted(registry), 2):
        a, b = registry[a_id], registry[b_id]
        pair = Pair(a_id, b_id, note=NOTES.get(frozenset((a_id, b_id)), ""))
        pair.overlaps = check_compatible([(a_id, _extents(a, firmware)),
                                          (b_id, _extents(b, firmware))])
        for copier, other in ((a, b), (b, a)):
            copied = getattr(copier, "COPIES", [])
            if any(c.overlaps(e) for c in copied for e in _extents(other, firmware)):
                pair.must_precede = (f"{other.ID} edits what {copier.ID} copies, so it must be "
                                     f"applied first (the CLI applies {copier.ID} last)")
        for first, second in ((a, b), (b, a)):
            try:
                payloads = dict(apply_one(first, firmware).payloads)
                payloads.update(apply_one(second, stage(firmware, payloads)).payloads)
            except ModError as exc:
                pair.refused[f"{first.ID}+{second.ID}"] = f"{second.ID} refuses after {first.ID}: {exc}"
        out.append(pair)
    return out


# -- rendering: the table on the page and in the docs is generated, never kept

MARK = {"yes": "&#10003;", "order": "&#10003;*", "NO": "&#10007;"}


def cell(pair: Pair) -> str:
    return "NO" if not pair.combines else ("order" if pair.order_only else "yes")


def _short(pair: Pair) -> str:
    """Why a pair is refused or ordered, in one clause a reader can use."""
    why = pair.reason()
    if "0x0000013f" in why:
        return "both need the start-up hook and the appended area"
    if "both write" in why:
        return "both use the same code cave"
    if "must be applied first" in why:
        return why.split(" (")[0]
    if "boot-screen code space" in why:
        return "bootscreen must be applied first"
    if "candidate parameter tables" in why:
        return "moddest must be applied first"
    return why


def combines_text(mod_id: str, found: list[Pair], names: dict[str, str]) -> str:
    """One card's 'Combines' line, from the matrix."""
    ok, ordered, no = [], [], []
    for p in found:
        if mod_id not in (p.a, p.b):
            continue
        other = p.b if p.a == mod_id else p.a
        kind = cell(p)
        (ok if kind == "yes" else ordered if kind == "order" else no).append((names[other], _short(p)))
    parts = []
    if ok:
        parts.append("With " + ", ".join(n for n, _ in ok))
    if ordered:
        parts.append("in one order only with " + "; ".join(f"{n} ({why})" for n, why in ordered))
    if no:
        parts.append("<strong>not</strong> with " + "; ".join(f"{n} ({why})" for n, why in no))
    return "; ".join(parts) + ". See the compatibility table"


def table_html(ids: list[str], found: list[Pair], names: dict[str, str]) -> str:
    by = {}
    for p in found:
        by[(p.a, p.b)] = by[(p.b, p.a)] = p
    head = "".join(f'<th scope="col"><code>{m}</code></th>' for m in ids)
    rows = []
    for a in ids:
        cells = []
        for b in ids:
            if a == b:
                cells.append('<td class="mx-self">&mdash;</td>')
                continue
            p = by[(a, b)]
            kind = cell(p)
            title = _short(p) if kind != "yes" else "disjoint bytes; applies in either order"
            cells.append(f'<td class="mx-{kind.lower()}" title="{title}">{MARK[kind]}</td>')
        rows.append(f'<tr><th scope="row">{names[a]} <code>{a}</code></th>{"".join(cells)}</tr>')
    return ('<div class="scroll">\n<table class="matrix">\n'
            f'  <thead><tr><th></th>{head}</tr></thead>\n  <tbody>\n    '
            + "\n    ".join(rows) + "\n  </tbody>\n</table>\n</div>")


def table_md(ids: list[str], found: list[Pair], names: dict[str, str]) -> str:
    by = {}
    for p in found:
        by[(p.a, p.b)] = by[(p.b, p.a)] = p
    sym = {"yes": "yes", "order": "order", "NO": "**NO**"}
    lines = ["| | " + " | ".join(f"`{m}`" for m in ids) + " |",
             "|---|" + "---|" * len(ids)]
    for a in ids:
        lines.append(f"| `{a}` | " + " | ".join("-" if a == b else sym[cell(by[(a, b)])]
                                              for b in ids) + " |")
    lines.append("")
    for p in found:
        if cell(p) != "yes" or p.note:
            lines.append(f"- **{p.a} + {p.b}: {cell(p)}**: {p.reason() or 'disjoint bytes'}."
                         + (f" *Note:* {p.note}" if p.note else ""))
    return "\n".join(lines)
