/**
 * The browser MIDI arpeggiator mod against the Python, byte for byte.
 *
 *   node scripts/js_midiarp_check.mjs --syx STOCK.syx --py-content PY_CONTENT.bin
 *
 * `PY_CONTENT.bin` is MAIN OS as `dnfw.mods.midiarp.apply` produces it. Checks:
 * the same section 3, and the rebuilt image verifies.
 */
import { readFileSync } from "node:fs";
import { build, load, replacement, verify } from "../site/js/firmware.js";
import { apply } from "../site/js/mods/midiarp.js";

const arg = (n) => { const i = process.argv.indexOf(`--${n}`); return i >= 0 ? process.argv[i + 1] : null; };
const same = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
const checks = [];

const firmware = await load(new Uint8Array(readFileSync(arg("syx"))));
const { content, notes } = apply(firmware);
checks.push(["MAIN OS == Python", same(content, new Uint8Array(readFileSync(arg("py-content"))))]);

const built = await build(firmware, new Map([[3, replacement(firmware, 3, content)]]));
const v = await verify(await load(built));
checks.push([`rebuilt image verifies (${v.filter((c) => c.ok).length}/${v.length})`, v.every((c) => c.ok)]);

for (const [name, ok] of checks) console.log(`${ok ? "OK" : "FAIL"}  ${name}`);
console.log(notes.join("\n"));
process.exit(checks.every(([, ok]) => ok) ? 0 : 1);
