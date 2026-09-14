/**
 * The Elektron block-streaming SysEx transport: data packets and markers on
 * one side, a flat decoded byte stream on the other.
 *
 * Port of `src/dnfw/syx/transport.py`, from `syx_transport_decode` / `syx_encode`
 * in mischa85/elektron-firmware-tool, MIT.
 *
 * Scope, deliberately the same as the Python's: the 126-byte-packet transport
 * every ELE3-era instrument uses, which covers both Digitones. The legacy
 * Machinedrum/Monomachine and Octatrack transports are not implemented -- no
 * Digitone uses them, and an untested implementation of a format we cannot
 * check against a real file is a liability, not a feature.
 *
 *     data packet, 126 B : 00 20 3C <dev> 00 7E <block:2> <seq> <116B payload> <cksum>
 *     marker,       14 B : 00 20 3C <dev> 00 7F <kind> <7B info>
 */

import { concat } from "../bytes.js";
import * as checksum from "./checksum.js";
import * as encode87 from "./encode87.js";
import * as frame from "./frame.js";

const MANUFACTURER = Uint8Array.of(0x00, 0x20, 0x3c);

export const PACKET_BODY = 126;
const PAYLOAD = 116;              // 8-in-7 encoded payload bytes
const DECODED_PER_PACKET = 101;   // decoded bytes carried by one packet
const MARKER_INFO = 7;

const CMD_DATA = 0x7e;
const CMD_MARKER = 0x7f;
const MARKER_START = 0x01;
const MARKER_END = 0x02;

const OFF_DEVICE = 3;
const OFF_COMMAND = 5;
const OFF_PAYLOAD = 9;
const OFF_MARKER_INFO = 7;

const MASK7 = 0x7f;

/**
 * Decode a `.syx` file into its flat byte stream.
 *
 * Throws if the file carries no start marker, because without one there is no
 * checksum seed and nothing can be verified.
 *
 * -> { stream, envelope, packets, checksumsOk, checksumsBad }
 *
 * `envelope` is everything about the file's transport that is not payload --
 * device id, checksum seed, and the marker info template carrying the starting
 * block/sequence counter -- kept so a rebuild reproduces the original framing
 * exactly rather than inventing its own.
 */
export function decode(raw) {
  const bodies = frame.split(raw);
  const envelope = readEnvelope(bodies);

  const chunks = [];
  let packets = 0;
  let ok = 0;
  let bad = 0;
  for (const body of bodies) {
    if (body.length !== PACKET_BODY || body[OFF_COMMAND] !== CMD_DATA) continue;
    packets += 1;
    chunks.push(encode87.decode(body.subarray(OFF_PAYLOAD, OFF_PAYLOAD + PAYLOAD)));
    if (checksum.packet(body, envelope.base) === body[checksum.CHECKSUM_OFFSET]) ok += 1;
    else bad += 1;
  }

  return {
    stream: concat(...chunks),
    envelope,
    packets,
    checksumsOk: ok,
    checksumsBad: bad,
  };
}

/**
 * Encode a flat byte stream back into a `.syx` file.
 *
 * The stream is zero-padded to a whole number of packets, and a stream that is
 * an exact multiple still gets one more packet -- matching `syx_encode`'s
 * `total // 101 + 1`, which is what the original files do.
 */
export function encode(stream, envelope) {
  const count = Math.floor(stream.length / DECODED_PER_PACKET) + 1;
  const padded = new Uint8Array(count * DECODED_PER_PACKET);
  padded.set(stream);

  const parts = [frame.wrap(marker(MARKER_START, count, envelope))];
  for (let k = 0; k < count; k++) {
    const chunk = padded.subarray(k * DECODED_PER_PACKET, (k + 1) * DECODED_PER_PACKET);
    parts.push(frame.wrap(dataPacket(k, chunk, envelope)));
  }
  parts.push(frame.wrap(marker(MARKER_END, count, envelope)));
  return concat(...parts);
}

function readEnvelope(bodies) {
  const device = bodies.length && bodies[0].length > OFF_DEVICE ? bodies[0][OFF_DEVICE] : 0;
  for (const body of bodies) {
    if (body.length >= OFF_MARKER_INFO + MARKER_INFO && body[OFF_COMMAND] === CMD_MARKER) {
      const info = body.slice(OFF_MARKER_INFO, OFF_MARKER_INFO + MARKER_INFO);
      return { device, base: info[0], markerInfo: info };
    }
  }
  throw new Error("no SysEx start marker: not an Elektron OS file");
}

function marker(kind, packets, envelope) {
  const info = envelope.markerInfo.slice();
  info[0] = envelope.base;
  info[4] = (packets >> 14) & MASK7;
  info[5] = (packets >> 7) & MASK7;
  info[6] = packets & MASK7;
  return concat(
    MANUFACTURER,
    Uint8Array.of(envelope.device, 0x00, CMD_MARKER, kind),
    info,
  );
}

/**
 * One data packet. Block and sequence are a single 7-bit-wrapping counter
 * starting at the marker's info[1..3], so a rebuild continues the original
 * file's numbering rather than restarting it.
 */
function dataPacket(index, chunk, envelope) {
  const startBlock = (envelope.markerInfo[1] << 7) | envelope.markerInfo[2];
  const cumulative = envelope.markerInfo[3] + index;
  const block = startBlock + (cumulative >> 7);

  const body = concat(
    MANUFACTURER,
    Uint8Array.of(envelope.device, 0x00, CMD_DATA),
    Uint8Array.of((block >> 7) & MASK7, block & MASK7, cumulative & MASK7),
    encode87.encode(chunk),
    Uint8Array.of(0),  // the checksum byte, filled in below
  );
  body[checksum.CHECKSUM_OFFSET] = checksum.packet(body, envelope.base);
  return body;
}
