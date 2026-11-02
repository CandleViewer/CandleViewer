// E11-X02 (CE-T01, CE-D01): a decoded value indexes a typed array only after a bounds check.
declare function assertFits(count: number, stride: number, available: number, what: string): void;
declare const closes: Float64Array;
declare const MAX_ROW: number;

export function viewBad(view: DataView): number | undefined {
  const row = view.getUint32(0, true);
  return closes[row]; // ruleid: cv-engine-typed-array-index-unchecked
}

export function messageBad(msg: Record<string, unknown>): void {
  const at = msg["row"] as number;
  closes[at] = 0; // ruleid: cv-engine-typed-array-index-unchecked
}

export function layoutBad(layout: { count: number }): number | undefined {
  return closes[layout.count - 1]; // ruleid: cv-engine-typed-array-index-unchecked
}

export function guardOk(view: DataView): number | undefined {
  const row = view.getUint32(0, true);
  if (row >= closes.length) return undefined;
  return closes[row]; // ok: cv-engine-typed-array-index-unchecked
}

export function assertOk(view: DataView): number | undefined {
  const row = view.getUint32(0, true);
  assertFits(row, 8, closes.byteLength, "row");
  return closes[row]; // ok: cv-engine-typed-array-index-unchecked
}

export function clampOk(view: DataView): number | undefined {
  const row = Math.min(view.getUint32(0, true), MAX_ROW);
  return closes[row]; // ok: cv-engine-typed-array-index-unchecked
}

export function loopOk(): number {
  let s = 0;
  for (let i = 0; i < closes.length; i += 1) s += closes[i] ?? 0; // ok: cv-engine-typed-array-index-unchecked
  return s;
}
