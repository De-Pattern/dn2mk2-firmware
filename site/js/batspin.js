/**
 * The mark as a 1966-style spinning transition, as frames for the 128 x 64 screen.
 *
 * The browser half of `src/dnfw/batspin.py`, which explains the design. Same
 * names, same order of operations, same polynomial `sin` --
 * `scripts/js_batspin_check.mjs` requires identical pixels.
 */

import { rnd } from "./asciiglitch.js";

export const W = 128, H = 64;
const CX = 63.5, CY = 31.5;
const PI = 3.141592653589793, TWO_PI = 6.283185307179586;

export class SpinError extends Error {}

export function sin_(x) {
  x = x - TWO_PI * Math.floor(x / TWO_PI);
  if (x > PI) x -= TWO_PI;
  if (x > PI / 2) x = PI - x;
  else if (x < -PI / 2) x = -PI - x;
  const x2 = x * x;
  return x * (1 - x2 / 6 * (1 - x2 / 20 * (1 - x2 / 42 * (1 - x2 / 72))));
}
export const cos_ = (x) => sin_(x + PI / 2);
const smooth = (t) => { t = Math.min(1, Math.max(0, t)); return t * t * (3 - 2 * t); };

function bbox(lit) {
  let x0 = W, y0 = H, x1 = -1, y1 = -1;
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      if (lit(x, y)) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
    }
  }
  if (x1 < 0) throw new SpinError("the mark has no lit pixels");
  return [x0, y0, x1, y1];
}

/** -> `resolve + idleFrames` frames, each a 128 x 64 Uint8Array of 0/1, row-major. */
export function frames(lit, {
  resolve = 120, idleFrames = 48, stars = 90, smear = 1.0, spin = 3.0, zoom = 1.0, seed = 26,
} = {}) {
  if (!(resolve >= 2) || !(idleFrames >= 1)) {
    throw new SpinError("resolve needs at least two frames and the loop at least one");
  }
  if (!(stars >= 0 && stars <= 400 && smear >= 0 && smear <= 3 && spin >= 0 && spin <= 12 && zoom >= 0 && zoom <= 2)) {
    throw new SpinError("stars 0..400, smear 0..3, spin 0..12 turns, zoom 0..2");
  }
  const [x0, y0, x1, y1] = bbox(lit);
  const lcx = (x0 + x1) / 2, lcy = (y0 + y1) / 2;
  const hw = (x1 - x0) / 2 + 0.5, hh = (y1 - y0) / 2 + 0.5;
  const reach = Math.sqrt(hw * hw + hh * hh);
  const field = [];
  for (let i = 0; i < stars; i++) {
    field.push([3 + rnd(seed + i * 97) * 72, rnd(seed + i * 131) * TWO_PI, rnd(seed + i * 57) < 0.35 ? 2 : 1]);
  }

  const out = [];
  let angle = 0.0;
  const idleStep = TWO_PI / idleFrames;
  for (let k = 0; k < resolve + idleFrames; k++) {
    let scale, phi, omega;
    if (k < resolve) {
      const p = k / (resolve - 1);
      const e = smooth(p);
      const u = 1 - e;
      scale = e * (1 + zoom * 0.45 * sin_(p * 3 * PI) * (1 - p));
      phi = spin * TWO_PI * u * u;
      omega = 0.08 + 0.55 * u;
    } else {
      scale = 1.0; phi = 0.0; omega = idleStep;
    }
    const px = new Uint8Array(W * H);

    for (const [r, theta, speed] of field) {
      const a = theta + angle * speed;
      const trail = Math.min(omega * speed * smear * 1.5, TWO_PI * 0.9);
      const steps = 1 + Math.floor(trail * r);
      for (let j = 0; j < steps; j++) {
        const t = a - trail * j / steps;
        const x = Math.floor(CX + r * cos_(t) + 0.5);
        const y = Math.floor(CY + r * sin_(t) + 0.5);
        if (x >= 0 && x < W && y >= 0 && y < H) px[y * W + x] = 1;
      }
    }

    if (scale > 0.02) {
      const c = cos_(phi), s = sin_(phi);
      const lim = Math.floor(reach * scale) + 2;
      for (let y = Math.max(0, Math.floor(CY - lim)); y < Math.min(H, Math.floor(CY + lim) + 2); y++) {
        for (let x = Math.max(0, Math.floor(CX - lim)); x < Math.min(W, Math.floor(CX + lim) + 2); x++) {
          const u_ = x - CX, v_ = y - CY;
          const mx = (u_ * c + v_ * s) / scale;
          const my = (v_ * c - u_ * s) / scale;
          if (mx >= -hw && mx <= hw && my >= -hh && my <= hh) {
            const sx = Math.floor(lcx + mx + 0.5);
            const sy = Math.floor(lcy + my + 0.5);
            const on = sx >= 0 && sx < W && sy >= 0 && sy < H && lit(sx, sy);
            px[y * W + x] = on ? 1 : 0;
          }
        }
      }
    }
    out.push(px);
    angle += omega;
    if (k === resolve - 1) angle = angle - TWO_PI * Math.floor(angle / TWO_PI);
  }
  return out;
}
