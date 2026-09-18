/**
 * The LFO Shape Bench: draws every shape on a 128 x 64 one-bit panel, and turns
 * a formula into a wavetable LFO Waves can import.
 *
 * Ported from the first bench (a claude.ai artifact) and brought up to what
 * ships: the LFO Waves names and knobs, TRAP and the wavetables, and an export in
 * the format `wavetable.js` reads. The shapes live in `../lfoshapes.js`.
 */

import { $ } from "./shell.js";
import { SHAPES } from "../lfoshapes.js";
import { FRAMES, sample, toTable } from "../wavetable.js";

const W = 128, H = 64, POINTS = 256;

const TEMPLATES = [
  ["staircase", "const n = 2 + Math.floor(s * 14);\nreturn 1 - (2 * Math.floor(p * n) + 1) / n;"],
  ["pulse", "return p < 0.05 + s * 0.9 ? 1 : -1;"],
  ["trapezoid", "const e = 0.02 + s * 0.48;\nif (p < e) return p / e;\nif (p < 0.5) return 1;\nif (p < 0.5 + e) return 1 - 2 * (p - 0.5) / e;\nreturn -1;"],
  ["exp decay", "return 2 * Math.exp(-(1 + s * 11) * p) - 1;"],
  ["sine power", "const v = Math.cos(2 * Math.PI * p);\nreturn Math.sign(v) * Math.abs(v) ** (1 + s * 5);"],
  ["two poles", "return 0.6 * Math.cos(2 * Math.PI * p)\n     + 0.4 * Math.cos(2 * Math.PI * p * (2 + Math.round(s * 6)));"],
  ["sine to square", "const v = Math.sin(2 * Math.PI * p);\nreturn Math.tanh(v * (1 + s * 12)) / Math.tanh(1 + s * 12);"],
];

/** Yours: a formula of p (phase 0..1) and s (0..1 across the 7 frames). */
const yours = {
  name: "YOURS", kind: "yours", what: "your wavetable, as the firmware will play it", exact: true,
  param: "POS", formula: TEMPLATES[6][1], table: null, error: "",
  means: (s) => `frame ${(Math.min(s * 49, 6144) / 1024).toFixed(2)} of 6`,
  fn: (p, s) => (yours.table ? sample(yours.table, p, s) : 0),
};

function compile() {
  try {
    const f = new Function("p", "s", `"use strict";\n${yours.formula}`);
    const frames = [];
    for (let k = 0; k < FRAMES; k++) {
      const row = [];
      for (let i = 0; i < POINTS; i++) {
        const v = Number(f(i / POINTS, k / (FRAMES - 1)));
        row.push(Number.isFinite(v) ? Math.max(-1, Math.min(1, v)) : 0);
      }
      frames.push(row);
    }
    yours.table = toTable(frames);
    yours.error = "";
  } catch (error) {
    yours.error = String(error.message ?? error);
  }
}

const all = [...SHAPES, yours];
let current = SHAPES.find((s) => s.name === "TRAP") ?? SHAPES[0];
let sph = 48;

/** A real one-bit buffer: nothing anti-aliased, because the panel cannot be. */
function render(canvas, shape, value, cycles = 2) {
  const w = canvas.width, h = canvas.height;
  const ctx = canvas.getContext("2d");
  const img = ctx.createImageData(w, h);
  for (let i = 0; i < w * h; i++) img.data.set([0, 0, 0, 255], 4 * i);
  const set = (x, y) => {
    if (x >= 0 && x < w && y >= 0 && y < h) img.data.set([236, 236, 236, 255], 4 * (y * w + x));
  };
  for (let x = 0; x < w; x += 4) set(x, (h >> 1) - 1);      // dotted zero line
  let prev = null;
  for (let x = 0; x < w; x++) {
    const t = (x / w) * cycles, cyc = Math.floor(t);
    let v;
    try { v = shape.fn(t - cyc, value, cyc); } catch { v = 0; }
    v = Number.isFinite(v) ? Math.max(-1, Math.min(1, v)) : 0;
    const y = Math.round((h - 1) / 2 - v * ((h - 3) / 2));
    if (prev !== null && Math.abs(y - prev) > 1) {
      for (let yy = Math.min(y, prev); yy <= Math.max(y, prev); yy++) set(x, yy);
    } else set(x, y);
    prev = y;
  }
  ctx.putImageData(img, 0, 0);
}

