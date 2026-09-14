/**
 * The ELE3 container: a header, a section table, and the sections themselves.
 *
 * Port of `src/dnfw/container/ele3.py`; field offsets from `format.h` in
 * mischa85/elektron-firmware-tool, MIT. All fields are big-endian.
 *
 *     0x00  magic "ELE3"
 *     0x07  build/model string
 *     0x13  version string
 *     0x1C  u32 section count
 *     0x20  section table, 16 bytes per entry: id, offset, stored length, dest
 *
 * Sections are laid out on 16-byte boundaries, in ascending offset order,
 * after the header and table. Everything past the last section belongs to the
 * trailer, which is `integrity/digest.js`'s business, not this module's.
 */

import { ascii, setU32, u32 } from "../bytes.js";
import { Section } from "./section.js";

export const MAGIC = ascii("ELE3");
const BUILD_OFFSET = 0x07;
const VERSION_OFFSET = 0x13;
const COUNT_OFFSET = 0x1c;
const TABLE_OFFSET = 0x20;
const ENTRY_SIZE = 16;
const MAX_SECTIONS = 64;
const ALIGN = 16;

/**
 * Labels, not ground truth: Elektron document none of these. Id 2 was "DSP"
 * until its content was read -- it is ColdFire code carrying the Early
 * Start-up Menu's own strings and the HMAC key string, i.e. the recovery
 * receiver.
 */
const NAMES = {
  1: "FPGA", 2: "bootstrap", 3: "MAIN OS", 4: "updater",
  5: "meta", 6: "boot", 7: "blob",
};

export function name(id) {
  return NAMES[id] ?? "?";
}

/**
 * Parse a container. `data` starts at the ELE3 magic; `declaredSize` is the
 * length from the transport preamble.
 *
 * `head` is every byte before the first section -- magic, strings, count and
 * table -- kept verbatim so a rebuild reproduces the parts we do not touch and
 * only rewrites the table entries it must.
 */
export function parse(data, declaredSize) {
  for (let i = 0; i < MAGIC.length; i++) {
    if (data[i] !== MAGIC[i]) throw new Error("not an ELE3 container");
  }
  const count = u32(data, COUNT_OFFSET);
  if (!(count > 0 && count <= MAX_SECTIONS)) {
    throw new Error(`implausible section count ${count}`);
  }

  const sections = [];
  const offsets = [];
  for (let i = 0; i < count; i++) {
    const entry = TABLE_OFFSET + i * ENTRY_SIZE;
    const id = u32(data, entry);
    const offset = u32(data, entry + 4);
    const length = u32(data, entry + 8);
    const dest = u32(data, entry + 12);
    sections.push(new Section(id, dest, data.subarray(offset, offset + length)));
    offsets.push(offset);
  }

  const first = Math.min(...offsets);
  return {
    head: data.subarray(0, first),
    firstOffset: first,
    sections,
    offsets,
    declaredSize,
    build: text(data, BUILD_OFFSET, VERSION_OFFSET),
    version: text(data, VERSION_OFFSET, COUNT_OFFSET),
    find(id) {
      return this.sections.find((s) => s.id === id) ?? null;
    },
  };
}

/**
 * Lay the container out again, returning the bytes up to the end of the last
 * section. The caller adds the trailer.
 *
 * Sections keep their original relative order; each starts on a 16-byte
 * boundary; the table is rewritten with the new offsets and lengths. That last
 * part is what lets a section change length at all -- the reason a store-only
 * section 7 works.
 *
 * `replacements` is a Map of section id -> Section.
 */
export function assemble(container, replacements) {
  const order = container.sections
    .map((_, i) => i)
    .sort((a, b) => container.offsets[a] - container.offsets[b]);

  // Size the output before writing it: head, then each section on its
  // boundary. Growing an array 3 MB at a time in a browser tab is the kind of
  // thing that turns a two-second operation into a visible stall.
  let end = container.firstOffset;
  const chosen = order.map((index) => {
    const original = container.sections[index];
    const section = replacements.get(original.id) ?? original;
    const at = align(end);
    end = at + section.stored.length;
    return { index, section, at };
  });

  const body = new Uint8Array(end);
  body.set(container.head);
  for (const { index, section, at } of chosen) {
    body.set(section.stored, at);
    const entry = TABLE_OFFSET + index * ENTRY_SIZE;
    setU32(body, entry + 4, at);
    setU32(body, entry + 8, section.stored.length);
  }
  return body;
}

function align(position) {
  return (position + ALIGN - 1) & ~(ALIGN - 1);
}

/**
 * One of the header's fixed-width strings.
 *
 * They are space- and NUL-padded and sometimes carry a leading non-printable
 * byte, so leading junk is skipped and the run of alphanumerics and dots is
 * taken -- the same shape as `header_fields` in the C tool.
 */
function text(data, start, end) {
  const ok = (b) =>
    (b >= 0x30 && b <= 0x39) || (b >= 0x41 && b <= 0x5a) ||
    (b >= 0x61 && b <= 0x7a) || b === 0x2e;
  let i = start;
  while (i < end && !ok(data[i])) i += 1;
  let out = "";
  while (i < end && ok(data[i])) out += String.fromCharCode(data[i++]);
  return out;
}
