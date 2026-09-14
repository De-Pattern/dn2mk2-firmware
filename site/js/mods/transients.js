/**
 * Replace the Digitone II's FM drum transient bank with your own samples.
 *
 * The browser half of `src/dnfw/mods/transients.py`. The measurements are that
 * module's; repeated here only as constants, because a value copied without its
 * evidence is a value nobody can check:
 *
 * | | | how |
 * |---|---|---|
 * | region | DDR `0x8045b000`-`0x804ac000` | bounded by float32 tables either side, not a threshold |
 * | format | 16-bit mono, little-endian | byte-plane and step-correlation match real transients |
 * | rate | 48 kHz | the period is exactly 100.0 ms at 48 k, an awkward 108.8 ms at 44.1 k |
 * | entry | 4,800 samples | envelope autocorrelation, with 2x and 3x harmonics also ranking |
 * | phase | 2,496 samples in | attack-at-start vs decay-at-end scores 14.27 against 1.46 for the next |
 *
 * **Confirmed on hardware, 2026-09-14** (`docs/flashing.md`): an image with
 * markers at five known slots was flashed to a Digitone II and every marker
 * played back from `TRAN`.
 *
 * **What stays conditional:** none of this is documented by Elektron, so
 * another OS release could move the bank. The address is resolved through the
 * boot stream every time this runs, and an image whose layout is not the one it
 * was measured against is refused rather than written to.
 *
 * This replaces **whole entries in place** and touches nothing else -- no
 * lengths change, no index is rewritten, and every byte outside the entries it
 * writes is left exactly as it was.
 */

import { readSpan, spans } from "../bootstream.js";
import { replacement } from "../firmware.js";

export const ID = "transients";
export const NAME = "FM drum transients";
export const SECTION = 7;

const REGION_START = 0x8045b000;
const REGION_END = 0x804ac000;
const PHASE_SAMPLES = 2496;
export const ENTRY_SAMPLES = 4800;
export const RATE = 48000;

const BYTES_PER_SAMPLE = 2;
export const ENTRY_BYTES = ENTRY_SAMPLES * BYTES_PER_SAMPLE;
const BANK_ADDR = REGION_START + PHASE_SAMPLES * BYTES_PER_SAMPLE;
// `Math.floor`, not bare division: the region is 326,784 bytes, which is 34.04
// entries, and Python's `//` floors it. Without this COUNT is 34.04, which
// reads as 34 everywhere it is used as a length and as **35** in the bounds
// check below -- letting a write land past the end of the bank, in the float32
// table that bounds it. Caught by `scripts/js_mod_check.mjs` asserting the
// count rather than assuming the port was faithful.
export const COUNT = Math.floor((REGION_END - BANK_ADDR) / ENTRY_BYTES);   // 34

/**
 * The bank's file pieces, in load order. See `bootstream.spans`.
 *
 * **Not one range.** The bank is contiguous in the DSP's memory and scattered
 * in the file: two payload blocks with a 36-byte fill block and two 16-byte
 * headers between them, 47,440 bytes in. Reading or writing it linearly
 * crosses those headers, which is what this module did until 2026-09-14.
 */
function bankSpans(content) {
  return spans(content, BANK_ADDR, COUNT * ENTRY_BYTES);
}

/** The factory entries, each `ENTRY_BYTES` of raw 16-bit LE PCM. */
export function extract(firmware) {
  const section = firmware.container.find(SECTION);
  if (section === null) throw new Error(`image has no section ${SECTION}`);
  const content = section.unpack() ?? section.rawPayload;
  const bank = readSpan(content, BANK_ADDR, COUNT * ENTRY_BYTES);
  return Array.from({ length: COUNT }, (_, k) =>
    bank.subarray(k * ENTRY_BYTES, (k + 1) * ENTRY_BYTES));
}

/** One entry's samples as Float32 in [-1, 1), for preview and drawing. */
export function toFloat(entry) {
  const view = new DataView(entry.buffer, entry.byteOffset, entry.byteLength);
  const out = new Float32Array(entry.byteLength / 2);
  for (let i = 0; i < out.length; i++) out[i] = view.getInt16(i * 2, true) / 32768;
  return out;
}

