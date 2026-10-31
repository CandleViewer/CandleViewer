// E11-X02 (CE-T02): the stores too; an integer read is not a float.
export function layoutBad(batch: { layout: { params: number[] } }): number {
  const origin = batch.layout.params[0] ?? 0;
  return origin + 1; // ruleid: cv-engine-decoded-nonfinite
}

export function intOk(view: DataView): number {
  const n = view.getUint32(0, true);
  return n + 1; // ok: cv-engine-decoded-nonfinite
}
