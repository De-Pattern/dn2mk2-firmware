"""P-IML's DSP2 ROM words (docs/md.md; read from the owner's firmware at build time):
PIML_T: the eight mode frequencies ($143F38), decay offsets ($143F40) and gains ($143F48),
then the mallet's excitation from $143F50 as far as its pointer can reach (its stored
pointer stops at $1449C9; a block reads up to 32 x 4 words and one more past it).
PIML_C: the decay curve the modes' radii come from ($142949, 512 words)."""

TABLES = {
    "PIML_T": (0x143F38, 0x144A4C - 0x143F38),
}
