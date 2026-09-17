/**
 * The MIDI Arpeggiator page: which mod, and what the user sees of it.
 * Loading, verifying, building and the download live in `shell.js`.
 */

import { $, buildAndOffer, openFirmware, status, wireDrop } from "./shell.js";
import { replacement } from "../firmware.js";
import { apply, extents } from "../mods/midiarp.js";

let state = { firmware: null, filename: "firmware.syx" };

async function ready(firmware) {
  // Applying is also the check that this image is one the mod was measured
  // against: every guard is read, and it throws rather than writing.
  apply(firmware);
  state.firmware = firmware;
  const found = extents();
  const bytes = found.reduce((n, e) => n + e.length, 0);
  $("writes").textContent = `${found.length} places in section 3, ${bytes} bytes; nothing appended`;
  for (const id of ["step2", "step3", "bar"]) $(id).classList.remove("hidden");
  status("Loaded. Ready to build.");
}

async function buildImage() {
  const { content, notes } = apply(state.firmware);
  await buildAndOffer(
    state.firmware,
    new Map([[3, replacement(state.firmware, 3, content)]]),
    { filename: state.filename, suffix: "midiarp", note: notes[1] });
}

function open(file) {
  state.filename = file.name;
  return openFirmware(file, { onReady: ready });
}

wireDrop($("drop"), open);
$("syx").addEventListener("change", (e) => {
  if (e.target.files?.[0]) open(e.target.files[0]);
});
$("buildBtn").addEventListener("click", buildImage);
$("resetBtn").addEventListener("click", () => location.reload());
