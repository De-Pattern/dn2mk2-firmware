/**
 * The FX Modulation page: which mod, and what the user sees of it.
 * Loading, verifying, building and the download live in `shell.js`.
 */

import { $, buildAndOffer, openFirmware, status, wireDrop } from "./shell.js";
import { replacement } from "../firmware.js";
import { COUNT, DESTINATIONS, apply, check, extents } from "../mods/fxmod.js";

let state = { firmware: null, filename: "firmware.syx" };

/** "DPTH Depth" -> its short name and its full name. */
function parts(entry) {
  const at = entry.indexOf(" ");
  return { short: entry.slice(0, at), name: entry.slice(at + 1) };
}

/**
 * One block per FX group, each a grid of its parameters.
 *
 * Text is set, never interpolated into HTML: the strings come from generated
 * data rather than from the user, but a page that only escapes when it must is
 * a page that escapes wrongly one day.
 */
function drawDestinations() {
  const host = $("params");
  host.innerHTML = "";
  for (const { group, parameters } of DESTINATIONS) {
    const heading = document.createElement("p");
    heading.className = "group-name";
    heading.textContent = `${group} — ${parameters.length}`;
    const grid = document.createElement("div");
    grid.className = "params";
    for (const entry of parameters) {
      const { short, name } = parts(entry);
      const el = document.createElement("div");
      el.className = "param on";
      el.innerHTML = '<span class="sh"></span><span class="pg"></span>'
                   + '<span class="nm"></span>';
      el.querySelector(".sh").textContent = short;
      el.querySelector(".pg").textContent = group;
      el.querySelector(".nm").textContent = name;
      grid.append(el);
    }
    host.append(heading, grid);
  }
}

async function ready(firmware) {
  // Checking is also what says this image is one the mod was measured against:
  // every guard is read, and it throws rather than writing.
  check(firmware);
  state.firmware = firmware;
  const found = extents();
  const bytes = found.reduce((n, e) => n + e.length, 0);
  drawDestinations();
  $("writes").textContent =
    `${found.length} places in section 3, ${bytes} bytes; nothing appended`;
  for (const id of ["step2", "step3", "bar"]) $(id).classList.remove("hidden");
  status(`Loaded. ${COUNT} destinations ready to open.`);
}

async function buildImage() {
  const { content, notes } = apply(state.firmware);
  await buildAndOffer(
    state.firmware,
    new Map([[3, replacement(state.firmware, 3, content)]]),
    { filename: state.filename, suffix: "fxmod", note: notes[0] });
}

function open(file) {
  state.filename = file.name;
  return openFirmware(file, {
    onReady: ready,
    extraFacts: () => [["Will open", `${COUNT} FX destinations`]],
  });
}

wireDrop($("drop"), open);
$("syx").addEventListener("change", (e) => {
  if (e.target.files?.[0]) open(e.target.files[0]);
});
$("buildBtn").addEventListener("click", buildImage);
$("resetBtn").addEventListener("click", () => location.reload());
