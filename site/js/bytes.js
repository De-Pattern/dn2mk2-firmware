/**
 * The few byte operations every other module here needs.
 *
 * Python has `int.from_bytes(x, "big")` and slicing that copies; JS has
 * `DataView` and views that alias. That difference is the source of most of
 * the bugs a port like this can have, so the conversions live in one place
 * where they can be read once.
 *
 * Everything in `site/js` passes `Uint8Array`, never `ArrayBuffer` and never
 * `Buffer`: a `Uint8Array` may be a *view* into a larger buffer, and a
 * `DataView` built from `.buffer` without the byte offset reads from the wrong
 * place. `u32` below takes that offset into account, which is why it exists.
 */

/** Big-endian u32 at `at`. */
export function u32(data, at) {
  return ((data[at] << 24) >>> 0) + (data[at + 1] << 16) + (data[at + 2] << 8) + data[at + 3];
}

/** Write a big-endian u32 into `data` at `at`. */
export function setU32(data, at, value) {
  data[at] = (value >>> 24) & 0xff;
  data[at + 1] = (value >>> 16) & 0xff;
  data[at + 2] = (value >>> 8) & 0xff;
  data[at + 3] = value & 0xff;
}

/** Concatenate byte arrays into one new `Uint8Array`. */
export function concat(...parts) {
  let total = 0;
  for (const part of parts) total += part.length;
  const out = new Uint8Array(total);
  let at = 0;
  for (const part of parts) {
    out.set(part, at);
    at += part.length;
  }
  return out;
}

/** Constant-time-ish equality. Length is compared first because it is public. */
export function equal(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

/** Index of the first occurrence of `needle` in `haystack` at or after `from`. */
export function indexOf(haystack, needle, from = 0) {
  outer: for (let i = from; i + needle.length <= haystack.length; i++) {
    for (let k = 0; k < needle.length; k++) {
      if (haystack[i + k] !== needle[k]) continue outer;
    }
    return i;
  }
  return -1;
}

/**
 * A Uint8Array that grows by doubling, so no output size has to be guessed.
 *
 * Shared by the depacker and the packer, which is why it lives here: they both
 * produce a stream whose length is not known until it is finished, and two
 * copies of a growth policy is two places to get an off-by-one wrong.
 */
export class Growable {
  constructor(capacity = 1 << 16) {
    this.buf = new Uint8Array(capacity);
    this.length = 0;
  }

  /** Ensure room for `n` more bytes, so a caller can write `buf` directly. */
  room(n) {
    if (this.length + n <= this.buf.length) return;
    let capacity = this.buf.length * 2;
    while (capacity < this.length + n) capacity *= 2;
    const grown = new Uint8Array(capacity);
    grown.set(this.buf.subarray(0, this.length));
    this.buf = grown;
  }

  push(value) {
    this.room(1);
    this.buf[this.length++] = value;
  }

  bytes() {
    return this.buf.slice(0, this.length);
  }
}

/** ASCII bytes for a string literal, for magics and anchors. */
export function ascii(text) {
  const out = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i++) out[i] = text.charCodeAt(i) & 0xff;
  return out;
}
