/**
 * SysEx message framing: splitting a byte stream into F0..F7 message bodies,
 * and wrapping a body back up.
 *
 * Port of `src/dnfw/syx/frame.py`. A "body" throughout this package is the
 * bytes *between* F0 and F7, exclusive. Nothing here knows what a body means
 * -- see `transport.js` for that.
 */

import { indexOf } from "../bytes.js";

export const START = 0xf0;
export const END = 0xf7;

const END_BYTE = Uint8Array.of(END);

/**
 * Every complete F0..F7 body in `stream`, in order.
 *
 * Bytes outside a message are skipped, and a trailing F0 with no F7 is dropped
 * rather than guessed at. Bodies are **views** into `stream`, not copies: a
 * 2.4 MB file holds ~23,000 of them and copying each would be wasted work in a
 * browser tab.
 */
export function split(stream) {
  const bodies = [];
  let i = 0;
  while (i < stream.length) {
    if (stream[i] !== START) {
      i += 1;
      continue;
    }
    const end = indexOf(stream, END_BYTE, i + 1);
    if (end < 0) break;
    bodies.push(stream.subarray(i + 1, end));
    i = end + 1;
  }
  return bodies;
}

/** Wrap one body in F0..F7. */
export function wrap(body) {
  const out = new Uint8Array(body.length + 2);
  out[0] = START;
  out.set(body, 1);
  out[out.length - 1] = END;
  return out;
}
