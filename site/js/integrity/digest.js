/**
 * The container's HMAC-SHA256 trailer: where it sits, and how to write it.
 *
 * Port of `src/dnfw/integrity/digest.py`, from `append_trailer` and
 * `syx_content_digest` in mischa85/elektron-firmware-tool, MIT.
 *
 * The trailer is the last 32 bytes of the declared container. It is placed on
 * the first 16-byte boundary at least four bytes past the end of the sections,
 * the gap is zeroed, and the digest covers everything before it -- so the
 * digest is over the container *including* that padding, not only the sections.
 *
 * Async, unlike the Python, because `crypto.subtle` is. Node 18+ and every
 * browser on a secure context (which GitHub Pages is) provide it; there is no
 * fallback and there should not be -- a hand-rolled SHA-256 in a page that
 * signs firmware is exactly the wrong place to save a dependency.
 */

import { concat, equal } from "../bytes.js";

export const DIGEST_BYTES = 32;
const ALIGN = 16;
const MIN_GAP = 4;

/** Where the digest goes, given the offset just past the last section. */
export function offset(sectionsEnd) {
  return (sectionsEnd + MIN_GAP + ALIGN - 1) & ~(ALIGN - 1);
}

/** HMAC-SHA256 over `container[:upto]`. */
export async function compute(key, container, upto) {
  const imported = await crypto.subtle.importKey(
    "raw", key, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = await crypto.subtle.sign("HMAC", imported, container.subarray(0, upto));
  return new Uint8Array(signature);
}

/** `body` padded and signed: the complete declared container. */
export async function append(body, key) {
  const at = offset(body.length);
  const padded = new Uint8Array(at);
  padded.set(body);
  return concat(padded, await compute(key, padded, at));
}

/**
 * The length an unsigned container takes: sections rounded up to 16 bytes.
 * The Digitone 1.42A image is unsigned and this is the shape its container
 * takes -- no digest, just alignment padding.
 */
export function padUnsigned(body) {
  const out = new Uint8Array((body.length + ALIGN - 1) & ~(ALIGN - 1));
  out.set(body);
  return out;
}

/** Check a complete declared container against its own trailer. */
export async function verify(key, container) {
  if (container.length < DIGEST_BYTES) return false;
  const upto = container.length - DIGEST_BYTES;
  return equal(await compute(key, container, upto), container.subarray(upto));
}
