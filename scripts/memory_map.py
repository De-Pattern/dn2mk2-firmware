"""Where every mod puts its bytes: caves, in-place edits, appended data and RAM.

The owner, 2026-09-17: *"a data cave space availability analysis with a visual
memory map showing each data section and cave. I want to understand how much
space we have available and how much we use with each mod. And where each piece
of each mod goes."*

This measures it rather than reciting it: every build is diffed byte by byte
against stock 1.11, and each changed run is attributed to the free run (cave) it
falls in, to an in-place edit of code or read-only data, or to the data appended
past the end of MAIN OS. RAM above BSS is not in the image, so its tenants come
from the build scripts' own constants, listed here with their source.

    python scripts/memory_map.py            -> out/memory-map/map.json
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.cli.files import read_image
from dnfw.firmware.load import load
from dnfw.cli.cave import SAFE_END, SAFE_START
from dnfw.image.coldfire import LoadedImage
from dnfw.patch import cave as cavelib

MAIN_OS = 3
BASE = 0x40000400
STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
BUILDS = ROOT / "00_Resources/02_Builds"
OUT = ROOT / "out/memory-map/map.json"

# The mods as they stand: the best build per feature, plus the intro variants.
MODS = [
    ("lfo4-tick6a", "Fourth LFO (engine)", "passed"),
    ("lfo-waveshapes8", "LFO waves STEP/PULS/NOIS + glyphs + labels", "to test (v6 passed)"),
    ("lfo-wavetable4", "Table-driven LFO wave TRP + glyph + label", "to test (v2 passed)"),
    ("arp-on-midi2", "Arpeggiator menu on MIDI tracks", "partial"),
    ("bootscreen-bang", "Boot screen (mod pipeline)", "passed"),
    ("intro-tunnel", "Denser intro tunnel", "not flashed"),
    ("intro-stamp", "MOD stamp on the intro", "not flashed"),
]

# What lives at each patched site, from the build scripts and their docs.
SITES = [
    (0x4000053E, 0x40000548, "startup calls: boot hook copies the appended area above BSS"),
    (0x4000766C, 0x400076D0, "waveform short-name formatter"),
    (0x400372DA, 0x400372FE, "getShortName: SPH label (STPS / WDTH / TYPE / RPTS)"),
    (0x4005F9C2, 0x4005F9C6, "ARP key handler: the MIDI-track check"),
    (0x400D3740, 0x400D3790, "intro tunnel texture scale (two floats)"),
    (0x400D3886, 0x400D388E, "intro copy routine: per-frame stamp hook"),
    (0x400E34AC, 0x400E3520, "waveform value formatter (the name on the page)"),
    (0x4010DC82, 0x4010E000, "MOD page wave widget: clamp, flag and glyph-set hooks"),
    (0x401372F0, 0x401373DC, "LFO state arrays: relocation and 3 -> 4 LFO bounds"),
    (0x401373DC, 0x40137726, "LFO evaluator B: WAVE clamp, tables, generator call"),
    (0x40137726, 0x40137B40, "LFO evaluator A: WAVE clamp, tables, generator call, SPH phase"),
    (0x401DB7FC, 0x401DB8A0, "sound ParameterSet vtable: value format (slot 92)"),
    (0x401F9200, 0x401F9700, "LFO1-3 Waveform records: maximum 6 -> new count"),
]
CAVE_USE = {
    ("lfo-waveshapes8", 0x402CF52C): "STP / PLS / NOI generators, evaluator call hooks, name formatters, SPH colour.loop wrapper",
    ("lfo-waveshapes8", 0x402D0664): "NOI seed, 10-entry name and waveform tables, glyph sets and labels, glyph renderer and label code",
    ("lfo-wavetable4", 0x402CF52C): "TRP name, 8-entry tables, table generator, hooks, formatters, glyph renderer and label code",
    ("lfo-wavetable4", 0x402D0664): "the 256-word waveform table, glyph set and label",
    ("lfo4-tick6a", 0x402DFA1C): "seven stubs: fourth-LFO parameters and state-array handling",
    ("bootscreen-bang", 0x402DFA1C): "boot copy stub and per-frame stamp stub (pre-assembled)",
    ("intro-stamp", 0x402DFA1C): "stamp stub and the MOD pixel table",
}


def site_of(va: int) -> str:
    return next((w for lo, hi, w in SITES if lo <= va < hi), "")


# The image, from docs/memory-map.md (1.11 section).
IMAGE_REGIONS = [
    (0x40000400, 0x40000600, "boot", "reset vector and C runtime bring-up"),
    (0x40000600, 0x401D0000, "code", "program code, about 1.95 MB"),
    (0x401D0000, 0x40287000, "rodata", "parameter tables, vtables, RTTI, strings"),
    (0x40287000, 0x402FC000, "records", "packed data records and the free padding runs"),
    (0x402FC000, 0x40304000, "init", ".data initializer block 1 (copied to 0x80000000)"),
    (0x40304000, 0x4030B980, "init", ".data initializer block 2 (copied to 0x80008000)"),
]
IMAGE_END = 0x4030B980

# RAM that is not in the image. BSS ends at 0x466b74d0; SDRAM tops out at 0x48000000.
BSS = (0x402FC000, 0x466B74D0)
SDRAM_TOP = 0x48000000
RAM_TENANTS = [
    (0x46700000, 0x46700000 + 3 * 0x1000, "lfo4-tick6a",
     "three 2,560-byte LFO state arrays (LIVE/SECOND/BACKUP), 4 KB slots",
     "scripts/build_lfo4_tick.py"),
    (0x46710000, 0x46710000 + 2056, "bootscreen-bang",
     "the appended data area, copied here before the BSS clear (size of intro-bang's)",
     "src/dnfw/mods/bootscreen.py"),
    (0x46740000, 0x46740000 + 1024 * 8, "lfo-waveshapes8",
     "NOIS per-LFO loop state: 1,024 keys x 8 bytes", "scripts/build_lfo_waveshapes.py"),
    (0x46750000, 0x46750000 + 3 * 112, "lfo-waveshapes8 / lfo-wavetable4",
     "rendered glyph tiles, 112 bytes per new waveform", "scripts/lfo_wave_glyph.py"),
]


def main_os(path: pathlib.Path) -> bytes:
    return load(read_image(path)).container.find(MAIN_OS).unpack()


def runs(a: bytes, b: bytes) -> list[tuple[int, int]]:
    """Maximal runs of differing bytes, as (start VA, end VA)."""
    out, i, n = [], 0, len(a)
    while i < n:
        if a[i] == b[i]:
            i += 1
            continue
        j = i
        while j < n and a[j] != b[j]:
            j += 1
        out.append((BASE + i, BASE + j))
        i = j
    return out


def region_of(va: int) -> str:
    for lo, hi, kind, _ in IMAGE_REGIONS:
        if lo <= va < hi:
            return kind
    return "?"


def main() -> int:
    stock = main_os(STOCK)
    image = LoadedImage(dest=BASE, content=stock)
    found = cavelib.find_free_runs(image, SAFE_START, SAFE_END, 32)
    verdicts = cavelib.classify(image, found, SAFE_START, SAFE_END)
    # Every zero run of 32+ bytes in the scanned region, with dnfw cave's verdict:
    # "clean" passes both checks; the others are zero but referenced by code or
    # part of a fixed-stride group, so a build must not assume they are free.
    caves = [{"start": v.run.address, "end": v.run.address + v.run.size, "size": v.run.size,
              "clean": v.passes, "strided": v.strided, "references": len(v.references),
              "users": []} for v in verdicts]

    mods = []
    for name, what, status in MODS:
        built = main_os(BUILDS / f"{name}_DN2_1.11.syx")
        body, tail = built[:len(stock)], built[len(stock):]
        in_caves: dict[int, list[int]] = {}
        edits = []
        for lo, hi in runs(stock, body):
            home = next((c for c in caves if c["start"] <= lo < c["end"]), None)
            if home is None:
                edits.append({"start": lo, "end": hi, "size": hi - lo, "region": region_of(lo),
                              "what": site_of(lo)})
            else:
                span = in_caves.setdefault(home["start"], [lo, hi])
                span[0], span[1] = min(span[0], lo), max(span[1], hi)
        cave_use = []
        for start, (lo, hi) in sorted(in_caves.items()):
            cave = next(c for c in caves if c["start"] == start)
            use = {"cave": start, "start": lo, "end": hi, "size": hi - lo,
                   "what": CAVE_USE.get((name, start), "")}
            cave["users"].append({"mod": name, **use})
            cave_use.append(use)
        mods.append({
            "name": name, "what": what, "status": status,
            "cave_bytes": sum(u["size"] for u in cave_use),
            "edit_bytes": sum(e["size"] for e in edits),
            "appended_bytes": len(tail),
            "caves": cave_use, "edits": edits,
            "ram": [{"start": lo, "end": hi, "size": hi - lo, "what": w, "source": s}
                    for lo, hi, owner, w, s in RAM_TENANTS if name in owner],
        })

    data = {
        "image": {"base": BASE, "end": IMAGE_END, "size": IMAGE_END - BASE,
                  "regions": [{"start": lo, "end": hi, "kind": k, "what": w}
                              for lo, hi, k, w in IMAGE_REGIONS]},
        "scan": {"start": SAFE_START, "end": SAFE_END},
        "caves": caves,
        "cave_total": sum(c["size"] for c in caves),
        "clean_total": sum(c["size"] for c in caves if c["clean"]),
        "ram": {"bss": list(BSS), "sdram_top": SDRAM_TOP,
                "free_above_bss": SDRAM_TOP - BSS[1],
                "tenants": [{"start": lo, "end": hi, "size": hi - lo, "owner": o, "what": w,
                             "source": s} for lo, hi, o, w, s in RAM_TENANTS]},
        "mods": mods,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1))

    print(f"{len(caves)} zero runs >= 32 B, {data['cave_total']:,} B; "
          f"clean {sum(1 for c in caves if c['clean'])} runs, {data['clean_total']:,} B")
    for c in caves:
        if c["users"]:
            used = sum(u["size"] for u in c["users"])
            who = ", ".join(sorted({u['mod'] for u in c['users']}))
            print(f"  {c['start']:#010x} {c['size']:>5} B  used by {who} (max {max(u['size'] for u in c['users'])} B)")
    for m in mods:
        print(f"{m['name']:<16} caves {m['cave_bytes']:>5} B  edits {m['edit_bytes']:>4} B "
              f"in {len(m['edits'])} sites  appended {m['appended_bytes']:>5} B  "
              f"RAM {sum(r['size'] for r in m['ram']):>6} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
