/**
 * The arpeggiator on MIDI tracks.
 *
 * The browser half of `src/dnfw/mods/midiarp.py`, which carries the evidence and
 * the hardware result. Same steps, same order: check every guard and every
 * edit's stock bytes, write the edits, rebuild the N.LEN lookup from this
 * image's own length tables. `scripts/js_midiarp_check.mjs` fails if the bytes
 * differ from the Python's.
 */

import { CODE } from "./midiarp-code.js";

export const ID = "midiarp";
export const NAME = "Arpeggiator on MIDI tracks";
export const SECTION = 3;
const BASE = 0x40000400;
const LUT_BYTES = 128;

export class ModError extends Error {}

const hex = (s) => Uint8Array.from(s.match(/../g) ?? [], (b) => parseInt(b, 16));
const toHex = (a) => Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
const i32 = (d, at) => ((d[at] << 24) | (d[at + 1] << 16) | (d[at + 2] << 8) | d[at + 3]);

export function extents() {
  return CODE.edits.map((e) => ({ section: SECTION, start: e.va - BASE,
                                  length: e.new.length / 2, what: e.what }));
}

/**
 * For each N.LEN, the trig length index nearest in duration (ties shorter);
 * INF becomes 126. The MIDI task times notes only through the trig table.
 */
export function nlenLut(content) {
  const table = (va) => Array.from({ length: 128 }, (_, k) => i32(content, va - BASE + 4 * k));
  const trig = table(CODE.trig_lengths_va).slice(0, 127);
  return Uint8Array.from(table(CODE.arp_lengths_va), (want) => {
    if (want < 0) return 126;
    let best = 0;
    for (let i = 1; i < 127; i++) {
      const d = Math.abs(trig[i] - want), bd = Math.abs(trig[best] - want);
      if (d < bd || (d === bd && trig[i] < trig[best])) best = i;
    }
    return best;
  });
}

/** -> `{ content, notes }`, the new section 3. */
export function apply(firmware) {
  const section = firmware.container.find(SECTION);
  if (section === null) throw new ModError("image has no MAIN OS section");
  const original = section.unpack();
  if (original === null) throw new ModError("MAIN OS did not depack");
  // Longer is fine: data appended after the stock end moves no address used here.
  if (original.length < CODE.stock_length) {
    throw new ModError(`MAIN OS is ${original.length.toLocaleString()} B, shorter than `
      + `${CODE.stock_length.toLocaleString()}: not Digitone II 1.11`);
  }
  const at = (va, n) => toHex(original.subarray(va - BASE, va - BASE + n));
  for (const g of CODE.guards) {
    if (at(g.va, g.bytes.length / 2) !== g.bytes) {
      throw new ModError(`0x${g.va.toString(16)} is not stock; this mod is for unmodified Digitone II 1.11`);
    }
  }
  for (const e of CODE.edits) {
    if (at(e.va, e.stock.length / 2) !== e.stock) {
      throw new ModError(`0x${e.va.toString(16)} is not stock; this mod is for unmodified `
        + "Digitone II 1.11, or another mod already wrote there");
    }
  }

  const content = original.slice();
  for (const e of CODE.edits) content.set(hex(e.new), e.va - BASE);
  content.set(nlenLut(original), CODE.lut_va - BASE);

  return {
    content,
    notes: ["ARPEGGIATOR menu opens on MIDI tracks",
            "an arp-enabled MIDI track plays its arp out over MIDI",
            `${CODE.edits.length} edits in section 3, nothing appended`],
  };
}
