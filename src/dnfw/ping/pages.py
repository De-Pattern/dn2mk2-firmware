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
    GRAN   FDBK -    MIX  -     /  SIZE DENS MODE SPRD    (DRIV on page 2)
"""

from __future__ import annotations

SETS = {                  # filter type -> {record id: (long name, short name)}, short <= 5
    6: {38: ("Ping Type", "TYPE"),      # Multi-Mode's Filter Type: SVF / LADR / VCFQ / LPG
        37: ("Ring Time", "RING"),      # Multi-Mode's Resonance
        44: ("Ping Drive", "DRIV"),     # the filter envelope's Env. Delay
        47: ("Env. Curve", "CURV"),     # ... Sustain Level: log <- lin -> exp
        48: ("Strike", "STRK")},        # ... Release Time: the built-in strike's level
}
NAMED = tuple((rid, *SETS[6][rid]) for rid in SETS[6])     # PING's, as P2 had it
FILTER = 6


def ids() -> list[int]:
    return sorted({rid for names in SETS.values() for rid in names})


# the TYPE cell (Multi-Mode's Filter Type, record 38) as text, quarters / thirds of its
# range: what the type's core or mode is called (dnfw.ping.live.TYPES, shft.live.MODES)
TYPE_ID = 38
TYPE_TEXT = {6: ("SVF", "LADR", "VCFQ", "LPG")}   # v0.27: SHFT (7) and GRAN (8) removed


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
            f"{{{', '.join(row(t, 1) for t in filters)}}};\n"
            f"#define PING_TYPE_ID {TYPE_ID}\n"
            f"static const unsigned char ping_type_count[PING_SETS] = "
            f"{{{', '.join(str(len(TYPE_TEXT[t])) for t in filters)}}};\n"
            f"static const char ping_type_text[PING_SETS][4][5] = "
            f"{{{', '.join('{' + ', '.join(q + x + q for x in TYPE_TEXT[t]) + '}' for t in filters)}}};\n")
