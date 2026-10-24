"""P-IRC's, P-ICC's and P-IHH's DSP2 ROM words (read from the owner's firmware at build
time): BR's and AU's biquad coefficients (128 rows of four from $145224 and $145424) and
RING's coupling gain ($142B49; an index reaches 510). P-ISD's PISD_GAIN is the first 100
of the same words."""

TABLES = {
    "PIRC_BR": (0x145224, 512),
    "PIRC_AU": (0x145424, 512),
}
