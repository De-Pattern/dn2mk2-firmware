/**
 * aPLib-variant codec for the browser: depack, and a store-only pack.
 *
 * A second implementation of the format `src/dnfw/codec/aplib.py` reads, so
 * the page can rebuild firmware with nothing uploaded anywhere. The depacker
 * is a direct port and must agree with the Python token for token; the packer
 * deliberately is not a port.
 *
 * ## Why the packer emits only literals
 *
 * `codec/aplibpack.py` is a real packer -- greedy with lazy lookahead over a
 * hashed match chain, cost-decided, and every section it produces comes out
 * smaller than the ones Elektron ship. Porting it is a day of work and a
 * second place for a subtle parse bug to live, in code whose output people
 * flash.
 *
 * Only **section 7** is modified by the transients mod, so sections 2, 3 and 8
 * keep their original stored bytes and are never repacked at all. That reduces
 * the problem to one section, and a literal-only stream is the easiest kind of
 * aPLib stream to be sure of: it exercises one token type and the terminator,
 * with no offsets, no match lengths and no reuse state.
 *
 *     section 7:  602,076 stored  ->  836,956 unpacked  ->  941,575 store-only
 *
 * The image grows by roughly 340 KB. `docs/ideas-backlog.md` §1 is about space
 * *inside* section 3's address range, which this does not touch, so the cost is
 * file size and flash, not addressable room.
 *
 * The size is exactly 9/8 of the input plus the terminator, because every byte
 * costs one control bit and itself. If that ever matters, port the real packer;
 * `aplibpack.py` is the reference and this module's `depack` is the check.
 *
 * Ported from `ap_depack` in mischa85/elektron-firmware-tool (`decompress.c`),
 * MIT, with thanks, by way of `src/dnfw/codec/aplib.py`.
 */

export const OFFSET_BIAS = 767;     // raw offset field; this value ends the stream
export const REUSE_GAMMA = 2;       // gamma selecting "reuse the last offset"
export const FAR_THRESHOLD = 3328;  // beyond this: +1 length bonus

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

/** A Uint8Array that grows by doubling, so no size has to be guessed up front. */
class Growable {
  constructor(capacity = 1 << 16) {
    this.buf = new Uint8Array(capacity);
    this.length = 0;
  }

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

/**
 * Interlaced bit/byte output. Control bits accumulate into a tag byte reserved
 * in the stream the moment its first bit is written, so bits and inline bytes
 * stay in the order the depacker expects.
 */
class Writer {
  constructor(capacity) {
    this.out = new Growable(capacity);
    this.tagPos = -1;
    this.tagBits = 0;
  }

  bit(value) {
    if (this.tagBits === 0) {
      this.tagPos = this.out.length;
      this.out.push(0);
      this.tagBits = 8;
    }
    if (value) this.out.buf[this.tagPos] |= 1 << (this.tagBits - 1);
    this.tagBits -= 1;
  }

  gamma(value) {
    // bit_length - 1, without assuming the value fits a 32-bit shift: the
    // terminator's gamma is 0x1000002.
    let width = 0;
    for (let v = value; v > 1; v = Math.floor(v / 2)) width += 1;
    for (let i = width - 1; i >= 0; i--) {
      this.bit(Math.floor(value / 2 ** i) % 2);
      this.bit(i === 0 ? 1 : 0);
    }
  }

  literal(value) {
    this.bit(1);
    this.out.push(value);
  }

  /** End of stream: a match whose raw offset field decodes to the bias. */
  end() {
    this.bit(0);
    this.gamma(0x1000002);
    this.out.push(0xff);
  }
}

/**
 * Compress `data` into an aPLib stream (no section header) -> Uint8Array.
 *
 * Literals only -- see the module docstring for why that is the right trade
 * here and what to do if it stops being one. The result is a valid stream, not
 * a small one: expect 9/8 of the input.
 */
export function packStore(data) {
  const writer = new Writer(Math.ceil(data.length * 1.13) + 64);
  for (let i = 0; i < data.length; i++) writer.literal(data[i]);
  writer.end();
  return writer.out.bytes();
}
