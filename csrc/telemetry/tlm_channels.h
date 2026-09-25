/* GENERATED from src/dnfw/telemetry/channels.json -- do not edit.
 * Regenerate with `python -m dnfw.telemetry.gen`.
 */
#ifndef TLM_CHANNELS_H
#define TLM_CHANNELS_H

#define TLM_CHANNEL 16    /* MIDI channel, 1-based */

#define TLM_CC_TRACK       20   /* the index the tick was handed */
#define TLM_CC_MASK_LO     21   /* enable mask, low 7 bits */
#define TLM_CC_MASK_MID    22   /* enable mask, bits 7..13 */
#define TLM_CC_MASK_HI     23   /* enable mask, bits 14..20 */
#define TLM_CC_DEST        24   /* the destination code in the row */
#define TLM_CC_MOD_HI      25   /* sweeping block's value, high 7 bits */
#define TLM_CC_PROBE_A     26   /* unassigned, for whatever is being chased */
#define TLM_CC_PROBE_B     27   /* unassigned */
#define TLM_CC_MOD_BLOCK   28   /* which of the 16 blocks moves most at this destination; 127 none */
#define TLM_CC_MOD_LO      29   /* sweeping block's value, low 7 bits */
#define TLM_CC_MARKER      30   /* a caller-chosen tag, to separate call sites */
#define TLM_CC_FRAME_ST    31   /* frame read status: 0 read, 1 destination never copied to the frame, 2 no destination */

#endif /* TLM_CHANNELS_H */
