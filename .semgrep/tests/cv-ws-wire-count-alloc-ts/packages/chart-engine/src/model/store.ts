// E11-X02 (F-11, CE-D01): the rule's paths include the engine's stores.
declare const MAX_BARS: number;

export function columnBad(view: DataView): Float64Array {
  const count = view.getUint32(0, true);
  return new Float64Array(count); // ruleid: cv-ws-wire-count-alloc-ts
}

export function columnOk(view: DataView): Float64Array {
  const count = view.getUint32(0, true);
  if (count > MAX_BARS) throw new RangeError("count over maxBars");
  return new Float64Array(count); // ok: cv-ws-wire-count-alloc-ts
}
