// E11-X02 (F-11, CE-D01): and the worker boundary, where the counts arrive.
export function rowsBad(view: DataView): number[] {
  const rows = view.getUint16(2, true);
  return new Array(rows); // ruleid: cv-ws-wire-count-alloc-ts
}

export function rowsOk(view: DataView): number[] {
  const rows = Math.min(view.getUint16(2, true), 64);
  return new Array(rows); // ok: cv-ws-wire-count-alloc-ts
}
