/**
 * What every tool page does the same way.
 *
 * Both pages pick a firmware file, verify it, show its facts, build a modified
 * image, re-verify that, and offer a download. Only the middle differs — which
 * mod, and what the user adjusts.
 *
 * **Extracted 2026-09-14, after an architecture review measured the cost of not
 * having it**: `destinations-page.js` was 174 lines of which **127 were copied
 * from `transients-page.js`**, both written the same day. Six functions —
 * `wireDrop`, `addFact`, `showChecks`, `status`, and the load and build flows —
 * existed twice, already diverging in wording.
 *
 * Two rules live here rather than in each page, because they are about what
 * reaches a user and a page should not be able to forget them:
 *
 * - **Nothing is offered that has not verified.** `buildAndOffer` reloads the
 *   image it just built *from its own bytes* and re-checks it before creating a
 *   download link. Verifying the object we assembled in memory would be
 *   verifying our own intentions.
 * - **A file that does not verify stops there.** `openFirmware` refuses to hand
 *   an unverified or unsigned image to a mod at all.
 */

import { build, load, verify } from "../firmware.js";

export const $ = (id) => document.getElementById(id);

/** Drag-and-drop onto any element, with the hover state the CSS expects. */
export function wireDrop(element, onFile) {
  const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
  element.addEventListener("dragover", (e) => { stop(e); element.classList.add("over"); });
  element.addEventListener("dragleave", (e) => { stop(e); element.classList.remove("over"); });
  element.addEventListener("drop", (e) => {
    stop(e);
    element.classList.remove("over");
    const file = e.dataTransfer?.files?.[0];
    if (file) onFile(file);
  });
}

export function addFact(into, term, value) {
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  dd.textContent = value;
  into.append(dt, dd);
}

/** Render a `verify()` result. Text is set, never interpolated into HTML. */
export function showChecks(into, checks) {
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

export function status(text, busy = false) {
  const el = $("status");
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("busy", busy);
}

/**
 * Load, verify and describe a firmware file; call `onReady(firmware)` only if
 * it is a signed image that fully verifies.
 *
 * `extraFacts(firmware)` may return `[[term, value], ...]` for anything the
 * page wants beside the standard four.
 */
export async function openFirmware(file, { onReady, extraFacts = () => [] }) {
  status("Reading…", true);
  const facts = $("facts");
  const verdict = $("verdict");
  try {
    const raw = new Uint8Array(await file.arrayBuffer());
    const firmware = await load(raw);
    const checks = await verify(firmware);

    facts.innerHTML = "";
    addFact(facts, "File", file.name);
    addFact(facts, "Version", firmware.container.version || "—");
    addFact(facts, "Build", firmware.container.build || "—");
    addFact(facts, "Signed", firmware.signed
      ? `yes — key derived from “${firmware.key.derivationString}”` : "no");
    showChecks(verdict, checks);
    $("loaded").classList.remove("hidden");

    if (!checks.every((c) => c.ok)) {
      status("This file does not verify as it stands. Nothing further is offered.");
      return null;
    }
    if (!firmware.signed) {
      status("This image is unsigned, so it is not a Digitone II OS file.");
      return null;
    }

    for (const [term, value] of extraFacts(firmware)) addFact(facts, term, value);
    await onReady(firmware);
    return firmware;
  } catch (error) {
    $("loaded").classList.remove("hidden");
    showChecks(verdict, [{ name: "could not use this file", ok: false,
                           detail: String(error.message ?? error) }]);
    status("");
    return null;
  }
}

/**
 * Build with `replacements`, re-verify from the built bytes, and offer a
 * download only if every check passes.
 *
 * `suffix` names the output: `dn2_1.11.syx` -> `dn2_1.11_<suffix>.syx`.
 */
export async function buildAndOffer(firmware, replacements, {
  filename, suffix, into = $("buildVerdict"), button = $("buildBtn"), note = "",
}) {
  if (button) button.disabled = true;
  status("Rebuilding…", true);
  // One frame, so the status paints before the main thread is taken by a
  // megabyte of packing and an HMAC.
  await new Promise((r) => requestAnimationFrame(r));
  try {
    const bytes = await build(firmware, replacements);
    const reloaded = await load(bytes);
    const checks = await verify(reloaded);
    showChecks(into, checks);

    if (!checks.every((c) => c.ok)) {
      status("The rebuilt image does not verify. It is not offered for download.");
      return null;
    }

    const name = filename.replace(/\.syx$/i, "") + `_${suffix}.syx`;
    into.querySelector("a.filebtn")?.remove();
    const link = document.createElement("a");
    link.className = "filebtn";
    link.href = URL.createObjectURL(new Blob([bytes], { type: "application/octet-stream" }));
    link.download = name;
    link.textContent = `Download ${name}`;
    link.style.marginTop = ".8rem";
    into.append(link);
    link.scrollIntoView({ behavior: "smooth", block: "nearest" });
    status(`${note}${note ? " — " : ""}${bytes.length.toLocaleString()} bytes.`);
    return bytes;
  } catch (error) {
    showChecks(into, [{ name: "build failed", ok: false,
                        detail: String(error.message ?? error) }]);
    status("");
    return null;
  } finally {
    if (button) button.disabled = false;
  }
}
