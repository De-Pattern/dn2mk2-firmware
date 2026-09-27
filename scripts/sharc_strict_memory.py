"""A strict ADSP-21569 memory map around digikit's SHARC runner (a wrapper; digikit is untouched).

digikit's executor models flat memory: a read of a byte the boot stream never loaded
is served (0, or the loader's bytes), and any address resolves. The silicon has four
L1 blocks of real size with gaps between them, three 16 KB caches carved from the
tops of blocks 1-3 (the startup's SHL1C_CFG, docs/waverider-dsp-silence.md), L2, DDR
and MMR windows. Milestones 1-4 put tables in the gap between L1 blocks 0 and 1 and
the runner never complained.

`install(dk, image_stream)` wraps every module-level `_dm_read`/`_dm_write` binding in
digikit's `sharc_core` (and our fixups) and the runner's instruction decode, and
records a violation, with the PC, for any access that is:

  outside    -- not in any real memory or MMR window, in any address form;
  cache      -- inside the part of an L1 block the caches own;
  misaligned -- a 2- or 4-byte access not aligned to its width;
  unwritten  -- an L1 read of a byte neither the boot stream nor any earlier write put there;
  fetch      -- an instruction fetched from outside real code memory.

The runner's own address resolution is kept (so the run is the same run); this only
observes. `report()` -> the violations, deduplicated by (kind, pc, space).
"""

from __future__ import annotations

import collections
import sys

ALIAS = 0x28000000
# byte-space L1 blocks of the ADSP-21569 (640 KB): (lo, hi, top-16K cache or None)
L1 = [(0x240000, 0x270000, None), (0x2C0000, 0x2F0000, 0x2EC000),
      (0x300000, 0x320000, 0x31C000), (0x380000, 0x3A0000, 0x39C000)]
NW = [(lo // 4, hi // 4) for lo, hi, _ in L1]              # normal-word images
SW = [(lo // 2, hi // 2) for lo, hi, _ in L1]              # short-word images
L2 = (0x20000000, 0x20100000)                              # 1 MB
DDR = (0x80000000, 0xA0000000)
MMR = [(0x30000, 0x40000), (0x31000000, 0x32000000), (0x3000000, 0x3100000)]
CODE_SW = [(0x120000, 0x138000), (0x160000, 0x178000), (0x180000, 0x190000),
           (0x1C0000, 0x1D0000), (0xB80000, 0xC00000)]     # L1 blocks in sw form, then L2 code

# The harness's own stand-ins, not firmware memory: the runner's stack grows down from
# 0x300000 (sharc_waverider_voice.STACK) and sharc_waverider_m4.UNPACK_LOCAL is a scratch
# for the caller's 10-word local. Accesses there are counted as `harness`, not flagged.
EXEMPT = [(0x2F0000, 0x300000), (0x284800, 0x284840)]

violations: list[dict] = []
counts: collections.Counter = collections.Counter()
_loaded: list[tuple[int, int]] = []
_seen: set = set()


def classify(a: int):
    """-> (space, l1_block or None, byte address in the alias form or None)."""
    for k, (lo, hi, _) in enumerate(L1):
        if lo <= a < hi:
            return "byte", k, ALIAS + a
        if ALIAS + lo <= a < ALIAS + hi:
            return "byte+alias", k, a
    for k, (lo, hi) in enumerate(NW):
        if lo <= a < hi:
            return "nw", k, None
    if L2[0] <= a < L2[1]:
        return "L2", None, None
    if DDR[0] <= a < DDR[1]:
        return "DDR", None, None
    for lo, hi in MMR:
        if lo <= a < hi:
            return "mmr", None, None
    return None, None, None


def _loaded_at(a: int) -> bool:
    return any(lo <= a < hi for lo, hi in _loaded)


def _flag(kind, state, address, width, space, extra=""):
    pc = getattr(state, "pc_sw", None)
    key = (kind, pc, space)
    counts[kind] += 1
    if key in _seen:
        return
    _seen.add(key)
    violations.append({"kind": kind, "pc": pc, "address": address, "width": width,
                       "space": space, "extra": extra})


def check(state, address, width, write: bool):
    a = getattr(address, "value", address)
    if not isinstance(a, int):
        return
    if any(lo <= a < hi or ALIAS + lo <= a < ALIAS + hi for lo, hi in EXEMPT):
        counts["harness"] += 1
        return
    space, blk, alias = classify(a)
    if space is None:
        _flag("outside", state, a, width, None)
        return
    if width in (2, 4, 8) and a % min(width, 4):
        _flag("misaligned", state, a, width, space)
    if blk is not None and space.startswith("byte"):
        cache = L1[blk][2]
        off = alias - ALIAS
        if cache is not None and off >= cache:
            _flag("cache", state, a, width, space, f"L1 block {blk} cache from {cache:#x}")
        if not write:
            for b in range(alias, alias + width):
                if not _loaded_at(b) and b not in state.overlay and (b - ALIAS) not in state.overlay:
                    _flag("unwritten", state, a, width, space, f"byte {b:#x} never loaded or written")
                    break


def _wrap_read(fn):
    def r(state, address, width, *args, **kw):
        check(state, address, width, False)
        return fn(state, address, width, *args, **kw)
    r.__wrapped_strict__ = fn
    return r


def _wrap_write(fn):
    def w(state, address, width, value):
        check(state, address, width, True)
        return fn(state, address, width, value)
    w.__wrapped_strict__ = fn
    return w


def install(dk, stream: bytes) -> None:
    from dnfw.image import bootstream
    _loaded.clear()
    for at, data in bootstream.load_regions(stream):
        _loaded.append((at, at + len(data)))
    import sharc_core.memory as mem
    orig_r, orig_w = mem._dm_read, mem._dm_write
    orig_r = getattr(orig_r, "__wrapped_strict__", orig_r)
    orig_w = getattr(orig_w, "__wrapped_strict__", orig_w)
    wr, ww = _wrap_read(orig_r), _wrap_write(orig_w)
    for m in list(sys.modules.values()):
        for name, new, old in (("_dm_read", wr, orig_r), ("_dm_write", ww, orig_w)):
            cur = getattr(m, name, None)
            if cur is old or getattr(cur, "__wrapped_strict__", None) is old:
                setattr(m, name, new)
    Runner = dk.run.Runner
    dec = getattr(Runner._decode, "__wrapped_strict__", Runner._decode)

    def _decode(self, pc):
        if not any(lo <= pc < hi for lo, hi in CODE_SW):
            _flag("fetch", self.state, pc, 0, "sw")
        return dec(self, pc)
    _decode.__wrapped_strict__ = dec
    Runner._decode = _decode


def reset() -> None:
    violations.clear(); counts.clear(); _seen.clear()


def pages(kind: str) -> dict[str, int]:
    """Distinct (kind) violations grouped by 4 KB page of the address."""
    c = collections.Counter(f"{v['address'] & ~0xFFF:#x}" for v in violations if v["kind"] == kind)
    return dict(sorted(c.items()))


def report(limit: int = 40) -> list[str]:
    n = sum(v for k, v in counts.items() if k != "harness")
    out = [f"{n} violating accesses: {dict(counts)}; {len(violations)} distinct (kind, pc, space)"]
    for v in violations[:limit]:
        out.append(f"  {v['kind']:10s} pc {v['pc']:#x}  addr {v['address']:#x}  width {v['width']}  "
                   f"space {v['space']}  {v['extra']}")
    return out
