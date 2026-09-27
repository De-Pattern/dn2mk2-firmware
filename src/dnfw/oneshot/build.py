"""The DN2 section 7 for the ONESHOT port: bytes in, bytes out.

    stream, report = section7(dn2_section7, plan, adapter, samples, entry_jump=...)

It adds, as boot-stream blocks spliced before the final block (the Milestone 4
mechanism, `bootstream.insert_before_final`), all in **L1 block 2** above
Waverider M5's spans (`docs/waverider-m5-dsp.md`, correction 1: the M1-M4 spans
at DM 0x28xxxx-0x29xxxx were in the gap between blocks 0 and 1, not memory):

- the transplanted render (`plan.blocks()`: the user's own DT2 bytes, relocated);
- our adapter (`csrc/oneshot/sharc/oneshot5.asm`) at sw 0x185800;
- our step table and the sample bank with its directory;
- a zero-fill block for the 16 voice records;

and two guarded patches, Waverider M5's: the entry `JUMP 0x185800` + the
firmware's 16-bit NOP over `i5=dm(-0x18,i6); r10=dm(-0x22,i6)` at sw 0x1c9448
(the adapter re-executes both before it jumps back to 0x1c944c), and the frame
lookup `0x25d748[5] = 5`. The clamp `min(R2, 4)` at 0x1c294c stays stock: it is
not the machine clamp (M5, correction 2), and #133's raising of it is withdrawn.
Nothing is written to disk here; `report` carries no donor bytes.
"""

from __future__ import annotations

import hashlib
import struct

from ..image import bootstream
from ..transplant import sharc
from ..transplant.plan import Plan, loaded_bytes
from . import bank, params

# L1 block 2 (byte 0x300000..0x320000; M5 uses 0x300000..0x30a000, and its top
# 16 KB, 0x31c000.., is left alone in case a cache is carved there).
BLOCK2 = (0x30A000, 0x31C000)
ADAPTER_SW = 0x185800                  # PM byte 0x30b000
VARS_DM, VARS_BYTES = 0x30C000, 0x100
RECORDS_DM, RECORD_STRIDE, TRACKS = 0x30E000, 0x1D8, 16
STEPS_DM = 0x310000
BANK_DM, BANK_END = 0x310800, 0x31C000

ENTRY_SW = 0x1C9448                    # i5=dm(-0x18,i6); r10=dm(-0x22,i6)
ENTRY_STOCK = bytes.fromhex("089ce80a089c5e05")
NOP16 = bytes.fromhex("0100")          # the firmware's own 16-bit NOP (sw 0x1c9447)
LOOKUP_DM = 0x25D748 + 4 * 5           # frame machine nibble 5 -> DSP type (stock: 0)


def record_address(track: int) -> int:
    return RECORDS_DM + RECORD_STRIDE * track


def section7(dn2: bytes, plan: Plan, adapter: bytes, samples: list[list[int]], *,
             entry_jump: bytes) -> tuple[bytes, dict]:
    bank_bytes, entries = bank.build(BANK_DM, samples, limit=BANK_END - BANK_DM)
    ours = [("adapter", sharc.code_address(ADAPTER_SW), adapter),
            ("step table", sharc.data_address(STEPS_DM), params.step_table()),
            ("sample bank", sharc.data_address(BANK_DM), bank_bytes)]
    fills = [("voice records", sharc.data_address(RECORDS_DM), RECORD_STRIDE * TRACKS)]
    reserved = [("adapter variables", sharc.data_address(VARS_DM), VARS_BYTES)]
    placement = []
    for name, at, size in ([(n, a, len(b)) for n, a, b in ours] + fills + reserved):
        if loaded_bytes(dn2, at, size):
            raise ValueError(f"{name} at {at:#x}+{size:#x} is loaded by the DN2 stream")
        placement.append({"what": name, "load_address": f"{at:#010x}", "bytes": size, "whose": "ours"})
    for (at, payload), sp in zip(plan.blocks(), plan.spec.spans):
        placement.append({"what": f"transplant: {sp.name}", "load_address": f"{at:#010x}",
                          "bytes": len(payload), "whose": "the user's DT2 file, relocated"})
    _no_overlap(placement)
    for p in placement:
        lo = int(p["load_address"], 16) - sharc.SW_ALIAS
        if not (BLOCK2[0] <= lo and lo + p["bytes"] <= BLOCK2[1]):
            raise ValueError(f"{p['what']} at DM {lo:#x}+{p['bytes']:#x} leaves ONESHOT's part "
                             f"of L1 block 2 ({BLOCK2[0]:#x}..{BLOCK2[1]:#x})")
    entry = entry_jump + NOP16
    if len(entry) != len(ENTRY_STOCK):
        raise ValueError(f"the entry patch is {len(entry)} bytes, not {len(ENTRY_STOCK)}")

    extra = b"".join(bootstream.block(at, payload) for at, payload in plan.blocks())
    extra += b"".join(bootstream.block(at, payload) for _, at, payload in ours)
    extra += b"".join(bootstream.block(at, flags=bootstream.FLAG_FILL, count=n) for _, at, n in fills)
    stream = bytearray(bootstream.insert_before_final(dn2, extra))

    patches = [_patch(stream, f"entry JUMP {ADAPTER_SW:#x} + NOP at sw {ENTRY_SW:#x}",
                      sharc.code_address(ENTRY_SW), ENTRY_STOCK, entry),
               _patch(stream, "frame machine lookup [5] = 5", sharc.data_address(LOOKUP_DM),
                      struct.pack("<I", 0), struct.pack("<I", 5))]
    stream = bytes(stream)
    return stream, {"sha256": hashlib.sha256(stream).hexdigest(), "bytes": len(stream),
                    "placement": placement, "patches": patches, "bank": entries,
                    "adapter_sha256": hashlib.sha256(adapter).hexdigest()}


def _patch(stream: bytearray, what: str, address: int, before: bytes, after: bytes) -> dict:
    pieces = bootstream.writable(bytes(stream), address, len(before))
    found = bootstream.read_span(bytes(stream), address, len(before))
    if found != before:
        raise ValueError(f"{what}: {address:#x} holds {found.hex()}, not {before.hex()}; refusing")
    bootstream.write_span(stream, address, after)
    return {"what": what, "load_address": f"{address:#010x}", "from": before.hex(), "to": after.hex(),
            "stream_offset": pieces[0][0]}


def _no_overlap(placement: list[dict]) -> None:
    spans = sorted((int(p["load_address"], 16), p["bytes"], p["what"]) for p in placement)
    for (a, n, w), (b, _, v) in zip(spans, spans[1:]):
        if a + n > b:
            raise ValueError(f"{w} overlaps {v}")
