// The `bar-cell` vertex shader's y (E11-S05, BQ-113) emulated in float32 with Math.fround on the
// real uniform block: the CPU stand-in (BQ-78) until E11-T08's SwiftShader golden (G-16). GLSL's
// `log` is taken as float32-rounded `Math.log`, and `step(abs(r), 0.05)` as `abs(r) <= 0.05`.
import type { PaneUniforms } from "../../src/viewport/index.js";

const fr = Math.fround;
const THIRD = fr(0.33333333);
const FLOOR = fr(-0.999999);

/** The shader's y for `tick` at the cell's corner, back to CSS px. */
export function shaderY(tick: number, b: PaneUniforms, dpr: number): number {
  const f = b.floats;
  const [ky, kz, lx, on] = [f[1] ?? 0, f[2] ?? 0, f[6] ?? 0, f[7] ?? 0];
  const t = fr(tick - (b.ints[1] ?? 0));
  const r = fr(Math.max(fr(t * lx), FLOOR));
  const series = fr(r * fr(1 - fr(r * fr(0.5 - fr(r * fr(THIRD - fr(r * 0.25)))))));
  const ln = fr(Math.log(fr(1 + r)));
  const step = Math.abs(r) <= 0.05 ? 1 : 0;
  const l = fr(fr(ln * (1 - step)) + fr(series * step));
  return fr(fr(fr(fr(t * fr(1 - on)) + fr(l * on)) * ky) + kz) / dpr;
}
