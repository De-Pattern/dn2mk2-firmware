/**
 * aPLib-variant packer: produces a stream `aplib.depack` accepts.
 *
 * Port of `src/dnfw/codec/aplibpack.py`, whose bit-level encoding and cost
 * model come from `ap_pack` in mischa85/elektron-firmware-tool (`compress.c`),
 * MIT, with thanks. **The parse strategy is ported exactly too**, including the
 * order matches are considered in and the point at which the hash chain is
 * updated, because the goal here is not merely a valid stream but the *same*
 * stream the Python produces — that equality is what `test/test_js_codec.py`
 * asserts, and it is a far sharper check than "it round-trips".
 *
 * ## Why this exists when `packStore` already worked
 *
 * `packStore` below emits literals only. It is correct, trivially so, and it
 * was the right first move. But it costs 9/8 of the input, which took a
 * modified section 7 from 602 KB to 942 KB and the `.syx` from 2,389,280 to
 * 2,819,488 bytes — **340 KB larger than any image Elektron ship, and larger
 * than anything that has ever been flashed to a Digitone II.**
 *
 * The owner asked the obvious question: the transient entries are fixed-size
 * slots replaced in place, so why does anything grow? It doesn't. The
 * *unpacked* section is 836,956 bytes whatever you put in it. Only the
 * compressed size moves, and only because compression finds redundancy and how
 * much is there depends on the audio.
 *
 * Measured on 1.11, section 7, through this parse:
 *
 *     stock                                602,076   syx 2,389,280
 *     markers (the image flashed 09-14)    564,196   syx 2,341,280   -48,000
 *     34 realistic drum hits               576,364   syx 2,356,640   -32,640
 *     34 slots of white noise (worst)      653,852   syx 2,454,816   +65,536
 *     store-only                           941,583   syx 2,819,488  +430,208
 *
 * So the real packer stays within ±64 KB and is *smaller* for anything
 * musical — and the image confirmed on hardware was 48,000 bytes **smaller**
 * than stock. Store-only was buying a day of work and paying for it with an
 * untested hardware condition on the one path a user would actually take.
 *
 * `packStore` is kept: it is the fallback whose correctness can be argued in a
 * sentence, and it is what `pack` is checked against when a stream has to be
 * known-good rather than small.
 */

import { Growable } from "./bytes.js";
import { FAR_THRESHOLD, MIN_MATCH, OFFSET_BIAS, REUSE_GAMMA } from "./aplib.js";
import { MAX_MATCH, PACK_MAX_OFFSET } from "./limits.js";

const LITERAL_BITS = 9;            // 1 control bit + 8 data bits
export const DEFAULT_CHAIN_DEPTH = 32;

/**
 * Two, not three or four. The minimum match in this format is two, so a wider
 * hash key silently discards every short match: measured on the Digitone II
 * bootstrap section, a 4-byte key costs 12.4% and a 3-byte key 3.2% against
 * stock, while a 2-byte key at depth 32 comes out 0.2% *smaller* than Elektron
 * ship.
 */
const HASH_BYTES = 2;
const HASH_SLOTS = 1 << 16;        // a 2-byte key indexes this directly

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

  /**
   * Elias gamma, interlaced. Written without assuming the value fits a 32-bit
   * shift: the end-of-stream token's gamma is 0x1000002.
   */
  gamma(value) {
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

  /** -> the new last-offset, which a match may reuse instead of encoding. */
  match(offset, length, lastOffset) {
    this.bit(0);
    if (offset === lastOffset) {
      this.gamma(REUSE_GAMMA);
    } else {
      const raw = offset + OFFSET_BIAS;
      this.gamma(raw >>> 8);
      this.out.push(raw & 0xff);
      lastOffset = offset;
    }
    const base = length - 1 - (offset > FAR_THRESHOLD ? 1 : 0);
    if (base <= 3) {
      this.bit(base >> 1);
      this.bit(base & 1);
    } else {
      this.bit(0);
      this.bit(0);
      this.gamma(base - 2);
    }
    return lastOffset;
  }

  /** End of stream: a match whose raw offset field decodes to the bias. */
  end() {
    this.bit(0);
    this.gamma(0x1000002);
    this.out.push(0xff);
  }
}

const bitLength = (value) => 32 - Math.clz32(value);
const gammaCost = (value) => 2 * (bitLength(value) - 1);

/** Cost in bits of encoding this match, by the compress.c model. */
export function matchCost(offset, length, lastOffset) {
  let bits = 1 + (offset === lastOffset
    ? 2
    : gammaCost((offset + OFFSET_BIAS) >>> 8) + 8);
  const base = length - 1 - (offset > FAR_THRESHOLD ? 1 : 0);
  bits += base <= 3 ? 2 : 2 + gammaCost(base - 2);
  return bits;
}

const minMatch = (offset) => (offset > FAR_THRESHOLD ? MIN_MATCH + 1 : MIN_MATCH);

/**
 * Common-prefix length of data[a:] and data[b:], capped at `cap`.
 *
 * Overlapping matches are fine: the depacker's copy reads what it has just
 * written, and equality on the original array is exactly the condition that
 * makes that reproduce the original.
 */
