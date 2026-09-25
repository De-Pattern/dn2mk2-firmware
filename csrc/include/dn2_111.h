/* Digitone II OS 1.11: firmware addresses the C code calls or reads.
 *
 * Every entry is checked against the stock image by the build that uses it;
 * the routines follow GCC's ColdFire convention (arguments on the stack,
 * result in d0), which is also what this compiler emits.
 */
#ifndef DN2_111_H
#define DN2_111_H

#ifndef __ASSEMBLER__
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#endif

/* Startup: the .data initialiser and the BSS clear the startup hook wraps. */
#define DN2_DATA_INIT  0x4000045C
#define DN2_BSS_CLEAR  0x400004B2

/* The appended area, and where its data chunks run (dnfw.patch.area). */
#define DNFW_AREA      0x4030B980
#define DNFW_RUNTIME   0x46710000
#define DNFW_MAGIC     0x444E4657      /* 'DNFW' */
#define DNFW_CODE      0x434F4445      /* 'CODE' */

/* The stored <-> live sound converters (`docs/lfo4-build-plan.md` §4), and the
 * two sites just past their value loops, where both pointers are still live.
 * Deserialize takes (live, stored); serialize takes (stored, live, flag). */
#define DN2_SOUND_LOAD 0x400DD1EA
#define DN2_SOUND_SAVE 0x400DD6A6
#define DN2_LOAD_SITE  0x400DD282      /* mvs.b 28(a2),d0 ; moveq #6,d2 -- 6 bytes */
#define DN2_SAVE_SITE  0x400DD724      /* mvs.b 54(a2),d0 ; move.l (a0,d0.l*4),d0 -- 8 */

/* The parameter setter, and the bound that makes room for LFO4's slots.
 * 0x40037bd0 is `moveq #100,d0 ; cmp.l d2,d0 ; blt.s skip` -- six bytes, the
 * width of a `jmp <abs.l>` exactly -- guarding `values[d2] = d3` at
 * 0x40037be8. Above 100 stock firmware writes nothing at all, which is what
 * makes it a safe divert (`docs/lfo4-build-plan.md` §"Why that bound is the
 * opening"). */
#define DN2_SET_BOUND  0x40037BD0      /* the six bytes replaced */
#define DN2_SET_WRITE  0x40037BD6      /* on to the firmware's own write */
#define DN2_SET_SKIP   0x40037C48      /* the epilogue the bound branches to */

/* Step 4b, the page. Two sites, both in UI code that runs every frame.
 *
 * `DN2_PAGE_RECORD` is `id -> 0x42432c00 + 44 * id`, and it rejects anything
 * above 36 -- so a fourth MOD page's record cannot come from that table and
 * has to be answered before the arithmetic. The six bytes replaced are two
 * whole instructions the stub replays (`moveq #36,%d1 ; movel %sp@(4),%d0`).
 *
 * `DN2_MODE_HEADER` is the mode-header renderer, which reads the page vector
 * at the mode object's `+124` and the current index at `+144`. The stub is
 * entered after `%a2` would have been loaded and replays that load and the
 * one after it. */
#define DN2_PAGE_RECORD  0x400C2474    /* the six bytes replaced */
#define DN2_PAGE_AFTER   0x400C247A    /* cmpl %d0,%d1, where the stock code resumes */
#define DN2_MODE_HEADER  0x40063F5C    /* moveal %sp@(16),%a2 ; moveal %a0,%a3 */
#define DN2_MODE_AFTER   0x40063F62

/* The page id a fourth MOD page takes: one past the table's last, which only
 * the stub above ever answers for. */
#define LFO4_PAGE        37
/* The first of the ten parameter records appended to the relocated table --
 * an entry, so index + 1 (`dnfw.patch.paramtable`). */
#define LFO4_ENTRY0      321

/* Step 4c, the read side, and it is the setter's own shape.
 *
 * `0x4003717c` is `moveq #100,%d0 ; cmpl %d2,%d0 ; blts <zero>` -- six bytes,
 * the width of a `jmp <abs.l>`, guarding `mvs.w %a0@(20,%d2:l:2),%d0` at
 * `0x40037194`. Above 100 the firmware returns 0 and touches nothing, exactly
 * as its write path writes nothing, so the divert cannot corrupt a value the
 * firmware owns.
 *
 * Found by running: of the 119 instructions in the image that address the
 * value array's shape, **two** execute while a MOD page draws, and the other
 * clamps its index to 0..15 (`scripts/emu_value_reads.py`). */
