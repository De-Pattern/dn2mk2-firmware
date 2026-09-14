/**
 * What a compressed stream asks of the depacker, measured by walking it.
 *
 * Port of `src/dnfw/codec/profile.py`. It exists for one reason: **a stream can
 * checksum perfectly and still be unflashable.** Images of ours whose matches
 * reached further back than Elektron's own booted fine through the normal
 * update path and **stalled in the Early Start-up Menu's recovery flash**
 * (`codec/limits.js`, `docs/flashing.md`).
 *
 * That is the failure this project has actually hit, and until 2026-09-14 the
 * browser's `verify()` did not check for it — it reported 9 checks where the
 * Python reports 21, missing the per-section limits and padding tests entirely.
 * The browser's own packer is bounded and so cannot produce a violation, but
 * **`verify` exists to check the artifact, not to trust the producer**; a
 * verifier that only passes because of what it knows about its own upstream is
 * verifying its own intentions.
 */

import { tokens } from "./aplib.js";
import { MAX_MATCH, WINDOW } from "./limits.js";

/**
 * -> { output, literals, matches, maxOffset, maxLength, beyond, withinLimits }
 *
 * `beyond` counts matches reaching `WINDOW` bytes or more — the ones that make
 * an image stall in recovery.
 */
export function profile(stream, window = WINDOW) {
  let output = 0;
  let literals = 0;
  let matches = 0;
  let maxOffset = 0;
  let maxLength = 0;
  let beyond = 0;

  for (const [offset, value] of tokens(stream)) {
    if (offset === 0) {
      literals += 1;
      output += 1;
    } else {
      matches += 1;
      output += value;
      if (offset > maxOffset) maxOffset = offset;
      if (value > maxLength) maxLength = value;
      if (offset >= window) beyond += 1;
    }
  }

  return {
    output, literals, matches, maxOffset, maxLength, beyond, window,
    withinLimits: maxOffset < window && maxLength <= MAX_MATCH,
  };
}
