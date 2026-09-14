/**
 * The Transient Swapper page: wiring, and nothing else.
 *
 * Every decision that could be *wrong* -- codec, container, integrity, bank
 * location, slot fitting -- lives in the modules under `site/js/` and is tested
 * in `test/test_js_*.py` against real firmware. This file reads the DOM, calls
 * them in order, and draws the result. It is deliberately the only untested
 * file in the stack, which is only defensible because it decides nothing.
 *
 * Two rules it does enforce, because they are about what reaches a user:
 *
 * - **Nothing downloads that has not verified.** The rebuilt image is reloaded
 *   from its own bytes and re-checked, and the download link is only created if
 *   every field passes. `docs/PRINCIPLES.md`: nothing is flashed that the
 *   toolchain cannot verify end to end, and a browser is not an excuse.
 * - **Nothing leaves the tab.** There is no fetch in this file and no server to
 *   fetch from; the page is static files.
 */

import {
  $, buildAndOffer, openFirmware as openFirmwareShell, status, wireDrop,
} from "./shell.js";
import { decode, fit } from "../audio.js";
import {
  COUNT, ENTRY_SAMPLES, RATE, apply, extract, toEntry, toFloat,
} from "../mods/transients.js";

/** Page state. One object so `reset` is one assignment and cannot half-clear. */
let state = null;

function fresh() {
  return {
    firmware: null,
    filename: "firmware.syx",
    factory: [],                  // Float32Array per slot, the original bank
    replacements: new Map(),      // slot -> { name, source, options, fitted }
  };
}

/**
 * Created on first play, not at load.
 *
 * Constructing an AudioContext eagerly means a browser that refuses one — no
 * output device, a hardened profile, a headless render — throws while this
 * module is still evaluating, and the whole page renders nothing. Audition is
 * a convenience; building firmware is the job, and the job should not depend
 * on the convenience being available.
 */
let audio = null;

function audioContext() {
  if (audio === null) {
    const Ctor = window.AudioContext || window.webkitAudioContext;
    if (!Ctor) return null;
    try {
      audio = new Ctor();
    } catch {
      return null;
    }
  }
  return audio;
}

// ---------------------------------------------------------------- step 1

async function openFirmware(file) {
  state = fresh();
  state.filename = file.name;
  return openFirmwareShell(file, {
    onReady: (firmware) => {
      state.firmware = firmware;
      state.factory = extract(firmware).map(toFloat);
      drawSlots();
      for (const id of ["step2", "step3", "bar"]) $(id).classList.remove("hidden");
      status(`Loaded. ${COUNT} slots ready.`);
    },
    extraFacts: (fw) => [["Packets", fw.packets.toLocaleString()]],
  });
}

// ---------------------------------------------------------------- step 2

function drawSlots() {
  const host = $("slots");
  host.innerHTML = "";
  for (let slot = 0; slot < COUNT; slot++) host.append(slotCard(slot));
}

function slotCard(slot) {
  const card = document.createElement("div");
  card.className = "slot";
  card.dataset.slot = String(slot);

  const top = document.createElement("div");
  top.className = "slot-top";
  const n = document.createElement("span");
  n.className = "slot-n";
  n.textContent = String(slot).padStart(2, "0");
  const name = document.createElement("span");
  name.className = "slot-name";
  name.textContent = "factory";
  // Whether this slot had to cut the user's file, and from what. The slot is
  // always 100 ms and there is no length field to change, so truncation is not
  // an edge case -- most samples people reach for are longer than 100 ms. A
  // tool that silently kept the first tenth of a second would be lying by
  // omission, and `fit` already returns the flag.
  const fit = document.createElement("span");
  fit.className = "slot-fit";
  top.append(n, name, fit);

  const canvas = document.createElement("canvas");
  canvas.width = 460;
  canvas.height = 92;
  canvas.title = "Click to hear this slot";
  canvas.addEventListener("click", () => play(currentSamples(slot)));

  const actions = document.createElement("div");
  actions.className = "slot-actions";

  const input = document.createElement("input");
  input.type = "file";
  input.accept = "audio/*";
  input.id = `file-${slot}`;
  const label = document.createElement("label");
  label.className = "filebtn";
  label.htmlFor = input.id;
  label.textContent = "Replace";
  input.addEventListener("change", () => {
    if (input.files?.[0]) loadSample(slot, input.files[0]);
  });

  const revert = document.createElement("button");
  revert.textContent = "Revert";
  revert.disabled = true;
  revert.addEventListener("click", () => {
    state.replacements.delete(slot);
    refreshSlot(slot);
    updateStatus();
  });

  actions.append(label, input, revert);

  const tune = document.createElement("div");
  tune.className = "tune hidden";

  card.append(top, canvas, actions, tune);
  wireDrop(card, (file) => loadSample(slot, file));
  requestAnimationFrame(() => paint(slot));
  return card;
}

