// E11-S11 PR A (BQ-266): R8 textures for the SDF atlas — 1 B/px, UNPACK_ALIGNMENT 1, the packed
// rows patched and kept as the restore copy, nothing uploaded while the context is lost.
import { describe, expect, it } from "vitest";
import { GL } from "../../src/gl/gl-types.js";
import { GlRegistry } from "../../src/gl/registry.js";
import { ATLAS_TEXTURE, GlTextures } from "../../src/gl/textures.js";
import { FakeGl } from "./fake-gl.js";

const rows = Uint8Array.from({ length: 64 * 3 }, (_, i) => i % 256);
const IMAGE = `image ${GL.R8} 64x32`;

function setup() {
  const gl = new FakeGl();
  const registry = new GlRegistry(gl);
  return { gl, registry, tex: new GlTextures(gl, registry) };
}

describe("GlTextures R8 and rows (BQ-266)", () => {
  it("defines R8 at 1 B/px with UNPACK_ALIGNMENT 1, then uploads only the packed rows", () => {
    const { gl, tex } = setup();
    tex.define(ATLAS_TEXTURE, 64, 32, null, "r8");
    tex.patchRows(ATLAS_TEXTURE, 0, rows);
    expect(tex.bytes).toBe(64 * 32);
    expect(gl.textures).toEqual([
      `store ${GL.UNPACK_ALIGNMENT} 1`,
      IMAGE,
      `store ${GL.UNPACK_ALIGNMENT} 1`,
      expect.stringMatching(/^rows 3 \d+$/),
    ]);
  });

  it("the atlas clamps at its edges in both axes: a UV never wraps to the opposite edge", () => {
    const { gl, tex } = setup();
    tex.define(ATLAS_TEXTURE, 64, 32, null, "r8");
    expect(gl.texParams).toEqual(
      expect.arrayContaining([
        `${GL.TEXTURE_WRAP_S} ${GL.CLAMP_TO_EDGE}`,
        `${GL.TEXTURE_WRAP_T} ${GL.CLAMP_TO_EDGE}`,
      ]),
    );
  });

  it("a restore re-uploads the image and its rows; RGBA textures still count 4 B/px", () => {
    const { gl, registry, tex } = setup();
    tex.define(2, 4, 4, null);
    tex.define(ATLAS_TEXTURE, 64, 32, null, "r8");
    tex.patchRows(ATLAS_TEXTURE, 0, rows);
    expect(tex.bytes).toBe(64 * 32 + 64);
    const before = gl.textures.length;
    gl.loseContext();
    registry.invalidateAll();
    gl.restoreContext();
    registry.recreateAll();
    tex.restore();
    const rowsUpload = gl.textures.find((t) => t.startsWith("rows"));
    expect(gl.textures.slice(before).filter((t) => !t.startsWith("store"))).toEqual([
      IMAGE,
      rowsUpload,
      `image ${GL.RGBA8} 4x4`,
    ]);
  });

  it("while lost nothing uploads; the restore uploads the atlas exactly once", () => {
    const { gl, registry, tex } = setup();
    gl.loseContext();
    registry.invalidateAll();
    tex.define(ATLAS_TEXTURE, 64, 32, null, "r8");
    tex.patchRows(ATLAS_TEXTURE, 0, rows);
    expect(gl.textures).toEqual([]);
    gl.restoreContext();
    registry.recreateAll();
    tex.restore();
    expect(gl.textures.filter((t) => !t.startsWith("store"))).toHaveLength(2);
  });

  it("patchRows ignores an unknown, RGBA or offset target", () => {
    const { gl, tex } = setup();
    tex.define(2, 4, 4, null);
    tex.patchRows(9, 0, rows);
    tex.patchRows(2, 0, rows);
    tex.define(ATLAS_TEXTURE, 64, 32, null, "r8");
    tex.patchRows(ATLAS_TEXTURE, 1, rows);
    expect(gl.textures.filter((t) => t.startsWith("rows"))).toEqual([]);
  });
});
