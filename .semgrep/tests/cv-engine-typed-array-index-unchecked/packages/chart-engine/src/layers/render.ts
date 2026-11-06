// E11-X02 (BQ-161): render loops are outside the decode and ingest paths; the rule does not look.
declare const xs: Float32Array;

export function render(view: DataView): number | undefined {
  return xs[view.getUint32(0, true)]; // ok: cv-engine-typed-array-index-unchecked
}