function card(slot) {
  return $("slots").querySelector(`.slot[data-slot="${slot}"]`);
}

/** What this slot currently holds: the fitted replacement, or the factory. */
function currentSamples(slot) {
  return state.replacements.get(slot)?.fitted?.samples ?? state.factory[slot];
}

async function loadSample(slot, file) {
  status(`Decoding ${file.name}…`, true);
  try {
    const source = await decode(await file.arrayBuffer());
    const entry = {
      name: file.name,
      source,
      options: { leadMs: 3, startMs: null, gain: 1 },
      fitted: null,
    };
    entry.fitted = fit(source, entry.options);
    state.replacements.set(slot, entry);
    refreshSlot(slot);
    play(entry.fitted.samples);
    updateStatus();
    if (entry.fitted.truncated) {
      status(`${file.name} is ${(source.length / RATE).toFixed(2)}s — `
             + `cut to the ${(ENTRY_SAMPLES / RATE * 1000).toFixed(0)}ms a slot holds.`);
    }
  } catch (error) {
    status(`${file.name}: ${error.message ?? error}`);
  }
}

function refreshSlot(slot) {
  const element = card(slot);
  const entry = state.replacements.get(slot);
  element.classList.toggle("filled", Boolean(entry));
  element.querySelector(".slot-name").textContent = entry ? entry.name : "factory";

  const fit = element.querySelector(".slot-fit");
  if (!entry) {
    fit.textContent = "";
    fit.classList.remove("cut");
  } else {
    const whole = entry.source.length / RATE;
    const kept = ENTRY_SAMPLES / RATE;
    fit.classList.toggle("cut", entry.fitted.truncated);
    fit.textContent = entry.fitted.truncated
      ? `cut ${whole.toFixed(2)}s → ${(kept * 1000).toFixed(0)}ms`
      : `${(whole * 1000).toFixed(0)}ms, padded to ${(kept * 1000).toFixed(0)}ms`;
    fit.title = entry.fitted.truncated
      ? `Your file is ${whole.toFixed(2)} s. A slot holds ${(kept * 1000).toFixed(0)} ms, `
        + `so only the window starting at ${(entry.fitted.start / RATE * 1000).toFixed(0)} ms is kept. `
        + "Move it with the start control."
      : `Your file is shorter than a slot; the rest is silence.`;
  }
  element.querySelector(".slot-actions button").disabled = !entry;

  const tune = element.querySelector(".tune");
  tune.classList.toggle("hidden", !entry);
  if (entry) drawTuning(slot, tune, entry);
  paint(slot);
}

/**
 * The per-sample controls.
 *
 * Per sample and not global, because the right lead depends on the sound: a
 * sharp click wants almost none, a soft attack wants more or the onset detector
 * fires partway up the rise and cuts the front off. One value for a whole bank
 * is the kind of fixed assumption this project keeps having to retract.
 */
