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
import { depack } from "../site/js/aplib.js";
import { pack, packStore } from "../site/js/aplibpack.js";

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

// 2. The store-only packer's output survives our own depacker.
const stored_only = packStore(expected);
checks.push(compare("packStore round-trips", depack(stored_only), expected));

// 3. The real packer: same, and timed, because it is the one that ships and a
//    browser tab is where it has to run.
const began = Date.now();
const packed = pack(expected);
const pack_ms = Date.now() - began;
checks.push(compare("pack round-trips", depack(packed), expected));

// 4. And it must not exceed what Elektron's own stream for this section costs
//    by more than a small margin -- the whole reason for porting it.
checks.push({
  check: "pack stays near Elektron's own size",
  ok: packed.length <= declaredLength * 1.15,
  got: packed.length,
  want: declaredLength,
});

if (arg("packed-out")) writeFileSync(arg("packed-out"), packed);
if (arg("store-out")) writeFileSync(arg("store-out"), stored_only);

const report = {
  stored_bytes: stored.length,
  declared_stream_bytes: declaredLength,
  unpacked_bytes: expected.length,
  packed_bytes: packed.length,
  store_only_bytes: stored_only.length,
  pack_ms,
  // Against Elektron's own stream for this section, which is the number that
  // decides whether an image is bigger than anything the device has seen.
  vs_stock: packed.length - declaredLength,
  // The store-only cost, stated rather than worked out: every byte becomes one
  // control bit plus itself.
  store_only_ratio: Number((stored_only.length / expected.length).toFixed(4)),
  checks,
};
console.log(JSON.stringify(report, null, 2));
process.exit(checks.every((c) => c.ok) ? 0 : 1);
