"""A read-only USB SysEx probe: live ColdFire state on a PC, without a reflash per question.

derived from irpina/digihealth (sysinfo.s), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project

The instrument answers SysEx on its own channel, `F0 00 20 3C 7D 00 ... F7`
(Elektron's manufacturer header and a device byte no Elektron machine uses, so
a stock OS drops it), over USB only, with three commands, all of which only
read: HELLO, STATS (the audio-frame ISR's cost, idle time, and DSP liveness)
and PEEK (DDR, the on-chip SRAM and the SSI0 audio windows; never a peripheral
register). `tools/dn2probe.py` is the other end; `docs/usbprobe.md` has the
sites, the evidence and the hardware test.

The protocol and the router hook are irpina's (irpina/digihealth, and irpina's
probing handoff (local)), for the Digitakt mk1 1.53; the DN2 1.11 sites were
found again by the signature of each mk1 site.

## How it applies

`scripts/gen_usbprobe_code.py` assembles `csrc/usbprobe/` into the 896-byte
cave at `0x402cf52c` and records it with four 6-byte `jsr` hooks in
`usbprobe_code.json`. Here:

1. every guard and every edit's stock bytes are checked -- an image that
   differs is refused;
2. the edits are written, and the HELLO tag is filled in.

Section 3 only, no length change, nothing appended. Its caves are also used by
arpplocks and midiarp, so it does not combine with those two. lfowaves left the
cave on the mod platform (2026-09-30) and combines with it.
"""

from __future__ import annotations

import json
import pathlib

from . import RAM, Extent, ModError, Result

ID = "usbprobe"
NAME = "USB SysEx probe (diagnostic)"
SUMMARY = "Read-only live state over USB SysEx (device 0x7D): HELLO, STATS, PEEK."
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("usbprobe_code.json")).read_text())
DEFAULT_TAG = "usbprobe 1"


def extents(firmware=None) -> list[Extent]:
    return [Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, e["what"]) for e in SPEC["edits"]]


def tag_bytes(tag: str) -> bytes:
    """-> the HELLO tag as stored: ASCII, NUL-terminated, in the tag field."""
    raw = tag.encode("ascii")
    if not raw or len(raw) >= SPEC["tag"]["length"] or any(b < 0x20 or b > 0x7E for b in raw):
        raise ModError(f"tag {tag!r}: 1..{SPEC['tag']['length'] - 1} printable ASCII characters")
    return raw + bytes(SPEC["tag"]["length"] - len(raw))


def apply(firmware, tag: str = DEFAULT_TAG) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    original = section.unpack()
    if len(original) < SPEC["stock_length"]:
        raise ModError(f"MAIN OS is {len(original):,} B, shorter than "
                       f"{SPEC['stock_length']:,}: not Digitone II 1.11")
    for g in SPEC["guards"]:
        want = bytes.fromhex(g["bytes"])
        if original[g["va"] - BASE:g["va"] - BASE + len(want)] != want:
            raise ModError(f"0x{g['va']:08x} is not stock; this mod is for Digitone II 1.11")
    for e in SPEC["edits"]:
        want = bytes.fromhex(e["stock"])
        if original[e["va"] - BASE:e["va"] - BASE + len(want)] != want:
            raise ModError(f"0x{e['va']:08x} is not stock; this mod is for unmodified "
                           "Digitone II 1.11, or another mod already wrote there "
                           "(arpplocks and midiarp share the probe's caves)")

    content = bytearray(original)
    for e in SPEC["edits"]:
        new = bytes.fromhex(e["new"])
        content[e["va"] - BASE:e["va"] - BASE + len(new)] = new
    at = SPEC["tag"]["va"] - BASE
    content[at:at + SPEC["tag"]["length"]] = tag_bytes(tag)

    return Result(payloads={SECTION: bytes(content)}, extents=extents(),
                  notes=[f"USB SysEx probe on device byte 0x7D, tag {tag!r}: "
                         "python tools/dn2probe.py hello",
                         f"{len(SPEC['edits']) - 1} hooks and a {SPEC['cave']['used']} B cave "
                         "in section 3, nothing appended"])


def ram() -> list[Extent]:
    """The scratch buffers and timing words above BSS (`csrc/usbprobe/layout.inc`)."""
    return [Extent(RAM, SPEC["ram"]["va"], SPEC["ram"]["length"], "the probe's buffers and timing state")]


# Bytes that only look like RAM above BSS (`dnfw.mods.ramcheck`):
# 0x402cf6b4: `move.w %sr,%d0 ; move.w #0x2700,%sr` (40 c0 46 fc 27 00);
# 0x402cf6dc: `move.w %d7,%sr ; movem.l ...` (46 c7 48 d1).
NOT_RAM = (0x402CF6B4, 0x402CF6DC)
