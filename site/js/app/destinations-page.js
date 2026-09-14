/**
 * The Modulation Destinations page: what is specific to this mod, and nothing
 * else.
 *
 * Everything both tool pages do the same way — drag and drop, loading and
 * verifying a firmware file, showing its facts, building and re-verifying,
 * offering a download — lives in `shell.js`. This file is the middle: which
 * mod, and what the user sees of it.
 */

import { $, buildAndOffer, openFirmware, status, wireDrop } from "./shell.js";
import { replacement } from "../firmware.js";
import { TARGETS, apply, extents } from "../mods/moddest.js";

let state = { firmware: null, filename: "firmware.syx" };

/** "SYN A Trig (ATRG)" -> its page, full name and short name. */
function parts(label) {
  const m = /^(.*?)\s*\(([^)]+)\)$/.exec(label ?? "");
  const full = m ? m[1] : (label ?? "");
  return { page: full.split(" ")[0], name: full, short: m ? m[2] : "" };
}

function drawParams(found) {
  const host = $("params");
  host.innerHTML = "";
  // `extents()` names each range in `what`, the mod system's vocabulary rather
  // than this mod's. Reading `label` here left every card undefined and took
  // the page down with it -- found by rendering the page, not by reading it.
  for (const { what } of found) {
    const { page, name, short } = parts(what);
    const el = document.createElement("div");
    el.className = "param on";
    el.innerHTML = '<span class="sh"></span><span class="pg"></span>'
                 + '<span class="nm"></span>';
    el.querySelector(".sh").textContent = short;
    el.querySelector(".pg").textContent = page;
    el.querySelector(".nm").textContent = name;
    host.append(el);
  }
}

async function ready(firmware) {
  state.firmware = firmware;
  // Resolving the targets is also the check that this image is one the mod was
  // measured against: it throws rather than writing somewhere plausible.
  const found = extents(firmware);
  drawParams(found);
  for (const id of ["step2", "step3", "bar"]) $(id).classList.remove("hidden");
  status(`Loaded. ${TARGETS.length} parameters ready to open.`);
}

async function buildImage() {
  const { content, notes } = apply(state.firmware);
  await buildAndOffer(
    state.firmware,
    new Map([[3, replacement(state.firmware, 3, content)]]),
    { filename: state.filename, suffix: "destinations",
      note: notes[notes.length - 1] });
}

function open(file) {
  state.filename = file.name;
  return openFirmware(file, {
    onReady: ready,
    extraFacts: (fw) => [["Will change", `${extents(fw).length} bytes in section 3`]],
  });
}

wireDrop($("drop"), open);
$("syx").addEventListener("change", (e) => {
  if (e.target.files?.[0]) open(e.target.files[0]);
});
$("buildBtn").addEventListener("click", buildImage);
$("resetBtn").addEventListener("click", () => location.reload());
