/**
 * 8-in-7 packing: MIDI SysEx carries 7-bit bytes, so the high bit of each of
 * seven data bytes is gathered into a leading byte.
 *
 * Port of `src/dnfw/syx/encode87.py`, itself from `decode_payload` /
 * `encode_8in7` in mischa85/elektron-firmware-tool, MIT. Bit order is
 * MSB-first: data byte n of a group takes bit (6 - n) of its leading byte.
 */

export const GROUP = 7;      // data bytes carried by one group
const HIGH_BIT = 0x80;
const MASK7 = 0x7f;

/**
 * Pack 8-bit bytes into 8-in-7 groups. A trailing partial group is emitted
 * with only the data bytes it has; its unused high-bit positions stay zero.
 */
export function encode(data) {
  const groups = Math.ceil(data.length / GROUP);
  const out = new Uint8Array(groups + data.length);
  let at = 0;
  for (let i = 0; i < data.length; i += GROUP) {
    const count = Math.min(GROUP, data.length - i);
    let high = 0;
    for (let n = 0; n < count; n++) {
      if (data[i + n] & HIGH_BIT) high |= 1 << (GROUP - 1 - n);
    }
    out[at++] = high;
    for (let n = 0; n < count; n++) out[at++] = data[i + n] & MASK7;
  }
  return out;
}

/**
 * Unpack 8-in-7 groups back to 8-bit bytes. The final group may be short,
 * which is how a 116-byte payload yields 101 bytes.
 */
export function decode(payload) {
  const out = new Uint8Array(payload.length);
  let at = 0;
  let i = 0;
  while (i < payload.length) {
    const high = payload[i];
    const count = Math.min(GROUP, payload.length - i - 1);
    for (let k = 0; k < count; k++) {
      const bit = (high >> (GROUP - 1 - k)) & 1;
      out[at++] = payload[i + 1 + k] | (bit ? HIGH_BIT : 0);
    }
    i += GROUP + 1;
  }
  return out.subarray(0, at);
}
