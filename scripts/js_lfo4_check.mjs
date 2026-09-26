/**
 * The browser LFO4 mod against the Python, byte for byte, and chained the way a
 * user chains it: one page's download loaded into the next.
 *
 *   node scripts/js_lfo4_check.mjs --syx STOCK.syx --py-lfo4 LFO4.bin \
 *        --py-fx-lfo4 FX_LFO4.bin --py-moddest-lfo4 MODDEST_LFO4.bin  *        [--refusals-out REFUSALS.json]
 *
 * `LFO4.bin` is MAIN OS as `dnfw.mods.lfo4.compose` makes it from stock, which
 * `scripts/gen_lfo4_code.py` checks byte for byte against the release build.
 * `FX_LFO4.bin` is MAIN OS of the CLI's `--mod fxmod --mod lfo4`, and
 * `MODDEST_LFO4.bin` is `lfo4.compose` over `moddest.apply`'s MAIN OS: moddest's
 * thirteen opened masks have to arrive in the relocated table on both sides.
 *
 * Checks: stock -> lfo4 equals the Python; fxmod -> build -> reload -> lfo4
 * equals the CLI's pair; moddest then lfo4 equals the Python; lfo4 accepts a
 * midiarp image; the rebuilt images verify. The refusals -- lfo4 on an
 * lfowaves image, on a longer image, on an edited site, and fxmod and moddest
 * on an lfo4 image -- are written to `--refusals-out` for the Python side to
 * compare against its own wording.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { build, load, replacement, verify } from "../site/js/firmware.js";
import * as lfo4 from "../site/js/mods/lfo4.js";
import * as fxmod from "../site/js/mods/fxmod.js";
import * as moddest from "../site/js/mods/moddest.js";
import * as lfowaves from "../site/js/mods/lfowaves.js";
import * as midiarp from "../site/js/mods/midiarp.js";

const arg = (n) => { const i = process.argv.indexOf(`--${n}`); return i >= 0 ? process.argv[i + 1] : null; };
const same = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
const checks = [];

/** Build with a new section 3 and load the result, as a download re-opened would be. */
async function chain(firmware, content) {
  const bytes = await build(firmware, new Map([[3, replacement(firmware, 3, content)]]));
  const reloaded = await load(bytes);
  const v = await verify(reloaded);
  return { bytes, firmware: reloaded, passed: v.filter((c) => c.ok).length, total: v.length };
}

function refusal(fn) {
  try { fn(); return null; } catch (e) { return String(e.message ?? e); }
}

const stock = await load(new Uint8Array(readFileSync(arg("syx"))));
const stockContent = stock.container.find(3).unpack();

// 1. stock -> lfo4
const alone = lfo4.apply(stock);
checks.push(["lfo4 on stock: MAIN OS == Python", same(alone.content, new Uint8Array(readFileSync(arg("py-lfo4"))))]);
const built = await chain(stock, alone.content);
checks.push([`lfo4 on stock: rebuilt image verifies (${built.passed}/${built.total}), `
             + `${built.bytes.length} B .syx, MAIN OS ${alone.content.length} B`, built.passed === built.total]);

// 2. stock -> fxmod -> .syx -> lfo4, the browser's way of chaining
const fx = await chain(stock, fxmod.apply(stock).content);
checks.push([`fxmod image verifies (${fx.passed}/${fx.total})`, fx.passed === fx.total]);
const pair = lfo4.apply(fx.firmware);
checks.push(["fxmod then lfo4: MAIN OS == CLI --mod fxmod --mod lfo4",
             same(pair.content, new Uint8Array(readFileSync(arg("py-fx-lfo4"))))]);
const pairBuilt = await chain(fx.firmware, pair.content);
checks.push([`fxmod then lfo4: rebuilt image verifies (${pairBuilt.passed}/${pairBuilt.total})`,
             pairBuilt.passed === pairBuilt.total]);

// 3. the other mods lfo4 is applied after: moddest (table edits) and midiarp
checks.push(["moddest then lfo4: MAIN OS == Python",
             same(lfo4.compose(moddest.apply(stock).content),
                  new Uint8Array(readFileSync(arg("py-moddest-lfo4"))))]);
checks.push(["midiarp then lfo4: applies",
             refusal(() => lfo4.compose(midiarp.apply(stock).content)) === null]);

// 4. refusals
const longer = new Uint8Array(stockContent.length + 16);
longer.set(stockContent);
const edited = stockContent.slice();
edited[lfo4.extents()[0].start] ^= 0xff;
const waves = lfowaves.apply(stock).content;
const refusals = {
  lfo4_after_lfowaves: refusal(() => lfo4.compose(waves)),
  lfo4_on_longer: refusal(() => lfo4.compose(longer)),
  lfo4_on_edited: refusal(() => lfo4.compose(edited)),
  fxmod_after_lfo4: refusal(() => fxmod.apply(built.firmware)),
  moddest_after_lfo4: refusal(() => moddest.apply(built.firmware)),
};
for (const [name, why] of Object.entries(refusals)) checks.push([`refuses: ${name}`, why !== null]);
if (arg("refusals-out")) writeFileSync(arg("refusals-out"), JSON.stringify(refusals, null, 1));


for (const [name, ok] of checks) console.log(`${ok ? "OK" : "FAIL"}  ${name}`);
console.log(alone.notes.join("\n"));
process.exit(checks.every(([, ok]) => ok) ? 0 : 1);
