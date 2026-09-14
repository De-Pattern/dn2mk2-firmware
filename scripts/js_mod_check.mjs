/**
 * Run the browser transients mod over a real `.syx`, from the command line.
 *
 * The check that matters is the one `docs/mods.md` calls the factory
 * round-trip: **extract the bank and write it straight back.** The Python tool
 * produces a byte-identical section 7 doing this. The browser tool cannot --
 * store-only packing encodes differently -- so the standard here is that the
 * *unpacked* section comes back byte-identical, which is the same statement
 * about the bank and a weaker one only about the compressor.
 *
 * It is a strong check rather than a pleasant one: a wrong bank offset, entry
 * size, count, endianness or sample width would each corrupt bytes, and the
 * boot-stream walk that resolves the address is exercised on the way.
 *
 * `fit` is checked separately and synthetically, because its job is to make
 * judgement calls about audio and the only way to know it made the right one is
 * to feed it a signal whose answer is known in advance.
 *
 * Usage:
 *   node scripts/js_mod_check.mjs --syx FILE
 */

import { readFileSync, writeFileSync } from "node:fs";
import { build, load, verify } from "../site/js/firmware.js";
import { fit } from "../site/js/audio.js";
import {
  COUNT, ENTRY_BYTES, ENTRY_SAMPLES, RATE, apply, extents, extract, toEntry, toFloat,
} from "../site/js/mods/transients.js";

function arg(name) {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : null;
}

function same(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

const syxPath = arg("syx");
if (!syxPath) {
  console.error("usage: js_mod_check.mjs --syx FILE");
  process.exit(2);
}

const firmware = await load(new Uint8Array(readFileSync(syxPath)));
const checks = [];

// The bank, located by walking the boot stream for the block covering its load
// address -- an offset into section 7 is not an address.
const factory = extract(firmware);
const where = extents(firmware)[0];
// `--bank-out` writes the 34 entries end to end so the Python side can compare
// them against its own extraction. Locating the bank is the one thing both
// implementations do from the same measured constants, so it is the one place
// a shared misreading of those constants could hide.
if (arg("bank-out")) {
  const bank = new Uint8Array(COUNT * ENTRY_BYTES);
  factory.forEach((entry, k) => bank.set(entry, k * ENTRY_BYTES));
  writeFileSync(arg("bank-out"), bank);
}
checks.push({
  check: `bank is ${COUNT} entries of ${ENTRY_BYTES} bytes`,
  ok: factory.length === COUNT && factory.every((e) => e.length === ENTRY_BYTES),
  detail: `at section ${where.section} offset ${where.start.toLocaleString()}`,
});

// The factory round-trip. Every entry written back exactly as it came out.
const unchanged = new Map(factory.map((entry, slot) => [slot, entry]));
const applied = apply(firmware, unchanged);
const rebuilt = await load(await build(firmware, new Map([[7, applied.section]])));
const back = rebuilt.container.find(7).unpack();
const before = firmware.container.find(7).unpack();
checks.push({
  check: "factory round-trip reproduces section 7 unpacked, byte for byte",
  ok: same(back, before),
  detail: `${before.length.toLocaleString()} bytes`,
});
const after = await verify(rebuilt);
checks.push({
  check: "round-tripped image verifies",
  ok: after.every((c) => c.ok),
  detail: `${after.filter((c) => c.ok).length}/${after.length}`,
});

// One slot changed, and only that slot. A round-trip alone cannot catch a mod
// that writes nothing at all; this can.
const marker = toEntry(new Float32Array(ENTRY_SAMPLES).fill(0).map(
  (_, i) => Math.sin((2 * Math.PI * 440 * i) / RATE) * 0.5));
const one = apply(firmware, new Map([[17, marker]]));
const oneImage = await load(await build(firmware, new Map([[7, one.section]])));
const oneBack = extract(oneImage);
checks.push({
  check: "replacing slot 17 changes slot 17",
  ok: same(oneBack[17], marker),
});
checks.push({
  check: "...and leaves the other 33 alone",
  ok: oneBack.every((entry, slot) => slot === 17 || same(entry, factory[slot])),
});

// `fit`, against signals whose right answer is known in advance.
const silenceThenClick = new Float32Array(RATE);   // 1 s
silenceThenClick[4800] = 1;                        // a click exactly 100 ms in
const fitted = fit(silenceThenClick, { leadMs: 3 });
checks.push({
  check: "fit finds the onset past leading silence",
  ok: fitted.onset === 4800,
  detail: `onset ${fitted.onset}, window starts ${fitted.start}`,
});
checks.push({
  check: "fit leaves exactly leadMs of room before the onset",
  ok: fitted.start === 4800 - Math.round((3 * RATE) / 1000),
});
checks.push({
  check: "fit always returns exactly one slot",
  ok: fitted.samples.length === ENTRY_SAMPLES,
});

const explicit = fit(silenceThenClick, { startMs: 200 });
checks.push({
  check: "an explicit startMs overrides onset detection",
  ok: explicit.start === Math.round((200 * RATE) / 1000),
});

// start = 0 means the file's own beginning, not "unset". JS makes this easy to
// get wrong: 0 is falsy, so a truthiness test anywhere on this path would fall
// back to onset detection and silently skip the user's leading silence --
// exactly the thing they chose 0 to keep.
const fromZero = fit(silenceThenClick, { startMs: 0 });
checks.push({
  check: "startMs 0 takes the sample from its very start",
  ok: fromZero.start === 0,
  detail: `start ${fromZero.start}, onset would have given ${fromZero.onset}`,
});
checks.push({
  check: "startMs 0 keeps the first 100 ms verbatim",
  // The last 2 ms are faded, so compare only up to the fade.
  ok: Array.from({ length: ENTRY_SAMPLES - 120 }, (_, i) => i)
    .every((i) => fromZero.samples[i] === silenceThenClick[i]),
});

const loud = new Float32Array(ENTRY_SAMPLES).fill(1);
const faded = fit(loud, { startMs: 0 });
checks.push({
  check: "fit fades the last 2 ms so the cut adds no click",
  ok: faded.samples[ENTRY_SAMPLES - 1] === 0 && faded.samples[0] === 1,
  detail: `last sample ${faded.samples[ENTRY_SAMPLES - 1]}`,
});

// A factory entry survives Float32 and back. Catches a scaling error that a
// round-trip of raw bytes would never see, because it never converts.
const original = factory[0];
checks.push({
  check: "int16 -> float -> int16 is lossless for a factory entry",
  ok: same(toEntry(toFloat(original)), original),
});

console.log(JSON.stringify({ checks }, null, 2));
process.exit(checks.every((c) => c.ok) ? 0 : 1);
