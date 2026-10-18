"""PING's and SHFT's names on the FLTR page (P2, S2).

A PING (6) or SHFT (7) track's FLTR page is Multi-Mode's page (`dnfw.ping.coldfire`):
the same records, which the DSP side reads as that type's controls (`dnfw.ping.live`,
`dnfw.shft.live`). While the active track's filter is one of them, `ping_names`
(csrc/waverider/page.c, from the UI loop's poll, as W2's `wr_names` does for Waverider)
points the records whose meaning changes at that type's names, so the page, the LFO and
modulation destination lists and the header's parameter line all say what the knob
does; the stock pointers go back as soon as it is neither. Records whose meaning is
unchanged keep their names.

    PING   ATK  DEC  CURV STRK  /  FREQ RING TYPE ENV     (DRIV on page 2)
    SHFT   ATK  DEC  MIX  -     /  SHFT FDBK MODE ENV     (DRIV on page 2)
"""

from __future__ import annotations

SETS = {                  # filter type -> {record id: (long name, short name)}, short <= 5
    6: {38: ("Ping Type", "TYPE"),      # Multi-Mode's Filter Type: SVF / LADR / VCFQ / LPG
        37: ("Ring Time", "RING"),      # Multi-Mode's Resonance
        44: ("Ping Drive", "DRIV"),     # the filter envelope's Env. Delay
        47: ("Env. Curve", "CURV"),     # ... Sustain Level: log <- lin -> exp
        48: ("Strike", "STRK")},        # ... Release Time: the built-in strike's level
    7: {36: ("Shift", "SHFT"),          # Multi-Mode's Frequency: -2.5 .. +2.5 kHz
        37: ("Shift Feedback", "FDBK"),  # Resonance
        38: ("Shift Mode", "MODE"),     # Filter Type: UP / DOWN / BOTH
        44: ("Shift Drive", "DRIV"),    # Env. Delay
        47: ("Shift Mix", "MIX"),       # Sustain Level: dry -> wet
        48: ("Unused", "-")},           # Release Time: nothing
}
NAMED = tuple((rid, *SETS[6][rid]) for rid in SETS[6])     # PING's, as P2 had it
FILTER = 6


def ids() -> list[int]:
    return sorted({rid for names in SETS.values() for rid in names})


def c_header() -> str:
    q = chr(34)
    order = ids()
    filters = sorted(SETS)

    def row(t, col):
        return "{" + ", ".join(q + SETS[t][r][col] + q if r in SETS[t] else "0" for r in order) + "}"
    return (f"#define PING_SETS {len(filters)}\n"
            f"static const signed char ping_filters[PING_SETS] = {{{', '.join(map(str, filters))}}};\n"
            f"#define PING_NAMED {len(order)}\n"
            f"static const unsigned short ping_named_ids[PING_NAMED] = {{{', '.join(map(str, order))}}};\n"
            f"static const char *const ping_named_long[PING_SETS][PING_NAMED] = "
            f"{{{', '.join(row(t, 0) for t in filters)}}};\n"
            f"static const char *const ping_named_short[PING_SETS][PING_NAMED] = "
            f"{{{', '.join(row(t, 1) for t in filters)}}};\n")