#define DN2_GET_BOUND  0x4003717C      /* the six bytes replaced */
#define DN2_GET_READ   0x40037182      /* on to the firmware's own read */
#define DN2_GET_ZERO   0x4003719A      /* clr.l %d0, then the epilogue */
#define DN2_GET_RETURN 0x4003719C      /* the epilogue, with the answer in d0 */

/* Step 4d: the companion table, and why LFO4's page drew plain dials.
 *
 * `0x400c2418` is `entry -> 0x4243325c + 68 * entry`, bounded at 321 and
 * clamping anything above to entry 0. Drawing LFO4's page asks it for entries
 * 321-329 -- the right ones, the page's own eight -- and every one of the 96
 * lookups answered `0x4243325c`, the fallback (`scripts/emu_lfo4_widget.py`).
 * So each parameter got the fallback's widget: a dial with no value, no `512`
 * in a box, no waveform glyph, where LFO3's page has all three.
 *
 * The table cannot move -- its initialiser is unrolled and writes 902 absolute
 * addresses -- so the accessor is diverted for LFO4's entries instead, to ten
 * rows this build owns. Ten bytes are replaced and both instructions replayed.
 */
#define DN2_COMPANION        0x4243325C   /* the table itself, 321 x 68 */
#define DN2_COMPANION_STRIDE 68
#define DN2_COMPANION_BOUND  0x400C2418   /* the ten bytes replaced */
#define DN2_COMPANION_AFTER  0x400C2422   /* scs %d1, where the stock code resumes */

/* LFO3's ten entries, the ones LFO4's are copied from. Entry = index + 1, and
 * LFO3's records are indices 94..103. */
#define LFO3_ENTRY0      95
#define LFO4_ENTRYN      (LFO4_ENTRY0 + 10)

/* Step 4e: the waveform preview, which is re-coded per LFO.
 *
 * `0x4010e1f4` onward is three near-identical blocks selected by an LFO index
 * in `%d0` -- 0, 1, 2 -- each calling `0x4006538e` five times with its own
 * LFO's **entry numbers written as literals**:
 *
 *     index 0:  79, 81, 82, 75, 83      WAVE, SPH, MODE, SPD, DEP
 *     index 1:  89, 91, 92, 85, 93
 *     index 2:  99, 101, 102, 95, 103
 *
 * Anything else falls to `0x4010e2f0` and draws no preview -- which is why
 * LFO4's `SPH` came out a plain dial where LFO1-3 have the phase braces around
 * the waveform. **The dispatch already computes 3 for LFO4**
 * (`scripts/emu_lfo4_wave.py`); there is simply no block for it.
 *
 * So a fourth block is added, transcribing the firmware's own with five
 * constants changed, and the fallback's first eight bytes become a jump to it.
 */
#define DN2_WAVE_FALLBACK 0x4010E2F0   /* the eight bytes replaced */
#define DN2_WAVE_CALL     0x4006597A   /* what the fallback does, replayed */
#define DN2_WAVE_AFTER    0x4010E2F8
#define DN2_WAVE_TAIL     0x4010E2C6   /* the common tail all three blocks reach */
#define DN2_WIDGET_GET    0x4006538E   /* (page, entry, buffer) -> the drawn value */
#define DN2_WAVE_INDEX    3            /* what the dispatch hands LFO4 */

/* LFO4's five, in the order the blocks call for them. */
#define LFO4_E_WAVE  (LFO4_ENTRY0 + 4)
#define LFO4_E_SPH   (LFO4_ENTRY0 + 6)
#define LFO4_E_MODE  (LFO4_ENTRY0 + 7)
#define LFO4_E_SPD   (LFO4_ENTRY0 + 0)
#define LFO4_E_DEP   (LFO4_ENTRY0 + 8)
#define LFO4_E_SLEW  (LFO4_ENTRY0 + 5)

