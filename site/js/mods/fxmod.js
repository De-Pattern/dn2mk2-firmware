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
 */

import { CODE } from "./fxmod-code.js";

export const ID = "fxmod";
export const NAME = "LFO modulation of the FX";
export const SECTION = 3;
const BASE = 0x40000400;

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