/**
 * Float samples -> one slot's worth of 16-bit LE PCM, padded or truncated.
 *
 * Scaled by **32768 and clamped**, not by 32767. The two differ by one bit on
 * quiet material and nobody would hear it, but 32767 makes this the inexact
 * inverse of `toFloat`: a factory entry read out and written straight back
 * comes home altered, and the round-trip that is this mod's strongest check
 * would be testing the conversion instead of the bank. Clamping is what makes
 * 32768 safe -- it is the only value that would overflow.
 */
export function toEntry(samples) {
  const out = new Uint8Array(ENTRY_BYTES);
  const view = new DataView(out.buffer);
  const n = Math.min(samples.length, ENTRY_SAMPLES);
  for (let i = 0; i < n; i++) {
    const scaled = Math.round(samples[i] * 32768);
    view.setInt16(i * 2, Math.max(-32768, Math.min(32767, scaled)), true);
  }
  return out;
}

/**
 * Which bytes this mod writes, so a set of mods can be checked for overlap
 * before any of them runs (`src/dnfw/mods/__init__.py`).
 *
 * Byte-range overlap is the whole test, and it is the weakest useful
 * guarantee: two mods writing disjoint bytes can still fight over the same
 * feature and nothing here detects that.
 */
export function extents(firmware) {
  const section = firmware.container.find(SECTION);
  const content = section.unpack() ?? section.rawPayload;
  return bankSpans(content)
    .filter((piece) => piece.at !== null)
    .map((piece) => ({
      section: SECTION,
      start: piece.at,
      length: piece.length,
      what: `transient bank, ${piece.length.toLocaleString()} bytes`,
    }));
}

/**
 * Replace entries with `entries` -- a sparse Map of slot index -> Uint8Array of
 * `ENTRY_BYTES`. Slots absent from the map keep their factory bytes.
 *
 * Sparse on purpose: replacing one transient out of 34 is the common case, and
 * an API taking a full list would make a user supply 33 samples they do not
 * care about, or make the tool invent them.
 *
 * -> a Section ready for `firmware.build`.
 */
export function apply(firmware, entries) {
  const section = firmware.container.find(SECTION);
  if (section === null) throw new Error(`image has no section ${SECTION}`);
  const original = section.unpack() ?? section.rawPayload;
  const content = original.slice();       // a copy: the loaded image stays clean

  // Build the whole bank in load order, then scatter it back across the blocks
  // that hold it. Writing entry by entry at a computed file offset is what put
  // header bytes in the audio, and would have written audio over two block
  // headers -- leaving a boot stream the DSP cannot load.
  const bank = readSpan(content, BANK_ADDR, COUNT * ENTRY_BYTES);

  const notes = [];
  for (const [slot, entry] of entries) {
    if (!Number.isInteger(slot) || slot < 0 || slot >= COUNT) {
      throw new Error(`slot ${slot} is outside 0..${COUNT - 1}`);
    }
    if (entry.length !== ENTRY_BYTES) {
      throw new Error(
        `slot ${slot}: ${entry.length} bytes, expected exactly ${ENTRY_BYTES}`);
    }
    bank.set(entry, slot * ENTRY_BYTES);
    notes.push(`${String(slot).padStart(2, "0")} replaced`);
  }

  let cursor = 0;
  for (const { at, length } of bankSpans(content)) {
    if (at === null) {
      // A fill block has no file bytes, so whatever the user put here cannot
      // be stored. Reported rather than dropped in silence: it is 36 bytes
      // near the end of entry 4, and the loader zeroes them regardless.
      if (bank.subarray(cursor, cursor + length).some((b) => b !== 0)) {
        notes.push(
          `${length} bytes at bank offset ${cursor.toLocaleString()} (entry `
          + `${Math.floor(cursor / ENTRY_BYTES)}) fall in a boot-stream fill `
          + "block and CANNOT be written; the loader zeroes them");
      }
    } else {
      content.set(bank.subarray(cursor, cursor + length), at);
    }
    cursor += length;
  }

  return {
    section: replacement(firmware, SECTION, content),
    notes,
    extents: extents(firmware),
  };
}
