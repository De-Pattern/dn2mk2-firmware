/**
 * Open thirteen more parameters to LFO and modulation control.
 *
 * The browser half of `src/dnfw/mods/moddest.py`, which carries the evidence.
 * The short version: a 32-bit mask at `record+0x24` decides whether a parameter
 * is ever offered as a modulation destination. `0x1e00` means yes, `0` means
 * never. Thirteen per-voice parameters ship closed, and opening them was
 * **confirmed on hardware on 2026-09-12** — all thirteen appeared and
 * modulated.
 *
 * Only those thirteen. Nineteen more ship closed and stay closed here, because
 * the same hardware test showed the mask does nothing for them: for global FX
 * the gate is the enumeration, not the mask. Offering flips that provably do
 * nothing would be worse than not offering them.
 *
 * The table is **found, not hardcoded** — it moves between builds. See the
 * Python for the signature and for the first version of it, which was wrong.
 */

const STRIDE = 60;       // one parameter record
const MASK_AT = 0x24;    // the modulation mask inside a record
const GROUP_AT = 0x00;
const ID_AT = 0x04;

export const OPEN = 0x1e00;
const CLOSED = 0x0;
const MIN_RECORDS = 100;

const ALLOWED = new Set([0x1e00, 0x0e00, 0x0600, 0x0200, 0x0,
                         0x40000, 0x20000, 0x10000]);

export const ID = "moddest";
export const NAME = "More modulation destinations";
export const SECTION = 3;

/** (group, parameter id, label) — identity, independent of where the table is. */
export const TARGETS = [
  [14, 93, "Portamento Time (PTIM)"],
  [14, 94, "Portamento Enabled (PORT)"],
  [11, 80, "Amp Delay Time (DEL)"],
  [11, 91, "Amp Mode (MODE)"],
  [11, 92, "Amp Env Reset (RSET)"],
  [0, 44, "SYN A Trig (ATRG)"],
  [0, 45, "SYN A Env Reset (ARST)"],
  [0, 47, "SYN B Trig (BTRG)"],
  [0, 48, "SYN B Env Reset (BRST)"],
  [0, 33, "SYN Phase Reset (PHRT)"],
  [0, 62, "SYN Key Tracking A (KSA)"],
  [0, 63, "SYN Key Tracking B1 (KSB1)"],
  [0, 64, "SYN Key Tracking B2 (KSB2)"],
];

export class ModError extends Error {}

const u32 = (d, at) => ((d[at] << 24) >>> 0) + (d[at + 1] << 16)
                     + (d[at + 2] << 8) + d[at + 3];

const allowed = (d, at) =>
  at >= 0 && at + 4 <= d.length && ALLOWED.has(u32(d, at));

/**
 * Locate the parameter table by the shape of its mask column: a long run of
 * 60-byte-strided words drawn only from the eight values the column may hold,
 * containing all four ordinary masks. Seeded on `0x0600`, the rarest of them.
 */
export function findTable(data) {
  const seeds = [];
  for (let i = 0; i + 4 <= data.length; i += 4) {
    if (u32(data, i) === 0x0600) seeds.push(i);
  }

  const runs = new Map();
  for (const seed of seeds) {
    let lo = seed;
    while (lo - STRIDE >= 0 && allowed(data, lo - STRIDE)) lo -= STRIDE;
    let n = 0;
    while (allowed(data, lo + n * STRIDE)) n += 1;
    if (n < MIN_RECORDS) continue;
    const column = new Set();
    for (let k = 0; k < n; k++) column.add(u32(data, lo + k * STRIDE));
    if (![0x0e00, 0x0600, 0x0200, 0x1e00].every((v) => column.has(v))) continue;
    runs.set(`${lo - MASK_AT}:${n}`, [lo - MASK_AT, n]);
  }

  if (runs.size !== 1) {
    throw new ModError(
      `found ${runs.size} candidate parameter tables, expected 1; this image's `
      + "layout is not the one this mod was measured against");
  }
  return [...runs.values()][0];
}

/** -> [{ at, label }] for all thirteen, or throw. */
export function targets(data) {
  const [start, count] = findTable(data);
  const found = new Map();
  for (let i = 0; i < count; i++) {
    const at = start + i * STRIDE;
    const group = u32(data, at + GROUP_AT);
    if (group === 0xffffffff) continue;
    const key = `${group}:${u32(data, at + ID_AT)}`;
    if (!found.has(key)) found.set(key, at);
  }

  return TARGETS.map(([group, pid, label]) => {
    const at = found.get(`${group}:${pid}`);
    if (at === undefined) {
      throw new ModError(`${label}: no record with group=${group} id=${pid}`);
    }
    const mask = u32(data, at + MASK_AT);
    if (mask === OPEN) {
      throw new ModError(
        `${label}: already open; this image may already carry this mod`);
    }
    if (mask !== CLOSED) {
      throw new ModError(
        `${label}: mask is 0x${mask.toString(16)}, expected 0`);
    }
    return { at: at + MASK_AT, label };
  });
}

/**
 * Which bytes this mod writes — one extent per parameter, and only the byte
 * that actually changes. `0x00000000` -> `0x00001e00` alters one byte of four,
 * and extents are the only compatibility guarantee the system offers, so
 * over-claiming would refuse combinations that are in fact fine.
 */
export function extents(firmware) {
  const section = firmware.container.find(SECTION);
  if (section === null) throw new ModError(`image has no section ${SECTION}`);
  const data = section.unpack() ?? section.rawPayload;
  return targets(data).map(({ at, label }) => ({
    section: SECTION, start: at + 2, length: 1, what: label,
  }));
}

/** -> { content, notes } — the new section 3 bytes. */
export function apply(firmware) {
  const section = firmware.container.find(SECTION);
  if (section === null) throw new ModError(`image has no section ${SECTION}`);
  const original = section.unpack() ?? section.rawPayload;
  const content = original.slice();

  const notes = [];
  for (const { at, label } of targets(content)) {
    content[at] = 0;
    content[at + 1] = 0;
    content[at + 2] = (OPEN >> 8) & 0xff;
    content[at + 3] = OPEN & 0xff;
    notes.push(`${label} opened`);
  }
  notes.push(`${TARGETS.length} parameters opened, `
             + `${TARGETS.length} bytes changed`);
  return { content, notes };
}
