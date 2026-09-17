/**
 * The LFO Waves page: what is specific to this mod, and nothing else.
 *
 * Loading and verifying the firmware, building, re-verifying and offering the
 * download live in `shell.js`. This file shows the seven waves and lets the user
 * keep or replace each of the three wavetables, previewing a table exactly the way
 * the firmware reads it (`wavetable.sample`, the generator's bilinear arithmetic).
 */

import { $, buildAndOffer, openFirmware, status, wireDrop } from "./shell.js";
import { replacement } from "../firmware.js";
import { WavetableError, fromBytes, loadTable, sample, toBytes } from "../wavetable.js";
import { LABELS, TABLES, WAVES, apply, defaultTables } from "../mods/lfowaves.js";

const ABOUT = {
  STEP: "a staircase; STPS sets the number of steps",
  PULS: "a pulse; WDTH sets its width",
  NOIS: "noise; TYPE sets colour.loop (1.01 – 4.--)",
  TRAP: "a trapezoid; SLOP sets the edges, square to triangle",
  WTB1: "wavetable: basic shapes, sine to thin pulse",
  WTB2: "wavetable: harmonic sweep, one to fifteen harmonics",
  WTB3: "wavetable: vowels, A E I O U and back",
};
const OURS = ["basic shapes", "harmonic sweep", "vowels"];

const ours = defaultTables().map(fromBytes);
const state = {
  firmware: null,
  filename: "firmware.syx",
  slots: TABLES.map((t, k) => ({ table: ours[k], custom: null, pos: 64 })),
};

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function drawWaves() {
  const host = $("waves");
  host.innerHTML = "";
  WAVES.forEach((name, k) => {
    const el = document.createElement("div");
    el.className = "wave";
    el.innerHTML = "<b></b><span></span><small></small>";
    el.querySelector("b").textContent = name;
    el.querySelector("span").textContent = LABELS[k];
    el.querySelector("small").textContent = ABOUT[name] ?? "";
    host.append(el);
  });
}

/** Seven faint frames stacked, and the curve at POS on top, as the firmware reads it. */
function drawTable(canvas, slot) {
  const ratio = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 280, h = Math.round(w * 0.42);
  canvas.width = Math.round(w * ratio);
  canvas.height = Math.round(h * ratio);
  const g = canvas.getContext("2d");
  g.setTransform(ratio, 0, 0, ratio, 0, 0);
  g.clearRect(0, 0, w, h);
  const mid = h / 2, amp = h * 0.42;

  g.strokeStyle = css("--rule");
  g.lineWidth = 1;
  g.beginPath(); g.moveTo(0, mid); g.lineTo(w, mid); g.stroke();

  g.strokeStyle = css("--ink-soft");
  g.globalAlpha = 0.28;
  slot.table.forEach((frame) => {
    g.beginPath();
    for (let x = 0; x <= w; x++) {
      const p = (x / w) * 32, s = Math.floor(p) % 32, t = p - Math.floor(p);
      const v = (frame[s] * (1 - t) + frame[(s + 1) % 32] * t) / 127;
      x ? g.lineTo(x, mid - v * amp) : g.moveTo(x, mid - v * amp);
    }
    g.stroke();
  });
  g.globalAlpha = 1;

  g.strokeStyle = css("--accent");
  g.lineWidth = 2;
  g.beginPath();
  for (let x = 0; x <= w; x++) {
    const v = sample(slot.table, Math.min(x / w, 0.999999), slot.pos);
    x ? g.lineTo(x, mid - v * amp) : g.moveTo(x, mid - v * amp);
  }
  g.stroke();
}

function drawTables() {
  const host = $("tables");
  host.innerHTML = "";
  TABLES.forEach((t, k) => {
    const slot = state.slots[k];
    const card = document.createElement("div");
    card.className = "table" + (slot.custom ? " custom" : "");
    card.innerHTML = `
      <h3><span></span><span class="src"></span></h3>
      <canvas></canvas>
      <label class="pos">POS <input type="range" min="0" max="127"><output></output></label>
      <div class="row">
        <label class="filebtn">Use your own…<input type="file" accept=".wav,.WAV,.json" hidden></label>
        <button type="button">Use ours</button>
      </div>
      <div class="err" role="status"></div>`;
    card.querySelector("h3 span").textContent = t.name;
    card.querySelector(".src").textContent = slot.custom ?? `ours: ${OURS[k]}`;
    const canvas = card.querySelector("canvas");
    const range = card.querySelector("input[type=range]");
    const out = card.querySelector("output");
    const file = card.querySelector("input[type=file]");
    const reset = card.querySelector("button");
    const err = card.querySelector(".err");
    range.id = `pos${k + 1}`;
    file.id = `table${k + 1}`;
    range.value = slot.pos;
    out.textContent = slot.pos;
    reset.disabled = !slot.custom;

    range.addEventListener("input", () => {
      slot.pos = Number(range.value);
      out.textContent = slot.pos;
      drawTable(canvas, slot);
    });
    file.addEventListener("change", async () => {
      const f = file.files?.[0];
      if (!f) return;
      try {
        slot.table = loadTable(new Uint8Array(await f.arrayBuffer()), f.name);
        slot.custom = f.name;
        drawTables();
      } catch (e) {
        err.textContent = e instanceof WavetableError ? e.message : `could not read ${f.name}: ${e.message ?? e}`;
      }
    });
    reset.addEventListener("click", () => {
      slot.table = ours[k];
      slot.custom = null;
      drawTables();
    });
    wireDrop(card, async (f) => {
      try {
        slot.table = loadTable(new Uint8Array(await f.arrayBuffer()), f.name);
        slot.custom = f.name;
        drawTables();
      } catch (e) {
        err.textContent = e instanceof WavetableError ? e.message : `could not read ${f.name}`;
      }
    });
    host.append(card);
    requestAnimationFrame(() => drawTable(canvas, slot));
  });
}

async function ready(firmware) {
  state.firmware = firmware;
  apply(firmware);                       // refuses a non-stock or already-modded image, before any choice
  for (const id of ["step2", "step3", "step4", "bar"]) $(id).classList.remove("hidden");
  drawTables();
  status("Loaded. Keep our wavetables or replace any of them, then build.");
}

async function buildImage() {
  const tables = state.slots.map((s) => (s.custom ? toBytes(s.table) : null));
  const { content, notes } = apply(state.firmware, tables);
  await buildAndOffer(state.firmware, new Map([[3, replacement(state.firmware, 3, content)]]),
    { filename: state.filename, suffix: "lfowaves", note: notes[1] });
}

function open(file) {
  state.filename = file.name;
  return openFirmware(file, {
    onReady: ready,
    extraFacts: () => [["Adds", `${WAVES.length} LFO waveforms: ${WAVES.join(" ")}`]],
  });
}

drawWaves();
wireDrop($("drop"), open);
$("syx").addEventListener("change", (e) => { if (e.target.files?.[0]) open(e.target.files[0]); });
$("buildBtn").addEventListener("click", buildImage);
$("resetBtn").addEventListener("click", () => location.reload());
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => state.firmware && drawTables());
