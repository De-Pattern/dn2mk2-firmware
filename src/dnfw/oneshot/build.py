"""The DN2 section 7 for the ONESHOT port: bytes in, bytes out.

    stream, report = section7(dn2_section7, plan, adapter, samples)

It adds, as boot-stream blocks spliced before the final block (the Milestone 4
mechanism, `bootstream.insert_before_final`):

- the transplanted render (`plan.blocks()`: the user's own DT2 bytes, relocated);
- our adapter (`csrc/oneshot/sharc/oneshot5.asm`) at sw 0x181000;
- our step table and the sample bank with its directory;
- a zero-fill block for the 16 voice records;

and two guarded one-word patches that admit machine type 5, Milestone 3/4's:
the DSP type clamp `min(R2, 4)` -> `min(R2, 5)` and the frame lookup `[5] = 5`.
Nothing is written to disk here; `report` carries no donor bytes.
"""

from __future__ import annotations

import hashlib
import struct

from ..image import bootstream
from ..transplant import sharc
from ..transplant.plan import Plan, loaded_bytes
from . import bank, params

ADAPTER_SW = 0x181000
VARS_DM, VARS_BYTES = 0x295900, 0x100
RECORDS_DM, RECORD_STRIDE, TRACKS = 0x296000, 0x1D8, 16
STEPS_DM = 0x297E00
BANK_DM, BANK_END = 0x298800, 0x2A0000

CLAMP_SW = 0x1C294A                    # `R0 = 0x4` feeding min(R2, R0) at 0x1c294c
CLAMP_FROM, CLAMP_TO = bytes.fromhex("800f0400"), bytes.fromhex("800f0500")
LOOKUP_DM = 0x25D748 + 4 * 5           # frame machine nibble 5 -> DSP type (stock: 0)


def record_address(track: int) -> int:
    return RECORDS_DM + RECORD_STRIDE * track


def section7(dn2: bytes, plan: Plan, adapter: bytes, samples: list[list[int]]
             ) -> tuple[bytes, dict]:
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

    extra = b"".join(bootstream.block(at, payload) for at, payload in plan.blocks())
    extra += b"".join(bootstream.block(at, payload) for _, at, payload in ours)
    extra += b"".join(bootstream.block(at, flags=bootstream.FLAG_FILL, count=n) for _, at, n in fills)
    stream = bytearray(bootstream.insert_before_final(dn2, extra))

    patches = [_patch(stream, "type clamp min(R2,4) -> min(R2,5)", sharc.code_address(CLAMP_SW),
                      CLAMP_FROM, CLAMP_TO),
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
