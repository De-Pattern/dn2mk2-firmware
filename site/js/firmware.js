/**
 * Loading and rebuilding a `.syx` OS file: the three layers tied together.
 *
 * Port of `src/dnfw/firmware/{load,build,verify}.py`. Kept as one module
 * because it is one subject -- the order the layers go in -- and that order is
 * not negotiable:
 *
 *   load:   transport -> preamble -> container -> key
 *   build:  sections  -> trailer  -> content checksum -> transport
 *
 * Each integrity field covers everything decided before it, so computing one
 * early silently invalidates it. The `.syx` the browser hands back is only
 * valid because these run in this order.
 */

import { concat, indexOf, setU32, u32 } from "./bytes.js";
import * as ele3 from "./container/ele3.js";
import { compress, storeRaw } from "./container/section.js";
import * as contentChecksum from "./integrity/checksum.js";
import * as digest from "./integrity/digest.js";
import * as keyderive from "./integrity/keyderive.js";
import * as transport from "./syx/transport.js";
import { profile } from "./profile.js";
import { MAX_MATCH, WINDOW } from "./limits.js";
import { STORED_ALIGN } from "./container/section.js";

const PREAMBLE = 8;  // [u32 container size][u32 content checksum]

/**
 * Parse a `.syx` file. Throws if it is not an ELE3 OS image.
 *
 * `storedChecksum` and `packets` are what the file *claimed*, kept so `verify`
 * can compare them against what we compute rather than silently recomputing
 * and reporting success.
 */
export async function load(raw) {
  const decoded = transport.decode(raw);
  const stream = decoded.stream;

  const magic = indexOf(stream, ele3.MAGIC);
  if (magic < PREAMBLE) throw new Error("no ELE3 container in this file");
  const declaredSize = u32(stream, magic - PREAMBLE);
  const storedChecksum = u32(stream, magic - 4);

  const rawContainer = stream.subarray(magic);
  const container = ele3.parse(rawContainer, declaredSize);

  return {
    envelope: decoded.envelope,
    container,
    rawContainer,
    key: await findKey(rawContainer, declaredSize, container),
    storedChecksum,
    packets: decoded.packets,
    checksumsOk: decoded.checksumsOk,
    checksumsBad: decoded.checksumsBad,
    get signed() { return this.key !== null; },
  };
}

/**
 * Wrap new content for `sectionId` the way that section is stored.
 *
 * A section that depacks is recompressed; one that does not is stored raw. The
 * decision is taken from the **original section**, not from an argument,
 * because getting it backwards produces a file that passes every checksum and
 * bricks the instrument.
 */
export function replacement(firmware, sectionId, content) {
  const original = firmware.container.find(sectionId);
  if (original === null) throw new Error(`no section id=${sectionId} in this image`);
  return original.unpack() !== null
    ? compress(sectionId, original.dest, content)
    : storeRaw(sectionId, original.dest, content);
}

/**
 * The complete `.syx` bytes for this firmware, with `replacements` applied.
 * `replacements` is a Map of section id -> Section, normally built with
 * `replacement()` above.
 */
export async function build(firmware, replacements = new Map()) {
  const body = ele3.assemble(firmware.container, replacements);
  const container = firmware.key !== null
    ? await digest.append(body, firmware.key.value)
    : digest.padUnsigned(body);

  const preamble = new Uint8Array(PREAMBLE);
  setU32(preamble, 0, container.length);
  setU32(preamble, 4, contentChecksum.content(container));

  return transport.encode(concat(preamble, container), firmware.envelope);
}

/**
 * Every integrity field this firmware carries -> `[{ name, ok, detail }]`.
 *
 * Run on a *rebuild* before offering it for download. Nothing leaves the page
 * that has not verified here: `docs/PRINCIPLES.md` -- nothing is flashed that
 * the toolchain cannot verify end to end -- and a browser is not an excuse.
 */
