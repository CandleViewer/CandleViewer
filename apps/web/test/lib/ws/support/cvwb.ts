// Test-only CVWB builders (23 3.4): the 24-byte common header (magic "CVWB", version, kind, flags,
// scales 2 and 3, record count) followed by hand-laid body bytes.
export const FLAG_REPLAY = 0b0100;
export const FLAG_PARTIAL = 0b1000;

export const le = (n: number): number[] => [
  ...new Uint8Array(new BigUint64Array([BigInt(n)]).buffer),
];

export function cvwb(
  kind: number,
  version: number,
  count: number,
  body: readonly number[] = [],
  flags = 0,
): Uint8Array {
  const out = new Uint8Array(24 + body.length);
  out.set([0x42, 0x57, 0x56, 0x43, version, kind, flags, 2, 3]);
  new DataView(out.buffer).setUint32(12, count, true);
  out.set(body, 24);
  return out;
}

/** body_kind 2 with one 17-byte level (side, price, size). */
export const bookDelta = (flags = 0): Uint8Array =>
  cvwb(2, 1, 1, [0, ...le(10050), ...le(1500)], flags);

/** body_kind 1: one level and the 16-byte `xu`/`xseq` trailer. */
export const bookSnapshot = (flags = 0): Uint8Array =>
  cvwb(1, 1, 1, [0, ...le(10050), ...le(1500), ...le(7), ...le(8)], flags);

/** body_kind 4 (format 2) with one 85-byte bar; its `flags` byte is bit0 `confirm` (3.4). */
export function bars(confirm: boolean): Uint8Array {
  const record = new Array<number>(85).fill(0);
  record[80] = confirm ? 1 : 0;
  return cvwb(4, 2, 1, record);
}

export const b64 = (bin: Uint8Array): string => btoa(String.fromCharCode(...bin));
