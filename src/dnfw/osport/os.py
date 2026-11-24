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


def A(x: int) -> int:
    """a 1.11 address on the OS of this run"""
    return x if current() == "1.11" else to112(x)
