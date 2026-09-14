/**
 * aPLib-variant depacker: LZ77 with interlaced Elias-gamma codes.
 *
 * Port of `src/dnfw/codec/aplib.py`, itself from `ap_depack` in
 * mischa85/elektron-firmware-tool (`decompress.c`), MIT, with thanks. It must
 * agree with the Python token for token, and `test/test_js_codec.py` asserts
 * exactly that over every compressed section of a real image.
 *
 * Packing lives in `aplibpack.js`, mirroring the same split in `src/dnfw/`.
 * The deviation the Python notes applies here too: the C codec is handed the
 * section's 8-byte `[length][sum]` header and skips it. That header is a
 * property of an ELE3 *section*, not of the compression, so it belongs to
 * `container/section.js` and this module sees only the compressed stream.
 */

import { Growable } from "./bytes.js";

export const OFFSET_BIAS = 767;     // raw offset field; this value ends the stream
export const REUSE_GAMMA = 2;       // gamma selecting "reuse the last offset"
export const FAR_THRESHOLD = 3328;  // beyond this: +1 length bonus
export const MIN_MATCH = 2;

export class DepackError extends Error {}

/** The input ran out mid-token. Separate so `depack` can tolerate it. */
export class TruncatedError extends DepackError {}

/**
 * The interlaced bit reader. Control bits come from a tag byte refilled every
 * eight bits; literal and offset bytes are read inline.
 */
class Bits {
  constructor(data) {
    this.data = data;
    this.pos = 0;
    this.tag = 0;
    this.exhausted = false;
  }

  byte() {
    if (this.pos >= this.data.length) {
      this.exhausted = true;
      return 0;
    }
    return this.data[this.pos++];
  }

  bit() {
    this.tag = (this.tag << 1) >>> 0;
    if ((this.tag & 0xff) === 0) {
      const value = this.byte();
      this.tag = ((value << 1) | 1) >>> 0;
      return (value >> 7) & 1;
    }
    return (this.tag >>> 8) & 1;
  }

  gamma() {
    let value = 1;
    for (;;) {
      value = value * 2 + this.bit();
      if (this.bit()) break;
      if (this.exhausted || value > 0x02000000) break;
    }
    return value;
  }
}

/**
 * Walk one stream's tokens without producing output.
 *
 * Each token is `[offset, value]`: `[0, byte]` for a literal, since no match
 * has offset zero, and `[offset, count]` for a match copying `count` bytes
 * from `offset` back. One reading of the grammar, so `depack` and anything
 * else that inspects a stream cannot disagree about it.
 */
export function* tokens(stream) {
  const bits = new Bits(stream);
  let produced = 0;
  let lastOffset = 1;

  for (;;) {
    if (bits.exhausted) throw new TruncatedError("input ran out mid-token");

    if (bits.bit()) {
      if (bits.pos >= bits.data.length) {
        throw new TruncatedError("input ran out mid-token");
      }
      yield [0, bits.data[bits.pos++]];
      produced += 1;
      continue;
    }

    const g = bits.gamma();
    let offset;
    if (g === REUSE_GAMMA) {
      offset = lastOffset;
    } else {
      // Masked to 32 bits on purpose: the end-of-stream token is a gamma of
      // 0x1000002 followed by 0xFF, which only decodes to the bias because the
      // C computes it in a uint32 and the high bits fall off. `g` can exceed
      // 2**31 here, so the mask is arithmetic rather than `>>> 0` on a shift.
      offset = ((g * 256) + bits.byte()) % 0x100000000;
      if (bits.exhausted) throw new TruncatedError("input ran out mid-token");
      if (offset === OFFSET_BIAS) return;   // end of stream
      offset -= OFFSET_BIAS;
      lastOffset = offset;
    }

    const high = bits.bit();
    const low = bits.bit();
    const short = 2 * high + low;
    let length = short ? short : bits.gamma() + 2;
    if (bits.exhausted) throw new TruncatedError("input ran out mid-token");
    if (offset > FAR_THRESHOLD) length += 1;

    const count = length + 1;
    // `offset <= 0` rather than `=== 0`: a raw offset below the bias makes this
    // negative here, where the C wraps it to a huge unsigned value and catches
    // it on the range test instead.
    if (offset <= 0 || produced < offset) {
      throw new DepackError(
        `offset ${offset} outside the ${produced} bytes emitted so far`);
    }
    yield [offset, count];
    produced += count;
  }
}

/**
 * Decompress one aPLib stream (no section header) -> Uint8Array.
 *
 * `allowTruncated` returns whatever was produced before the input ran out,
 * which is how a caller probes whether a section is compressed at all without
 * trusting its declared length.
 */
export function depack(stream, { allowTruncated = false } = {}) {
  const out = new Growable(Math.max(1 << 16, stream.length * 2));
  try {
    for (const [offset, value] of tokens(stream)) {
      if (offset === 0) {
        out.push(value);
      } else {
        // One byte at a time in both cases: an overlapping copy reads what it
        // has just written, and that is what makes a run reproduce.
        out.room(value);
        let src = out.length - offset;
        for (let k = 0; k < value; k++) out.buf[out.length++] = out.buf[src++];
      }
    }
  } catch (error) {
    if (error instanceof TruncatedError && allowTruncated) return out.bytes();
    throw error;
  }

  if (out.length === 0 && !allowTruncated) {
    throw new DepackError("stream decoded to nothing");
  }
  return out.bytes();
}
