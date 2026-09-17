/**
 * Seven new LFO waveforms, with three wavetables the user can swap.
 *
 * The browser half of `src/dnfw/mods/lfowaves.py`, which carries the evidence and
 * the hardware result. Same steps, same order: check every edit's stock bytes,
 * fill the appended blob (stock table entries from this image, each wavetable
 * ours or the user's), write the edits, append the blob.
 * `scripts/js_lfowaves_check.mjs` fails if the bytes differ from the Python's.
 */

import { CODE } from "./lfowaves-code.js";

export const ID = "lfowaves";
export const NAME = "New LFO waveforms";
export const SECTION = 3;
export const TABLE_BYTES = 7 * 32;
export const WAVES = CODE.waves;
export const LABELS = CODE.labels;
export const TABLES = CODE.tables;
const BASE = 0x40000400;

export class ModError extends Error {}

const hex = (s) => Uint8Array.from(s.match(/../g) ?? [], (b) => parseInt(b, 16));
const toHex = (a) => Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");

export function defaultTables() {
  const blob = hex(CODE.blob);
  return CODE.tables.map((t) => blob.slice(t.offset, t.offset + TABLE_BYTES));
}

export function extents(blobLength = CODE.blob.length / 2) {
  return [
    ...CODE.edits.map((e) => ({ section: SECTION, start: e.va - BASE, length: e.new.length / 2,
                                what: "LFO waves edit" })),
    { section: SECTION, start: CODE.area_va - BASE, length: blobLength, what: "appended data area" },
  ];
}

/**
 * -> `{ content, notes, extents }`. `tables`: three entries, each a 224-byte
 * Uint8Array or null for ours.
 */
export function apply(firmware, tables = [null, null, null]) {
  if (tables.length !== 3) throw new ModError("give three tables (null keeps ours)");
  const section = firmware.container.find(SECTION);
  if (section === null) throw new ModError("image has no MAIN OS section");
  const original = section.unpack();
  if (original === null) throw new ModError("MAIN OS did not depack");
  if (original.length !== CODE.stock_length) {
    throw new ModError(`MAIN OS is ${original.length.toLocaleString()} B, not `
      + `${CODE.stock_length.toLocaleString()}: either not Digitone II 1.11, or another `
      + "mod has already appended data");
  }
  for (const e of CODE.edits) {
    const at = e.va - BASE;
    const have = toHex(original.subarray(at, at + e.stock.length / 2));
    if (have !== e.stock) {
      throw new ModError(`0x${e.va.toString(16)} is not stock; this mod is for unmodified Digitone II 1.11`);
    }
  }

  const blob = hex(CODE.blob);
  for (const f of CODE.fills) {
    const src = f.from_va - BASE;
    blob.set(original.subarray(src, src + 4 * f.count), f.offset);
  }
  const custom = [];
  CODE.tables.forEach((t, k) => {
    const table = tables[k];
    if (!table) return;
    if (table.length !== TABLE_BYTES) {
      throw new ModError(`${t.name}: a table is ${TABLE_BYTES} bytes, got ${table.length}`);
    }
    blob.set(table, t.offset);
    custom.push(t.name);
  });

  const pad = (4 - (blob.length % 4)) % 4;
  const content = new Uint8Array(original.length + blob.length + pad);
  content.set(original);
  for (const e of CODE.edits) content.set(hex(e.new), e.va - BASE);
  content.set(blob, original.length);

  const notes = [
    `waves after RAND: ${CODE.waves.join(" ")}`,
    "wavetables: " + CODE.tables.map((t) => `${t.name} ${custom.includes(t.name) ? "custom" : "ours"}`).join(", "),
    `appended data ${blob.length.toLocaleString()} B; MAIN OS ${content.length.toLocaleString()} B`,
  ];
  return { content, notes, extents: extents(blob.length) };
}
