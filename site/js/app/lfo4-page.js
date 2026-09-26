/**
 * The A Fourth LFO page: which mod, and what the user sees of it.
 * Loading, verifying, building and the download live in `shell.js`.
 */

import { $, buildAndOffer, openFirmware, status, wireDrop } from "./shell.js";
import { replacement } from "../firmware.js";
import { APPENDED, EDITS, RECORDS, apply, check } from "../mods/lfo4.js";

const CONTROLS = ["SPD", "MULT", "FADE", "DEST", "WAVE", "SPH", "MODE", "DEP"];

let state = { firmware: null, filename: "firmware.syx" };

function drawControls() {
  const host = $("params");
  host.innerHTML = "";
  for (const name of CONTROLS) {
    const el = document.createElement("div");
    el.className = "param";
    el.textContent = name;
    host.append(el);
  }
}

async function ready(firmware) {
  // Checking is also what says this image is one the mod applies to: the
  // length and every edit's stock bytes, and it throws rather than writing.
  check(firmware);
  state.firmware = firmware;
  drawControls();
  $("writes").textContent =
    `${EDITS} places in section 3, and ${(APPENDED / 1000).toFixed(1)} KB appended: a start-up `
    + `loader, the compiled C that runs LFO4, and a ${RECORDS}-record copy of the parameter table `
    + "rebuilt from this file";
  for (const id of ["step2", "step3", "bar"]) $(id).classList.remove("hidden");
  status("Loaded. LFO4 is ready to add.");
}

async function buildImage() {
  $("integrity").classList.add("hidden");
  const { content, notes } = apply(state.firmware);
  const bytes = await buildAndOffer(
    state.firmware,
    new Map([[3, replacement(state.firmware, 3, content)]]),
    { filename: state.filename, suffix: "lfo4", note: notes[0] });
  const rows = $("buildVerdict").querySelectorAll(".pass, .fail");
  const passed = $("buildVerdict").querySelectorAll(".pass").length;
  if (bytes && rows.length) {
    $("integrity").textContent = `Integrity: ${passed}/${rows.length} checks pass. `
      + `${bytes.length.toLocaleString()} bytes, ready to save.`;
    $("integrity").classList.remove("hidden");
  }
}

function open(file) {
  state.filename = file.name;
  return openFirmware(file, {
    onReady: ready,
    extraFacts: () => [["Will add", "LFO4, a fourth page under [MOD]"]],
  });
}

wireDrop($("drop"), open);
$("syx").addEventListener("change", (e) => {
  if (e.target.files?.[0]) open(e.target.files[0]);
});
$("buildBtn").addEventListener("click", buildImage);
$("resetBtn").addEventListener("click", () => location.reload());
