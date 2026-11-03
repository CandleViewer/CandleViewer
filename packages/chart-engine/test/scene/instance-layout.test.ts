// BQ-87: one instance-layout declaration both backends read; each WebGL2 shader declares exactly
// the per-instance attributes its layout places, so the two backends cannot drift apart. E12-S07
// PR B: the ribbon's +1 instance attributes (`next`) count too, and every `layout(location)` int
// `in` of the candle and ribbon shaders is bound by its `AttributeLayout` at the layout's offset.
import { describe, expect, it } from "vitest";
import type { AttributeLayout } from "../../src/gl/buffers.js";
import { PROGRAMS } from "../../src/gl/program-cache.js";
import { PROGRAM_VERTICES } from "../../src/gl/submit.js";
import { PAINTERS } from "../../src/canvas2d/painters.js";
import { CANDLE_ATTRIBUTES, CANDLE_STRIDE } from "../../src/layers/index.js";
import { RIBBON_ATTRIBUTES } from "../../src/gl/shaders/ribbon.js";
import { attributeOffset, INSTANCE_LAYOUTS, PROGRAM } from "../../src/scene/instance-layout.js";

describe("instance layouts (E11-T05, BQ-87)", () => {
  it.each(Object.entries(PROGRAM))("%s: the shader's `in` attributes are its layout's", (_, id) => {
    const layout = INSTANCE_LAYOUTS[id];
    const vertex = PROGRAMS[id]?.vertex ?? "";
    // E12-S06: `layout(location = N) in` (the candle's int attributes) counts as an `in` too.
    const declared = [...vertex.matchAll(/^(?:layout\(location = \d+\) )?in \w+ (\w+);$/gm)].map(
      (m) => m[1],
    );
    const next = layout?.next ?? [];
    expect(declared.filter((n) => n !== "a_corner")).toEqual(
      [...(layout?.attributes ?? []), ...next].map(([n]) => n),
    );
  });

  it("numbers every program once, densely, in all four program tables", () => {
    const ids = Object.values(PROGRAM).sort((a, b) => a - b);
    expect(ids).toEqual(ids.map((_, i) => i));
    for (const table of [INSTANCE_LAYOUTS, PROGRAMS, PROGRAM_VERTICES, PAINTERS]) {
      expect(table).toHaveLength(ids.length);
    }
    expect(PROGRAMS[PROGRAM.ribbon]?.name).toBe("ribbon");
  });

  it("places each +1 instance attribute one stride past its slot attribute", () => {
    for (const { stride, attributes, next } of INSTANCE_LAYOUTS) {
      for (const [, offset, size, int] of next ?? []) {
        expect(
          attributes.some(([, o, sz, i]) => o + stride === offset && sz === size && i === int),
        ).toBe(true);
      }
    }
  });

  const BOUND: readonly (readonly [string, number, AttributeLayout])[] = [
    ["candle", PROGRAM.candle, CANDLE_ATTRIBUTES],
    ["ribbon", PROGRAM.ribbon, RIBBON_ATTRIBUTES],
  ];
  it.each(BOUND)(
    "%s: every `layout(location)` int `in` is bound where its layout puts it",
    (_, id, bound) => {
      const layout = INSTANCE_LAYOUTS[id];
      const vertex = PROGRAMS[id]?.vertex ?? "";
      const ins = [...vertex.matchAll(/^layout\(location = (\d+)\) in (int|ivec4) (\w+);$/gm)];
      expect(ins.length).toBeGreaterThan(0);
      expect(bound.stride).toBe(layout?.stride);
      expect(bound.stride).toBe(CANDLE_STRIDE); // both read the CandleRing's words
      const all = [...(layout?.attributes ?? []), ...(layout?.next ?? [])];
      for (const [, loc, type, name] of ins) {
        const at = all.find(([n]) => n === name);
        const b = bound.ints.find(([l]) => l === Number(loc));
        expect(b, `${name} at location ${loc}`).toEqual([
          Number(loc),
          at?.[1],
          type === "int" ? 1 : 4,
        ]);
        expect(at?.[3]).toBe(true);
      }
      expect(bound.ints).toHaveLength(ins.length);
    },
  );

  it("packs every attribute inside its stride, without overlap", () => {
    for (const { stride, attributes } of INSTANCE_LAYOUTS) {
      let end = 0;
      for (const [, offset, size] of attributes) {
        expect(offset).toBe(end);
        end = offset + size;
      }
      expect(end).toBe(stride);
    }
  });

  it("names a missing attribute instead of reading slot 0", () => {
    expect(attributeOffset(PROGRAM.barCell, "a_color")).toBe(4);
    expect(() => attributeOffset(PROGRAM.quad, "a_cell")).toThrow(/no a_cell/);
  });
});
