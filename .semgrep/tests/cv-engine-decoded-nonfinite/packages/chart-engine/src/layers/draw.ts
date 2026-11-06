// E11-X02 (BQ-161): outside the decode and ingest paths the rule does not look.
export function draw(view: DataView): number {
  return view.getFloat32(0, true) * 2; // ok: cv-engine-decoded-nonfinite
}