function buildSlots() {
  all.forEach((s, i) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "slot"; b.dataset.kind = s.kind;
    b.setAttribute("aria-pressed", String(s === current));
    b.innerHTML = '<span class="ix"></span><span class="nm"></span>';
    b.querySelector(".ix").textContent = s === yours ? "" : String(i);
    b.querySelector(".nm").textContent = s === yours ? "YOURS" : s.name;
    const cv = document.createElement("canvas");
    cv.width = W; cv.height = 26; cv.className = "panel";
    b.append(cv);
    b.addEventListener("click", () => select(s));
    s.thumb = cv;
    $("slots").append(b);
  });
}

function select(s) {
  current = s;
  [...$("slots").children].forEach((b, i) => b.setAttribute("aria-pressed", String(all[i] === s)));
  draw();
}

function drawSweep() {
  const host = $("sweep");
  host.innerHTML = "";
  for (let i = 0; i < 8; i++) {
    const v = Math.round((i * 127) / 7);
    const fig = document.createElement("figure");
    const cv = document.createElement("canvas");
    cv.width = W; cv.height = 34; cv.className = "panel";
    render(cv, current, v);
    const cap = document.createElement("figcaption");
    cap.textContent = v;
    fig.append(cv, cap);
    host.append(fig);
  }
}

function download() {
  const blob = new Blob([JSON.stringify({ frames: yours.table }, null, 1) + "\n"], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "my-wavetable.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function drawDef() {
  const def = $("def");
  def.innerHTML = "";
  const label = document.createElement("p");
  label.className = "label";
  if (current !== yours) {
    label.textContent = current.kind === "stock" ? "Stock shape" : "Added by LFO Waves";
    const p = document.createElement("p");
    p.textContent = current.kind === "stock"
      ? "Ships with the Digitone II. SPH is its start phase: it does not change the outline."
      : `LFO Waves renames SPH to ${current.param} on this shape. Drag it to see what it does.`;
    def.append(label, p);
    return;
  }
  label.textContent = "Your wavetable";
  const tpl = document.createElement("div");
  tpl.className = "tpl";
  for (const [name, code] of TEMPLATES) {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = name;
    b.addEventListener("click", () => { yours.formula = code; $("formula").value = code; compile(); draw(); });
    tpl.append(b);
  }
  const ta = document.createElement("textarea");
  ta.id = "formula"; ta.rows = 6; ta.spellcheck = false; ta.value = yours.formula;
  ta.setAttribute("aria-label", "Formula");
  ta.addEventListener("input", () => { yours.formula = ta.value; compile(); draw(); });
  const err = document.createElement("div");
  err.className = "err"; err.textContent = yours.error;
  const hint = document.createElement("p");
  hint.className = "hint";
  hint.textContent = "p is the phase, 0 to 1. s runs 0 to 1 across the seven frames that POS sweeps. "
    + "Return -1 to 1. The drawing is after the reduction to 7 × 32, exactly as the firmware reads it.";
  const actions = document.createElement("div");
  actions.className = "actions";
  const save = document.createElement("button");
  save.type = "button"; save.className = "primary"; save.textContent = "Download my-wavetable.json";
  save.disabled = !yours.table || Boolean(yours.error);
  save.addEventListener("click", download);
  const next = document.createElement("span");
  next.className = "hint";
  next.innerHTML = 'Then open <a href="lfo.html">LFO Waves</a> and choose it for WTB1, 2 or 3.';
  actions.append(save, next);
  def.append(label, tpl, ta, err, hint, actions);
}

function draw() {
  $("shapeName").textContent = current.name;
  $("shapeWhat").textContent = `${current.what} · ${current.exact ? "exact" : "approximate"}`;
  $("sphLabel").textContent = current.param;
  $("sphMeans").textContent = current.means ? current.means(sph) : "start phase — no effect on the outline";
  $("sweepLabel").textContent = `${current.param} swept across its range`;
  render($("scope"), current, sph);
  for (const s of all) render(s.thumb, s, sph);
  drawSweep();
  if (current === yours && $("formula")) {
    const err = $("def").querySelector(".err");
    if (err) err.textContent = yours.error;
    const save = $("def").querySelector("button.primary");
    if (save) save.disabled = !yours.table || Boolean(yours.error);
    return;
  }
  drawDef();
}

$("sph").addEventListener("input", (e) => {
  sph = Number(e.target.value);
  $("sphVal").textContent = sph;
  draw();
});

compile();
buildSlots();
$("sphVal").textContent = sph;
draw();