/* The `SLEW` substitution, and the gate LFO4 never got past.
 *
 * `0x4010db00` is handed the entry a column is about to draw and returns
 * either that entry or the `SLEW` that replaces it when the waveform is `RND`.
 * Its first act is a three-way compare against **81, 91 and 101** -- LFO1's,
 * LFO2's and LFO3's `SPH` entries, written as literals -- and anything else
 * leaves by `DN2_SLEW_DECLINE` with the entry unchanged.
 *
 * `scripts/emu_lfo4_slew.py` measured it with the waveform actually set to
 * `RND`: LFO3's page and LFO4's ask the gate the identical 124 times, LFO3
 * accepts 11 of them and reads entry 100 out of the table, LFO4 accepts none.
 *
 * Past the gate there are two more per-LFO facts. The index is clamped to
 * **2**, so page 3 would read LFO3's row; and the three entries are a table of
 * three longwords at `DN2_SLEW_ENTRIES`, immediately followed by a mangled
 * RTTI string, so it cannot grow where it stands.
 */
#define DN2_SLEW_GATE     0x4010DB18   /* the 22 bytes the stub replaces */
#define DN2_SLEW_ACCEPT   0x4010DB2E   /* the entry is an `SPH`: carry on */
#define DN2_SLEW_DECLINE  0x4010DBDA   /* it is not: hand the entry back */
#define DN2_SLEW_CLAMP    0x4010DBC6   /* moveq #2,%d1 -- the ceiling tested */
#define DN2_SLEW_CLAMPED  0x4010DBCC   /* moveq #2,%d0 -- what a bigger index becomes */
#define DN2_SLEW_TABLE    0x4010DBCE   /* lea 0x40205454,%a0 */
#define DN2_SLEW_ENTRIES  0x40205454   /* {80, 90, 100}, with a string behind it */
#define DN2_SLEW_COUNT    4            /* ours, one per MOD page */

/* The `DEST` browser, and the one site of six that actually opens it.
 *
 * `scan_lfo_triples.py` finds six places comparing a parameter entry against
 * **78, 88, 98** -- the `DEST` entries -- and five mask cascades testing bits
 * 18, 17 and 16 of a record's `+44`. Eleven patches, if all of them matter.
 *
 * `scripts/emu_lfo4_dest.py` opened the browser on each of the four MOD pages
 * and counted: **one** gate fires, once per page, and one cascade behind it.
 * The other ten never ran on any page. LFO1, LFO2 and LFO3 reach the gate and
 * then the cascade; LFO4 reaches the gate and stops there.
 *
 * The gate is interleaved with the function's prologue -- the first compare
 * sits at `0x40039a9a`, before the arguments are even loaded -- so only its
 * **last** compare is replaced, which is enough: 78 and 88 still match ahead
 * of it, and 98 is re-tested inside the stub.
 *
 * The cascade needs a fourth branch because the staircase `0x1e00 / 0x0e00 /
 * 0x0600` continues to **`0x0200`**, the mask that admits every record LFO3
 * may target plus LFO3's own eight. `lfo4records.DEST_FLAGS` is bit 15, which
 * is the bit this fourth branch tests.
 */
#define LFO4_E_DEST         (LFO4_ENTRY0 + 3)
#define DN2_DEST_GATE       0x40039ABA   /* moveb #98,%d1 ; cmpl %d0,%d1 ; bne */
#define DN2_DEST_ACCEPT     0x40039AC2   /* it is a `DEST`: choose the mask */
#define DN2_DEST_DECLINE    0x40039B0E   /* it is not, and `%d1` is dead there */
#define DN2_DEST_MASK       0x40039AD4   /* the 34-byte cascade */
#define DN2_DEST_MASK_AFTER 0x40039AF6   /* where all four branches converge */
#define DN2_DEST_MASK4      0x0200       /* what a fourth LFO may target */
#define DN2_DEST_FLAG_BIT   15           /* lfo4records.DEST_FLAGS = 0x8000 */

