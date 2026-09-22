/* The other half of `RND` shows `SLEW`: two sites that ask the waveform.
 *
 * `slewhooks.S` extends the gate that decides **which entry** a column draws.
 * These two decide **whether the waveform is `RND` at all**, and they do it by
 * naming each LFO's `WAVE` entry as a literal: `pea 79`, `pea 89`, `pea 99`,
 * chosen by the `SPH` entry in `%d2`. LFO4's `SPH` is 327, so both declined
 * and the instrument kept drawing `SPH` even with the first gate extended.
 *
 * Each stub replaces the **last** of three compares. The first two -- 91 and
 * 101 -- are tested and taken before it, and what is left is
 * `moveb #81,%d0 ; cmpl %d2,%d0 ; bne <decline>`, eight bytes holding both
 * exits. `%d0` is the routine's own scratch and is dead on every exit: each
 * path's next act is `moveal %a2@,%a0`, and the decline path never reads it.
 *
 * `%a2` is the object the value is fetched from and `%a0` its vtable, exactly
 * as the three stock paths set them up; the only thing that differs is which
 * entry number is pushed.
 */
#include "dn2_111.h"
#include "slots.h"

    .globl  lfo4_rnd_a_stub
lfo4_rnd_a_stub:
    cmp.l   #81,%d2
    beq.s   lfo4_rnd_a_lfo1
    cmp.l   #LFO4_E_SPH,%d2
    bne.s   lfo4_rnd_a_no
    movea.l %a2@,%a0
    pea     LFO4_E_WAVE
    jmp     DN2_RND_A_AFTER
lfo4_rnd_a_lfo1:
    jmp     DN2_RND_A_LFO1
lfo4_rnd_a_no:
    jmp     DN2_RND_A_DECLINE

    .globl  lfo4_rnd_b_stub
lfo4_rnd_b_stub:
    cmp.l   #81,%d2
    beq.s   lfo4_rnd_b_lfo1
    cmp.l   #LFO4_E_SPH,%d2
    bne.s   lfo4_rnd_b_no
    movea.l %a2@,%a0
    pea     LFO4_E_WAVE
    jmp     DN2_RND_B_AFTER
lfo4_rnd_b_lfo1:
    jmp     DN2_RND_B_LFO1
lfo4_rnd_b_no:
    jmp     DN2_RND_B_DECLINE
