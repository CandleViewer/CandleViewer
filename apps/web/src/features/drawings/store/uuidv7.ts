// E14-T02 (#400, BQ-03): a client UUIDv7 for `create.id` (`22` batchUpsertDrawings recommends v7).
// RFC 9562 §5.7: 48-bit Unix ms, version 7, 74 random bits, variant 10. No dependency.

export type RandomFill = (bytes: Uint8Array) => Uint8Array;

const cryptoFill: RandomFill = (bytes) => crypto.getRandomValues(bytes);

export function uuidv7(nowMs: number = Date.now(), fill: RandomFill = cryptoFill): string {
  const b = fill(new Uint8Array(16));
  let ms = Math.max(0, Math.floor(nowMs));
  for (let i = 5; i >= 0; i -= 1) {
    b[i] = ms % 256;
    ms = Math.floor(ms / 256);
  }
  b[6] = ((b[6] ?? 0) & 0x0f) | 0x70;
  b[8] = ((b[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
