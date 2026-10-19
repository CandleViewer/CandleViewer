// Fixtures for cv-ws-wire-count-alloc-ts (E17-X02, SR-128): a count read from the wire must be
// bounded before it sizes an array, a typed array or a loop. `todoruleid` marks an accepted miss
// and `todook` an accepted false positive (the rule's Known limits). `assertFits` is the CVWB
// decoder's own check.
declare const MAX_RECORDS: number;
declare function makeBuffer(n: number): void;
declare function readCount(view: DataView): number;
declare function assertFits(count: number, stride: number, available: number, what: string): void;
declare namespace P {
  interface BinaryFrameHeader {
    recordCount: number;
    priceScale: number;
  }
  function parseBinaryFrameHeader(buf: ArrayBufferView): BinaryFrameHeader;
}
type H = P.BinaryFrameHeader;

// The Gherkin: a list sized from a decoded record_count.
export function recordCountArrayBad(view: DataView): unknown[] {
  const recordCount = view.getUint32(8, true);
  return new Array(recordCount); // ruleid: cv-ws-wire-count-alloc-ts
}

export function recordCountArrayOk(view: DataView): unknown[] {
  const recordCount = view.getUint32(8, true);
  if (recordCount > MAX_RECORDS) throw new Error("record_count over the cap");
  return new Array(recordCount); // ok: cv-ws-wire-count-alloc-ts
}

export function everySourceBad(view: DataView, u8: Uint8Array, buf: ArrayBuffer): unknown[] {
  const header = P.parseBinaryFrameHeader(u8);
  const a = view.getUint16(1, true);
  const b = view.getInt32(3, true);
  const c = Number(view.getBigUint64(7, true));
  const d = u8[4] | (u8[5] << 8);
  const e = new Uint32Array(buf, 8, 1)[0];
  const [f] = new Uint32Array(buf, 12, 1);
  const words = new Uint16Array(buf);
  let cells = new Uint32Array(buf);
  cells = cells.subarray(1);
  return [
    new Array(a), // ruleid: cv-ws-wire-count-alloc-ts
    new Array(b), // ruleid: cv-ws-wire-count-alloc-ts
    new Array(c), // ruleid: cv-ws-wire-count-alloc-ts
    new Array(d), // ruleid: cv-ws-wire-count-alloc-ts
    new Array(e), // ruleid: cv-ws-wire-count-alloc-ts
    new Array(f), // ruleid: cv-ws-wire-count-alloc-ts
    new Array(words[2]), // ruleid: cv-ws-wire-count-alloc-ts
    new Array(cells[0]), // ruleid: cv-ws-wire-count-alloc-ts
    new Array(header.recordCount), // ruleid: cv-ws-wire-count-alloc-ts
  ];
}

// A header parameter's count, whatever the function form or the spelling of the type.
export const arrowBad = (h: P.BinaryFrameHeader) => new Array(h.recordCount); // ruleid: cv-ws-wire-count-alloc-ts
export const expressionBad = function (h: Readonly<P.BinaryFrameHeader>) {
  return new Array(h.recordCount); // ruleid: cv-ws-wire-count-alloc-ts
};

