/**
 * Every LFO shape the Digitone II can make with the LFO Waves mod, as functions.
 *
 * `fn(phase, sph, cycle)` returns -1..1 for a phase in [0, 1), SPH 0..127 and
 * the cycle number (only NOIS and RND use it).
 *
 * The LFO Waves shapes follow the reference arithmetic their generators were
 * checked against under Unicorn (`scripts/check_lfo_waves.py`,
 * `scripts/wavetables.py`); the wavetables read the real tables through the
 * firmware's own bilinear read (`wavetable.sample`). NOIS is the right colour
 * and loop but not the generator's exact hash. The stock shapes carried from
 * the first bench are marked `exact: false` where only the family is known.
 */

import { sample } from "./wavetable.js";
import { LABELS, WAVES, defaultTables } from "./mods/lfowaves.js";
import { fromBytes } from "./wavetable.js";

const shape = (name, kind, what, exact, param, means, fn) =>
  ({ name, kind, what, exact, param, means, fn });

/** A deterministic value per integer, -1..1 (for RND and NOIS). */
function hash(n) {
  let x = (Math.imul(n | 0, 1103515245) + 12345) >>> 0;
  x = (x ^ (x >>> 15)) >>> 0;
  x = Math.imul(x, 2246822519) >>> 0;
  x = (x ^ (x >>> 13)) >>> 0;
  return (x / 4294967295) * 2 - 1;
}

const STOCK = [
  shape("TRI", "stock", "triangle", false, "SPH", null, (p) => (p < 0.5 ? 1 - 4 * p : -3 + 4 * p)),
  shape("SIN", "stock", "sine", false, "SPH", null, (p) => Math.cos(2 * Math.PI * p)),
  shape("SQR", "stock", "square", true, "SPH", null, (p) => (p < 0.5 ? 1 : -1)),
  shape("SAW", "stock", "descending ramp", true, "SPH", null, (p) => 1 - 2 * p),
  shape("EXP", "stock", "exponential decay", false, "SPH", null, (p) => 2 * Math.exp(-6 * p) - 1),
  shape("RMP", "stock", "ascending ramp", false, "SPH", null, (p) => 2 * p - 1),
  shape("RND", "stock", "one value per cycle", true, "SPH", null, (p, s, cyc) => hash(cyc)),
];

const levels = (sph) => 2 ** (1 + (sph >> 4));
const duty = (sph) => (2 * sph + 1) / 256;
const COLOURS = ["white", "pink", "brown", "violet"];

/** Voss-McCartney style octave sums of one hash, as the generator does. */
function noise(p, sph, cyc) {
  const loop = sph & 31;
  const c = loop === 31 ? cyc : cyc % (loop + 1);
  const step = c * 64 + Math.floor(p * 64);
  const colour = sph >> 5;
  if (colour === 0) return hash(step);
  if (colour === 3) return (hash(step) - hash(step - 1)) / 2;
  let total = 0, weight = 0;
  for (let o = 0; o < 6; o++) {
    const w = colour === 1 ? 1 : 2 ** o;
    total += w * hash((step >> o) * 7919 + o * 104729);
    weight += w;
  }
  return total / weight;
}

/** TRAP: a triangle with gain 127 / SLOP, clipped; SLOP 0 is a square. */
function trap(p, sph) {
  const tri = 4 * (p < 0.5 ? p : 1 - p) - 1;
  if (sph === 0) return tri >= 0 ? 1 : -1;
  return Math.max(-1, Math.min(1, Math.trunc(tri * 127 / sph * 8388608) / 8388608));
}

const tables = defaultTables().map(fromBytes);

const ADDED = [
  shape(WAVES[0], "added", "the ramp, quantised", true, LABELS[0],
        (s) => `${levels(s)} levels`,
        (p, s) => { const n = levels(s); return 1 - (2 * Math.floor(p * n) + 1) / n; }),
  shape(WAVES[1], "added", "pulse, width from WDTH", true, LABELS[1],
        (s) => `${(duty(s) * 100).toFixed(1)}% duty`,
        (p, s) => (p < duty(s) ? 1 : -1)),
  shape(WAVES[2], "added", "noise, clocked by the phase", false, LABELS[2],
        (s) => `${1 + (s >> 5)}.${String(s & 31).padStart(2, "0")} — ${COLOURS[s >> 5]}, `
              + ((s & 31) === 31 ? "never repeats" : `repeats every ${(s & 31) + 1} cycle${(s & 31) ? "s" : ""}`),
        noise),
  shape(WAVES[3], "added", "trapezoid, edges from SLOP", true, LABELS[3],
        (s) => (s === 0 ? "square" : `edges ${(s / 127 * 100).toFixed(0)}% of a half-cycle`),
        trap),
  ...tables.map((t, k) => shape(WAVES[4 + k], "added",
        ["wavetable: basic shapes", "wavetable: harmonic sweep", "wavetable: vowels"][k], true, LABELS[4 + k],
        (s) => `frame ${(Math.min(s * 49, 6144) / 1024).toFixed(2)} of 6`,
        (p, s) => sample(t, p, s))),
];

export const SHAPES = [...STOCK, ...ADDED];
