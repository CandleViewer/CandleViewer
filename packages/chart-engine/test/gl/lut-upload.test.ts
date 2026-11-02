// E11-T04 PR-3 (26 §5 rule 1, BQ-T04-06): the LUT texture through the fake GL — one upload per
// theme switch (the first defines it, every later switch is one texSubImage2D), clamped at its
// edges, the current theme's bytes re-uploaded after a context restore, freed on dispose.
import { describe, expect, it } from "vitest";
import { GLBackend } from "../../src/gl/backend.js";
import { GL } from "../../src/gl/gl-types.js";
import { ATLAS_TEXTURE, LUT_TEXTURE } from "../../src/gl/textures.js";
import { ColorLutWriter, LUT_BYTES, LUT_ROWS, LUT_WIDTH } from "../../src/theme/ColorLut.js";
import { ingestTheme } from "../../src/theme/ThemeIngest.js";
import { rampInput } from "../theme/fixture.js";
import { FakeGl } from "./fake-gl.js";

const uploads = (gl: FakeGl): string[] => gl.textures.filter((t) => !t.startsWith("store"));

function setup() {
  const gl = new FakeGl();
  const backend = new GLBackend(gl, null);
  const pixels = new Uint8Array(LUT_BYTES);
  const writer = new ColorLutWriter();
  const image = { width: LUT_WIDTH, height: LUT_ROWS, pixels };
  const switchTo = (name: "dark" | "light"): void => {
    writer.writeAll(ingestTheme(rampInput(name)), pixels);
    backend.uploadLuts(image);
  };
  return { gl, backend, pixels, switchTo };
}

describe("GLBackend.uploadLuts", () => {
  it("reserves its own texture id, apart from the atlas", () => {
    expect(LUT_TEXTURE).not.toBe(ATLAS_TEXTURE);
  });

  it("each theme switch is exactly one upload: the first defines, later ones sub-image", () => {
    const { gl, backend, switchTo } = setup();
    switchTo("dark");
    expect(uploads(gl)).toEqual([`image ${GL.RGBA8} ${LUT_WIDTH}x${LUT_ROWS}`]);
    for (const name of ["light", "dark", "light"] as const) {
      const before = uploads(gl).length;
      switchTo(name);
      const added = uploads(gl).slice(before);
      expect(added).toHaveLength(1);
      expect(added[0]).toMatch(new RegExp(`^rows ${LUT_ROWS} \\d+$`));
    }
    expect(backend.textures.bytes).toBe(LUT_BYTES);
  });

  it("a different theme's bytes reach the sub-image upload", () => {
    const { gl, switchTo } = setup();
    switchTo("dark");
    switchTo("light");
    switchTo("dark");
    const [, light, dark] = uploads(gl);
    expect(light).not.toBe(dark);
  });

  it("the LUT clamps in both axes: t = −1 never samples the +1 end", () => {
    const { gl, switchTo } = setup();
    switchTo("dark");
    expect(gl.texParams).toEqual(
      expect.arrayContaining([
        `${GL.TEXTURE_WRAP_S} ${GL.CLAMP_TO_EDGE}`,
        `${GL.TEXTURE_WRAP_T} ${GL.CLAMP_TO_EDGE}`,
      ]),
    );
  });

  it("a new buffer or size redefines the texture (one image upload, the restore copy moves)", () => {
    const { gl, backend, switchTo } = setup();
    switchTo("dark");
    backend.uploadLuts({ width: LUT_WIDTH, height: 2, pixels: new Uint8Array(LUT_WIDTH * 8) });
    expect(uploads(gl).at(-1)).toBe(`image ${GL.RGBA8} ${LUT_WIDTH}x2`);
    expect(backend.textures.bytes).toBe(LUT_WIDTH * 8);
  });

  it("while lost nothing uploads; the restore uploads the current theme's LUTs once", () => {
    const { gl, backend, switchTo } = setup();
    switchTo("dark");
    gl.loseContext();
    backend.invalidate();
    const calls = gl.log.length;
    switchTo("light");
    // patch() returns early on a lost context, as define() and patchRows() do.
    expect(gl.log.slice(calls).filter((c) => c !== "isContextLost")).toEqual([]);
    const before = uploads(gl).length;
    gl.restoreContext();
    expect(backend.restore()).toBe(true);
    expect(uploads(gl).slice(before)).toEqual([`image ${GL.RGBA8} ${LUT_WIDTH}x${LUT_ROWS}`]);
  });

  it("rejects a short buffer and uploads nothing", () => {
    const { gl, backend } = setup();
    const short = { width: LUT_WIDTH, height: LUT_ROWS, pixels: new Uint8Array(LUT_BYTES - 1) };
    expect(() => backend.uploadLuts(short)).toThrow(RangeError);
    expect(uploads(gl)).toEqual([]);
  });

  it("dispose frees the LUT texture", () => {
    const { gl, backend, switchTo } = setup();
    switchTo("dark");
    expect(gl.alive.size).toBeGreaterThan(0);
    backend.dispose();
    expect(gl.alive.size).toBe(0);
  });
});
