// E12-S06 (#5307 review): a uniform both stages declare must have ONE precision, or ESSL 3.00 /
// ANGLE refuses to link ("Precisions of uniform differ between VERTEX and FRAGMENT shaders"),
// which the fake GL cannot see. Parses every program's two sources: an explicit qualifier wins,
// else the stage's `precision` statement, else the ESSL 3.00 default (vertex: highp float and int;
// fragment: no float default, mediump int).
import { describe, expect, it } from "vitest";
import { PROGRAMS } from "../../src/gl/program-cache.js";

type Stage = "vertex" | "fragment";
const DEFAULTS: Record<Stage, Record<string, string | undefined>> = {
  vertex: { float: "highp", int: "highp" },
  fragment: { float: undefined, int: "mediump" },
};
const base = (type: string): string | null =>
  /^(u?int|[iu]vec[234])$/.test(type)
    ? "int"
    : /^(float|vec[234]|mat[234](x[234])?)$/.test(type)
      ? "float"
      : null;

/** Uniform name → its precision in one stage's source. */
export function uniformPrecisions(src: string, stage: Stage): Map<string, string | undefined> {
  const defaults = { ...DEFAULTS[stage] };
  for (const m of src.matchAll(/^\s*precision\s+(lowp|mediump|highp)\s+(float|int)\s*;/gm)) {
    defaults[m[2] as string] = m[1];
  }
  const out = new Map<string, string | undefined>();
  const re = /^\s*uniform\s+(?:(lowp|mediump|highp)\s+)?(\w+)\s+(\w+)\s*(?:\[[^\]]*\])?\s*;/gm;
  for (const m of src.matchAll(re)) {
    const kind = base(m[2] as string);
    if (kind === null) continue; // samplers carry their own default; none is shared today
    out.set(m[3] as string, m[1] ?? defaults[kind]);
  }
  return out;
}

describe("shader sources: one precision per shared uniform", () => {
  it.each(PROGRAMS.map((p) => [p.name, p] as const))("%s", (_, p) => {
    const v = uniformPrecisions(p.vertex, "vertex");
    const f = uniformPrecisions(p.fragment, "fragment");
    const mismatched = [...f].filter(([name, prec]) => v.has(name) && v.get(name) !== prec);
    expect(mismatched).toEqual([]);
    for (const [name, prec] of f) expect(prec, `${p.name}: ${name} has no precision`).toBeDefined();
  });

  it("the parser sees a mismatch (the pre-fix candle fragment)", () => {
    const v = uniformPrecisions("uniform vec4 u_geom[2];", "vertex");
    const f = uniformPrecisions("precision mediump float;\nuniform vec4 u_geom[2];", "fragment");
    expect([v.get("u_geom"), f.get("u_geom")]).toEqual(["highp", "mediump"]);
  });
});
