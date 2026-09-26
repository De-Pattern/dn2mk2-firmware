/**
 * The browser arp modes mod against the CLI, byte for byte, and chained the way
 * a user chains it: one page's download loaded into the next.
 *
 *   node scripts/js_arpmodes_check.mjs --syx STOCK.syx --cli-arpmodes A.syx \
 *        --cli-midiarp-arpmodes MA.syx --cli-lfo4-arpmodes LA.syx \
 *        [--refusals-out REFUSALS.json]
 *
 * The three `--cli-*` files are the CLI's `dnfw mods apply` output for
 * `--mod arpmodes`, `--mod midiarp --mod arpmodes` and `--mod lfo4 --mod arpmodes`.
 *
 * Checks, for each: the browser's MAIN OS equals the CLI's, and the whole
 * rebuilt `.syx` does too (the file a user saves). The chained cases build the
 * first mod, reload its bytes, then apply arpmodes, as loading one page's
 * download into the next does. Also: arpmodes accepts a longer (appended) image,
 * and midiarp and lfo4 still apply after it. The refusals -- arpmodes applied
 * twice, on a shorter image, on an edited guard -- are written to
 * `--refusals-out` for the Python side to compare against its own wording.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { build, load, replacement, verify } from "../site/js/firmware.js";
import * as arpmodes from "../site/js/mods/arpmodes.js";
import * as midiarp from "../site/js/mods/midiarp.js";
import * as lfo4 from "../site/js/mods/lfo4.js";
import { CODE } from "../site/js/mods/arpmodes-code.js";

const BASE = 0x40000400;
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

/** Just enough of a firmware for a mod that reads section 3. */
const staged = (content) => ({ container: { find: () => ({ unpack: () => content }) } });

function refusal(fn) {
  try { fn(); return null; } catch (e) { return String(e.message ?? e); }
}

async function against(label, firmware, cliPath) {
  const cli = new Uint8Array(readFileSync(cliPath));
  const cliMain = (await load(cli)).container.find(3).unpack();
  const { content } = arpmodes.apply(firmware);
  checks.push([`${label}: MAIN OS == CLI`, same(content, cliMain)]);
  const built = await chain(firmware, content);
  checks.push([`${label}: rebuilt image verifies (${built.passed}/${built.total})`,
               built.passed === built.total]);
  checks.push([`${label}: .syx == CLI (${built.bytes.length} B)`, same(built.bytes, cli)]);
  return built;
}

const stock = await load(new Uint8Array(readFileSync(arg("syx"))));
const stockContent = stock.container.find(3).unpack();

// 1. stock -> arpmodes
const alone = await against("arpmodes on stock", stock, arg("cli-arpmodes"));

// 2. stock -> midiarp -> .syx -> arpmodes, and the same with lfo4 (which appends)
const ma = await chain(stock, midiarp.apply(stock).content);
checks.push([`midiarp image verifies (${ma.passed}/${ma.total})`, ma.passed === ma.total]);
await against("midiarp then arpmodes", ma.firmware, arg("cli-midiarp-arpmodes"));
const la = await chain(stock, lfo4.apply(stock).content);
checks.push([`lfo4 image verifies (${la.passed}/${la.total})`, la.passed === la.total]);
await against("lfo4 then arpmodes", la.firmware, arg("cli-lfo4-arpmodes"));

// 3. the other order applies too
checks.push(["arpmodes then midiarp: applies", refusal(() => midiarp.apply(alone.firmware)) === null]);
checks.push(["arpmodes then lfo4: applies", refusal(() => lfo4.apply(alone.firmware)) === null]);
const longer = new Uint8Array(stockContent.length + 16);
longer.set(stockContent);
checks.push(["arpmodes on a longer image: applies", refusal(() => arpmodes.apply(staged(longer))) === null]);

// 4. refusals
const guarded = stockContent.slice();
guarded[CODE.guards[0].va - BASE] ^= 0xff;
const refusals = {
  arpmodes_twice: refusal(() => arpmodes.apply(alone.firmware)),
  arpmodes_on_shorter: refusal(() => arpmodes.apply(staged(stockContent.subarray(0, stockContent.length - 16)))),
  arpmodes_on_edited_guard: refusal(() => arpmodes.apply(staged(guarded))),
};
for (const [name, why] of Object.entries(refusals)) checks.push([`refuses: ${name}`, why !== null]);
if (arg("refusals-out")) writeFileSync(arg("refusals-out"), JSON.stringify(refusals, null, 1));

for (const [name, ok] of checks) console.log(`${ok ? "OK" : "FAIL"}  ${name}`);
console.log(arpmodes.apply(stock).notes.join("\n"));
process.exit(checks.every(([, ok]) => ok) ? 0 : 1);
