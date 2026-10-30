// The GPU resource registry (E11-S02, README BQ-57): the one owner of every GL object, so a context
// loss invalidates and recreates them all in one place. Nothing else calls `create*` (guarded by
// test/gl/ownership.test.ts); other code holds a `Handle`, a logical slot that survives a loss,
// and resolves it with `get()` each frame. The scene graph and the DataModel stay CPU-side truth.
import type { GL2Like, GLObject } from "./gl-types.js";

/** Recreate order after a restore (ticket design: programs, then textures, then buffers, VAOs). */
export const RESOURCE_KINDS = ["program", "texture", "buffer", "vertexArray"] as const;
export type ResourceKind = (typeof RESOURCE_KINDS)[number];

declare const BRAND: unique symbol;
/** A registry slot of one kind; only src/gl may name this type (BQ-57). */
export type Handle<K extends ResourceKind = ResourceKind> = number & { readonly [BRAND]: K };

type Ops = { create(gl: GL2Like): GLObject | null; remove(gl: GL2Like, o: GLObject): void };
const OPS: Readonly<Record<ResourceKind, Ops>> = {
  program: { create: (gl) => gl.createProgram(), remove: (gl, o) => gl.deleteProgram(o) },
  texture: { create: (gl) => gl.createTexture(), remove: (gl, o) => gl.deleteTexture(o) },
  buffer: { create: (gl) => gl.createBuffer(), remove: (gl, o) => gl.deleteBuffer(o) },
  vertexArray: { create: (gl) => gl.createVertexArray(), remove: (g, o) => g.deleteVertexArray(o) },
};

interface Slot {
  readonly kind: ResourceKind;
  object: GLObject | null;
}

/**
 * Counters behind `engine.gl.*` (README BQ-57). `created` counts every successful `create*` call,
 * recreations included (`recreated` is that subset). A release while the context is lost frees
 * the slot without a delete, so `created - deleted` is not the live count; use `counts().live`.
 */
export interface RegistryStats {
  created: number;
  deleted: number;
  recreated: number;
  invalidations: number;
}

export class GlRegistry {
  /** Bumped by every `invalidateAll()`: GPU state derived under an older one is stale. */
  generation = 0;
  readonly stats: RegistryStats = { created: 0, deleted: 0, recreated: 0, invalidations: 0 };
  private readonly slots = new Map<number, Slot>();
  private seq = 0;

  constructor(private gl: GL2Like) {}

  /** A new slot; its object is null while the context is lost, until `recreateAll()`. */
  create<K extends ResourceKind>(kind: K): Handle<K> {
    this.seq += 1;
    this.slots.set(this.seq, { kind, object: this.make(kind) });
    return this.seq as Handle<K>;
  }

  /** The live GL object behind `h`, or null (released, or invalidated and not yet recreated). */
  get(h: Handle): GLObject | null {
    return this.slots.get(h)?.object ?? null;
  }

  /** Deletes the object (a lost context's objects are already gone) and frees the slot. */
  release(h: Handle): void {
    const slot = this.slots.get(h);
    if (slot === undefined) return;
    this.slots.delete(h);
    if (slot.object !== null && !this.gl.isContextLost()) {
      OPS[slot.kind].remove(this.gl, slot.object);
      this.stats.deleted += 1;
    }
  }

  /** On `webglcontextlost`: every object is dead; drop them without GL calls, keep the slots. */
  invalidateAll(): void {
    for (const slot of this.slots.values()) slot.object = null;
    this.generation += 1;
    this.stats.invalidations += 1;
  }

  /**
   * On restore (or on a replacement context, `gl`): one fresh object per slot, in
   * `RESOURCE_KINDS` order. Returns how many slots still have no object (the context was lost
   * again); the caller treats a non-zero result as a failed attempt. A replacement context
   * invalidates first, so no object of the old context survives even without `invalidateAll()`.
   */
  recreateAll(gl: GL2Like = this.gl): number {
    if (gl !== this.gl) this.invalidateAll();
    this.gl = gl;
    let missing = 0;
    for (const kind of RESOURCE_KINDS) {
      for (const slot of this.slots.values()) {
        if (slot.kind !== kind || slot.object !== null) continue;
        slot.object = this.make(kind);
        if (slot.object === null) missing += 1;
        else this.stats.recreated += 1;
      }
    }
    return missing;
  }

  /** Slots per kind, and how many of them hold a live object. */
  counts(): Record<ResourceKind | "live", number> {
    const out = { program: 0, texture: 0, buffer: 0, vertexArray: 0, live: 0 };
    for (const slot of this.slots.values()) {
      out[slot.kind] += 1;
      if (slot.object !== null) out.live += 1;
    }
    return out;
  }

  private make(kind: ResourceKind): GLObject | null {
    const object = OPS[kind].create(this.gl);
    if (object !== null) this.stats.created += 1;
    return object;
  }
}
