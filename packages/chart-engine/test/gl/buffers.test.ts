// E11-S02 PR2: sub-range uploads land at the ring's physical slots (BQ-46).
import { describe, expect, it } from "vitest";
import { GlBuffers } from "../../src/gl/buffers.js";
import { GlRegistry } from "../../src/gl/registry.js";
import { GlTextures } from "../../src/gl/textures.js";
import type { RetainedBatch } from "../../src/scene/batch-builder.js";
import { FakeGl } from "./fake-gl.js";

const batch = (nodeId: string) => ({ nodeId }) as RetainedBatch;

describe("GlBuffers", () => {
  it("maps logical ranges through the ring head, splits a wrap, and re-uploads a reallocation", () => {
    const gl = new FakeGl();
    const buffers = new GlBuffers(gl, new GlRegistry(gl));
    const source = { data: new Float32Array(8 * 2), head: 0, stride: 2 }; // 8 slots of 2 floats
    buffers.attach("s", source);
    buffers.attach("s", source); // idempotent
    buffers.uploadSubRange(batch("s"), 0, 8); // first upload: in full
    buffers.uploadSubRange(batch("s"), 2, 5); // slots 2..4: floats 4..9, bytes 16..
    source.head = 6;
    buffers.uploadSubRange(batch("s"), 0, 4); // slots 6, 7 then 0, 1: wraps
    source.data = new Float32Array(16 * 2); // the store grew: re-linearised, in full
    buffers.uploadSubRange(batch("s"), 3, 4);
    buffers.uploadSubRange(batch("absent"), 0, 1); // no buffer: ignored
    expect(gl.writes).toEqual(["full 64", "sub 16 4 6", "sub 48 12 4", "sub 0 0 4", "full 128"]);
    expect(buffers.bytes).toBe(128);
    expect(buffers.takeUploaded()).toBe(64 + 24 + 16 + 16 + 128);
    expect(buffers.takeUploaded()).toBe(0);
    expect(buffers.vao("absent")).toBeNull();
    expect(buffers.vao("s")).not.toBeNull();
  });
});

describe("GlTextures", () => {
  it("defines, patches and binds RGBA8 textures, counting their bytes", () => {
    const gl = new FakeGl();
    const textures = new GlTextures(gl, new GlRegistry(gl));
    textures.define(1, 256, 1, null); // a LUT
    textures.define(1, 256, 2, new Uint8Array(256 * 2 * 4)); // redefined: same object
    textures.patch(1, 0, 0, 1, 1, new Uint8Array(4));
    textures.patch(7, 0, 0, 1, 1, new Uint8Array(4)); // undefined: ignored
    textures.bind(0);
    expect(textures.bytes).toBe(2048);
    expect(gl.log.filter((c) => c.startsWith("tex"))).toEqual([
      ...["texParameteri", "texParameteri", "texImage2D"],
      ...["texParameteri", "texParameteri", "texImage2D", "texSubImage2D"],
    ]);
    expect(gl.log.filter((c) => c === "createTexture")).toHaveLength(1);
  });
});
