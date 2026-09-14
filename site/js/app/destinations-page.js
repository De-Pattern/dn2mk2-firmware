/**
 * The Modulation Destinations page: wiring, and nothing else.
 *
 * Same shape as `transients-page.js` and for the same reason — every decision
 * that could be wrong lives in tested modules, and this file reads the DOM,
 * calls them in order, and draws the result.
 *
 * The one rule it enforces: **nothing downloads that has not verified.** The
 * rebuilt image is reloaded from its own bytes and re-checked before a download
 * link exists, because verifying the object we just built in memory would be
 * verifying our own intentions.
 */

import { build, load, replacement, verify } from "../firmware.js";
import { TARGETS, apply, extents } from "../mods/moddest.js";

const $ = (id) => document.getElementById(id);

let state = { firmware: null, filename: "firmware.syx" };

function wireDrop(element, onFile) {
  const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
  element.addEventListener("dragover", (e) => { stop(e); element.classList.add("over"); });
  element.addEventListener("dragleave", (e) => { stop(e); element.classList.remove("over"); });
  element.addEventListener("drop", (e) => {
    stop(e);
    element.classList.remove("over");
    const file = e.dataTransfer?.files?.[0];
    if (file) openFirmware(file);
  });
}

function addFact(term, value) {
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  dd.textContent = value;
  $("facts").append(dt, dd);
}

function showChecks(into, checks) {
  into.innerHTML = "";
  for (const check of checks) {
    const row = document.createElement("div");
    row.className = check.ok ? "pass" : "fail";
    const mark = document.createElement("span");
    mark.className = "mark";
    mark.textContent = check.ok ? "OK" : "X";
    const text = document.createElement("span");
    text.textContent = check.detail ? `${check.name} — ${check.detail}` : check.name;
    row.append(mark, text);
    into.append(row);
  }
}

function status(text, busy = false) {
  $("status").textContent = text;
  $("status").classList.toggle("busy", busy);
}

/** The page/label split in each target's label: "SYN A Trig (ATRG)". */
function parts(label) {
  const m = /^(.*?)\s*\(([^)]+)\)$/.exec(label);
  const full = m ? m[1] : label;
  const short = m ? m[2] : "";
  const page = full.split(" ")[0];
  return { page, name: full, short };
}

function drawParams(found) {
  const host = $("params");
  host.innerHTML = "";
  // `extents()` names the range in `what`, not `label` -- the mod system's
  // vocabulary, not this mod's. Reading `label` here left every card
  // undefined and took the page down with it.
  for (const { what } of found) {
    const { page, name, short } = parts(what);
    const el = document.createElement("div");
    el.className = "param on";
    el.innerHTML = `<span class="sh"></span><span class="pg"></span>`
                 + `<span class="nm"></span>`;
    el.querySelector(".sh").textContent = short;
    el.querySelector(".pg").textContent = page;
    el.querySelector(".nm").textContent = name;
    host.append(el);
  }
}

async function openFirmware(file) {
  status("Reading…", true);
  try {
    const raw = new Uint8Array(await file.arrayBuffer());
    const firmware = await load(raw);
    const checks = await verify(firmware);

    state = { firmware, filename: file.name };

    $("facts").innerHTML = "";
    addFact("File", file.name);
    addFact("Version", firmware.container.version || "—");
    addFact("Build", firmware.container.build || "—");
    addFact("Signed", firmware.signed
      ? `yes — key derived from “${firmware.key.derivationString}”` : "no");
    showChecks($("verdict"), checks);
    $("loaded").classList.remove("hidden");

    if (!checks.every((c) => c.ok)) {
      status("This file does not verify as it stands. Nothing further is offered.");
      return;
    }
    if (!firmware.signed) {
      status("This image is unsigned, so it is not a Digitone II OS file.");
      return;
    }

    // Resolving the targets is also the check that this image is one the mod
    // was measured against: it throws rather than writing somewhere plausible.
    const found = extents(firmware);
    drawParams(found);
    addFact("Will change", `${found.length} bytes in section 3`);
    $("step2").classList.remove("hidden");
    $("step3").classList.remove("hidden");
    $("bar").classList.remove("hidden");
    status(`Loaded. ${TARGETS.length} parameters ready to open.`);
  } catch (error) {
    $("loaded").classList.remove("hidden");
    showChecks($("verdict"), [{ name: "could not use this file", ok: false,
                                detail: String(error.message ?? error) }]);
    status("");
  }
}

async function buildImage() {
  $("buildBtn").disabled = true;
  status("Rebuilding…", true);
  await new Promise((r) => requestAnimationFrame(r));
  try {
    const { content, notes } = apply(state.firmware);
    const bytes = await build(state.firmware,
      new Map([[3, replacement(state.firmware, 3, content)]]));

    const reloaded = await load(bytes);
    const checks = await verify(reloaded);
    showChecks($("buildVerdict"), checks);
    if (!checks.every((c) => c.ok)) {
      status("The rebuilt image does not verify. It is not offered for download.");
      $("buildBtn").disabled = false;
      return;
    }

    const name = state.filename.replace(/\.syx$/i, "") + "_destinations.syx";
    const link = document.createElement("a");
    link.className = "filebtn";
    link.href = URL.createObjectURL(new Blob([bytes], { type: "application/octet-stream" }));
    link.download = name;
    link.textContent = `Download ${name}`;
    link.style.marginTop = ".8rem";
    $("buildVerdict").querySelector("a.filebtn")?.remove();
    $("buildVerdict").append(link);
    status(`${notes[notes.length - 1]} — ${bytes.length.toLocaleString()} bytes.`);
  } catch (error) {
    showChecks($("buildVerdict"), [{ name: "build failed", ok: false,
                                     detail: String(error.message ?? error) }]);
    status("");
  }
  $("buildBtn").disabled = false;
}

wireDrop($("drop"), openFirmware);
$("syx").addEventListener("change", (e) => {
  if (e.target.files?.[0]) openFirmware(e.target.files[0]);
});
$("buildBtn").addEventListener("click", buildImage);
$("resetBtn").addEventListener("click", () => location.reload());
