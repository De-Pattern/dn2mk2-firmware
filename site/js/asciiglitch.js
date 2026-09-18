/**
 * A mark decomposed into glitching ASCII, as frames for the 128 x 64 screen.
 *
 * The browser half of `src/dnfw/asciiglitch.py`, which explains the design (a
 * port of DNX's PHOSPHOR loader to one bit and a 3 x 5 font). Same names, same
 * order of operations, same arithmetic -- `scripts/js_asciiglitch_check.mjs`
 * requires identical pixels.
 */

import { FONT } from "./font3x5.js";

export const W = 128, H = 64, CW = 4, CH = 6;
export const COLS = W / CW, ROWS = Math.floor(H / CH);
const Y0 = Math.floor((H - ROWS * CH) / 2);
export const RAMP = " .:+#";
export const GLITCH = "01/:=+<>[]{}#%*?_|-\\";
export const GLYPHS = Object.keys(FONT).join("");

export class GlitchError extends Error {}

/** DNX's stable integer noise, 0 <= r < 1. */
export function rnd(key) {
  let n = key >>> 0;
  n = Math.imul(n ^ (n >>> 16), 0x45d9f3b) >>> 0;
  n = Math.imul(n ^ (n >>> 16), 0x45d9f3b) >>> 0;
  return ((n ^ (n >>> 16)) >>> 0) / 4294967296;
}

const smooth = (t) => { t = Math.min(1, Math.max(0, t)); return t * t * (3 - 2 * t); };

export function checkChars(chars, what) {
  chars = String(chars).toUpperCase();
  const missing = [...new Set([...chars].filter((c) => !(c in FONT)))].sort();
  if (missing.length) throw new GlitchError(`${what}: no glyph for "${missing.join("")}"`);
  if (!chars.length) throw new GlitchError(`${what}: give at least one character`);
  return chars;
}

export function cells(lit) {
  const out = [];
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      let n = 0;
      for (let y = Y0 + r * CH; y < Y0 + r * CH + CH; y++) {
        for (let x = c * CW; x < c * CW + CW; x++) n += lit(x, y) ? 1 : 0;
      }
      out.push(n);
    }
  }
  return out;
}

function draw(px, ch, x0, y0) {
  FONT[ch].forEach((row, gy) => {
    const y = y0 + gy;
    if (y < 0 || y >= H) return;
    for (let gx = 0; gx < row.length; gx++) {
      const x = x0 + gx;
      if (row[gx] === "1" && x >= 0 && x < W) px[y * W + x] = 1;
    }
  });
}

/**
 * -> `resolve + idleFrames` frames, each a 128 x 64 Uint8Array of 0/1, row-major.
 * Frames 0..resolve-1 go from noise to the picture; the rest loop.
 */
export function frames(lit, {
  ramp = RAMP, glitchChars = GLITCH, resolve = 40, idleFrames = 16,
  seed = 26, glitch = 1.0, idle = 0.3,
} = {}) {
  ramp = checkChars(ramp, "picture characters");
  glitchChars = checkChars(glitchChars, "glitch characters");
  if (!(resolve >= 1) || !(idleFrames >= 0)) {
    throw new GlitchError("resolve needs at least one frame, and idle frames cannot be negative");
  }
  if (!(glitch >= 0 && glitch <= 2) || !(idle >= 0 && idle <= 1)) throw new GlitchError("glitch is 0..2 and idle 0..1");
  const cover = cells(lit);
  const steps = ramp.length - 1;
  const target = cover.map((n) => ramp[Math.floor((n * steps * 2 + 24) / 48)]);
  const g = glitchChars.length;
  const grid = [];
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      const key = (c + 7) * 733 + (r + 4) * 7919 + seed;
      grid.push([key, 0.035 + rnd(key + 19) * 0.84 + (c / COLS) * 0.11]);
    }
  }

  const out = [];
  for (let k = 0; k < resolve + idleFrames; k++) {
    const progress = k < resolve ? (resolve > 1 ? k / (resolve - 1) : 1.0) : 1.0;
    const reveal = smooth((progress - 0.10) / 0.90);
    const u = 1 - reveal;
    const chaos = u * Math.sqrt(u) * glitch;
    const idleAmt = k >= resolve ? idle : idle * smooth((progress - 0.72) / 0.28);
    const rowTick = k >> 1;
    const px = new Uint8Array(W * H);
    for (let r = 0; r < ROWS; r++) {
      const rowKey = r * 919 + rowTick * 311 + seed;
      const tearing = rnd(rowKey + 41) < 0.22 ? 2.4 : 1.0;
      let sx = Math.floor((rnd(rowKey) - 0.5) * CW * 15 * chaos * tearing + 0.5);
      const sy = Math.floor((rnd(rowKey + 11) - 0.5) * CH * 1.8 * chaos * chaos + 0.5);
      if (k >= resolve) {
        const j = k - resolve;
        if (rnd(seed * 31 + j * 977 + r * 13) < idle * 0.08) {
          const step = 1 + Math.floor(rnd(seed + j * 71 + r * 7) * 3);
          sx += rnd(seed + j * 53 + r) < 0.5 ? step : -step;
        }
      }
      for (let c = 0; c < COLS; c++) {
        const [key, lockAt] = grid[r * COLS + c];
        let ch;
        if (reveal >= lockAt) {
          ch = target[r * COLS + c];
          if (ch !== " " && rnd(key + k * 1103) < idleAmt * 0.04) {
            ch = glitchChars[Math.floor(rnd(key + k * 97) * g)];
          }
          if (ch === " ") continue;
        } else {
          const n = rnd(key + k * 13007);
          if (n > 0.50 + chaos * 0.12) continue;
          ch = glitchChars[Math.floor(rnd(key + k * 701 + 7) * g)];
          const alpha = 0.24 + rnd(key + k * 503) * 0.72;
          if (rnd(key + k * 211) > alpha) continue;
        }
        draw(px, ch, c * CW + sx, Y0 + r * CH + sy);
      }
    }
    if (chaos > 0.04) {
      for (let i = 0; i < 4; i++) {
        const yy = Math.floor(rnd(rowTick * 263 + i * 73 + seed) * H);
        const hh = Math.max(1, Math.floor(CH * (0.08 + chaos * 0.5) + 0.5));
        const dx = Math.floor((rnd(i * 31 + rowTick * 911) - 0.5) * CW * chaos * 18 + 0.5);
        for (let y = yy; y < Math.min(H, yy + hh); y++) {
          const row = px.slice(y * W, (y + 1) * W);
          for (let x = 0; x < W; x++) {
            const s = x - dx;
            px[y * W + x] = s >= 0 && s < W ? row[s] : 0;
          }
        }
      }
    }
    out.push(px);
  }
  return out;
}
