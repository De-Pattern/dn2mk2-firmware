/**
 * Analog Devices boot stream: enough of it to turn a load address into a file
 * offset, and no more.
 *
 * Section 7 of a Digitone II update is the SHARC program in this format. A boot
 * stream is a chain of 16-byte headers, each followed by its payload:
 *
 *     0  block code      top byte 0xAD, the header signature
 *     1  target address  where the payload is loaded
 *     2  byte count      payload length
 *     3  argument
 *
 * **The signature alone is not evidence** -- `0xAD` appears 1,833 times in this
 * section by chance. What identifies the format is that the chain *walks*: step
 * over the payload the header's own count declares and the next header is
 * there. See `src/dnfw/image/bootstream.py` for the full model and the
 * evidence; this is the subset the browser needs.
 *
 * Why it is needed at all: **an offset into section 7 is not an address.** The
 * payloads are scattered across L1, L2 and DDR, so the block covering an
 * address has to be found rather than assumed, and writing to the wrong one
 * would corrupt an unrelated region of the DSP image.
 */

const SIGNATURE = 0xad;
const HEADER = 16;

const FLAG_FILL = 0x01;    // zero the target range; no payload in the stream
const FLAG_IGNORE = 0x08;  // skip the payload

/** The block header at `offset`, or null if there is not a signed one there. */
function headerAt(data, offset) {
  if (offset < 0 || offset + HEADER > data.length) return null;
  const view = new DataView(data.buffer, data.byteOffset + offset, HEADER);
  const code = view.getUint32(0, true);
  if (code >>> 24 !== SIGNATURE) return null;
  const flags = (code >>> 8) & 0xff;
  const count = view.getUint32(8, true);
  return {
    offset,
    code,
    flags,
    target: view.getUint32(4, true),
    count,
    argument: view.getUint32(12, true),
    // A fill block declares a target range to zero and carries nothing, so it
    // advances the load address without advancing the file -- which is exactly
    // why a walk ignoring the distinction desynchronises immediately.
    hasPayload: !(flags & (FLAG_FILL | FLAG_IGNORE)) && count > 0,
    payloadAt: offset + HEADER,
  };
}

/** Follow the block chain from `start` for as far as it holds. */
export function walk(data, start = 0, maxBlocks = 100000) {
  const blocks = [];
  let at = start;
  while (blocks.length < maxBlocks) {
    const block = headerAt(data, at);
    if (block === null) return { blocks, stoppedAt: at, dataLength: data.length };
    // Only a block that actually carries bytes has to fit in the stream: a fill
    // block can be far larger than the file -- section 7 ends with a 4.5 MB
    // fill into DDR, and a blunter guard than this truncates the walk.
    if (block.hasPayload && block.payloadAt + block.count > data.length) {
      return { blocks, stoppedAt: at, dataLength: data.length };
    }
    blocks.push(block);
    at = block.payloadAt + (block.hasPayload ? block.count : 0);
  }
  return { blocks, stoppedAt: at, dataLength: data.length };
}

export class SpanError extends Error {}

/**
 * Map a load-address range to the file pieces that hold it.
 *
 * -> `[{ at, length }]` in load order, covering exactly `length` bytes from
 * `address`. A piece whose `at` is **null** is a *fill* block: the loader
 * writes zeros there and **the file holds no bytes for it at all**, so it can
 * be read but never written.
 *
 * **A load-address range is not a file range**, and this image proves it. The
 * FM drum transient bank at `0x8045c380` spans two payload blocks with a
 * 36-byte fill block and two 16-byte headers between them, 47,440 bytes in.
 * Reading or writing it linearly crosses those headers — which is exactly what
 * `mods/transients.js` did until 2026-09-14, putting header bytes in the audio
 * and shifting 85.5% of the bank by 34 samples.
 *
 * Throws if any byte is not covered by a block at all: a gap means the
 * caller's model of the image is wrong, and guessing an offset there corrupts
 * a region nobody was looking at.
 */
export function spans(data, address, length) {
  const blocks = walk(data).blocks
    .filter((b) => b.count > 0)
    .sort((a, b) => a.target - b.target);

  const pieces = [];
  let at = address;
  let remaining = length;
  let progressed = true;
  while (remaining > 0 && progressed) {
    progressed = false;
    for (const block of blocks) {
      if (!(block.target <= at && at < block.target + block.count)) continue;
      const take = Math.min(remaining, block.target + block.count - at);
      pieces.push({
        at: block.hasPayload ? block.payloadAt + (at - block.target) : null,
        length: take,
      });
      at += take;
      remaining -= take;
      progressed = true;
      break;
    }
  }
  if (remaining > 0) {
    throw new SpanError(
      `0x${at.toString(16).padStart(8, "0")} is not inside any boot-stream `
      + `block (${remaining} of ${length} bytes unmapped); this image's layout `
      + "is not the one this was measured against");
  }
  return pieces;
}

/** The bytes loaded at `address`, gathered across blocks; fill reads as zeros. */
export function readSpan(data, address, length) {
  const out = new Uint8Array(length);
  let cursor = 0;
  for (const { at, length: n } of spans(data, address, length)) {
    if (at !== null) out.set(data.subarray(at, at + n), cursor);
    cursor += n;
  }
  return out;
}

/**
 * Load address -> offset inside the section's unpacked payload.
 *
 * Throws rather than guessing when no block covers the address: an image whose
 * layout is not the one a mod was measured against must be refused, not
 * written to at a plausible-looking offset.
 */
export function offsetOf(section, address) {
  for (const block of walk(section).blocks) {
    if (!block.hasPayload) continue;
    if (block.target <= address && address < block.target + block.count) {
      return block.payloadAt + (address - block.target);
    }
  }
  throw new Error(
    `0x${address.toString(16).padStart(8, "0")} is not inside any boot-stream `
    + "block carrying data; this image's layout is not the one this mod was "
    + "measured against");
}
