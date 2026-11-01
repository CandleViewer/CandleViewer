// Non-cryptographic hashes for the atlas cache (E11-S11, BQ-264, G-90). FNV-1a 32 is the record
// checksum (integrity against corruption, not tampering: F-03 owns that); FNV-1a 64 keys the font
// bytes where `crypto.subtle` is unavailable (an insecure context).
const FNV32_OFFSET = 0x811c9dc5;
const FNV32_PRIME = 0x01000193;

/** FNV-1a 32 over `bytes`, continuing from `h` (chain several views into one checksum). */
export function fnv1a(bytes: Uint8Array, h = FNV32_OFFSET): number {
  let x = h;
  for (let i = 0; i < bytes.length; i += 1) {
    x ^= bytes[i] as number;
    x = Math.imul(x, FNV32_PRIME);
  }
  return x >>> 0;
}

/** FNV-1a 32 over a string's UTF-16 code units, as 8 hex digits. */
export function fnv1aHex(text: string): string {
  let x = FNV32_OFFSET;
  for (let i = 0; i < text.length; i += 1) {
    x ^= text.charCodeAt(i);
    x = Math.imul(x, FNV32_PRIME);
  }
  return (x >>> 0).toString(16).padStart(8, "0");
}

const FNV64_OFFSET = 0xcbf29ce484222325n;
const FNV64_PRIME = 0x100000001b3n;

/** FNV-1a 64 over `bytes`, as 16 hex digits (the key fallback, G-90). */
export function fnv64Hex(bytes: Uint8Array): string {
  let x = FNV64_OFFSET;
  for (let i = 0; i < bytes.length; i += 1) {
    x = BigInt.asUintN(64, (x ^ BigInt(bytes[i] as number)) * FNV64_PRIME);
  }
  return x.toString(16).padStart(16, "0");
}
