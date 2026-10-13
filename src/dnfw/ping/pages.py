"""PING's names on the FLTR page (P2).

A PING track's FLTR page is Multi-Mode's page (`dnfw.ping.coldfire`): the same records,
which the DSP side reads as PING's controls (`dnfw.ping.live`). While the active
track's filter is PING, `ping_names` (csrc/waverider/page.c, from the UI loop's poll,
as W2's `wr_names` does for Waverider) points the records whose meaning changes at
PING's names, so the page, the LFO and modulation destination lists and the header's
parameter line all say what the knob does; the stock pointers go back as soon as it is
not. Records whose meaning is unchanged (FREQ, ATK, DEC, ENV, KEY.T, BASE, WDTH) keep
their names.

    FLTR page 1   ATK  DEC  CURV STRK  /  FREQ RING TYPE ENV
    (the filter envelope's delay is DRIV)
"""

from __future__ import annotations

NAMED = (                 # (record id, long name, short name), short names at most 5
    (38, "Ping Type", "TYPE"),          # Multi-Mode's Filter Type: SVF / LADR / VCFQ / LPG
    (37, "Ring Time", "RING"),          # Multi-Mode's Resonance
    (44, "Ping Drive", "DRIV"),         # the filter envelope's Env. Delay
    (47, "Env. Curve", "CURV"),         # ... Sustain Level: log <- lin -> exp
    (48, "Strike", "STRK"),             # ... Release Time: the built-in strike's level
)
FILTER = 6


def c_header() -> str:
    q = chr(34)
    return (f"#define PING_FILTER {FILTER}\n"
            f"#define PING_NAMED {len(NAMED)}\n"
            f"static const unsigned short ping_named_ids[PING_NAMED] = "
            f"{{{', '.join(str(r) for r, _, _ in NAMED)}}};\n"
            f"static const char *const ping_named_long[PING_NAMED] = "
            f"{{{', '.join(q + l + q for _, l, _ in NAMED)}}};\n"
            f"static const char *const ping_named_short[PING_NAMED] = "
            f"{{{', '.join(q + s + q for _, _, s in NAMED)}}};\n")
