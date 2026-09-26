/**
 * The Arp Modes page: which mod, and what the user sees of it.
 * Loading, verifying, building and the download live in `shell.js`.
 */

import { $, buildAndOffer, openFirmware, status, wireDrop } from "./shell.js";
import { replacement } from "../firmware.js";
import { CAVES, EDITED_BYTES, EDITS, RAM_BYTES, apply, check } from "../mods/arpmodes.js";

// The MODE menu after the mod; the last two are new. CHRD stays hidden.
const MODES = ["OFF", "TRUE", "UP", "DOWN", "CYCL", "SHUF", "RAND"];
const NEW = new Set(["SHUF", "RAND"]);

let state = { firmware: null, filename: "firmware.syx" };

function drawModes() {
  const host = $("modes");
  host.innerHTML = "";
  for (const name of MODES) {
    const el = document.createElement("div");
    el.className = NEW.has(name) ? "param new" : "param";
    el.textContent = name;
    host.append(el);
  }
}

async function ready(firmware) {
  // Checking is also what says this image is one the mod applies to: the
  // length, every guard and every edit's stock bytes, and it throws rather
  // than writing.
  check(firmware);
  state.firmware = firmware;
  drawModes();
  $("writes").textContent =
    `${EDITS} places in section 3, ${EDITED_BYTES} bytes: two code caves `
    + `(${CAVES.map((c) => c.new.length / 2).join(" and ")} bytes), the arp step's dispatch `
    + `and five MODE bounds. ${RAM_BYTES.toLocaleString("en")} bytes of unused RAM at run time; `
    + "nothing appended, no length changes";
  for (const id of ["step2", "step3", "bar"]) $(id).classList.remove("hidden");
  status("Loaded. SHUF and RAND are ready to add.");
}

async function buildImage() {
  $("integrity").classList.add("hidden");
  const { content, notes } = apply(state.firmware);
  const bytes = await buildAndOffer(
    state.firmware,
    new Map([[3, replacement(state.firmware, 3, content)]]),
    { filename: state.filename, suffix: "arpmodes", note: notes[0] });
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
    extraFacts: () => [["Will add", "SHUF and RAND to the arpeggiator's MODE menu"]],
  });
}

wireDrop($("drop"), open);
$("syx").addEventListener("change", (e) => {
  if (e.target.files?.[0]) open(e.target.files[0]);
});
$("buildBtn").addEventListener("click", buildImage);
$("resetBtn").addEventListener("click", () => location.reload());
