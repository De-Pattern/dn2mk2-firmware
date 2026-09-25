/* Wavefinder Milestone 0: the baked table, and the one read that proves it.
 *
 * **What this proves.** The delivery chain -- reduce, bake, load, address,
 * read -- end to end, before any render code exists
 * (`docs/wavefinder-feasibility.md`, "The staging"). The table is `const` data
 * in our own image, so the project's loader copies it to the `CODE` chunk's
 * address with the code; reading it back on the instrument and matching the
 * host's numbers is the whole test.
 *
 * **What it deliberately does not do.** No machine, no selector, no engine
 * path, no audio: data, one reader, and a report from a caller's telemetry
 * burst (`csrc/lfo4/bridge.c`, after `probe_a`).
 *
 * **The data is generated, never hand-written.** `wf_table_data.h` comes from
 * `dnfw.wavefinder` at build time (`dnfw wavefinder header`), from an original
 * formula in `dnfw.wavefinder.testtable` -- no Elektron data. The probe points
 * come from the same generator, so the host's expectations
 * (`dnfw wavefinder expect`) cannot drift from what is read here.
 *
 * **Every read goes through a volatile pointer.** The table and the probe
 * indices are compile-time constants, and a compiler is entitled to fold a
 * read of constant data into an immediate -- which would report the right
 * number without the bytes ever having reached the instrument. That would be a
 * pass that proves nothing, so the reads are forced to be loads.
 *
 * **Cost per burst**: one probe read, `WF_SLICE` words of checksum, ten CCs.
 */
#include "wavefinder.h"

#include "tlm.h"
#include "wf_table_data.h"

const short wf_table[WF_WORDS] = WF_TABLE_INIT;
static const unsigned short wf_probe_frame[WF_PROBES] = WF_PROBE_FRAME_INIT;
static const unsigned short wf_probe_index[WF_PROBES] = WF_PROBE_INDEX_INIT;

/* State, all in our BSS -- zeroed by the loader. Exported for the emulator
 * check, which reads them from memory after a boot. */
u32 wf_probe_at;       /* next probe, 0..WF_PROBES-1 */
u32 wf_sum_at;         /* next word of the running checksum pass */
u16 wf_sum_run;        /* the pass in progress */
u16 wf_sum;            /* the last completed pass; valid once wf_passes > 0 */
u32 wf_passes;         /* completed passes since boot */

static const volatile short *const table = wf_table;

short wf_read(unsigned int frame, unsigned int index)
{
    if (frame >= WF_FRAMES)
        frame = WF_FRAMES - 1;
    if (index >= WF_POINTS)
        index = WF_POINTS - 1;
    return table[frame * WF_POINTS + index];
}

/* Advance the running checksum by one slice; latch it at the end of a pass.
 * The same `h = h * 31 + w` over u16 words as `dnfw.wavefinder.bake`. */
static void wf_sum_step(void)
{
    u32 i = wf_sum_at, end = i + WF_SLICE;
    u16 h = wf_sum_run;

    if (i == 0)
        h = 0;
    for (; i < end; i++)
        h = (u16)(h * WF_MULT + (u16)table[i]);
    if (end >= WF_WORDS) {
        wf_sum = h;
        wf_passes++;
        end = 0;
    }
    wf_sum_at = end;
    wf_sum_run = h;
}

static void send16(u8 lo, u8 mid, u8 hi, u16 v)
{
    tlm_cc(lo, (u8)(v & 0x7Fu));
    tlm_cc(mid, (u8)((v >> 7) & 0x7Fu));
    tlm_cc(hi, (u8)((v >> 14) & 0x03u));
}

void wf_m0_report(void)
{
    const volatile unsigned short *frames = wf_probe_frame, *indices = wf_probe_index;
    u32 p = wf_probe_at;
    u32 frame = frames[p], index = indices[p];

    tlm_cc(TLM_CC_WF_FRAME, (u8)frame);
    tlm_cc14(TLM_CC_WF_IDX_LO, TLM_CC_WF_IDX_HI, (u16)index);
    send16(TLM_CC_WF_VAL_LO, TLM_CC_WF_VAL_MID, TLM_CC_WF_VAL_HI, (u16)wf_read(frame, index));
    wf_probe_at = (p + 1 >= WF_PROBES) ? 0 : p + 1;

    wf_sum_step();
    send16(TLM_CC_WF_SUM_LO, TLM_CC_WF_SUM_MID, TLM_CC_WF_SUM_HI, wf_sum);
    tlm_cc(TLM_CC_WF_PASSES, (u8)(wf_passes & 0x7Fu));
}
