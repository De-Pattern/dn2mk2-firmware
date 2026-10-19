"""Which voices of one of our machines render a block: the newest, up to a cap.

RESONATOR (type 6) and CZ (type 7) render at most `MAX_VOICES` slots a block, to bound
the DSP's load. Until v0.10 the cap counted slots in slot order, so with the DN2's
dynamic voice allocation -- which hands each new note to some slot of the 16 -- a new
note on a high slot found the cap taken by older voices on lower slots and stayed
silent (owner, 2026-10-19: "a lot of dead notes"). Now the voices are ranked by age and
the newest render; an older voice past the cap is stolen (its state to rest).

A slot's age, in blocks: 0 the block it is triggered, one more each block it stays
active, saturating at AGE_TOP; a slot neither triggered nor active has none and is not
ranked. Rank: the slots with a smaller age, plus those with the same age on a lower
slot. A slot renders if its rank is below the cap.
"""

from __future__ import annotations

AGE_TOP = 0x7FFFFF00
NONE = 0x7FFFFFFF          # the asm's "no age": not triggered, not active


def age_of(trig: bool, active: bool, age: int) -> int:
    if trig:
        return 0
    if active:
        return min(age + 1, AGE_TOP)
    return NONE


def plan(slots: dict[int, tuple[bool, bool, int]], cap: int) -> dict[int, bool]:
    """SLOTS: {slot: (triggered, active, age)} for the slots of one machine type ->
    {slot: renders}. Slots with no age are absent from the ranking and render nothing."""
    ages = {t: age_of(*x) for t, x in slots.items()}
    out = {}
    for t, a in ages.items():
        if a == NONE:
            out[t] = False
            continue
        rank = sum(1 for u, b in ages.items() if b < a or (b == a and u < t))
        out[t] = rank < cap
    return out
