// E11-X02 (F-11): outside the decode and ingest paths the rule does not look (render loops).
export function outside(view: DataView): number[] {
  const rows = view.getUint16(2, true);
  return new Array(rows); // ok: cv-ws-wire-count-alloc-ts
}
