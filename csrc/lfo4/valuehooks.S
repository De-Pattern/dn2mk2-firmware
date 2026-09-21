/* Step 4c and 4d's stubs: the value read, and the companion row behind it.
 *
 * **These live apart from `hooks.S` and `pagehooks.S` because an assembly file
 * is linked whole.** `--gc-sections` works on sections and each of these files
 * is one, so every stub in a file is kept whenever any stub in it is an entry
 * -- and then every symbol those stubs call has to be linked too, by *every*
 * build that compiles the file. Putting a stub beside the others broke the
 * build three times in one evening, each time in a build that had no interest
 * in the site the new stub patched.
 *
 * The rule that falls out of it: **a stub belongs in a file that only the
 * builds patching its site compile.** `hooks.S` is the sites every LFO4 build
 * has; `pagehooks.S` is the page's two; this is `lfo4-value`'s two.
 */
/* Both, and in this order: `slots.h` keeps its C behind `__ASSEMBLER__`, so
 * it does not pull in the site addresses the way it does for C. */
#include "dn2_111.h"
#include "slots.h"

/* The read side, and it is `lfo4_set_stub` in a mirror.
 *
 * `DN2_GET_BOUND` is `moveq #100,%d0 ; cmpl %d2,%d0 ; blts <zero>`, six bytes
 * for three instructions, guarding the page's own `mvs.w %a0@(20,%d2:l:2)`.
 * Like the setter's bound it has two exits and this stub controls both, so it
 * is entered with `jmp` and leaves with `jmp`: nothing is replayed.
 *
 *   slot <= 100   the firmware's own read, untouched
 *   101..108      LFO4's: fetch the live sound the way the next instructions
 *                 are about to, and answer from the extension table
 *   > 108         zero, which is what stock does
 *
 * d0 held 100 at the site and is dead either way -- both paths overwrite it.
 * The sound comes from the firmware's *own* virtual call, `a2@(16)` and its
 * vtable slot 40, which is what the instructions at DN2_GET_READ do: the same
 * pointer, not one this code went looking for. d2 and a2 survive it, which the
 * firmware relies on across the identical call six instructions later.
 */

    .globl  lfo4_get_stub
lfo4_get_stub:
    cmp.l   #100,%d2
    ble.s   lfo4_get_stock
    cmp.l   #LFO4_LAST,%d2
    bgt.s   lfo4_get_none
    movea.l %a2@(16),%a0            | the object that owns the sound
    movea.l %a0@,%a1                | its vtable
    move.l  %a0,-(%sp)              | this
    movea.l %a1@(40),%a0
    jsr     %a0@                    | -> d0 = the live sound
    addq.l  #4,%sp
    move.l  %d2,-(%sp)              | slot
    move.l  %d0,-(%sp)              | sound
    jsr     lfo4_on_get             | -> d0 = the value, sign extended
    addq.l  #8,%sp
    jmp     DN2_GET_RETURN
lfo4_get_none:
    jmp     DN2_GET_ZERO
lfo4_get_stock:
    jmp     DN2_GET_READ

/* The companion table's accessor, diverted for LFO4's ten entries.
 *
 * `DN2_COMPANION_BOUND` is `movel %sp@(4),%d0 ; cmpil #321,%d0` -- ten bytes
 * for two instructions, both replayed, because unlike the setter's bound this
 * one is not a decision with two exits: it is the front of an arithmetic the
 * stock path still has to finish for every entry this build does not own.
 *
 * `lfo4_companion` answers 0 for those, and 0 falls through to the replay.
 */
    .globl  lfo4_comp_stub
lfo4_comp_stub:
    move.l  %sp@(4),%d0
    cmp.l   #LFO4_ENTRY0,%d0
    blt.s   lfo4_comp_stock
    cmp.l   #LFO4_ENTRYN,%d0
    bge.s   lfo4_comp_stock
    move.l  %d0,-(%sp)
    jsr     lfo4_companion
    addq.l  #4,%sp
    tst.l   %d0
    beq.s   lfo4_comp_stock         | not ours after all: the stock arithmetic
    rts
lfo4_comp_stock:
    .globl  lfo4_comp_displaced
lfo4_comp_displaced:
    move.l  %sp@(4),%d0
    cmpi.l  #321,%d0
    jmp     DN2_COMPANION_AFTER

/* The fourth waveform-preview block, transcribed from the firmware's third.
 *
 * `0x4010e27e` is LFO3's, and LFO1's and LFO2's sit just above it: the same
 * instructions five times over with their own entry numbers as literals. The
 * dispatch hands LFO4 index 3 already and has no block for it, so this is that
 * block, with five constants changed and `jmp` where the firmware's falls
 * through.
 *
 * The build asserts, byte for byte, that what the assembler produces here is
 * the firmware's own block with exactly those five immediates substituted --
 * so this is a transcription that cannot drift into a paraphrase.
 *
 * Entered by a jump over the fallback's first eight bytes, with `%d0` still
 * the index and `%a2` still the page. Anything that is not LFO4 replays those
 * eight bytes and carries on.
 */
    .globl  lfo4_wave_stub
lfo4_wave_stub:
    cmp.l   #DN2_WAVE_INDEX,%d0
    beq.s   lfo4_wave_four
    .globl  lfo4_wave_displaced
lfo4_wave_displaced:
    move.l  %a2,-(%sp)
    jsr     DN2_WAVE_CALL
    jmp     DN2_WAVE_AFTER

    .globl  lfo4_wave_four
lfo4_wave_four:
    move.l  %sp,%d3
    addi.l  #67,%d3
    move.l  %d3,-(%sp)
    pea     LFO4_E_WAVE
    move.l  %a2,-(%sp)
    lea     DN2_WIDGET_GET,%a3
    jsr     %a3@
    move.l  %d3,-(%sp)
    pea     LFO4_E_SPH
    move.l  %a2,-(%sp)
    move.l  %d0,%d4
    jsr     %a3@
    move.l  %d3,-(%sp)
    pea     LFO4_E_MODE
    move.l  %a2,-(%sp)
    move.l  %d0,%d5
    jsr     %a3@
    lea     %sp@(32),%sp
    move.l  %d3,%sp@
    pea     LFO4_E_SPD
    move.l  %a2,-(%sp)
    move.l  %d0,%d6
    jsr     %a3@
    move.l  %d3,-(%sp)
    pea     LFO4_E_DEP
    move.l  %d0,%d7
    jmp     DN2_WAVE_TAIL
