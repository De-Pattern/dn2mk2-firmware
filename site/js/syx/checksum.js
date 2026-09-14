/**
 * The per-packet transport checksum, in the last byte of a data-packet body.
 *
 * Port of `src/dnfw/syx/checksum.py`, from `syx_block_checksum` in
 * mischa85/elektron-firmware-tool, MIT.
 *
 * The sum covers body[BLOCK_OFFSET .. CHECKSUM_OFFSET), each byte XORed with a
 * running `base + index`, and `base` added once more at the end. `base` is not
 * a constant: it is the start marker's first info byte, so it comes from the
 * file being read or reproduced -- see `transport.js`.
 */

export const BLOCK_OFFSET = 6;     // first body byte the checksum covers
export const CHECKSUM_OFFSET = 125; // body offset of the checksum byte itself
const SPAN = CHECKSUM_OFFSET - BLOCK_OFFSET;  // 119 covered bytes
const MASK7 = 0x7f;

/** Checksum byte for one 126-byte data-packet body, seeded with `base`. */
export function packet(body, base) {
  let acc = 0;
  for (let i = 0; i < SPAN; i++) {
    acc += body[BLOCK_OFFSET + i] ^ ((base + i) & 0xff);
  }
  return (base + acc) & MASK7;
}
