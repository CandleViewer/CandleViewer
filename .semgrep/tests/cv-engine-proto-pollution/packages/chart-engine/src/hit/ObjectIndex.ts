// E11-X02 (F-15): `hit/ObjectIndex.ts` fills an entry from an object literal it builds itself.
declare const e: Record<string, unknown>;
declare const t0: number;

export function fill(): void {
  Object.assign(e, { type: "point", t0, handles: Float64Array.from([t0]) }); // ok: cv-engine-proto-pollution
}
