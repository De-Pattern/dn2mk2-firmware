/**
 * LFO modulation of the FX: Chorus, Delay and Reverb in the `DEST` list.
 *
 * The browser half of `src/dnfw/mods/fxmod.py`, which carries the evidence and
 * the hardware result. Same steps, same order: check every guard and every
 * edit's stock bytes, then write the edits. `scripts/js_fxmod_check.mjs` fails
 * if the bytes differ from the Python's — and the Python's output is
 * byte-identical to `fxbrowser3_DN2_1.11.syx`, the image that was gated, so
 * what this produces is the image that was measured rather than a re-derivation
 * of it.
 *
 * Nothing here is discovered at apply time. Every address is fixed for
 * Digitone II 1.11 and every one of them is guarded: 26 sites the mod reads and
 * reasons from, plus each edit's own stock bytes. An image that differs
 * anywhere is refused rather than written somewhere plausible.
 *
 * One more refusal, for order: ten of the edits open records in the parameter
 * table, and `lfo4` moves that table into the appended area. Applied after
 * lfo4, those edits would find their stock bytes and land on a copy nothing
 * reads, so an image whose table accessors no longer reach the stock table is
 * refused, with the order that works (`tableInPlace`, the port of
 * `dnfw.patch.paramtable.base_sites`).
 */

import { CODE } from "./fxmod-code.js";

export const ID = "fxmod";
export const NAME = "LFO modulation of the FX";
export const SECTION = 3;
const BASE = 0x40000400;

// dnfw.patch.paramtable: the stock table, and the biased bases its accessors carry.
const TABLE = 0x401f7fc8, RECORD = 60;
const STOCK_END = 0x4030b980;
const EXPECTED_BASES = [[8, 53], [16, 1], [40, 2]];

export class ModError extends Error {}

const hex = (s) => Uint8Array.from(s.match(/../g) ?? [], (b) => parseInt(b, 16));
const toHex = (a) => Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");

/** -> [{ group, parameters }] — what the `DEST` list gains, for the page. */
export const DESTINATIONS = CODE.destinations;

export const COUNT = CODE.destinations.reduce((n, g) => n + g.parameters.length, 0);

export function extents() {
  return CODE.edits.map((e) => ({ section: SECTION, start: e.va - BASE,
                                  length: e.new.length / 2, what: e.what }));
}

/**
 * Throw unless every accessor of the parameter table still carries the stock
 * table's biased base: the same count `paramtable.base_sites` asserts.
 */
export function tableInPlace(content) {
  const end = Math.max(0, Math.min(content.length, STOCK_END - BASE));
  for (const [bias, expected] of EXPECTED_BASES) {
    const literal = (TABLE - RECORD + bias) >>> 0;
    const want = [literal >>> 24, (literal >>> 16) & 0xff, (literal >>> 8) & 0xff, literal & 0xff];
    let found = 0;
    for (let i = 0; i + 4 <= end; i += 2) {
      if (content[i] === want[0] && content[i + 1] === want[1]
          && content[i + 2] === want[2] && content[i + 3] === want[3]) found++;
    }
    if (found !== expected) {
      throw new ModError(`the parameter table has been moved (expected ${expected} site(s) holding `
        + `0x${literal.toString(16).padStart(8, "0")} (table - ${RECORD} + ${bias}), found ${found}); `
        + "lfo4 does that, and fxmod opens records in the stock table, which nothing reads once it "
        + "has moved: apply fxmod first, then lfo4");
    }
  }
}

/** Throw unless this image is the one the mod was measured against. */
export function check(firmware) {
  const section = firmware.container.find(SECTION);
  if (section === null) throw new ModError("image has no MAIN OS section");
  const original = section.unpack();
  if (original === null) throw new ModError("MAIN OS did not depack");
  // Longer is fine: data appended after the stock end moves no address here.
  if (original.length < CODE.stock_length) {
    throw new ModError(`MAIN OS is ${original.length.toLocaleString()} B, shorter than `
      + `${CODE.stock_length.toLocaleString()}: not Digitone II 1.11`);
  }
  tableInPlace(original);
  const at = (va, n) => toHex(original.subarray(va - BASE, va - BASE + n));
  for (const g of CODE.guards) {
    if (at(g.va, g.bytes.length / 2) !== g.bytes) {
      throw new ModError(`0x${g.va.toString(16)} (${g.what}) is not stock; `
        + "this mod is for unmodified Digitone II 1.11");
    }
  }
  for (const e of CODE.edits) {
    if (at(e.va, e.stock.length / 2) !== e.stock) {
      throw new ModError(`0x${e.va.toString(16)} (${e.what}) is not stock; this mod is `
        + "for unmodified Digitone II 1.11, or another mod already wrote there");
    }
  }
  return original;
}

/** -> `{ content, notes }`, the new section 3. */
export function apply(firmware) {
  const original = check(firmware);
  const content = original.slice();
  for (const e of CODE.edits) content.set(hex(e.new), e.va - BASE);

  return {
    content,
    notes: [`${COUNT} FX destinations appear in the LFO DEST list`,
            "Chorus, Delay and Reverb parameters follow the LFO",
            "the Chorus group reads CHR, not ERR",
            `${CODE.edits.length} edits in section 3, nothing appended`],
  };
}
