// The cases both halves of the ASCII-glitch parity check render (mirrored in py_asciiglitch_ref.py).
export const CASES = [
  {},
  { ramp: " .-=+*#%@", glitchChars: "01<>/\\", resolve: 24, idleFrames: 8, seed: 7, glitch: 1.6, idle: 0.9 },
  { resolve: 1, idleFrames: 0, glitch: 0, idle: 0 },
];

/** A 128x64 binary PGM (P5) -> lit(x, y), thresholded at half. */
export function markFromPgm(bytes) {
  let at = 0; const f = [];
  const sp = (b) => b === 0x20 || b === 0x0a || b === 0x0d || b === 0x09;
  while (f.length < 4) { while (sp(bytes[at])) at++; let s = ""; while (!sp(bytes[at])) s += String.fromCharCode(bytes[at++]); f.push(s); }
  const pix = bytes.subarray(at + 1);
  return (x, y) => pix[y * 128 + x] > 127;
}
