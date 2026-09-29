/**
 * The browser platform against the Python, byte for byte, chained the way a user
 * chains pages: one page's download loaded into the next.
 *
 *   node scripts/js_platform_check.mjs --syx STOCK.syx --py-dir DIR [--refusals-out R.json]
 *
 * DIR holds the Python side's MAIN OS for each case (`test/test_js_platform.py`
 * writes them): lfowaves.bin, bootscreen.bin (a static mark, the diagonal
 * y = x / 2), waves_boot.bin (lfowaves then bootscreen) and trio.bin (lfowaves,
 * bootscreen, lfo4). Every image is rebuilt, re-signed and reloaded before the
 * next mod sees it, and each rebuilt image must verify.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { build, load, replacement, verify } from "../site/js/firmware.js";
import * as lfo4 from "../site/js/mods/lfo4.js";
import * as lfowaves from "../site/js/mods/lfowaves.js";
import * as bootscreen from "../site/js/mods/bootscreen.js";

const arg = (n) => { const i = process.argv.indexOf(`--${n}`); return i >= 0 ? process.argv[i + 1] : null; };
const same = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
const py = (name) => new Uint8Array(readFileSync(`${arg("py-dir")}/${name}`));
const checks = [];

async function chain(firmware, content) {
  const bytes = await build(firmware, new Map([[3, replacement(firmware, 3, content)]]));
  const reloaded = await load(bytes);
  const v = await verify(reloaded);
  return { firmware: reloaded, passed: v.filter((c) => c.ok).length, total: v.length };
}

function refusal(fn) {
  try { fn(); return null; } catch (e) { return String(e.message ?? e); }
}

const mark = [bootscreen.imageFromPixels((x, y) => y === x >> 1)];
const run = {
  lfowaves: (f) => lfowaves.apply(f).content,
  bootscreen: (f) => bootscreen.apply(f, mark).content,
  lfo4: (f) => lfo4.apply(f).content,
};
const stock = await load(new Uint8Array(readFileSync(arg("syx"))));

const cases = [["lfowaves.bin", ["lfowaves"]], ["bootscreen.bin", ["bootscreen"]],
               ["waves_boot.bin", ["lfowaves", "bootscreen"]],
               ["trio.bin", ["lfowaves", "bootscreen", "lfo4"]]];
for (const [file, order] of cases) {
  let firmware = stock, content = null;
  for (const mod of order) {
    content = run[mod](firmware);
    const next = await chain(firmware, content);
    checks.push([`${order.join(" then ")}: after ${mod}, the rebuilt image verifies `
                 + `(${next.passed}/${next.total})`, next.passed === next.total]);
    firmware = next.firmware;
  }
  checks.push([`${order.join(" then ")}: MAIN OS == Python`, same(content, py(file))]);
}

const withLfo4 = await chain(stock, run.lfo4(stock));
const withBoot = await chain(stock, run.bootscreen(stock));
const refusals = {
  lfowaves_after_lfo4: refusal(() => lfowaves.apply(withLfo4.firmware)),
  bootscreen_twice: refusal(() => bootscreen.apply(withBoot.firmware, mark)),
};
for (const [name, why] of Object.entries(refusals)) checks.push([`refuses: ${name}`, why !== null]);
if (arg("refusals-out")) writeFileSync(arg("refusals-out"), JSON.stringify(refusals, null, 1));

for (const [name, ok] of checks) console.log(`${ok ? "OK" : "FAIL"}  ${name}`);
process.exit(checks.every(([, ok]) => ok) ? 0 : 1);
