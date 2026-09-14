/**
 * Recovering the device HMAC key from the firmware's own key material.
 *
 * Port of `src/dnfw/integrity/keyderive.py`, from `elektron_extract_key` /
 * `derive_key` in mischa85/elektron-firmware-tool, MIT.
 *
 * **No key is stored in this repository or in this page, and none needs to
 * be.** The material sits in a decompressed section of the user's own
 * firmware: an anchor, a printable string, a NUL, then a 32-byte constant.
 * The key is
 *
 *     SHA256(s) XOR SHA256(reverse(s)) XOR constant
 *
 * and a candidate is accepted only when it reproduces the image's own trailer,
 * so a wrong guess cannot be mistaken for the right one.
 *
 * The page derives this from the file the user picked, in their own browser,
 * and it never leaves the tab. Digitone II 1.10E and 1.11 derive from the
 * string "Multiplier" in their bootstrap section; Digitone 1.42A is unsigned
 * and `find` correctly returns null.
 */

import { equal, indexOf } from "../bytes.js";
import { compute } from "./digest.js";

/**
 * The last two SHA-256 round constants, which sit immediately before the key
 * material. Not itself a secret -- it is a published constant of the hash.
 */
const ANCHOR = Uint8Array.of(0xbe, 0xf9, 0xa3, 0xf7, 0xc6, 0x71, 0x78, 0xf2);
const MAX_STRING = 64;
const KEY_BYTES = 32;

async function sha256(data) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", data));
}

/** SHA256(s) XOR SHA256(reverse(s)) XOR constant. */
export async function derive(string, constant) {
  const reversed = Uint8Array.from(string).reverse();
  const forward = await sha256(string);
  const backward = await sha256(reversed);
  const key = new Uint8Array(KEY_BYTES);
  for (let i = 0; i < KEY_BYTES; i++) key[i] = forward[i] ^ backward[i] ^ constant[i];
  return key;
}

/**
 * Search decompressed sections for the key that signs `message` as `expected`.
 *
 * -> `{ value, derivationString }`, or `null` when no candidate verifies --
 * including when the firmware is simply unsigned.
 */
export async function find(sections, message, expected) {
  for (const blob of sections) {
    for (const { string, constant } of candidates(blob)) {
      const value = await derive(string, constant);
      if (equal(await compute(value, message, message.length), expected)) {
        return { value, derivationString: String.fromCharCode(...string) };
      }
    }
  }
  return null;
}

/** Every (string, constant) pair at an anchor in `blob`. */
function* candidates(blob) {
  let start = indexOf(blob, ANCHOR);
  while (start >= 0) {
    const text = start + ANCHOR.length;
    let end = text;
    while (end < blob.length && blob[end] >= 0x20 && blob[end] < 0x7f
           && end - text < MAX_STRING) {
      end += 1;
    }
    if (end > text && end < blob.length && blob[end] === 0
        && end + 1 + KEY_BYTES <= blob.length) {
      yield {
        string: blob.subarray(text, end),
        constant: blob.subarray(end + 1, end + 1 + KEY_BYTES),
      };
    }
    start = indexOf(blob, ANCHOR, start + 1);
  }
}
