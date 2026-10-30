// BQ-87: one instance-layout declaration both backends read; each WebGL2 shader declares exactly
// the per-instance attributes its layout places, so the two backends cannot drift apart.
import { describe, expect, it } from "vitest";
import { PROGRAMS } from "../../src/gl/program-cache.js";
import { attributeOffset, INSTANCE_LAYOUTS, PROGRAM } from "../../src/scene/instance-layout.js";

describe("instance layouts (E11-T05, BQ-87)", () => {
  it.each(Object.entries(PROGRAM))("%s: the shader's `in` attributes are its layout's", (_, id) => {
    const layout = INSTANCE_LAYOUTS[id];
    const vertex = PROGRAMS[id]?.vertex ?? "";
    const declared = [...vertex.matchAll(/^in \w+ (\w+);$/gm)].map((m) => m[1]);
    expect(declared.filter((n) => n !== "a_corner")).toEqual(layout?.attributes.map(([n]) => n));
  });

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
