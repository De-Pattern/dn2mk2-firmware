/**
 * The browser LFO waves mod and wavetable importer against the Python, byte for byte.
 *
 *   python out/ws3/pytest_lfowaves.py      (writes the Python side's outputs)
 *   node scripts/js_lfowaves_check.mjs --syx STOCK.syx --wav TABLE.wav \
 *        --py-table PY_TABLE.bin --py-content PY_CONTENT.bin
 *
 * Checks: the WAV reduces to the same 224 bytes as `dnfw.wavetable`; the mod with
 * that table in slot 2 produces the same MAIN OS as `dnfw.mods.lfowaves`; the built
 * image verifies; and the default tables round-trip.
 */
import { readFileSync } from "node:fs";
import { build, load, replacement, verify } from "../site/js/firmware.js";
import { loadTable, toBytes } from "../site/js/wavetable.js";
import { apply, defaultTables } from "../site/js/mods/lfowaves.js";

const arg = (n) => { const i = process.argv.indexOf(`--${n}`); return i >= 0 ? process.argv[i + 1] : null; };
const same = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
const checks = [];

const table = toBytes(loadTable(new Uint8Array(readFileSync(arg("wav"))), "table.wav"));
checks.push(["wavetable bytes == Python", same(table, new Uint8Array(readFileSync(arg("py-table"))))]);

const firmware = await load(new Uint8Array(readFileSync(arg("syx"))));
const { content, notes } = apply(firmware, [null, table, null]);
checks.push(["MAIN OS == Python", same(content, new Uint8Array(readFileSync(arg("py-content"))))]);

const built = await build(firmware, new Map([[3, replacement(firmware, 3, content)]]));
const v = await verify(await load(built));
checks.push([`rebuilt image verifies (${v.filter((c) => c.ok).length}/${v.length})`, v.every((c) => c.ok)]);

const defaults = apply(firmware, defaultTables());
checks.push(["default tables passed explicitly == omitted", same(defaults.content, apply(firmware).content)]);

for (const [name, ok] of checks) console.log(`${ok ? "OK" : "FAIL"}  ${name}`);
console.log(notes.join("\n"));
process.exit(checks.every(([, ok]) => ok) ? 0 : 1);
