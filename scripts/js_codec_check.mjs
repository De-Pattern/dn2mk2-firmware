/**
 * Run the browser codec over a real firmware section, from the command line.
 *
 * `site/js/aplib.js` is a second implementation of a format whose output people
 * flash, so it does not get trusted because it looks like the Python. This
 * harness drives it over bytes Elektron actually shipped and reports what it
 * found; `test/test_js_codec.py` calls it and then adds the check this script
 * cannot make -- depacking the JS packer's output with the *Python* depacker,
 * which is the only part with no shared lineage.
 *
 * Two of the three checks in `docs/mods.md` live here:
 *
 *   1. depack agreement  -- JS depack of the stored stream == Python's unpacked
 *   2. pack self-check   -- JS depack of JS packStore(unpacked) == unpacked
 *
 * Usage:
 *   node scripts/js_codec_check.mjs --stored S.bin --expect U.bin [--packed-out P.bin]
 *
 * `--stored` is a section exactly as the container holds it (`dnfw extract
 * --stored`): 8-byte header, stream, padding. `--expect` is the same section
 * depacked by Python (`dnfw extract`). Prints a JSON report and exits non-zero
 * if any check fails.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { depack, packStore } from "../site/js/aplib.js";

const SECTION_HEADER = 8;  // [u32 stream length BE][u32 stream byte-sum BE]

function arg(name) {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : null;
}

/** First differing index, or -1. Reported instead of a bare pass/fail so a
 *  failure says *where*, which is the difference between a bug report and a
 *  shrug. */
function firstDifference(a, b) {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) if (a[i] !== b[i]) return i;
  return a.length === b.length ? -1 : n;
}

function compare(label, got, want) {
  const at = firstDifference(got, want);
  const result = { check: label, ok: at === -1, got: got.length, want: want.length };
  if (at !== -1) {
    result.first_difference = at;
    result.got_byte = got[at] ?? null;
    result.want_byte = want[at] ?? null;
  }
  return result;
}

const storedPath = arg("stored");
const expectPath = arg("expect");
if (!storedPath || !expectPath) {
  console.error("usage: js_codec_check.mjs --stored S.bin --expect U.bin [--packed-out P.bin]");
  process.exit(2);
}

const stored = new Uint8Array(readFileSync(storedPath));
const expected = new Uint8Array(readFileSync(expectPath));
const declaredLength = new DataView(stored.buffer, stored.byteOffset).getUint32(0, false);
const stream = stored.subarray(SECTION_HEADER, SECTION_HEADER + declaredLength);

const checks = [];

// 1. The depacker agrees with Python over 602 KB of Elektron's own stream.
const unpacked = depack(stream);
checks.push(compare("depack matches python", unpacked, expected));

// 2. The packer's output survives our own depacker.
const packed = packStore(expected);
checks.push(compare("packStore round-trips", depack(packed), expected));

if (arg("packed-out")) writeFileSync(arg("packed-out"), packed);

const report = {
  stored_bytes: stored.length,
  declared_stream_bytes: declaredLength,
  unpacked_bytes: expected.length,
  packed_bytes: packed.length,
  // The store-only cost, stated rather than left to be worked out from the two
  // numbers above: every byte becomes one control bit plus itself.
  growth_ratio: Number((packed.length / expected.length).toFixed(4)),
  checks,
};
console.log(JSON.stringify(report, null, 2));
process.exit(checks.every((c) => c.ok) ? 0 : 1);