/* "Is this LFO's waveform `RND`?", asked twice and hard-coded both times.
 *
 * Extending `0x4010db00` was not enough: the instrument still drew `SPH` on
 * LFO4's `RND`. There is a second kind of site, and `scan_lfo_triples.py`
 * found two of them by the **`WAVE`** entries rather than the `SPH` ones --
 * `pea 79`, `pea 89`, `pea 99` pushed as arguments.
 *
 * Each takes the `SPH` entry a column is about to draw, picks **that LFO's
 * `WAVE` entry**, fetches its value and compares it against `0x600`, which is
 * `RND`. LFO4's `SPH` is 327 and neither knows it, so neither ever concludes
 * `RND` and the column keeps its own name.
 *
 * The two are byte-identical in shape, so each is patched at its **last**
 * compare -- the three are woven through the function and only those eight
 * bytes hold both exits.
 */
#define DN2_RND_A_GATE     0x4003662C   /* moveb #81,%d1 ; cmpl %d2 ; bne */
#define DN2_RND_A_LFO1     0x40036634   /* moveal %a2@,%a0 ; pea 79 */
#define DN2_RND_A_AFTER    0x4003664A   /* where all three converge */
#define DN2_RND_A_DECLINE  0x4003667A   /* not an `SPH` entry at all */
#define DN2_RND_B_GATE     0x40036A76
#define DN2_RND_B_LFO1     0x40036A7E
#define DN2_RND_B_AFTER    0x40036A94
#define DN2_RND_B_DECLINE  0x40036AC4

/* The parameter table as it sits in the image, for reading a record's own
 * default at init. `lfo4-table` relocates this table, but the image's copy is
 * still there and still correct -- and it is the one guaranteed to be loaded
 * when `lfo4_init` runs, which the relocated chunk is not. */
#define DN2_PARAM_TABLE   0x401F7FC8
#define DN2_PARAM_STRIDE  60
#define DN2_PARAM_DEFAULT 24           /* the record's default value */
#define LFO3_RECORD0      94           /* LFO3's group of ten starts here */

/* Where the live sound container actually is, which is **not** a constant.
 *
 * The firmware's own routine for it, `0x40025bda(track)`:
 *
 *     movel %sp@(4),%d0 ; movel #1163,%d1 ; mulsl %d1,%d0
 *     addil #52,%d0
 *     addl 0x800052a0,%d0        <- the base, read from a global
 *
 * `csrc/lfo4/bridge.c` used to compute the same thing from `LFO4_KIT`, a
 * constant measured once out of `ui1200M` -- and the snapshot agreed with it
 * only because that is where it was measured. On the instrument the container
 * moves, and then every turn lands in the table under the firmware's key while
 * every tick looks one up under ours: the page works, sounds save, and nothing
 * modulates.
 */
#define DN2_LIVE_CONTAINER 0x800052A0   /* holds the container's address */

/* **The MIDI byte sink**, found 2026-09-24 by walking MidiOutputStream's vtable.
 *
 * `tx(buffer, count, port, flags)`. Reached from `MidiOutputStream::flush`
 * (`0x401228e0`), which calls it with the stream's own buffer at `this+20` and
 * its count at `this+8`; the other three callers push `port` and `flags` as
 * plain constants -- `clrl` then `pea 0x2` -- so no stream instance is needed
 * to use it. That is what makes telemetry possible without constructing or
 * borrowing an object.
 *
 * The class was missed for a day because the RTTI name carries a length prefix:
 * the typeinfo points at `0x4023100c`, not at the "MidiOutputStream" text one
 * byte later, so searching for a pointer to the string found nothing. */
#define DN2_MIDI_TX     0x401233F2
#define DN2_MIDI_PORT   0
#define DN2_MIDI_FLAGS  2
#define DN2_SOUND_AT       52           /* the gate's own `addil #52` */
#define DN2_SOUND_STRIDE   1163         /* and its `movel #1163` */