function run(data, a, b, cap) {
  let n = 0;
  while (n < cap && data[a + n] === data[b + n]) n += 1;
  return n;
}

/**
 * Best (offset, length, cost) at position `i`, or zeros for none.
 *
 * Longest wins, ties broken by cost — so among equally long matches the one
 * that reuses the last offset, or sits nearer, is preferred. No match reaches
 * back further than `maxOffset`; see `limits.js`.
 *
 * Results go into the caller's `found` array rather than a fresh object: this
 * runs once or twice per input byte over megabytes, and allocating there is the
 * difference between a browser tab that works and one that stutters.
 */
function best(data, i, cap, head, prev, lastOffset, chainDepth, maxOffset, found) {
  let bestOffset = 0;
  let bestLength = 0;
  let bestCost = 0;
  let haveBest = false;

  const consider = (offset, length) => {
    if (length < minMatch(offset)) return;
    const cost = matchCost(offset, length, lastOffset);
    // The Python compares the tuple (-length, cost): longer first, then cheaper.
    if (!haveBest || length > bestLength || (length === bestLength && cost < bestCost)) {
      bestOffset = offset;
      bestLength = length;
      bestCost = cost;
      haveBest = true;
    }
  };

  if (lastOffset > 0 && lastOffset <= Math.min(i, maxOffset)) {
    consider(lastOffset, run(data, i - lastOffset, i, cap));
  }

  if (i + HASH_BYTES <= data.length) {
    let candidate = head[(data[i] << 8) | data[i + 1]];
    let depth = chainDepth;
    while (candidate >= 0 && depth) {
      // The chain runs nearest-first, so everything after this is further too.
      if (i - candidate > maxOffset) break;
      consider(i - candidate, run(data, candidate, i, cap));
      if (bestLength >= cap) break;
      candidate = prev[candidate];
      depth -= 1;
    }
  }

  found[0] = bestOffset;
  found[1] = bestLength;
  found[2] = bestCost;
}

/**
 * Compress `data` into an aPLib stream (no section header) -> Uint8Array.
 *
 * `chainDepth` trades time for size: how many earlier positions with the same
 * 2-byte prefix are considered at each step. `maxOffset` is the furthest back
 * any match may reach; the default keeps inside the window Elektron's own
 * streams use, and lowering it is for tests.
 */
export function pack(data, { chainDepth = DEFAULT_CHAIN_DEPTH,
                             maxOffset = PACK_MAX_OFFSET } = {}) {
  const size = data.length;
  // 9/8 plus slack: a literal-only parse is the worst this can do, so the
  // buffer never has to grow on real input.
  const writer = new Writer(Math.ceil(size * 1.15) + 64);
  if (size === 0) {
    writer.end();
    return writer.out.bytes();
  }

  // Int32Array rather than a Map: a 2-byte key indexes 65,536 slots directly,
  // and `prev` is one entry per input position. -1 means "no earlier match".
  const head = new Int32Array(HASH_SLOTS).fill(-1);
  const prev = new Int32Array(size).fill(-1);

  const here = new Int32Array(3);
  const ahead = new Int32Array(3);
  let lastOffset = 1;
  let i = 0;

  while (i < size) {
    const cap = Math.min(size - i, MAX_MATCH);
    best(data, i, cap, head, prev, lastOffset, chainDepth, maxOffset, here);
    let length = here[1];

    if (length && i + 1 < size) {
      // Lazy: is a literal here plus the next position's match cheaper per byte
      // than taking this match now? Note the hash chain has NOT yet been
      // updated for position i, matching the Python exactly -- the lookahead
      // cannot see a match starting where we are standing.
      const nextCap = Math.min(size - i - 1, MAX_MATCH);
      best(data, i + 1, nextCap, head, prev, lastOffset, chainDepth, maxOffset, ahead);
      if (ahead[1] && (LITERAL_BITS + ahead[2]) * length < here[2] * (1 + ahead[1])) {
        length = 0;
      }
    }

    let step;
    if (length) {
      lastOffset = writer.match(here[0], length, lastOffset);
      step = length;
    } else {
      writer.literal(data[i]);
      step = 1;
    }

    const limit = Math.min(i + step, size - HASH_BYTES + 1);
    for (let k = i; k < limit; k++) {
      const key = (data[k] << 8) | data[k + 1];
      prev[k] = head[key];
      head[key] = k;
    }
    i += step;
  }

  writer.end();
  return writer.out.bytes();
}

/**
 * Literals only: one control bit per byte, plus the byte. 9/8 of the input.
 *
 * Kept as the fallback whose correctness can be argued in a sentence — it
 * exercises one token type and the terminator, with no offsets, no lengths and
 * no reuse state. `pack` is what ships; this is what `pack` is measured
 * against when a stream has to be known-good rather than small.
 */
export function packStore(data) {
  const writer = new Writer(Math.ceil(data.length * 1.15) + 64);
  for (let i = 0; i < data.length; i++) writer.literal(data[i]);
  writer.end();
  return writer.out.bytes();
}
