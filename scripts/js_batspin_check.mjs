/**
 * The browser spin transition against the Python, pixel for pixel.
 *
 *   PYTHONPATH=src python scripts/py_batspin_ref.py OUT_DIR
 *   node scripts/js_batspin_check.mjs --ref OUT_DIR
 */
import { readFileSync } from "node:fs";
import { frames } from "../site/js/batspin.js";
import { markFromPgm } from "./asciiglitch_cases.mjs";

export const CASES = [
  {},
  { resolve: 30, idleFrames: 6, stars: 200, smear: 2.5, spin: 7, zoom: 2, seed: 3 },
  { resolve: 2, idleFrames: 1, stars: 0, smear: 0, spin: 0, zoom: 0 },
];
const arg = (n) => { const i = process.argv.indexOf(`--${n}`); return i >= 0 ? process.argv[i + 1] : null; };
const lit = markFromPgm(new Uint8Array(readFileSync("site/art/chimera.pgm")));
let ok = true;
CASES.forEach((opts, k) => {
  const js = frames(lit, opts);
  const py = new Uint8Array(readFileSync(`${arg("ref")}/case${k}.bin`));
  const flat = new Uint8Array(js.length * 128 * 64);
  js.forEach((f, i) => flat.set(f, i * 128 * 64));
  let diff = 0;
  for (let i = 0; i < Math.max(flat.length, py.length); i++) if (flat[i] !== py[i]) diff++;
  ok &&= diff === 0 && flat.length === py.length;
  console.log(`${diff === 0 ? "OK" : "FAIL"}  case ${k}: ${js.length} frames, ${diff} pixels differ from Python`);
});
process.exit(ok ? 0 : 1);
