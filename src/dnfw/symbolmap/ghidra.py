"""Emitting a names manifest for `ghidra/ApplyNames.java` to apply.

Ghidra 12 runs Java scripts, not Jython, so the applier is a committed Java
script (`ghidra/ApplyNames.java`) and this module writes the *data* it reads: a
tab-separated manifest of what to name. Keeping the data out of the script means
one generic applier handles a map of any size, and the manifest -- which carries
RTTI addresses derived from the firmware -- stays a local, gitignored artefact.

Manifest lines are `kind<TAB>address<TAB>name<TAB>note`:

    function  0x80003c9c  verify_and_flash_container  dn2-...: ...
    data      0x401e29d4  parameter_table             dn2-...: ...
    rtti      0x4001ce73  rtti_11LfoPageView          (no note)

`function` creates a function if none exists and names it; `data` and `rtti`
place a label. Tabs and newlines are stripped from names and notes so each
record is exactly one line.
"""

from .build import Names


def manifest(names: Names) -> str:
    """The tab-separated names manifest `ghidra/ApplyNames.java` consumes."""
    lines = [f"# base 0x{names.base:08x}  curated {len(names.curated_ok)}  rtti {len(names.derived)}"]

    for placed in names.curated_ok:
        s = placed.symbol
        kind = "function" if s.kind == "function" else "data"
        note = _clean(f"{s.id}: {s.note}" if s.note else s.id)
        lines.append(f"{kind}\t0x{s.address:08x}\t{_clean(s.name)}\t{note}")

    for placed in names.drift:
        s = placed.symbol
        lines.append(f"# skipped {s.id} @ 0x{s.address:08x}: guard no longer matches")

    for symbol in names.derived:
        label = "rtti_" + _identifier(symbol.text)
        lines.append(f"rtti\t0x{symbol.address:08x}\t{label}\t")

    return "\n".join(lines) + "\n"


def _clean(text: str) -> str:
    return text.replace("\t", " ").replace("\n", " ").strip()


def _identifier(text: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in text)[:96]
