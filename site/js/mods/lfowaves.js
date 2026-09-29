/**
 * Seven new LFO waveforms, with three wavetables the user can swap.
 *
 * The browser half of `src/dnfw/mods/lfowaves.py`, which carries the evidence and
 * the hardware result. Same steps, same order: check every edit's stock bytes,
 * fill the blob (stock table entries from this image, each wavetable ours or the
 * user's), write the edits, and add the blob to the platform's area as a CODE
 * chunk at 0x46780000, with a DISP chunk for the getShortName compare its hook
 * replays. The packaged build's own start-up hook and copy stub are left out:
 * the platform loader makes the same copy.
 * `scripts/js_lfowaves_check.mjs` fails if the bytes differ from the Python's.
 */

import { CODE } from "./lfowaves-code.js";
import * as platform from "./platform.js";

export const ID = "lfowaves";
export const NAME = "New LFO waveforms";
export const SECTION = 3;
export const TABLE_BYTES = 7 * 32;
export const WAVES = CODE.waves;
export const LABELS = CODE.labels;
export const TABLES = CODE.tables;
export const RUNTIME_VA = CODE.runtime_va;
const BASE = 0x40000400;
const STUB = [0x402cf52c, 46];                   // the packaged build's copy stub
const SHORT_NAME = 0x400372da, SHORT_NAME_DISPLACED = 10;

export class ModError extends Error {}

const hex = (s) => Uint8Array.from(s.match(/../g) ?? [], (b) => parseInt(b, 16));
const toHex = (a) => Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
/** Python's `f"{n:,}"`, whatever the browser's locale. */
const grouped = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");

const own = (e) => {
  const lo = e.va - BASE, hi = lo + e.new.length / 2, stub = STUB[0] - BASE;
  return !(platform.extents().some((x) => x.start < hi && lo < x.start + x.length)
           || (stub < hi && lo < stub + STUB[1]));
};
const EDITS = CODE.edits.filter(own);

export function defaultTables() {
  const blob = hex(CODE.blob);
  return CODE.tables.map((t) => blob.slice(t.offset, t.offset + TABLE_BYTES));
}

export function extents(blobLength = CODE.blob.length / 2) {
  return [
    ...EDITS.map((e) => ({ section: SECTION, start: e.va - BASE, length: e.new.length / 2,
                           what: "LFO waves edit", displaced: e.va === SHORT_NAME })),
    ...platform.extents(16 + blobLength),
  ];
}

/** Where in RAM the getShortName hook replays the instructions it displaced. */
function displacedCopy(blob) {
  const stock = CODE.edits.find((e) => e.va === SHORT_NAME).stock.slice(0, 2 * SHORT_NAME_DISPLACED);
  const want = stock + "4ef9" + (SHORT_NAME + SHORT_NAME_DISPLACED).toString(16).padStart(8, "0");
  const text = toHex(blob);
  const found = [];
  for (let at = text.indexOf(want); at >= 0; at = text.indexOf(want, at + 1)) {
    if (at % 2 === 0) found.push(at / 2);
  }
  if (found.length !== 1) {
    throw new ModError("lfowaves_code.json is damaged: getShortName's replay is not found once");
  }
  return RUNTIME_VA + found[0];
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
  const [base, others] = platform.split(original);
  for (const e of EDITS) {
    const at = e.va - BASE;
    const have = toHex(base.subarray(at, at + e.stock.length / 2));
    if (have !== e.stock) {
      const hint = e.va === SHORT_NAME ? "; lfo4 widens this bound: apply lfowaves first, then lfo4"
        : "; this mod is for unmodified Digitone II 1.11";
      throw new ModError(`0x${e.va.toString(16).padStart(8, "0")} is not stock (${have.slice(0, 24)}...)${hint}`);
    }
  }

  const blob = hex(CODE.blob);
  for (const f of CODE.fills) {
    const src = f.from_va - BASE;
    blob.set(base.subarray(src, src + 4 * f.count), f.offset);
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

  const edited = base.slice();
  for (const e of EDITS) edited.set(hex(e.new), e.va - BASE);
  const content = platform.join(edited, [
    ...others,
    [platform.CODE, platform.codeChunk(RUNTIME_VA, blob)],
    platform.displace(SHORT_NAME, SHORT_NAME_DISPLACED, displacedCopy(blob)),
  ]);

  const notes = [
    `waves after RAND: ${CODE.waves.join(" ")}`,
    "wavetables: " + CODE.tables.map((t) => `${t.name} ${custom.includes(t.name) ? "custom" : "ours"}`).join(", "),
    `a ${grouped(blob.length)} B CODE chunk at 0x${RUNTIME_VA.toString(16).padStart(8, "0")} in the `
      + `platform's area; MAIN OS ${grouped(content.length)} B`,
  ];
  return { content, notes, extents: extents(blob.length) };
}
