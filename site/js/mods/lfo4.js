/**
 * A fourth LFO: a fourth page under `[MOD]` that behaves like LFO1-3.
 *
 * The browser half of `src/dnfw/mods/lfo4.py`, which carries the evidence and
 * the hardware result. Same steps, same order: check the stock length and every
 * edit's stock bytes, rebuild the relocated parameter table from this image,
 * put it in the appended blob, write the edits, append the blob.
 * `scripts/js_lfo4_check.mjs` fails if the bytes differ from the Python's, and
 * the Python's are checked byte for byte against the release build when
 * `scripts/gen_lfo4_code.py` packages it.
 *
 * **No stock table bytes ship.** The relocated table is this image's own 320
 * records followed by LFO4's ten, which are this image's LFO3 records with five
 * fields rewritten -- the port of `dnfw.patch.paramtable.records` and
 * `dnfw.patch.lfo4records.build`. So a mod applied earlier that edits the stock
 * table (fxmod, moddest) is carried into the copy, **provided it is applied
 * first**: this one goes last.
 */

import { CODE } from "./lfo4-code.js";

export const ID = "lfo4";
export const NAME = "A fourth LFO";
export const SECTION = 3;
const BASE = 0x40000400;

// dnfw.patch.paramtable
const TABLE = 0x401f7fc8, RECORD = 60, COUNT = 320;
// dnfw.patch.lfo4records
const LFO3_FIRST = 94, GROUP_SIZE = 10, SLOT0 = 101;
const SLOT = 12, NRPN = 36, UNIQUE = 40, FLAGS = 44, PAGE_NAME = 52;
const UNSET = 0xffffffff;
const DEST_POSITION = 3, DEST_FLAGS = 0x00008000;
const SLOTS = [0, 1, 2, 3, 4, 5, 5, 6, 7, 1];

export class ModError extends Error {}

const hex = (s) => Uint8Array.from(s.match(/../g) ?? [], (b) => parseInt(b, 16));
const toHex = (a) => Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
/** Python's `f"{n:,}"`, whatever the browser's locale. */
const grouped = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
const u32 = (d, at) => ((d[at] << 24) >>> 0) + (d[at + 1] << 16) + (d[at + 2] << 8) + d[at + 3];
const put32 = (d, at, v) => {
  d[at] = v >>> 24; d[at + 1] = (v >>> 16) & 0xff; d[at + 2] = (v >>> 8) & 0xff; d[at + 3] = v & 0xff;
};

export const EDITS = CODE.edits.length;
export const EDITED_BYTES = CODE.edits.reduce((n, e) => n + e.new.length / 2, 0);
export const APPENDED = CODE.blob.length / 2;
export const RECORDS = CODE.table_records;

export function extents() {
  return [
    ...CODE.edits.map((e) => ({ section: SECTION, start: e.va - BASE,
                                length: e.new.length / 2, what: "LFO4 edit" })),
    { section: SECTION, start: CODE.area_va - BASE, length: APPENDED,
      what: "appended data area (loader, LFO4's C, the relocated table)" },
  ];
}

/** `want` values of field +40 inside the range the table uses and claimed by none. */
export function freeUniqueIds(content, want = GROUP_SIZE) {
  const used = new Set();
  for (let i = 0; i < COUNT; i++) used.add(u32(content, TABLE - BASE + RECORD * i + UNIQUE));
  used.delete(UNSET);
  let lo = Infinity, hi = -Infinity;
  for (const v of used) { if (v < lo) lo = v; if (v > hi) hi = v; }
  const gaps = [];
  for (let v = lo; v < hi; v++) if (!used.has(v)) gaps.push(v);
  if (gaps.length < want) {
    throw new ModError(`only ${gaps.length} unused id(s) inside the table's range, ${want} wanted`);
  }
  return gaps.slice(0, want);
}

/** LFO4's ten records: LFO3's, with the slot, NRPN, id, flags and page name rewritten. */
export function lfo4Records(content, pageNameVa) {
  const ids = freeUniqueIds(content);
  const out = new Uint8Array(RECORD * GROUP_SIZE);
  for (let k = 0; k < GROUP_SIZE; k++) {
    const at = TABLE - BASE + RECORD * (LFO3_FIRST + k);
    const record = content.slice(at, at + RECORD);
    put32(record, SLOT, SLOT0 + SLOTS[k]);
    put32(record, NRPN, UNSET);
    put32(record, UNIQUE, ids[k]);
    put32(record, FLAGS, k === DEST_POSITION ? DEST_FLAGS : 0);
    put32(record, PAGE_NAME, pageNameVa);
    out.set(record, RECORD * k);
  }
  return out;
}

/** The relocated table, from this image: its 320 records and LFO4's ten. */
export function table(content) {
  const nameVa = CODE.table_va + RECORD * CODE.table_records;
  const stock = content.subarray(TABLE - BASE, TABLE - BASE + RECORD * COUNT);
  const out = new Uint8Array(RECORD * (COUNT + GROUP_SIZE));
  out.set(stock);
  out.set(lfo4Records(content, nameVa), stock.length);
  return out;
}

/** Throw unless `content` is stock 1.11 MAIN OS wherever this mod writes. */
export function guard(content) {
  if (content.length !== CODE.stock_length) {
    throw new ModError(`MAIN OS is ${grouped(content.length)} B, not ${grouped(CODE.stock_length)}: `
      + "either not Digitone II 1.11, or another mod has already appended data "
      + "(lfowaves and bootscreen do)");
  }
  for (const e of CODE.edits) {
    const at = e.va - BASE;
    const have = toHex(content.subarray(at, at + e.stock.length / 2));
    if (have !== e.stock) {
      throw new ModError(`0x${e.va.toString(16).padStart(8, "0")} is not stock (${have.slice(0, 24)}...); `
        + "another mod has changed it, or this is not Digitone II 1.11");
    }
  }
}

/** Stock-guarded edits, then the appended area with the table filled in. */
export function compose(content) {
  guard(content);
  const blob = hex(CODE.blob);
  const records = table(content);
  const at = CODE.table_offset;
  if (blob.subarray(at, at + records.length).some((b) => b !== 0)) {
    throw new ModError("lfo4_code.json is damaged: the table's place is not blank");
  }
  blob.set(records, at);

  const out = new Uint8Array(content.length + blob.length);
  out.set(content);
  for (const e of CODE.edits) out.set(hex(e.new), e.va - BASE);
  out.set(blob, content.length);
  return out;
}

/** Throw unless this image is one the mod applies to; -> MAIN OS. */
export function check(firmware) {
  const section = firmware.container.find(SECTION);
  if (section === null) throw new ModError("image has no MAIN OS section");
  const original = section.unpack();
  if (original === null) throw new ModError("MAIN OS did not depack");
  guard(original);
  return original;
}

/** -> `{ content, notes }`, the new section 3. */
export function apply(firmware) {
  const original = check(firmware);
  const content = compose(original);
  return {
    content,
    notes: [`${EDITS} edits, appended ${grouped(APPENDED)} B; the parameter table rebuilt `
            + `from this image; MAIN OS ${grouped(content.length)} B`],
  };
}
