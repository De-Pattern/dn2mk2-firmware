/**
 * The container content checksum, carried in the transport preamble at [4:8].
 *
 * Port of `src/dnfw/integrity/checksum.py`, from `syx_content_checksum` in
 * mischa85/elektron-firmware-tool, MIT.
 *
 * Not a standard checksum: a running 32-bit sum where each big-endian word is
 * XORed with its own one-based index before being added. Trailing bytes that
 * do not fill a word are not covered.
 */

import { u32 } from "../bytes.js";

/** Checksum of `container` -- pass exactly the declared container length. */
export function content(container) {
  let acc = 0;
  const words = Math.floor(container.length / 4);
  for (let k = 0; k < words; k++) {
    // `>>> 0` after every step: JS bitwise ops yield signed 32-bit values, and
    // a negative intermediate here would make the sum diverge from the C.
    acc = (acc + (((k + 1) ^ u32(container, 4 * k)) >>> 0)) % 0x100000000;
  }
  return acc >>> 0;
}