export async function verify(firmware) {
  const checks = [];
  const total = firmware.checksumsOk + firmware.checksumsBad;
  checks.push({
    name: "transport packet checksums",
    ok: firmware.checksumsBad === 0,
    detail: `${firmware.checksumsOk}/${total} packets`,
  });

  const size = firmware.container.declaredSize;
  const calculated = contentChecksum.content(firmware.rawContainer.subarray(0, size));
  checks.push({
    name: "container content checksum",
    ok: calculated === firmware.storedChecksum,
    detail: `stored 0x${firmware.storedChecksum.toString(16).padStart(8, "0")}`
          + ` calculated 0x${calculated.toString(16).padStart(8, "0")}`,
  });

  for (const section of firmware.container.sections) {
    const label = `section ${section.id} (${ele3.name(section.id)})`;
    const content = section.unpack();
    if (content === null) {
      checks.push({ name: `${label} byte-sum`, ok: true, detail: "stored raw" });
      checks.push({ name: `${label} padded`, ok: true,
                    detail: "stored raw, not padded by Elektron either" });
      checks.push({ name: `${label} within Elektron's limits`, ok: true,
                    detail: "stored raw, nothing to decompress" });
      continue;
    }

    let sum = 0;
    const end = Math.min(8 + section.declaredLength, section.stored.length);
    for (let i = 8; i < end; i++) sum = (sum + section.stored[i]) >>> 0;
    checks.push({
      name: `${label} byte-sum`,
      ok: sum === u32(section.stored, 4),
      detail: `${section.declaredLength.toLocaleString()} bytes`,
    });

    // Elektron pad every compressed section to four bytes. A section that is
    // not padded can still checksum correctly, and images built without it
    // stall in recovery.
    const remainder = section.stored.length % STORED_ALIGN;
    checks.push({
      name: `${label} padded to ${STORED_ALIGN} bytes`,
      ok: remainder === 0,
      detail: `${section.stored.length.toLocaleString()} bytes stored`
            + (remainder ? `, ${remainder} past a ${STORED_ALIGN}-byte boundary` : ""),
    });

    // And a stream can checksum perfectly while asking more of the depacker
    // than any Elektron stream does. That is the failure this project has
    // actually hit, so it is checked rather than assumed.
    const p = profile(section.stream);
    let detail = `furthest match ${p.maxOffset.toLocaleString()} of a `
               + `${WINDOW.toLocaleString()}-byte window, longest `
               + `${p.maxLength.toLocaleString()} of ${MAX_MATCH.toLocaleString()}`;
    if (p.beyond) detail += `; ${p.beyond.toLocaleString()} matches reach past it`;
    checks.push({
      name: `${label} within Elektron's limits`,
      ok: p.withinLimits,
      detail,
    });
  }

  if (firmware.key !== null) {
    checks.push({
      name: "HMAC-SHA256 trailer",
      ok: await digest.verify(
        firmware.key.value, firmware.rawContainer.subarray(0, size)),
      detail: `key derived from "${firmware.key.derivationString}"`,
    });
  }

  return checks;
}

/**
 * Recover the signing key, or null when the image is unsigned.
 *
 * Two short-circuits, both of which matter. An all-zero trailer means
 * unsigned, and scanning for a key that cannot exist would mean depacking
 * every section for nothing. And sections are searched **smallest first**,
 * because the Digitone II key material lives in the 16 KB bootstrap section,
 * so the 3 MB MAIN OS never has to be depacked to sign a build -- which in a
 * browser is the difference between instant and a visible freeze.
 */
async function findKey(rawContainer, declaredSize, container) {
  if (declaredSize < digest.DIGEST_BYTES + 4 || declaredSize > rawContainer.length) {
    return null;
  }
  const expected = rawContainer.subarray(declaredSize - digest.DIGEST_BYTES, declaredSize);
  if (!expected.some((b) => b !== 0)) return null;

  const message = rawContainer.subarray(0, declaredSize - digest.DIGEST_BYTES);
  const ordered = [...container.sections].sort((a, b) => a.stored.length - b.stored.length);

  function* blobs() {
    for (const section of ordered) {
      const content = section.unpack();
      if (content) yield content;
    }
  }
  return keyderive.find(blobs(), message, expected);
}
