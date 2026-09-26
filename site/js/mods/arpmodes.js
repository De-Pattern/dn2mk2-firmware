/**
 * Two more arpeggiator modes: SHUF and RAND, whose names the firmware already has.
 *
 * The browser half of `src/dnfw/mods/arpmodes.py`, which carries the evidence and
 * the hardware result. Same steps, same order, same refusals: check the stock
 * length, every guard and every edit's stock bytes, then write the edits (two
 * code caves, the dispatch hook, five MODE bounds). Nothing is appended.
 * `scripts/js_arpmodes_check.mjs` fails if the bytes differ from the Python's,
 * and the Python's are checked byte for byte against the build when
 * `scripts/gen_arpmodes_code.py` packages it.
 */

import { CODE } from "./arpmodes-code.js";

export const ID = "arpmodes";
export const NAME = "Arpeggiator SHUF and RAND";
export const SECTION = 3;
const BASE = 0x40000400;

export class ModError extends Error {}

const hex = (s) => Uint8Array.from(s.match(/../g) ?? [], (b) => parseInt(b, 16));
const toHex = (a) => Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
/** Python's `f"{n:,}"`, whatever the browser's locale. */
const grouped = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
/** Python's `f"0x{va:08x}"`. */
const va8 = (va) => `0x${va.toString(16).padStart(8, "0")}`;

export const EDITS = CODE.edits.length;
export const EDITED_BYTES = CODE.edits.reduce((n, e) => n + e.new.length / 2, 0);
export const CAVES = CODE.edits.filter((e) => e.what === "arp modes code cave");
export const RAM_BYTES = CODE.ram.reduce((n, r) => n + r.bytes, 0);

export function extents() {
  return CODE.edits.map((e) => ({ section: SECTION, start: e.va - BASE,
                                  length: e.new.length / 2, what: e.what }));
}

/** Section 3 of `firmware`, refused unless this mod applies to it. */
export function check(firmware) {
  const section = firmware.container.find(SECTION);
  if (section === null || section === undefined) throw new ModError("image has no MAIN OS section");
  const original = section.unpack();
  if (original === null || original === undefined) throw new ModError("MAIN OS did not depack");
  // Longer is fine: data appended after the stock end (lfowaves, bootscreen)
  // moves no address this mod writes or reads. The guards identify the build.
  if (original.length < CODE.stock_length) {
    throw new ModError(`MAIN OS is ${grouped(original.length)} B, shorter than `
      + `${grouped(CODE.stock_length)}: not Digitone II 1.11`);
  }
  const at = (va, n) => toHex(original.subarray(va - BASE, va - BASE + n));
  for (const g of CODE.guards) {
    if (at(g.va, g.bytes.length / 2) !== g.bytes) {
      throw new ModError(`${va8(g.va)} (${g.what}) is not stock; this mod is `
        + "for unmodified Digitone II 1.11");
    }
  }
  for (const e of CODE.edits) {
    if (at(e.va, e.stock.length / 2) !== e.stock) {
      throw new ModError(`${va8(e.va)} (${e.what}) is not stock; this mod is `
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
    notes: ["the ARPEGGIATOR MODE menu offers SHUF and RAND after CYCL, and stops there",
            `${CODE.edits.length} edits in section 3, nothing appended`],
  };
}
