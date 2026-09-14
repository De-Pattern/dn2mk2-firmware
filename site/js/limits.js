/**
 * The limits Elektron's own compressed streams stay inside.
 *
 * Port of `src/dnfw/codec/limits.py`, which holds the measurements and the
 * reasoning. The short version, because it is the reason this file exists at
 * all rather than being three constants inlined somewhere:
 *
 * The aPLib format can express a match reaching back to the start of the
 * output, however far that is. **Elektron's packer never does.** Measured over
 * every compressed section of Digitone II OS 1.11, the furthest match is
 * 1,048,553 and the longest is exactly 2,048 in every section.
 *
 * Why it matters: images of ours with no window boot through the normal update
 * path and **stall in the Early Start-up Menu's recovery flash**. The normal
 * path decompresses into RAM, where any distance works; a bootloader writing
 * flash as it goes has no reason to keep more history than the packer that made
 * the image ever needed. That is the leading explanation, not a proven one --
 * `docs/flashing.md`.
 *
 * `WINDOW` is what an image is checked against. `PACK_MAX_OFFSET` is what we
 * emit, and sits a margin inside it on purpose: every offset we produce is then
 * smaller than one Elektron's own images already show the device accepting,
 * rather than merely inside a limit we inferred.
 */

export const WINDOW = 1 << 20;   // every match offset in an Elektron stream is below this
export const MAX_MATCH = 2048;   // and no match copies more bytes than this

const MARGIN = 4096;
export const PACK_MAX_OFFSET = WINDOW - MARGIN;  // 1,044,480