/* **Three sixteen-entry object arrays, and the question of what indexes them.**
 *
 * Found 2026-09-25 with digikit's `refscan.py`, which reports that the mirror
 * at `0x800068e4` has exactly **three** static references in the whole image,
 * all inside `0x400db12a` -- a routine that copies three words per 202-byte
 * block out of a twin table at `0x80003af0` and returns the mirror's base. Its
 * single caller is `0x4002717e`, in the per-frame driver.
 *
 * The loop that runs immediately after evaluator A (`0x400272de`, sixteen
 * iterations) walks all three of these in lockstep with its counter:
 *
 *   `DN2_OWNER_REG`  `%a4@+` at `0x400272e8`, four bytes per entry
 *   `DN2_TRACK_OBJ`  through `0x4002b22e`, which is a pure read of
 *                    `*(base + 20*i)` -- `lsll #4` plus `%a1@(0,%d0:l:4)`
 *   `DN2_ALT_ARRAY`  through `0x4002b246`, `*(base + 4*i)`
 *
 * **What is not known is whether that counter means track or voice**, and this
 * is the whole of the LFO4 gate. The firmware's own reverse lookup for the
 * first one (`0x400258da`) is a linear scan of sixteen pointers, which is what
 * a probe here can imitate exactly.
 *
 * `DN2_OWNER_REG` reads as sixteen zeros in a 400M-instruction boot snapshot
 * (`memdump.py`, 2026-09-25). That is not evidence it stays empty: no kit loads
 * and no audio runs under any harness here, so nothing has yet had cause to
 * fill it. It has to be read on the instrument.
 *
 * **Read on the instrument the same day, and neither is the map.** With audio
 * running, `DN2_OWNER_REG` is populated -- every entry non-null -- but no entry
 * is a `DN2_TRACK_OBJ` pointer, on any index, playing or idle. `DN2_ALT_ARRAY`
 * matched only track objects 0 and 1, and flipped between them whether or not
 * anything was playing: a two-state flag. 786 bursts, calibration constant
 * correct on every one, with a silent baseline beside a single held note
 * (`docs/lfo4-build-plan.md`). Kept here because the addresses are right and
 * the next reader should not have to find them again to rule them out. */
/* **The sound on each voice, written at the moment its parameters arrive.**
 *
 * `0x4002549c(sound, slot)` is the delivery, read 2026-09-25 after the owner
 * asked why LFO4 needs a lookup when LFO1-3 do not:
 *
 *   0x400254d4  movel %a2,%a0@(0,%d0:l:4)   ; 0x80003af0 + 4*(slot+1518) = sound
 *   0x400254f6  addil #0x80003b12,%d0       ; + 202*slot: block `slot`
 *   0x400254fe  jsr 0x40134490              ; memcpy(block, sound+20, 202)
 *   0x4002551a  jsr 0x40134490              ; memcpy(0x8000487c+153*slot, sound+222, 153)
 *
 * `0x80003b12` is `0x80003af0 + 34` -- block 0 of the table the mirror is
 * copied from. So a sound's parameters travel into a voice's block here, in
 * one `memcpy`, and **the same routine records which sound it was** in the
 * sixteen longs at `0x800052a8`. That is why stock LFOs follow a track onto
 * any voice without looking anything up.
 *
 * `DN2_OWNER_REG` below, 96 bytes further on, was the first guess at this and
 * was wrong: it is what the fan-out writers compare against, and on the
 * instrument it never held a live sound (`owner` = 127 on every voice,
 * `lfo4-voiceowner`, 2026-09-25). */
#define DN2_VOICE_SOUND    0x800052A8   /* 16 x 4, written by 0x4002549c */
#define DN2_OWNER_REG      0x80005308   /* 16 x 4, scanned at 0x400258f8 */
#define DN2_TRACK_OBJ        0x40287DD4 /* 16 x 20, read by 0x4002b22e */
#define DN2_TRACK_OBJ_STRIDE 20
#define DN2_ALT_ARRAY      0x4059C92C   /* 16 x 4, read by 0x4002b246 */

/* libc as the firmware has it. */
#define DN2_MEMCPY     0x40134490
#define DN2_MEMSET     0x401344D8

#ifndef __ASSEMBLER__
static inline void *dn2_memset(void *dst, int c, u32 n)
{
    return ((void *(*)(void *, int, u32))DN2_MEMSET)(dst, c, n);
}

static inline void *dn2_memcpy(void *dst, const void *src, u32 n)
{
    return ((void *(*)(void *, const void *, u32))DN2_MEMCPY)(dst, src, n);
}
#endif /* __ASSEMBLER__ */

#endif
