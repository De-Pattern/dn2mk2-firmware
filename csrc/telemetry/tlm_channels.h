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
#define TLM_CC_VOICE       25   /* the voice, when a caller knows it */
#define TLM_CC_PROBE_A     26   /* unassigned, for whatever is being chased */
#define TLM_CC_PROBE_B     27   /* unassigned */
#define TLM_CC_MARKER      30   /* a caller-chosen tag, to separate call sites */

#endif /* TLM_CHANNELS_H */
