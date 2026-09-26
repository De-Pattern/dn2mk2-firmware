/* Waverider Milestone 0: one baked wavetable, read back over telemetry.
 *
 * See `docs/waverider-feasibility.md` ("Milestone 0") and `table.c`. Nothing
 * here renders audio, selects a machine or touches the engine: it is data and
 * a read, reported from a caller's telemetry burst.
 */
#ifndef WAVERIDER_H
#define WAVERIDER_H

/* -> the int16 at (frame, index), both clamped to the table. */
short wr_read(unsigned int frame, unsigned int index);

/* One telemetry burst's worth: the next probe point, one checksum slice, and
 * the latest whole-table checksum. Sends only; the caller decides the rate. */
void wr_m0_report(void);

#endif /* WAVERIDER_H */