function drawTuning(slot, host, entry) {
  host.innerHTML = "";

  const startLimit = Math.max(0, Math.floor((entry.source.length / RATE) * 1000) - 1);
  const controls = [
    { key: "leadMs", label: "lead", min: 0, max: 50, step: 0.5, unit: "ms",
      disabled: () => entry.options.startMs !== null },
    { key: "startMs", label: "start", min: 0, max: Math.max(startLimit, 1), step: 1,
      unit: "ms", nullable: true },
    { key: "gain", label: "gain", min: 0.1, max: 4, step: 0.05, unit: "x" },
  ];

  for (const control of controls) {
    const label = document.createElement("label");
    label.textContent = control.label;

    const range = document.createElement("input");
    range.type = "range";
    range.min = String(control.min);
    range.max = String(control.max);
    range.step = String(control.step);
    range.value = String(entry.options[control.key] ?? control.min);

    const output = document.createElement("output");
    const show = () => {
      const value = entry.options[control.key];
      output.textContent = value === null ? "auto" : `${value}${control.unit}`;
      if (control.disabled) range.disabled = control.disabled();
    };
    show();

    range.addEventListener("input", () => {
      entry.options[control.key] = Number(range.value);
      entry.fitted = fit(entry.source, entry.options);
      host.querySelectorAll("output").forEach((o, i) => {
        const c = controls[i];
        const v = entry.options[c.key];
        o.textContent = v === null ? "auto" : `${v}${c.unit}`;
      });
      host.querySelectorAll("input[type=range]").forEach((r, i) => {
        if (controls[i].disabled) r.disabled = controls[i].disabled();
      });
      paint(slot);
    });
    range.addEventListener("change", () => play(entry.fitted.samples));

    host.append(label, range, output);

    // "start" is the one control with a meaningful off position: unset means
    // "find the onset for me", which is not a number on the slider's scale.
    if (control.nullable) {
      const auto = document.createElement("button");
      auto.textContent = "auto";
      auto.style.gridColumn = "1 / -1";
      auto.style.justifySelf = "start";
      auto.addEventListener("click", () => {
        entry.options.startMs = entry.options.startMs === null ? Number(range.value) : null;
        entry.fitted = fit(entry.source, entry.options);
        drawTuning(slot, host, entry);
        paint(slot);
        play(entry.fitted.samples);
      });
      host.append(auto);
    }
  }
}

/**
 * Draw one slot.
 *
 * **With no replacement:** the factory entry, filling the canvas.
 *
 * **With a replacement:** the user's *whole* file, with the 100 ms that will
 * actually be imported shaded and drawn in the accent; everything outside the
 * shaded band is greyed, because it is being thrown away.
 *
 * Drawing only the fitted 100 ms — which is what this did first — hides the
 * decision the tool just made on the user's behalf. A slot is a fixed 4,800
 * samples and most files people reach for are longer, so the interesting
 * question is never "what does the slot contain" but "which part of my sample
 * did it take". Shading it answers that, and the `start` control visibly slides
 * the band.
 */
