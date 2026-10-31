// E11-X02 (CE-T02): the stores, too.
declare const volumes: Uint32Array;

export function writeBad(ev: { data: { at: number } }): void {
  volumes[ev.data.at] = 1; // ruleid: cv-engine-typed-array-index-unchecked
}

export function writeOk(ev: { data: { at: number } }): void {
  const at = ev.data.at;
  if (at > volumes.length - 1) throw new RangeError("at past the column");
  volumes[at] = 1; // ok: cv-engine-typed-array-index-unchecked
}
