/**
 * Getting a user's audio file into one transient slot.
 *
 * Split deliberately into two halves, because only one of them can be tested:
 *
 * - **`decode`** needs Web Audio and runs only in a browser. It is three lines
 *   and delegates everything hard -- container parsing, codec, resampling,
 *   channel layout -- to the browser, which handles WAV, MP3, FLAC, AIFF and
 *   whatever else it supports. `src/dnfw/mods/transients.py` accepts 16-bit WAV
 *   only and resamples linearly; the browser is simply better at this, and
 *   pretending otherwise would mean hand-rolling a resampler nobody asked for.
 *
 * - **`fit`** is pure arithmetic over a Float32Array and is unit-tested in
 *   Node. It is where every decision that can be *wrong* lives.
 *
 * The split is the point: a function that both touches a browser API and makes
 * judgement calls is a function whose judgement calls never get tested.
 */

import { ENTRY_SAMPLES, RATE } from "./mods/transients.js";

const FADE_SAMPLES = RATE / 500;   // 2 ms, far shorter than any decay
const ONSET_FRACTION = 8;          // onset is the first point reaching peak/8

/**
 * Decode any audio file the browser can read -> mono Float32 at 48 kHz.
 *
 * The whole file, not one slot's worth: `fit` needs it all so it can choose
 * *which* 100 ms to keep, and truncating first would throw away the part the
 * user may be asking for.
 */
export async function decode(arrayBuffer) {
  // A 1-frame context, used only for its decoder. `decodeAudioData` resamples
  // to the context's rate, which is the entire reason the rate is set here.
  const context = new OfflineAudioContext(1, 1, RATE);
  const buffer = await context.decodeAudioData(arrayBuffer);

  const out = new Float32Array(buffer.length);
  for (let channel = 0; channel < buffer.numberOfChannels; channel++) {
    const data = buffer.getChannelData(channel);
    for (let i = 0; i < data.length; i++) out[i] += data[i];
  }
  if (buffer.numberOfChannels > 1) {
    for (let i = 0; i < out.length; i++) out[i] /= buffer.numberOfChannels;
  }
  return out;
}

/**
 * Fit any sample into one 100 ms slot -> Float32Array of exactly ENTRY_SAMPLES.
 *
 * A slot is 100 ms and a user's file is whatever it is, so something has to
 * choose *which* 100 ms.
 *
 * **`startMs` -- you choose.** The window starts exactly there. Use it when the
 * part you want is not the first attack: the second hit of a flam, a tail you
 * want on its own, a sample whose useful moment is 300 ms in.
 *
 * **Otherwise the onset is found** -- the first point reaching an eighth of the
 * peak -- and the window starts `leadMs` before it. Files routinely carry a few
 * milliseconds of silence, and starting at sample 0 would spend the slot on it.
 *
 * `leadMs` is a per-sample control, not a constant, because the right value
 * depends on the sound: a sharp click wants almost none, a soft or swelling
 * attack wants more or the detector fires partway up the rise and the front of
 * the sound is cut off. Guessing one number for a whole bank is exactly the
 * kind of fixed assumption this project keeps having to retract.
 *
 * A 2 ms fade at the end keeps the hard cut from adding a click of its own --
 * which would be a transient this tool invented.
 *
 * Returns `{ samples, onset, start, truncated }` rather than bare samples, so a
 * UI can show where the window landed instead of asking the user to trust it.
 */
export function fit(samples, { leadMs = 3, startMs = null, gain = 1 } = {}) {
  const out = new Float32Array(ENTRY_SAMPLES);
  if (!samples.length) return { samples: out, onset: 0, start: 0, truncated: false };

  let peak = 0;
  for (let i = 0; i < samples.length; i++) {
    const v = Math.abs(samples[i]);
    if (v > peak) peak = v;
  }

  let onset = 0;
  if (peak > 0) {
    const threshold = peak / ONSET_FRACTION;
    while (onset < samples.length && Math.abs(samples[onset]) < threshold) onset += 1;
    if (onset >= samples.length) onset = 0;
  }

  const start = startMs !== null
    ? Math.max(0, Math.round((startMs * RATE) / 1000))
    : Math.max(0, onset - Math.round((leadMs * RATE) / 1000));

  const available = Math.max(0, samples.length - start);
  const n = Math.min(available, ENTRY_SAMPLES);
  for (let i = 0; i < n; i++) out[i] = samples[start + i] * gain;

  for (let i = 0; i < Math.min(FADE_SAMPLES, ENTRY_SAMPLES); i++) {
    out[ENTRY_SAMPLES - 1 - i] *= i / FADE_SAMPLES;
  }

  return { samples: out, onset, start, truncated: available > ENTRY_SAMPLES };
}

/** Peak absolute value, for a normalise control and for drawing. */
export function peak(samples) {
  let highest = 0;
  for (let i = 0; i < samples.length; i++) {
    const v = Math.abs(samples[i]);
    if (v > highest) highest = v;
  }
  return highest;
}
