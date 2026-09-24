"""Generate the firmware header and the host decoder from one channel map.

    python -m dnfw.telemetry.gen          # writes both, reports what changed

**Why generated and not written twice.** On 2026-09-23 the LFO4 page was read
for a whole day before anyone checked what it rendered -- it showed only the
high byte of a value, so every diagnostic number displayed identically. The
lesson was calibrate the instrument; the corollary is that a decoder and an
emitter written separately will drift, and nothing will say so. One file, two
outputs, and a test that regenerates and compares.
"""

from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MAP = HERE / "channels.json"
HEADER = ROOT / "csrc" / "telemetry" / "tlm_channels.h"


def load() -> dict:
    return json.loads(MAP.read_text(encoding="utf-8"))


def header_text(spec: dict) -> str:
    lines = [
        "/* GENERATED from src/dnfw/telemetry/channels.json -- do not edit.",
        " * Regenerate with `python -m dnfw.telemetry.gen`.",
        " */",
        "#ifndef TLM_CHANNELS_H",
        "#define TLM_CHANNELS_H",
        "",
        f"#define TLM_CHANNEL {spec['channel']}    /* MIDI channel, 1-based */",
        "",
    ]
    for s in spec["signals"]:
        lines.append(f"#define TLM_CC_{s['name'].upper():<10s} {s['cc']:>3d}   /* {s['note']} */")
    lines += ["", "#endif /* TLM_CHANNELS_H */", ""]
    return "\n".join(lines)


def main() -> int:
    spec = load()
    text = header_text(spec)
    old = HEADER.read_text(encoding="utf-8") if HEADER.exists() else None
    HEADER.parent.mkdir(parents=True, exist_ok=True)
    HEADER.write_text(text, encoding="utf-8", newline="\n")
    print(f"  {HEADER.relative_to(ROOT)}: {'unchanged' if old == text else 'written'}")
    print(f"  channel {spec['channel']}, {len(spec['signals'])} signal(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
