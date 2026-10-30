// The GPU resource registry's lifecycle (E11-S02 Test plan: "resource registry lifecycle
// (create/invalidate/recreate)"); the fake GL's `alive` set is the leak check.
import { describe, expect, it } from "vitest";
import { GlRegistry, RESOURCE_KINDS } from "../../src/gl/registry.js";
import { FakeGl } from "./fake-gl.js";

function filled(gl: FakeGl): GlRegistry {
  const reg = new GlRegistry(gl);
  for (const kind of [...RESOURCE_KINDS].reverse()) reg.create(kind); // created out of order
  return reg;
}

describe("GlRegistry", () => {
  it("creates one GL object per slot and resolves handles to them", () => {
    const gl = new FakeGl();
    const reg = new GlRegistry(gl);
    const prog = reg.create("program");
    const buf = reg.create("buffer");
    expect(reg.get(prog)).toEqual({ kind: "Program", id: 1 });
    expect(reg.get(buf)).toEqual({ kind: "Buffer", id: 2 });
    expect(reg.counts()).toEqual({ program: 1, texture: 0, buffer: 1, vertexArray: 0, live: 2 });
    expect(gl.alive.size).toBe(2);
  });

  it("invalidates every object on loss without a GL call, then recreates in dependency order", () => {
    const gl = new FakeGl();
    const reg = filled(gl);
    const handles = [1, 2, 3, 4] as never[];
    gl.loseContext();
    gl.log.length = 0;
    reg.invalidateAll();
    expect(gl.log).toEqual([]);
    expect(handles.map((h) => reg.get(h))).toEqual([null, null, null, null]);
    expect([reg.generation, reg.counts().live, reg.stats.invalidations]).toEqual([1, 0, 1]);
    gl.restoreContext();
    expect(reg.recreateAll()).toBe(0);
    expect(gl.log).toEqual(["createProgram", "createTexture", "createBuffer", "createVertexArray"]);
    expect(handles.every((h) => reg.get(h) !== null)).toBe(true);
    expect([reg.counts().live, gl.alive.size, reg.stats.recreated]).toEqual([4, 4, 4]);
  });

  it("keeps slots made while lost and fills them on restore; a second loss reports the gap", () => {
    const gl = new FakeGl();
    const reg = new GlRegistry(gl);
    gl.loseContext();
    const tex = reg.create("texture");
    expect(reg.get(tex)).toBeNull();
    expect(reg.recreateAll()).toBe(1); // still lost: the attempt failed
    gl.restoreContext();
    expect(reg.recreateAll()).toBe(0);
    expect(reg.get(tex)).not.toBeNull();
  });

  it("recreates onto a replacement context", () => {
    const old = new FakeGl();
    const reg = filled(old);
    old.loseContext();
    reg.invalidateAll();
    const next = new FakeGl();
    expect(reg.recreateAll(next)).toBe(0);
    expect([old.alive.size, next.alive.size]).toEqual([0, 4]);
    const h = reg.create("buffer");
    expect(next.alive.has(reg.get(h) as object)).toBe(true);
  });

  it("drops the old context's objects when handed a replacement without invalidateAll", () => {
    const old = new FakeGl();
    const reg = filled(old);
    const next = new FakeGl();
    expect(reg.recreateAll(next)).toBe(0);
    expect([reg.generation, next.alive.size]).toEqual([1, 4]);
    expect([...next.alive].length).toBe(reg.counts().live);
  });

  it("releases every object it created: no leaks across a loss", () => {
    const gl = new FakeGl();
    const reg = filled(gl);
    gl.loseContext();
    reg.invalidateAll();
    gl.restoreContext();
    reg.recreateAll();
    for (const h of [1, 2, 3, 4] as never[]) reg.release(h);
    reg.release(99 as never); // unknown: a no-op
    expect([gl.alive.size, reg.counts().live, reg.counts().buffer]).toEqual([0, 0, 0]);
    expect(reg.stats).toEqual({ created: 8, deleted: 4, recreated: 4, invalidations: 1 });
  });

  it("releases a slot during a loss without a GL call", () => {
    const gl = new FakeGl();
    const reg = new GlRegistry(gl);
    const h = reg.create("vertexArray");
    gl.loseContext();
    gl.log.length = 0;
    reg.release(h);
    expect(gl.log).toEqual(["isContextLost"]);
    expect(reg.stats.deleted).toBe(0);
  });
});
