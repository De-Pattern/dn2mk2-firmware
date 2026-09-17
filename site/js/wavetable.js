/**
 * A user's wavetable file -> an LFO table: 7 frames of 32 signed bytes.
 *
 * The browser half of `src/dnfw/wavetable.py`, which documents the formats and
 * the reduction. Same names, same steps, same rounding, so
 * `scripts/js_lfowaves_check.mjs` can require identical bytes.
 *
 * Inputs: a WAV wavetable (Serum/Vital style; frame size from a `clm ` chunk,
 * else 2048 when it divides, else one cycle) or JSON
 * `{"frames": [[...], ...]}` with values in -1..1 or -127..127.
 */

export const FRAMES = 7;
export const SAMPLES = 32;
const PEAK = 127;
const DEFAULT_FRAME = 2048;

export class WavetableError extends Error {}

const round = (v) => Math.floor(Math.abs(v) + 0.5) * (v >= 0 ? 1 : -1);

export function parseWav(bytes) {
  const d = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const tag4 = (at) => String.fromCharCode(bytes[at], bytes[at + 1], bytes[at + 2], bytes[at + 3]);
  if (bytes.length < 12 || tag4(0) !== "RIFF" || tag4(8) !== "WAVE") {
    throw new WavetableError("not a WAV file (no RIFF/WAVE header)");
  }
  let fmt = null, frame = null, data = null;
  let at = 12;
  while (at + 8 <= bytes.length) {
    const id = tag4(at), size = d.getUint32(at + 4, true), body = at + 8;
    if (id === "fmt ") {
      if (size < 16) throw new WavetableError("WAV fmt chunk is too short");
      let tag = d.getUint16(body, true);
      const channels = d.getUint16(body + 2, true), bits = d.getUint16(body + 14, true);
      if (tag === 0xfffe && size >= 26) tag = d.getUint16(body + 24, true);
      fmt = { tag, channels, bits };
    } else if (id === "clm ") {
      let text = "";
      for (let k = 0; k < Math.min(size, 8); k++) text += String.fromCharCode(bytes[body + k]);
      if (text.startsWith("<!>")) {
        const digits = text.slice(3, 8).replace(/\D/g, "");
        if (digits) frame = parseInt(digits, 10);
      }
    } else if (id === "data") {
      data = [body, Math.min(size, bytes.length - body)];
    }
    at += 8 + size + (size & 1);
  }
  if (!fmt || !data) throw new WavetableError("WAV file has no fmt or data chunk");
  const { tag, channels, bits } = fmt;
  const width = bits >> 3;
  if (channels < 1 || width < 1) throw new WavetableError("WAV file has no channels");
  const step = width * channels, n = Math.floor(data[1] / step), out = new Array(n);
  for (let i = 0; i < n; i++) {
    const o = data[0] + i * step;
    let v;
    if (tag === 1 && bits === 8) v = (bytes[o] - 128) / 128;
    else if (tag === 1 && bits === 16) v = d.getInt16(o, true) / 32768;
    else if (tag === 1 && bits === 24) {
      const x = bytes[o] | (bytes[o + 1] << 8) | (bytes[o + 2] << 16);
      v = (x & 0x800000 ? x - 0x1000000 : x) / 8388608;
    } else if (tag === 1 && bits === 32) v = d.getInt32(o, true) / 2147483648;
    else if (tag === 3 && bits === 32) v = d.getFloat32(o, true);
    else if (tag === 3 && bits === 64) v = d.getFloat64(o, true);
    else throw new WavetableError(`unsupported WAV encoding: format ${tag}, ${bits}-bit`);
    out[i] = v;
  }
  if (!n) throw new WavetableError("WAV file has no samples");
  return { samples: out, frame };
}

export function splitFrames(samples, frame) {
  if (frame == null) frame = samples.length % DEFAULT_FRAME === 0 ? DEFAULT_FRAME : samples.length;
  if (frame <= 0 || samples.length < frame) {
    throw new WavetableError(`frame size ${frame} does not fit ${samples.length} samples`);
  }
  const count = Math.floor(samples.length / frame), frames = [];
  for (let k = 0; k < count; k++) frames.push(samples.slice(k * frame, (k + 1) * frame));
  return frames;
}

function box(frame) {
  const n = frame.length, out = [];
  for (let j = 0; j < SAMPLES; j++) {
    const lo = j * n / SAMPLES, hi = (j + 1) * n / SAMPLES;
    let total = 0, weight = 0;
    for (let k = Math.floor(lo); k < hi && k < n; k++) {
      const w = Math.min(hi, k + 1) - Math.max(lo, k);
      if (w > 0) { total += frame[k] * w; weight += w; }
    }
    out.push(weight ? total / weight : 0);
  }
  return out;
}

