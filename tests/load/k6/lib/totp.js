// RFC 6238 TOTP for the k6 auth profile (#2848): HMAC-SHA1, 6 digits, 30-second steps, as
// `candleviewer.auth.totp.generate_code` computes it. The seed is the base32 text that
// `services/api/scripts/seed_fixture_user.py --totp-secret-out` writes for a throwaway testnet
// user; nothing here holds or logs one.
import crypto from "k6/crypto";

export const STEP_S = 30;
const DIGITS = 6;
const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

// RFC 4648 base32 to bytes; case, padding and spaces are ignored, any other letter refused.
export function base32Bytes(text) {
  const clean = String(text).toUpperCase().replace(/[\s=]/g, "");
  const out = [];
  let bits = 0;
  let value = 0;
  for (const ch of clean) {
    const idx = ALPHABET.indexOf(ch);
    if (idx < 0) throw new Error("TOTP seed is not base32");
    value = (value << 5) | idx;
    bits += 5;
    if (bits >= 8) {
      bits -= 8;
      out.push((value >>> bits) & 0xff);
    }
  }
  return new Uint8Array(out).buffer;
}

// The 30-second step of a Unix time in seconds.
export function stepAt(unixS) {
  return Math.floor(unixS / STEP_S);
}

// The code of one time step: HOTP (RFC 4226) over the step as an 8-byte big-endian counter.
export function codeForStep(seedBytes, step) {
  const counter = new Uint8Array(8);
  let rest = step;
  for (let i = 7; i >= 0; i -= 1) {
    counter[i] = rest % 256;
    rest = Math.floor(rest / 256);
  }
  const hex = crypto.hmac("sha1", seedBytes, counter.buffer, "hex");
  const offset = parseInt(hex.slice(-1), 16);
  const word = parseInt(hex.slice(offset * 2, offset * 2 + 8), 16) & 0x7fffffff;
  return String(word % 10 ** DIGITS).padStart(DIGITS, "0");
}
