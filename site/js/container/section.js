/**
 * One ELE3 section: the 8-byte header in front of a compressed stream, and the
 * question of whether a section is compressed at all.
 *
 *     [u32 stream length BE][u32 sum of the stream bytes BE][stream ...]
 *
 * Port of `src/dnfw/container/section.py`. Not every section has this header.
 * On both Digitones `meta`, `updater` and `boot` are stored raw, and the only
 * reliable test is whether the bytes depack -- so a section is modelled as its
 * **stored** bytes, exactly as they sit in the container, and compression is
 * discovered rather than assumed. A rebuild must never recompress a section it
 * could not depack: getting that backwards produces a file that passes every
 * checksum and bricks the instrument.
 *
 * **A compressed section is zero-padded to a multiple of four bytes.** Images
 * built without that padding boot through the normal update path and stall in
 * recovery, so it is written here rather than left to chance.
 */

import { u32 } from "../bytes.js";
import { DepackError, depack } from "../aplib.js";
import { pack } from "../aplibpack.js";

export const HEADER = 8;
export const STORED_ALIGN = 4;

export class Section {
  constructor(id, dest, stored) {
    this.id = id;
    this.dest = dest;
    this.stored = stored;
    this._content = undefined;   // unpack() is memoised; it is not cheap
  }

  /** Stream length from the header. Meaningless on a raw section. */
  get declaredLength() {
    return u32(this.stored, 0);
  }

  /** The compressed stream the header describes, header excluded. */
  get stream() {
    return this.stored.subarray(HEADER, HEADER + this.declaredLength);
  }

  /**
   * What a *raw* section actually loads at `dest`, header excluded.
   *
   * The test is the declared sum, not the section id, because deciding it from
   * the id would be a guess and this is a check: a real header whose stream is
   * stored rather than packed has sum 0 -- there is no stream to sum -- while a
   * section that is nothing but payload has arbitrary bytes there.
   */
  get rawPayload() {
    if (this.stored.length > HEADER && u32(this.stored, 4) === 0) {
      return this.stored.subarray(HEADER);
    }
    return this.stored;
  }

  /**
   * The section content, or `null` if these bytes are not an aPLib stream.
   *
   * Truncation is tolerated: a raw section can decode a few plausible bytes
   * before running out, so the caller distinguishes raw from compressed by
   * `null` rather than by trusting a length field it has no reason to.
   */
  unpack() {
    if (this._content !== undefined) return this._content;
    this._content = null;
    if (this.stored.length > HEADER) {
      try {
        const out = depack(this.stored.subarray(HEADER), { allowTruncated: true });
        if (out.length) this._content = out;
      } catch (error) {
        if (!(error instanceof DepackError)) throw error;
      }
    }
    return this._content;
  }
}

/** Build a compressed section from raw content: header, stream, padding. */
export function compress(id, dest, content) {
  const stream = pack(content);
  let sum = 0;
  for (let i = 0; i < stream.length; i++) sum = (sum + stream[i]) >>> 0;
  const padding = (-(HEADER + stream.length) % STORED_ALIGN + STORED_ALIGN) % STORED_ALIGN;

  const stored = new Uint8Array(HEADER + stream.length + padding);
  const view = new DataView(stored.buffer);
  view.setUint32(0, stream.length, false);
  view.setUint32(4, sum, false);
  stored.set(stream, HEADER);
  return new Section(id, dest, stored);
}

/** Build a section stored verbatim, for the sections that are. */
export function storeRaw(id, dest, content) {
  return new Section(id, dest, content);
}
