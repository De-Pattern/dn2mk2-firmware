/**
 * Run the whole browser firmware stack over a real `.syx`, from the command line.
 *
 * `scripts/js_codec_check.mjs` proves the codec. This proves the four layers
 * above it -- transport, container, integrity, and the order they go in --
 * and its first check is the strongest one available anywhere in this project:
 *
 *   1. **transport round-trip** -- load the file and build it straight back
 *      with no replacements. The output must be **byte-identical** to the
 *      input. That exercises SysEx framing, 8-in-7, per-packet checksums,
 *      marker counters, the container layout, the content checksum and the
 *      HMAC trailer *at once*, and any one of them being wrong shows up as a
 *      differing byte. This is `docs/ROADMAP.md`'s Gate A, in JavaScript.
 *
 *   2. **key derivation** -- the HMAC key is recovered from the image's own
 *      material and reported by its derivation string, so a silent fallback to
 *      "unsigned" cannot pass as success.
 *
 *   3. **verify** -- every integrity field the file carries checks out.
 *
 *   4. **store-only rebuild** -- one section repacked by the browser packer,
 *      the image reassembled, reloaded and re-verified, and the section's
 *      content compared. This is the exact shape of image the tool produces.
 *
 * Usage:
 *   node scripts/js_firmware_check.mjs --syx FILE [--section 7]
 *
 * Prints a JSON report; exits non-zero if any check fails.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { build, load, replacement, verify } from "../site/js/firmware.js";
import { name } from "../site/js/container/ele3.js";

function arg(name, fallback = null) {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : fallback;
}

function firstDifference(a, b) {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) if (a[i] !== b[i]) return i;
  return a.length === b.length ? -1 : n;
}

const syxPath = arg("syx");
if (!syxPath) {
  console.error("usage: js_firmware_check.mjs --syx FILE [--section 7] [--out FILE]");
  process.exit(2);
}
const sectionId = Number(arg("section", "7"));

const raw = new Uint8Array(readFileSync(syxPath));
const firmware = await load(raw);
const checks = [];

// 1. The round-trip. Nothing replaced, so every section keeps its original
//    stored bytes and the output must match the input exactly.
const rebuilt = await build(firmware);
const at = firstDifference(rebuilt, raw);
checks.push({
  check: "transport round-trip is byte-identical",
  ok: at === -1,
  ...(at === -1 ? {} : { first_difference: at, got: rebuilt.length, want: raw.length }),
});

// 2. The key. Reported by its derivation string, never by its value.
checks.push({
  check: "signing key recovered",
  ok: firmware.key !== null,
  detail: firmware.key ? `derived from "${firmware.key.derivationString}"` : "unsigned",
});

// 3. Every integrity field the original carries.
const original = await verify(firmware);
checks.push({
  check: "original verifies",
  ok: original.every((c) => c.ok),
  detail: `${original.filter((c) => c.ok).length}/${original.length}`,
  failed: original.filter((c) => !c.ok).map((c) => `${c.name}: ${c.detail}`),
});

// 4. A store-only rebuild of one section, reloaded and re-verified.
const target = firmware.container.find(sectionId);
if (target === null || target.unpack() === null) {
  checks.push({ check: `section ${sectionId} is compressed`, ok: false });
} else {
  const content = target.unpack();
  const replacements = new Map([[sectionId, replacement(firmware, sectionId, content)]]);
  const modified = await build(firmware, replacements);
  // `--out` exists so the Python side can compare this file against its own
  // rebuild of the same image. Two independent toolchains producing the same
  // bytes is a stronger statement than either one verifying itself.
  if (arg("out")) writeFileSync(arg("out"), modified);
  const reloaded = await load(modified);
  const back = reloaded.container.find(sectionId).unpack();

  checks.push({
    check: `section ${sectionId} (${name(sectionId)}) survives a store-only rebuild`,
    ok: back !== null && firstDifference(back, content) === -1,
    detail: `${content.length.toLocaleString()} bytes`,
  });
  const after = await verify(reloaded);
  checks.push({
    check: "store-only rebuild verifies",
    ok: after.every((c) => c.ok),
    detail: `${after.filter((c) => c.ok).length}/${after.length}`,
    failed: after.filter((c) => !c.ok).map((c) => `${c.name}: ${c.detail}`),
  });

  var report_sizes = { original_syx: raw.length, rebuilt_syx: modified.length };
}

console.log(JSON.stringify({
  build: firmware.container.build,
  version: firmware.container.version,
  packets: firmware.packets,
  sections: firmware.container.sections.map((s) => ({
    id: s.id, name: name(s.id), stored: s.stored.length,
    unpacked: s.unpack()?.length ?? null,
  })),
  ...(typeof report_sizes === "undefined" ? {} : report_sizes),
  checks,
}, null, 2));
process.exit(checks.every((c) => c.ok) ? 0 : 1);