export function toTable(frames) {
  if (!frames.length || frames.some((f) => f.length === 0)) {
    throw new WavetableError("a wavetable needs at least one non-empty frame");
  }
  const small = frames.map(box), picked = [];
  for (let k = 0; k < FRAMES; k++) {
    const pos = small.length > 1 ? k * (small.length - 1) / (FRAMES - 1) : 0;
    const a = Math.floor(pos), b = Math.min(a + 1, small.length - 1), t = pos - a;
    picked.push(small[a].map((v, j) => v * (1 - t) + small[b][j] * t));
  }
  let peak = 0;
  for (const f of picked) for (const v of f) peak = Math.max(peak, Math.abs(v));
  if (peak === 0) throw new WavetableError("the wavetable is silent");
  return picked.map((f) => f.map((v) => Math.max(-PEAK, Math.min(PEAK, round(v / peak * PEAK)))));
}

export const fromWav = (bytes) => {
  const { samples, frame } = parseWav(bytes);
  return toTable(splitFrames(samples, frame));
};

export function fromJson(bytes) {
  let doc;
  try { doc = JSON.parse(new TextDecoder().decode(bytes)); } catch (e) {
    throw new WavetableError(`not valid JSON: ${e.message}`);
  }
  const frames = doc && !Array.isArray(doc) ? doc.frames : null;
  if (!Array.isArray(frames) || !frames.length) throw new WavetableError('JSON needs a "frames" list');
  const length = Array.isArray(frames[0]) ? frames[0].length : 0;
  if (!length || frames.some((f) => !Array.isArray(f) || f.length !== length)) {
    throw new WavetableError("all frames must be lists of the same length");
  }
  const flat = frames.flat();
  if (!flat.every((v) => typeof v === "number" && Number.isFinite(v))) {
    throw new WavetableError("frame values must be numbers");
  }
  // Python distinguishes int from float; JSON text is the only place that shows.
  const text = new TextDecoder().decode(bytes);
  const allInts = !/[.eE]/.test(text.slice(text.indexOf("frames")));
  const scale = allInts && Math.max(...flat.map(Math.abs)) > 1 ? 127 : 1;
  return toTable(frames.map((f) => f.map((v) => v / scale)));
}

export function loadTable(bytes, name = "") {
  const head = String.fromCharCode(...bytes.slice(0, 4));
  if (head === "RIFF") return fromWav(bytes);
  const first = new TextDecoder().decode(bytes.slice(0, 64)).trimStart()[0];
  if (name.toLowerCase().endsWith(".json") || first === "{" || first === "[") return fromJson(bytes);
  throw new WavetableError("expected a .wav wavetable or a .json table");
}

export function toBytes(table) {
  if (table.length !== FRAMES || table.some((f) => f.length !== SAMPLES)) {
    throw new WavetableError(`a table is ${FRAMES} x ${SAMPLES}`);
  }
  const out = new Uint8Array(FRAMES * SAMPLES);
  table.forEach((f, k) => f.forEach((v, j) => { out[k * SAMPLES + j] = v & 0xff; }));
  return out;
}

export function fromBytes(bytes) {
  const table = [];
  for (let k = 0; k < FRAMES; k++) {
    table.push(Array.from(bytes.slice(k * SAMPLES, (k + 1) * SAMPLES), (b) => (b > 127 ? b - 256 : b)));
  }
  return table;
}

/**
 * The generator's run-time value in -1..1 at a phase (0..1) and SPH (0..127):
 * the same bilinear read the firmware does, for a preview that matches.
 */
export function sample(table, phase, sph) {
  const pos = Math.min((sph & 0x7f) * 49, (FRAMES - 1) * 1024);
  let f = pos >> 10, ff = pos & 1023;
  if (f === FRAMES - 1) { f = FRAMES - 2; ff = 1024; }
  const p = Math.floor(phase * 4294967296) >>> 0;
  const s = p >>> 27, sf = (p >>> 17) & 1023, s1 = (s + 1) & 31;
  const row = (fr) => table[fr][s] * 1024 + (table[fr][s1] - table[fr][s]) * sf;
  const ab = row(f), cd = row(f + 1);
  return (ab * 1024 + (cd - ab) * ff) / (127 * 1048576);
}
