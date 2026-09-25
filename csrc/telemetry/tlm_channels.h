/* GENERATED from src/dnfw/telemetry/channels.json -- do not edit.
 * Regenerate with `python -m dnfw.telemetry.gen`.
 */
#ifndef TLM_CHANNELS_H
#define TLM_CHANNELS_H

#define TLM_CHANNEL 16    /* MIDI channel, 1-based */

#define TLM_CC_TRACK       20   /* the row this burst reports */
#define TLM_CC_OWN_LO      21   /* this row's own mirror slot, low 7 */
#define TLM_CC_OWN_HI      22   /* this row's own mirror slot, high 7 */
#define TLM_CC_SFRM_HI     23   /* scanned frame record's word, high 7 */
#define TLM_CC_DEST        24   /* the destination code in the row */
#define TLM_CC_SMIR_HI     25   /* scanned mirror block's slot, high 7 */
#define TLM_CC_PROBE_A     26   /* the calibration constant, always 99 */
#define TLM_CC_SFRM_LO     27   /* scanned frame record's word, low 7 */
#define TLM_CC_SCAN_IDX    28   /* which of the 16 blocks/records this burst scanned */
#define TLM_CC_SMIR_LO     29   /* scanned mirror block's slot, low 7 */
#define TLM_CC_MARKER      30   /* burst counter */
#define TLM_CC_FRAME_ST    31   /* 0 read, 1 destination never copied to the frame, 2 no destination */
#define TLM_CC_OWNER       32   /* track whose live sound owns this voice via 0x80005308; 126 empty, 127 not a live sound */

#endif /* TLM_CHANNELS_H */
