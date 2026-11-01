// Two-pass Felzenszwalb–Huttenlocher exact Euclidean distance transform and 8-bit SDF (E11-S11,
// 26 §3.7), ported from the E06-K03 prototype (bench/scenes/edt.mjs; never imported). Float64 is
// K01's baseline; Float32 is K2's lever 2 and part of the generator version (BQ-262).
const INF = 1e20;
type Floats = Float64Array | Float32Array;

function edt1d(f: Floats, n: number, out: Floats, v: Int32Array, z: Floats): void {
  let k = 0;
  v[0] = 0;
  z[0] = -INF;
  z[1] = INF;
  const at = (i: number): number => f[i] as number;
  for (let q = 1; q < n; q += 1) {
    let r = v[k] as number;
    let s = (at(q) + q * q - (at(r) + r * r)) / (2 * q - 2 * r);
    while (s <= (z[k] as number)) {
      k -= 1;
      r = v[k] as number;
      s = (at(q) + q * q - (at(r) + r * r)) / (2 * q - 2 * r);
    }
    k += 1;
    v[k] = q;
    z[k] = s;
    z[k + 1] = INF;
  }
  k = 0;
  for (let q = 0; q < n; q += 1) {
    while ((z[k + 1] as number) < q) k += 1;
    const r = v[k] as number;
    out[q] = (q - r) * (q - r) + at(r);
  }
}

/** Squared distance, in place, from each cell to the nearest cell whose value is 0. */
export function edt2d(grid: Floats, w: number, h: number, f32 = false): void {
  const m = Math.max(w, h);
  const make = (n: number): Floats => (f32 ? new Float32Array(n) : new Float64Array(n));
  const [f, out, z] = [make(m), make(m), make(m + 1)];
  const v = new Int32Array(m);
  for (let x = 0; x < w; x += 1) {
    for (let y = 0; y < h; y += 1) f[y] = grid[y * w + x] as number;
    edt1d(f, h, out, v, z);
    for (let y = 0; y < h; y += 1) grid[y * w + x] = out[y] as number;
  }
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) f[x] = grid[y * w + x] as number;
    edt1d(f, w, out, v, z);
    for (let x = 0; x < w; x += 1) grid[y * w + x] = out[x] as number;
  }
}

/**
 * Coverage (≥ 128 is inside) to an 8-bit SDF: 128 is the edge and `spread` px each side maps to
 * the full range, inside above 128.
 */
export function sdfFromCoverage(
  coverage: Uint8Array,
  w: number,
  h: number,
  spread: number,
  f32 = false,
): Uint8Array {
  const n = w * h;
  const toIn = f32 ? new Float32Array(n) : new Float64Array(n);
  const toOut = f32 ? new Float32Array(n) : new Float64Array(n);
  for (let i = 0; i < n; i += 1) {
    const inside = (coverage[i] as number) >= 128;
    toIn[i] = inside ? 0 : INF;
    toOut[i] = inside ? INF : 0;
  }
  edt2d(toIn, w, h, f32);
  edt2d(toOut, w, h, f32);
  const sdf = new Uint8Array(n);
  for (let i = 0; i < n; i += 1) {
    const outside = Math.sqrt(toIn[i] as number) - Math.sqrt(toOut[i] as number);
    const norm = 0.5 - outside / (2 * spread);
    sdf[i] = Math.max(0, Math.min(255, Math.round(norm * 255)));
  }
  return sdf;
}
