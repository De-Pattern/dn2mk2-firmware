/**
 * The browser boot-screen mod against the Python, byte for byte.
 *
 *   PYTHONPATH=src python scripts/py_bootscreen_ref.py STOCK.zip OUT_DIR
 *   node scripts/js_bootscreen_check.mjs --syx STOCK.syx --pgm site/art/chimera.pgm --ref OUT_DIR
 *
 * `OUT_DIR` holds MAIN OS from `dnfw.mods.bootscreen.apply` for the two cases
 * below. Checks: the same section 3 for a static mark with the stock tunnel,
 * and for a flashing pair with a re-scaled tunnel; and each rebuilt image verifies.
 */
import { readFileSync } from "node:fs";
import { build, load, replacement, verify } from "../site/js/firmware.js";
import { apply, imageFromPixels, invert } from "../site/js/mods/bootscreen.js";

const arg = (n) => { const i = process.argv.indexOf(`--${n}`); return i >= 0 ? process.argv[i + 1] : null; };
const same = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);

/** A 128x64 binary PGM (P5), thresholded at half -- as the CLI reads it. */
function readPgm(bytes) {
  let at = 0, fields = [];
  while (fields.length < 4) {
    while (bytes[at] === 0x20 || bytes[at] === 0x0a || bytes[at] === 0x0d || bytes[at] === 0x09) at++;
    let s = "";
    while (!(bytes[at] === 0x20 || bytes[at] === 0x0a || bytes[at] === 0x0d || bytes[at] === 0x09)) s += String.fromCharCode(bytes[at++]);
    fields.push(s);
  }
  at++;
  if (fields[0] !== "P5" || fields[1] !== "128" || fields[2] !== "64") throw new Error("not a 128x64 P5");
  const pix = bytes.subarray(at);
  return (x, y) => pix[y * 128 + x] > 127;
}

const firmware = await load(new Uint8Array(readFileSync(arg("syx"))));
const mark = imageFromPixels(readPgm(new Uint8Array(readFileSync(arg("pgm")))));
const cases = [
  ["static, stock tunnel", [mark], {}],
  ["flashing, tunnel 96 x 48", [mark, invert(mark)], { slow: 4, fast: 3, rush: 48, stop: 72, tunnel: [96, 48] }],
];

const checks = [];
for (const [k, [name, images, opts]] of cases.entries()) {
  const { content } = apply(firmware, images, opts);
  checks.push([`${name}: MAIN OS == Python`, same(content, new Uint8Array(readFileSync(`${arg("ref")}/case${k}.bin`)))]);
  const built = await build(firmware, new Map([[3, replacement(firmware, 3, content)]]));
  const v = await verify(await load(built));
  checks.push([`${name}: rebuilt image verifies (${v.filter((c) => c.ok).length}/${v.length})`, v.every((c) => c.ok)]);
}
for (const [name, ok] of checks) console.log(`${ok ? "OK" : "FAIL"}  ${name}`);
process.exit(checks.every(([, ok]) => ok) ? 0 : 1);
