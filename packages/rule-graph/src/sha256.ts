/**
 * SHA-256 (FIPS 180-4) of a string's UTF-8 bytes, as 64 lowercase hex digits. It is the hash
 * primitive of the client mirror (E37-T01), the advisory copy of the server's canonical rule IR;
 * the server's `ir_hash` is the authority. Pure and synchronous (WebCrypto's `digest` is async and
 * `node:crypto` is not in browsers), with its own UTF-8 encoder, so it reads no host global.
 */
import { RuleGraphError } from "./errors.js";

// FIPS 180-4 section 4.2.2 (the round constants) and section 5.3.3 (the initial hash value).
const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);
const H0 = new Uint32Array([
  0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
]);

// In-range reads only: `as number` drops the undefined that noUncheckedIndexedAccess adds.
const at = (table: Uint32Array, i: number): number => table[i] as number;
const rotr = (x: number, n: number): number => (x >>> n) | (x << (32 - n));

/** `text`'s UTF-8 bytes. A lone surrogate has none and is refused: the server can't encode it. */
function utf8(text: string): number[] {
  const bytes: number[] = [];
  for (const char of text) {
    const c = char.codePointAt(0) as number; // a for-of step is one code point, never empty
    if (c >= 0xd800 && c <= 0xdfff) {
      throw new RuleGraphError("SCHEMA_VIOLATION", "a lone surrogate has no UTF-8 form");
    }
    // The lead byte holds the length prefix and the top bits; each continuation byte six more.
    const tail = c < 0x80 ? 0 : c < 0x800 ? 1 : c < 0x10000 ? 2 : 3;
    bytes.push(tail === 0 ? c : ((0xff << (7 - tail)) & 0xff) | (c >> (6 * tail)));
    for (let k = tail - 1; k >= 0; k--) bytes.push(0x80 | ((c >> (6 * k)) & 0x3f));
  }
  return bytes;
}

/** The lowercase hex SHA-256 of `text`'s UTF-8 bytes (FIPS 180-4). */
export function sha256Hex(text: string): string {
  const bytes = utf8(text);
  // The bytes, 0x80, zeros to a whole block less 8 bytes, then the bit length (64-bit big-endian).
  const message = new Uint8Array(((bytes.length + 72) >> 6) << 6);
  message.set(bytes);
  message[bytes.length] = 0x80;
  const view = new DataView(message.buffer);
  view.setUint32(message.length - 8, Math.floor(bytes.length / 0x20000000));
  view.setUint32(message.length - 4, (bytes.length * 8) >>> 0);
  const [h, w, v] = [H0.slice(), new Uint32Array(64), new Uint32Array(8)]; // v holds a..h
  for (let block = 0; block < message.length; block += 64) {
    for (let t = 0; t < 16; t++) w[t] = view.getUint32(block + 4 * t);
    for (let t = 16; t < 64; t++) {
      const x = at(w, t - 15);
      const y = at(w, t - 2);
      const s0 = rotr(x, 7) ^ rotr(x, 18) ^ (x >>> 3);
      w[t] = at(w, t - 16) + s0 + at(w, t - 7) + (rotr(y, 17) ^ rotr(y, 19) ^ (y >>> 10));
    }
    v.set(h);
    for (let t = 0; t < 64; t++) {
      const a = at(v, 0);
      const e = at(v, 4);
      const ch = (e & at(v, 5)) ^ (~e & at(v, 6));
      const t1 = at(v, 7) + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ch + at(K, t) + at(w, t);
      const maj = (a & at(v, 1)) ^ (a & at(v, 2)) ^ (at(v, 1) & at(v, 2));
      v.copyWithin(1, 0, 7); // h, g, f, e, d, c, b take g, f, e, d, c, b, a
      v[4] = at(v, 4) + t1; // e = d + T1
      v[0] = t1 + (rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + maj; // a = T1 + T2
    }
    for (let i = 0; i < 8; i++) h[i] = at(h, i) + at(v, i);
  }
  return Array.from(h, (x) => x.toString(16).padStart(8, "0")).join("");
}
