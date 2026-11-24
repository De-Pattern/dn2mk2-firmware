"""Legacy eleven-control storage layout and generic sixteen-control binding.

No plugin manifest or DSP dependency. Values are frozen for saved-sound
compatibility; new machines obtain all metadata from the Pi catalog.
"""

from __future__ import annotations

TYPE = 21
KIND = TYPE - 4
LEGACY_CONTROLS = (('Pitch', 'PTCH', 64), ('Attack', 'ATK', 0), ('Parameter 1', 'PAR1', 64), ('Decay', 'DEC', 64), ('Parameter 2', 'PAR2', 64), ('Velocity', 'VEL', 127), ('DigitalDrive', 'DDRV', 0), ('Level', 'LEV', 127), ('Source Voice', 'VOIC', 0), ('Algorithm', 'ALG', 0), ('Mode', 'MODE', 0))
KNOBS = tuple(dict(p=i + 1, long=label, short=short, default=value)
              for i, (label, short, value) in enumerate(LEGACY_CONTROLS))
# (record id, parameter slot), in the Pi manifest's P1..P11 order.
RECORDS = ((261, 48), (253, 40), (262, 49), (254, 41), (257, 44),
           (255, 42), (260, 47), (258, 45), (252, 38), (256, 43), (241, 30))
# The generic extension keeps every existing Perkons word stable. These five
# records need type-scoped range/value-type overrides; their stock ranges differ.
EXTRA_RECORDS = ((238, 25), (239, 26), (247, 27), (246, 28), (240, 29))
ALL_RECORDS = RECORDS + EXTRA_RECORDS
GENERIC_PAGES = tuple(tuple(r for r, _ in ALL_RECORDS[i:i + 8]) for i in (0, 8))
if len(KNOBS) != len(RECORDS) or tuple(k["p"] for k in KNOBS) != tuple(range(1, 12)):
    raise ValueError("Legacy controls no longer match the native parameter contract")
PAGES = (tuple(r for r, _ in RECORDS[:8]), tuple(r for r, _ in RECORDS[8:]) + (0,) * 5)
TITLES = ("PERKONS", "SOURCE")


def named() -> dict[int, tuple[str, str]]:
    rows = {r: ("Unused", "-") for r in range(238, 263)}
    rows.update({r: (k["long"], k["short"]) for (r, _), k in zip(RECORDS, KNOBS)})
    return rows


def c_header() -> str:
    from .native_return import FRAME_TAG, FRAME_NATIVE, FRAME_IDLE
    ids = ",".join("{" + ",".join(map(str, p)) + "}" for p in PAGES)
    defaults = ",".join(str(k["default"] << 8) for k in KNOBS)
    slots = ",".join(str(s) for _, s in RECORDS)
    all_ids = ",".join(str(r) for r, _ in ALL_RECORDS)
    return (f"#define SC_TYPE {TYPE}\n#define SC_KIND {KIND}\n#define SC_PARAMS {len(KNOBS)}\n"
            f"#define SC_FRAME_TAG {FRAME_TAG}\n#define SC_FRAME_NATIVE {FRAME_NATIVE}\n#define SC_FRAME_IDLE {FRAME_IDLE}\n"
            f"static const unsigned short sc_ids[2][8] = {{{ids}}};\n"
            f"static const unsigned short sc_defaults[SC_PARAMS] = {{{defaults}}};\n"
            f"#define SC_ALL_PARAMS {len(ALL_RECORDS)}\n"
            f"static const unsigned short sc_all_ids[SC_ALL_PARAMS] = {{{all_ids}}};\n"
            f"static const unsigned char sc_slots[SC_PARAMS] = {{{slots}}};\n")
