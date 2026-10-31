// E11-X02 (CE-T02): arithmetic on a decoded value only after Number.isFinite.
declare function finite(...v: unknown[]): boolean;

export function messageBad(msg: Record<string, unknown>): number {
  const dpr = msg["dpr"] as number;
  return 100 * dpr; // ruleid: cv-engine-decoded-nonfinite
}

export function viewBad(view: DataView): number {
  const price = view.getFloat64(8, true);
  return Math.round(price); // ruleid: cv-engine-decoded-nonfinite
}

export function isFiniteOk(view: DataView): number {
  const price = view.getFloat64(8, true);
  if (!Number.isFinite(price)) return 0;
  return price * 2; // ok: cv-engine-decoded-nonfinite
}

export function finiteOk(msg: Record<string, unknown>): number {
  const w = msg["width"] as number;
  if (!finite(w)) throw new RangeError("width");
  return w / 2; // ok: cv-engine-decoded-nonfinite
}

export function constantOk(): number {
  const a = 2;
  return a * 3; // ok: cv-engine-decoded-nonfinite
}
