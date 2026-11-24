"""Which stock OS a run is for, and its addresses (docs/os112-port.md).

Scripts and the gate are written in 1.11's addresses. `A(x)` gives the address on the OS this run
is for: `x` itself on 1.11, its translation on 1.12. The OS is `DN2_OS` ("1.11", the default, or
"1.12"). A literal only goes through `A` where its 1.12 address differs, and `A` refuses an address
it cannot place, so a script can never read the wrong place quietly.
"""
from __future__ import annotations

import functools
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
CACHE = ROOT / "out" / "osport" / "map112.json"
OSES = ("1.11", "1.12")


def current() -> str:
    v = os.environ.get("DN2_OS", "1.11")
    if v not in OSES:
        raise SystemExit(f"DN2_OS={v!r}: not one of {OSES}")
    return v


def stock_syx(osv: str | None = None) -> pathlib.Path:
    return ROOT.parent / f"Digitone_II_OS{osv or current()}.syx"


@functools.lru_cache(maxsize=1)
def _table() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return {}


def _save(t: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(t, indent=0, sort_keys=True))
    tmp.replace(CACHE)


def to112(x: int) -> int:
    if 0x46700000 <= x < 0x48000000 or x < 0x40000400:
        return x                    # our own RAM (the area's chunks, buffers), and below MAIN OS
    t = _table()
    k = f"{x:#010x}"
    if k not in t:
        from .addrmap import default
        nv, why = default().map(x)
        if nv is None:
            raise ValueError(f"{x:#x} has no 1.12 address: {why}")
        t[k] = nv
        _save(t)
    return t[k]


ISSUED: set[int] = set()


def A(x: int) -> int:
    """a 1.11 address on the OS of this run"""
    if current() == "1.11":
        return x
    v = to112(x)
    ISSUED.add(v)
    return v


def audit_unicorn() -> None:
    """On 1.12, refuse a code hook at an address that did not come from `A` and where 1.11 and 1.12
    hold different code: a 1.11 address a script forgot to translate. (Same code at the same
    address in both, before 1.12's first change, needs no translation.)"""
    if current() == "1.11":
        return
    import unicorn
    if getattr(unicorn.Uc, "_dnfw_audited", False):
        return
    main11 = (ROOT.parent / "sec111" / "section_3_MAIN_OS.bin").read_bytes()
    main12 = (ROOT.parent / "sec112" / "section_3_MAIN_OS.bin").read_bytes()
    base = 0x40000400
    orig = unicorn.Uc.hook_add

    def hook_add(self, htype, callback, user_data=None, begin=1, end=0, *a, **k):
        import sys as _sys
        caller = _sys._getframe(1).f_code.co_filename
        ours = "/scripts/" in caller.replace("\\", "/") or "/src/dnfw/" in caller.replace("\\", "/")
        if (ours and htype & unicorn.UC_HOOK_CODE and begin == end
                and base <= begin < base + len(main12)):
            # (digikit's own hooks, e.g. its instruction patches, come from scanning the image
            # it runs: 1.12's addresses already; only a hook our scripts set is judged)
            o = begin - base
            if begin not in ISSUED and main11[o:o + 6] != main12[o:o + 6]:
                import traceback
                where = "".join(traceback.format_stack(limit=6)[:-1])
                raise SystemExit(f"osport audit: a code hook at {begin:#x}, not from A() and not "
                                 f"the same code in 1.11 and 1.12: an untranslated 1.11 address\n{where}")
        return orig(self, htype, callback, user_data, begin, end, *a, **k)

    unicorn.Uc.hook_add = hook_add
    unicorn.Uc._dnfw_audited = True
