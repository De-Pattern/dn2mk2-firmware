/* Wavefinder Milestone 0: one baked wavetable, read back over telemetry.
 *
 * See `docs/wavefinder-feasibility.md` ("Milestone 0") and `table.c`. Nothing
 * here renders audio, selects a machine or touches the engine: it is data and
 * a read, reported from a caller's telemetry burst.
 */
#ifndef WAVEFINDER_H
#define WAVEFINDER_H

/* -> the int16 at (frame, index), both clamped to the table. */
short wf_read(unsigned int frame, unsigned int index);

/* One telemetry burst's worth: the next probe point, one checksum slice, and
 * the latest whole-table checksum. Sends only; the caller decides the rate. */
void wf_m0_report(void);

#endif /* WAVEFINDER_H */
