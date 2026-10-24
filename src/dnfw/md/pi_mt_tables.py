"""P-I MT's DSP2 ROM words (rom.DSP_TABLES, docs/md.md): the multipliers' two ends
(frequency, radius, gain: 8 + 8 each) and the excitation (to the first word of its zero
tail and one more). It reads P-I BD's radius curve and gain table (pi_bd_tables.py)."""

TABLES = {
    "PIMT_COEF": (0x143661, 48),
    "PIMT_EXC": (0x143691, 1677),
}
