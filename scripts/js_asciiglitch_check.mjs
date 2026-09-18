/**
 * The browser ASCII-glitch renderer against the Python, pixel for pixel.
 *
 *   PYTHONPATH=src python scripts/py_asciiglitch_ref.py OUT_DIR
 *   node scripts/js_asciiglitch_check.mjs --ref OUT_DIR
 */
import { readFileSync } from "node:fs";
import { frames } from "../site/js/asciiglitch.js";
import { CASES, markFromPgm } from "./asciiglitch_cases.mjs";

const arg = (n) => { const i = process.argv.indexOf(`--${n}`); return i >= 0 ? process.argv[i + 1] : null; };
const lit = markFromPgm(new Uint8Array(readFileSync("site/art/chimera.pgm")));
let ok = true;
CASES.forEach((opts, k) => {
  const js = frames(lit, opts);
  const py = new Uint8Array(readFileSync(`${arg("ref")}/case${k}.bin`));
  const flat = new Uint8Array(js.length * 128 * 64);
  js.forEach((f, i) => flat.set(f, i * 128 * 64));
  const same = flat.length === py.length && flat.every((v, i) => v === py[i]);
  ok &&= same;
  console.log(`${same ? "OK" : "FAIL"}  case ${k}: ${js.length} frames == Python`);
});
process.exit(ok ? 0 : 1);
