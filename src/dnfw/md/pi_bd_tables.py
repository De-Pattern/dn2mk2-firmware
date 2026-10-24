"""P-I BD's DSP2 ROM words (rom.DSP_TABLES, docs/md.md): the excitation (to the first word
of its zero tail and one more), the resonators' multipliers (frequency, radius, gain: 8
each), and the radius curve and gain table P-I MT shares."""

TABLES = {
    "PIBD_EXC": (0x142291, 1358),
    "PIBD_COEF": (0x142279, 24),
    "PIBD_CURVE": (0x142949, 512),
    "PIBD_GAIN": (0x142B49, 512),
}