function paint(slot) {
  const canvas = card(slot)?.querySelector("canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const { width, height } = canvas;
  const mid = height / 2;
  const style = getComputedStyle(document.documentElement);
  const ink = style.getPropertyValue("--ink-soft").trim() || "#888";
  const accent = style.getPropertyValue("--accent").trim() || "#b4530a";
  const band = style.getPropertyValue("--accent-dim").trim() || "#f0e3d6";

  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = ink;
  ctx.globalAlpha = 0.35;
  ctx.beginPath();
  ctx.moveTo(0, mid);
  ctx.lineTo(width, mid);
  ctx.stroke();
  ctx.globalAlpha = 1;

  const entry = state.replacements.get(slot);
  if (!entry) {
    trace(ctx, state.factory[slot], width, height, accent, 1, 0, width);
    return;
  }

  // The canvas spans whichever is longer: the user's file, or the window the
  // slot takes. A file *shorter* than 100 ms is padded with silence at the end,
  // and spanning only the file would hide that padding entirely -- the user
  // would see a full-width waveform and have no idea most of the slot is empty.
  const span = Math.max(entry.source.length, entry.fitted.start + ENTRY_SAMPLES);
  const from = (entry.fitted.start / span) * width;
  const to = ((entry.fitted.start + ENTRY_SAMPLES) / span) * width;
  const sourceEnd = (entry.source.length / span) * width;

  // The band first, so the waveform sits on top of it rather than under.
  ctx.fillStyle = band;
  ctx.fillRect(from, 0, Math.max(to - from, 2), height);
  ctx.strokeStyle = accent;
  ctx.globalAlpha = 0.6;
  ctx.beginPath();
  ctx.moveTo(from + 0.5, 0);
  ctx.lineTo(from + 0.5, height);
  ctx.moveTo(to - 0.5, 0);
  ctx.lineTo(to - 0.5, height);
  ctx.stroke();
  ctx.globalAlpha = 1;

  // Discarded either side in grey, the kept window in the accent. The source is
  // drawn against its own span, so it stops where the file stops and any
  // padding inside the band reads as the flat line it will actually be.
  trace(ctx, entry.source, sourceEnd, height, ink, 0.4, 0, from);
  trace(ctx, entry.source, sourceEnd, height, ink, 0.4, to, sourceEnd);
  trace(ctx, entry.source, sourceEnd, height, accent, 1, from, Math.min(to, sourceEnd));
}

/**
 * Draw `samples` across the full canvas, painting only columns in [x0, x1).
 *
 * The clip range is a column range rather than a sample range on purpose: the
 * kept window and the discarded parts must share one horizontal scale, or the
 * shaded band would not line up with the waveform under it.
 */
function trace(ctx, samples, width, height, colour, alpha, x0, x1) {
  if (!samples?.length) return;
  const mid = height / 2;
  const step = samples.length / width;
  ctx.globalAlpha = alpha;
  ctx.fillStyle = colour;
  const lo = Math.max(0, Math.floor(x0));
  const hi = Math.min(width, Math.ceil(x1));
  for (let x = lo; x < hi; x++) {
    let high = 0;
    let low = 0;
    const from = Math.floor(x * step);
    const to = Math.min(samples.length, Math.max(from + 1, Math.floor((x + 1) * step)));
    for (let i = from; i < to; i++) {
      if (samples[i] > high) high = samples[i];
      if (samples[i] < low) low = samples[i];
    }
    const top = mid - high * (mid - 1);
    const bottom = mid - low * (mid - 1);
    ctx.fillRect(x, top, 1, Math.max(1, bottom - top));
  }
  ctx.globalAlpha = 1;
}

function play(samples) {
  if (!samples?.length) return;
  const audio = audioContext();
  if (!audio) return;
  if (audio.state === "suspended") audio.resume();
  const buffer = audio.createBuffer(1, samples.length, RATE);
  buffer.copyToChannel(samples instanceof Float32Array ? samples
                       : Float32Array.from(samples), 0);
  const source = audio.createBufferSource();
  source.buffer = buffer;
  source.connect(audio.destination);
  source.start();
}

// ---------------------------------------------------------------- step 3

async function buildImage() {
  const count = state.replacements.size;
  if (!count) {
    status("Nothing replaced yet — drop audio on a slot first.");
    return;
  }
  const entries = new Map();
  for (const [slot, entry] of state.replacements) {
    entries.set(slot, toEntry(entry.fitted.samples));
  }
  const applied = apply(state.firmware, entries);
  await buildAndOffer(state.firmware, new Map([[7, applied.section]]), {
    filename: state.filename, suffix: "transients",
    note: `${count} slot${count === 1 ? "" : "s"} replaced`,
  });
}

// ---------------------------------------------------------------- wiring

function updateStatus() {
  const count = state.replacements.size;
  status(count ? `${count} of ${COUNT} slots replaced.` : `${COUNT} slots ready.`);
}

state = fresh();
wireDrop($("drop"), openFirmware);
$("syx").addEventListener("change", (event) => {
  if (event.target.files?.[0]) openFirmware(event.target.files[0]);
});
$("buildBtn").addEventListener("click", buildImage);
$("resetBtn").addEventListener("click", () => location.reload());

// Repaint on a theme change: the waveforms take their colours from the CSS
// tokens, and a canvas does not restyle itself.
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (state?.factory.length) for (let s = 0; s < COUNT; s++) paint(s);
});
