/**
 * The browser FX modulation mod against the Python, byte for byte.
 *
 *   node scripts/js_fxmod_check.mjs --syx STOCK.syx --py-content PY_CONTENT.bin
 *
 * `PY_CONTENT.bin` is MAIN OS as `dnfw.mods.fxmod.apply` produces it, which is
 * in turn byte-identical to `fxbrowser3_DN2_1.11.syx` — the image that was
 * gated and whose predecessor was flashed. So this is not "the two halves
 * agree with each other": it is "the browser produces the image that was
 * measured on the instrument".
 *
 * Checks: the same section 3, the rebuilt image verifies, and the group-name
 * longword really reads `CHR` afterwards where it read `ERR` before — the one
 * edit a byte comparison alone would not tell you the meaning of.
 */
import { readFileSync } from "node:fs";
import { build, load, replacement, verify } from "../site/js/firmware.js";
import { COUNT, apply } from "../site/js/mods/fxmod.js";

const arg = (n) => { const i = process.argv.indexOf(`--${n}`); return i >= 0 ? process.argv[i + 1] : null; };
const same = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
const checks = [];

const BASE = 0x40000400;
const CHORUS_SLOT = 0x401f7720;          // the group -> short-name table, group 16
const text = (d, va) => {
  let at = va - BASE, out = "";
  while (d[at] >= 0x20 && d[at] < 0x7f) out += String.fromCharCode(d[at++]);
  return out;
};
const pointerAt = (d, va) => {
  const at = va - BASE;
  return ((d[at] << 24) >>> 0) + (d[at + 1] << 16) + (d[at + 2] << 8) + d[at + 3];
};

const firmware = await load(new Uint8Array(readFileSync(arg("syx"))));
const before = firmware.container.find(3).unpack();
const { content, notes } = apply(firmware);

checks.push(["MAIN OS == Python", same(content, new Uint8Array(readFileSync(arg("py-content"))))]);
checks.push([`stock names group 16 'ERR' (${text(before, pointerAt(before, CHORUS_SLOT))})`,
             text(before, pointerAt(before, CHORUS_SLOT)) === "ERR"]);
checks.push([`modded names group 16 'CHR' (${text(content, pointerAt(content, CHORUS_SLOT))})`,
             text(content, pointerAt(content, CHORUS_SLOT)) === "CHR"]);
for (const [name, va] of [["17 Reverb 'REV'", 0x401f7724], ["18 Delay 'DEL'", 0x401f7728]]) {
  checks.push([`group ${name} unchanged`,
               pointerAt(before, va) === pointerAt(content, va)]);
}
checks.push([`${COUNT} destinations named for the page`, COUNT === 24]);

const built = await build(firmware, new Map([[3, replacement(firmware, 3, content)]]));
const v = await verify(await load(built));
checks.push([`rebuilt image verifies (${v.filter((c) => c.ok).length}/${v.length})`, v.every((c) => c.ok)]);

for (const [name, ok] of checks) console.log(`${ok ? "OK" : "FAIL"}  ${name}`);
console.log(notes.join("\n"));
process.exit(checks.every(([, ok]) => ok) ? 0 : 1);