export function everySinkBad(view: DataView, ok: boolean): unknown[] {
  const n = view.getUint32(8, true);
  const out: unknown[] = [];
  out.push(Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  out.push(Array<number>(n)); // ruleid: cv-ws-wire-count-alloc-ts
  out.push(new Uint8Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  out.push(new Float64Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  out.push(new ArrayBuffer(n)); // ruleid: cv-ws-wire-count-alloc-ts
  out.push(Array.from({ length: n }, () => 0)); // ruleid: cv-ws-wire-count-alloc-ts
  out.push("-".repeat(n)); // ruleid: cv-ws-wire-count-alloc-ts
  out.push("-".padStart(n)); // ruleid: cv-ws-wire-count-alloc-ts
  out.push("-".padEnd(n)); // ruleid: cv-ws-wire-count-alloc-ts
  out.push(new Uint8Array(n).slice(0)); // ruleid: cv-ws-wire-count-alloc-ts
  for (let i = 0; i < n; i += 1) out.push(i); // ruleid: cv-ws-wire-count-alloc-ts
  for (let i = 0; i <= n; i += 1) out.push(i); // ruleid: cv-ws-wire-count-alloc-ts
  for (let i = 0; i !== n; i += 1) out.push(i); // ruleid: cv-ws-wire-count-alloc-ts
  for (let i = 0; n > i; i += 1) out.push(i); // ruleid: cv-ws-wire-count-alloc-ts
  for (let i = 0; n !== i; i += 1) out.push(i); // ruleid: cv-ws-wire-count-alloc-ts
  for (let i = 0, len = view.getUint32(12, true); i < len; i += 1) out.push(i); // ruleid: cv-ws-wire-count-alloc-ts
  for (let i = 0; ok && i < n; i += 1) out.push(i); // ruleid: cv-ws-wire-count-alloc-ts
  for (let i = n - 1; i >= 0; i -= 1) out.push(i); // ruleid: cv-ws-wire-count-alloc-ts
  for (let i = 0; i < 4; i += 1) out.push(n); // ok: cv-ws-wire-count-alloc-ts
  let k = 0;
  while (k < n) k += 1; // ruleid: cv-ws-wire-count-alloc-ts
  while (k <= n) k += 1; // ruleid: cv-ws-wire-count-alloc-ts
  while (n > k) k += 1; // ruleid: cv-ws-wire-count-alloc-ts
  do {
    k += 1;
  } while (k < n); // ruleid: cv-ws-wire-count-alloc-ts
  do {
    k += 1;
  } while (ok && k < n); // ruleid: cv-ws-wire-count-alloc-ts
  let w = view.getUint32(12, true);
  while (w--) k += 1; // ruleid: cv-ws-wire-count-alloc-ts
  w = view.getUint32(16, true);
  while (w) w >>= 1; // ruleid: cv-ws-wire-count-alloc-ts
  return out;
}

export function guardsThatRefuseOk(buf: ArrayBuffer, header: H, offsets: number[]): void {
  const u = new Uint32Array(buf);
  if (u[0] * 16 > buf.byteLength - 12) {
    console.warn("short");
    throw new Error("u0");
  }
  if (u[1] >= MAX_RECORDS) throw new Error("u1");
  if (MAX_RECORDS < u[2]) throw new Error("u2");
  if (MAX_RECORDS <= u[3]) return;
  if (u[4] > MAX_RECORDS || u[4] < 0) throw new Error("u4");
  const expected = 24 + u[5] * 16;
  if (expected !== buf.byteLength) throw new Error("length");
  const need = 24 + u[6] * 16;
  if (buf.byteLength !== need) throw new Error("length");
  if (buf.byteLength !== 24 + u[7] * 16) throw new Error("length");
  if (24 + u[8] * 16 !== buf.byteLength) throw new Error("length");
  if (u[9] > MAX_RECORDS) throw new Error("u9");
  if (u[9]) new Array(u[9]); // ok: cv-ws-wire-count-alloc-ts
  assertFits(u[10], 16, buf.byteLength - 12, "records");
  assertFits(header.recordCount, 16, buf.byteLength - 12, "records");
  for (const offset of offsets) {
    const n = u[11] + offset;
    if (n > MAX_RECORDS) continue;
    new Array(n); // ok: cv-ws-wire-count-alloc-ts
  }
  new Array(u[12] <= MAX_RECORDS ? u[12] : 0); // ok: cv-ws-wire-count-alloc-ts
  new Array(u[13] < MAX_RECORDS ? u[13] : 0); // ok: cv-ws-wire-count-alloc-ts
  new Array(u[0]); // ok: cv-ws-wire-count-alloc-ts
  new Array(u[1]); // ok: cv-ws-wire-count-alloc-ts
  new Array(u[2]); // ok: cv-ws-wire-count-alloc-ts
  new Array(u[3]); // ok: cv-ws-wire-count-alloc-ts
  new Array(u[4]); // ok: cv-ws-wire-count-alloc-ts
  new Array(u[5]); // ok: cv-ws-wire-count-alloc-ts
  new Array(u[6]); // ok: cv-ws-wire-count-alloc-ts
  new Array(u[7]); // ok: cv-ws-wire-count-alloc-ts
  new Array(u[8]); // ok: cv-ws-wire-count-alloc-ts
  new Array(u[10]); // ok: cv-ws-wire-count-alloc-ts
  new Array(header.recordCount); // ok: cv-ws-wire-count-alloc-ts
  if (offsets.length !== 2) new Array(u[0]); // ok: cv-ws-wire-count-alloc-ts
  if (u[14] > MAX_RECORDS) throw new Error("too many rows for (u14)");
  new Array(u[14]); // ok: cv-ws-wire-count-alloc-ts
}

export function aCheckHoldsUntilTheNameIsAssignedAgain(view: DataView, offsets: number[]) {
  let n = view.getUint32(8, true);
  let k = view.getUint32(12, true);
  const m = view.getUint32(16, true);
  if (n > MAX_RECORDS) throw new Error("n");
  if (view.byteLength !== 24 + k * 16) throw new Error("k");
  k += m;
  const out = [new Array(k)]; // ruleid: cv-ws-wire-count-alloc-ts
  n = view.getUint32(20, true);
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  assertFits(n, 16, view.byteLength, "n");
  out.push(new Array(n)); // ok: cv-ws-wire-count-alloc-ts
  n = m;
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  assertFits(n, 16, view.byteLength, "n");
  for (const off of offsets) {
    n = view.getUint32(off, true);
    out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  }
  if (n > MAX_RECORDS) throw new Error("n");
  out.push(new Array(n)); // ok: cv-ws-wire-count-alloc-ts
  return out;
}

export function guardsOnAName(view: DataView, ok: boolean): unknown[] {
  const [a, b, c] = [view.getUint32(0, true), view.getUint32(4, true), view.getUint32(8, true)];
  const [d, e, f] = [view.getUint32(12, true), view.getUint32(16, true), view.getUint32(20, true)];
  const [g, h, x] = [view.getUint32(24, true), view.getUint32(28, true), view.getUint32(32, true)];
  const [y, z] = [view.getUint32(36, true), view.getUint32(40, true)];
  const out: unknown[] = [];
  if (z > 0) return [new Array(z)]; // ruleid: cv-ws-wire-count-alloc-ts
  if (x < 4) throw new Error("x");
  out.push(new Array(x)); // ruleid: cv-ws-wire-count-alloc-ts
  if (x === 4) throw new Error("x");
  out.push(new Array(x)); // ruleid: cv-ws-wire-count-alloc-ts
  if (x > MAX_RECORDS) console.warn("x");
  out.push(new Array(x)); // ruleid: cv-ws-wire-count-alloc-ts
  if (x > MAX_RECORDS) {
    if (ok) {
      throw new Error("x");
    }
  }
  out.push(new Array(x)); // ruleid: cv-ws-wire-count-alloc-ts
  if (a > MAX_RECORDS) return [new Array(a)]; // ruleid: cv-ws-wire-count-alloc-ts
  if (b >= MAX_RECORDS) return [new Array(b)]; // ruleid: cv-ws-wire-count-alloc-ts
  if (MAX_RECORDS < c) return [new Array(c)]; // ruleid: cv-ws-wire-count-alloc-ts
  if (MAX_RECORDS <= d) return [new Array(d)]; // ruleid: cv-ws-wire-count-alloc-ts
  if (view.byteLength !== 24 + e * 16) return [new Array(e)]; // ruleid: cv-ws-wire-count-alloc-ts
  if (24 + f * 16 !== view.byteLength) return [new Array(f)]; // ruleid: cv-ws-wire-count-alloc-ts
  const wantG = 24 + g * 16;
  if (view.byteLength !== wantG) return [new Array(g)]; // ruleid: cv-ws-wire-count-alloc-ts
  const wantH = 24 + h * 16;
  if (wantH !== view.byteLength) return [new Array(h)]; // ruleid: cv-ws-wire-count-alloc-ts
  if (y > MAX_RECORDS) return [new Array(y), "too many rows for (y)"]; // ruleid: cv-ws-wire-count-alloc-ts
  if (a > 0) return [new Array(a)]; // ok: cv-ws-wire-count-alloc-ts
  if (b > 8) console.warn(new Array(b)); // ok: cv-ws-wire-count-alloc-ts
  if (c > 8) {
    if (ok) {
      console.warn(new Array(c)); // ok: cv-ws-wire-count-alloc-ts
    }
    return [];
  }
  out.push(new Array(a + b + c + d + y), new Array(e + f + g + h)); // ok: cv-ws-wire-count-alloc-ts
  return out;
}

export function anyAssignmentEndsACheck(view: DataView, flag: boolean, k: number, offs: number[]) {
  let n = view.getUint32(8, true);
  const out: unknown[] = [];
  if (n > MAX_RECORDS) throw new Error("n");
  if (flag) {
    n = view.getUint32(12, true);
  }
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (view.byteLength !== 24 + n * 16) throw new Error("n");
  if (flag) {
    n = view.getUint32(12, true);
  }
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (n > MAX_RECORDS) throw new Error("n");
  for (const off of offs) n = view.getUint32(off, true);
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (view.byteLength !== 24 + n * 16) throw new Error("n");
  for (const off of offs) n = view.getUint32(off, true);
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (n > MAX_RECORDS) throw new Error("n");
  try {
    n = view.getUint32(12, true);
  } catch {}
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (view.byteLength !== 24 + n * 16) throw new Error("n");
  try {
    n = view.getUint32(12, true);
  } catch {}
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (n > MAX_RECORDS) throw new Error("n");
  switch (k) {
    case 1:
      n = view.getUint32(12, true);
  }
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (view.byteLength !== 24 + n * 16) throw new Error("n");
  switch (k) {
    case 1:
      n = view.getUint32(12, true);
  }
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (n > MAX_RECORDS) throw new Error("n");
  if (flag) k += 1;
  else if (k > 2) n = view.getUint32(12, true);
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (view.byteLength !== 24 + n * 16) throw new Error("n");
  if (flag) k += 1;
  else if (k > 2) n = view.getUint32(12, true);
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (n > MAX_RECORDS) throw new Error("n");
  for (n = view.getUint32(12, true); k < 1; k += 1) out.push(k);
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (view.byteLength !== 24 + n * 16) throw new Error("n");
  for (n = view.getUint32(12, true); k < 1; k += 1) out.push(k);
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (n > MAX_RECORDS) throw new Error("n");
  [n] = [view.getUint32(12, true)];
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (view.byteLength !== 24 + n * 16) throw new Error("n");
  [n] = [view.getUint32(12, true)];
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (n > MAX_RECORDS) throw new Error("n");
  ({ n } = { n: view.getUint32(12, true) });
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (view.byteLength !== 24 + n * 16) throw new Error("n");
  ({ n } = { n: view.getUint32(12, true) });
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (n > MAX_RECORDS) throw new Error("n");
  const m1 = (n = view.getUint32(12, true)) + 1;
  out.push(m1, new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (view.byteLength !== 24 + n * 16) throw new Error("n");
  const m2 = (n = view.getUint32(12, true)) + 1;
  out.push(m2, new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (n > MAX_RECORDS) throw new Error("n");
  if (flag) n += view.getUint32(12, true);
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  if (view.byteLength !== 24 + n * 16) throw new Error("n");
  if (flag) n += view.getUint32(12, true);
  out.push(new Array(n)); // ruleid: cv-ws-wire-count-alloc-ts
  return out;
}

export function clampsAndSafeSizesOk(view: DataView, buf: Uint8Array, h: H, sizes: number[]) {
  const a = view.getUint32(0, true);
  const b = view.getUint32(4, true);
  const c = view.getUint32(8, true);
  return [
    new Array(Math.min(a, MAX_RECORDS)), // ok: cv-ws-wire-count-alloc-ts
    new Array(Math.min(b, buf.byteLength)), // ok: cv-ws-wire-count-alloc-ts
    new Array(c & 0xff), // ok: cv-ws-wire-count-alloc-ts
    new Array(view.getUint8(12)), // ok: cv-ws-wire-count-alloc-ts
    new Array(sizes[0]), // ok: cv-ws-wire-count-alloc-ts
    new Uint8Array(buf.slice(a, a + b)), // ok: cv-ws-wire-count-alloc-ts
    new Uint8Array(buf.buffer, 0, a), // ok: cv-ws-wire-count-alloc-ts
    String(a), // ok: cv-ws-wire-count-alloc-ts
    String(a).repeat(3), // ok: cv-ws-wire-count-alloc-ts
    "0".repeat(h.priceScale), // ok: cv-ws-wire-count-alloc-ts
  ];
}

export function guardsThatDoNotBoundBad(buf: ArrayBuffer, other: number, h: H): unknown[] {
  const u = new Uint32Array(buf);
  if (u[0] === 0) return [];
  new Array(u[0]); // ruleid: cv-ws-wire-count-alloc-ts
  if (!u[1]) return [];
  new Array(u[1]); // ruleid: cv-ws-wire-count-alloc-ts
  if (u[2] < 1) throw new Error("u2");
  new Array(u[2]); // ruleid: cv-ws-wire-count-alloc-ts
  if (other > MAX_RECORDS) throw new Error("other");
  new Array(u[3]); // ruleid: cv-ws-wire-count-alloc-ts
  if (u[4] > MAX_RECORDS) console.warn("over the cap");
  new Array(u[4]); // ruleid: cv-ws-wire-count-alloc-ts
  const expected = 24 + u[5] * 16;
  if (expected !== buf.byteLength) console.warn("length");
  new Array(u[5]); // ruleid: cv-ws-wire-count-alloc-ts
  if (u[6] > 0) return new Array(u[6]); // ruleid: cv-ws-wire-count-alloc-ts
  if (u[13]) return new Array(u[13]); // ruleid: cv-ws-wire-count-alloc-ts
  if (u[7] >= 1) return new Array(u[7]); // ruleid: cv-ws-wire-count-alloc-ts
  if (0 < u[8]) return new Array(u[8]); // ruleid: cv-ws-wire-count-alloc-ts
  if (1 <= u[9]) return new Array(u[9]); // ruleid: cv-ws-wire-count-alloc-ts
  new Array(u[10]); // ruleid: cv-ws-wire-count-alloc-ts
  if (u[10] > MAX_RECORDS) throw new Error("late");
  new Array(Math.min(u[11], u[12])); // ruleid: cv-ws-wire-count-alloc-ts
  if (u[14] > MAX_RECORDS) {
    if (other > 0) {
      throw new Error("u14");
    }
  }
  new Array(u[14]); // ruleid: cv-ws-wire-count-alloc-ts
  if (buf.byteLength !== 24 + u[15] * 16) return new Array(u[15]); // ruleid: cv-ws-wire-count-alloc-ts
  if (24 + u[16] * 16 !== buf.byteLength) return new Array(u[16]); // ruleid: cv-ws-wire-count-alloc-ts
  const want = 24 + u[17] * 16;
  if (want !== buf.byteLength) return new Array(u[17]); // ruleid: cv-ws-wire-count-alloc-ts
  const need = 24 + u[18] * 16;
  if (buf.byteLength !== need) return new Array(u[18]); // ruleid: cv-ws-wire-count-alloc-ts
  if (h.recordCount === 0) return [];
  if (h.recordCount * 16 > 0) return new Array(h.recordCount); // ruleid: cv-ws-wire-count-alloc-ts
  return [];
}

export function knownLimits(buf: ArrayBuffer, ok: boolean, view: DataView, offs: number[]) {
  const u = new Uint32Array(buf);
  const { recordCount } = P.parseBinaryFrameHeader(new Uint8Array(buf));
  if (ok && u[0] > MAX_RECORDS) throw new Error("u0");
  new Array(u[0]); // todoruleid: cv-ws-wire-count-alloc-ts
  if (!(0 < u[1])) throw new Error("u1");
  new Array(u[1]); // todoruleid: cv-ws-wire-count-alloc-ts
  new Array(recordCount); // todoruleid: cv-ws-wire-count-alloc-ts
  makeBuffer(u[2]); // todoruleid: cv-ws-wire-count-alloc-ts
  const out: unknown[] = [];
  out.length = u[3]; // todoruleid: cv-ws-wire-count-alloc-ts
  if (!(u[4] <= MAX_RECORDS)) throw new Error("u4");
  new Array(u[4]); // todook: cv-ws-wire-count-alloc-ts
  if (u[5] <= MAX_RECORDS) return new Array(u[5]); // todook: cv-ws-wire-count-alloc-ts
  let n = u[6];
  if (n > MAX_RECORDS) n = MAX_RECORDS;
  new Array(n); // todook: cv-ws-wire-count-alloc-ts
  if (u[7] > u[8]) throw new Error("u7");
  new Array(u[7]); // todoruleid: cv-ws-wire-count-alloc-ts
  new Array(u[9] <= MAX_RECORDS ? 0 : u[9]); // todoruleid: cv-ws-wire-count-alloc-ts
  new Array(readCount(view)); // todoruleid: cv-ws-wire-count-alloc-ts
  new Array(view.getUint8(8) | (view.getUint8(9) << 8)); // todoruleid: cv-ws-wire-count-alloc-ts
  if (u[10] > MAX_RECORDS) throw new Error("u10");
  else new Array(u[10]); // todook: cv-ws-wire-count-alloc-ts
  let header = P.parseBinaryFrameHeader(new Uint8Array(buf));
  assertFits(header.recordCount, 16, buf.byteLength - 24, "a");
  header = P.parseBinaryFrameHeader(new Uint8Array(buf, 8));
  new Array(header.recordCount); // todoruleid: cv-ws-wire-count-alloc-ts
  if (u[12] * u[13] > buf.byteLength) throw new Error("u12");
  new Array(u[13]); // todoruleid: cv-ws-wire-count-alloc-ts
  if (!(u[14] > MAX_RECORDS)) throw new Error("u14");
  new Array(u[14]); // todoruleid: cv-ws-wire-count-alloc-ts
  let m = view.getUint32(0, true);
  try {
    if (m > MAX_RECORDS) throw new Error("m");
  } catch {}
  out.push(new Array(m)); // todoruleid: cv-ws-wire-count-alloc-ts
  for (const off of offs) {
    m = view.getUint32(off, true);
    if (m > MAX_RECORDS) continue;
  }
  out.push(new Array(m)); // todoruleid: cv-ws-wire-count-alloc-ts
  const need = u[15] * 16;
  if (need > buf.byteLength) throw new Error("need");
  new Array(u[15]); // todook: cv-ws-wire-count-alloc-ts
  let at = 0;
  while (at < view.byteLength) at += 4 + view.getUint16(at, true); // todook: cv-ws-wire-count-alloc-ts
  if (m > 8) return [new Array(m)]; // todook: cv-ws-wire-count-alloc-ts
  return out;
}
