"""P-IRS's ROM words (DSP2 address; read from the owner's firmware at build time): its 8 mode
frequencies, 9 decay steps, 8 mode gains, then the strike excitation (to the clamp plus a
block at the fastest step). Its gain and curve tables are P-ISD's (pi_sd_tables)."""

TABLES = {
    "PIRS_TAB": (0x144C9A, 674),
}
