// Vertex buffers (E11-S02, 26 §3.3/§3.4): the batch builder's `UploadSink`. Each source's GPU
// buffer (shared by the nodes drawing it, E12-S06) mirrors its store's ring slot for slot, so a logical range [from, to) lands at the
// physical slots (head + i) mod capacity: one `bufferSubData`, two when the range wraps. A new
// backing array (the store reallocated, or the first upload) is uploaded in full (BQ-46).
import type { RetainedBatch, UploadSink } from "../scene/batch-builder.js";
import type { AttributeLayout, VertexSource } from "../scene/gpu-types.js";
import { GL, type GL2Like, type GLObject } from "./gl-types.js";
import type { GlRegistry, Handle } from "./registry.js";

export type { AttributeLayout, VertexSource };

/** One GPU buffer per source (E12-S06): the nodes drawing one ring share it. */
interface Shared {
  readonly source: VertexSource;
  readonly buffer: Handle<"buffer">;
  /** The node whose batch uploads for every node of the source (one upload, not one per node). */
  readonly owner: string;
  uploaded: Float32Array | null;
}

interface Slot {
  readonly source: VertexSource;
  readonly shared: Shared;
  readonly vao: Handle<"vertexArray">;
  readonly layout: AttributeLayout | null;
  /** The VAO's attributes are bound (false after creation and after a context loss). */
  configured: boolean;
}

export class GlBuffers implements UploadSink {
  /** GPU bytes held, for `gpuMemoryMbEstimate`. */
  bytes = 0;
  /** Bytes uploaded since the last `takeUploaded()`. */
  uploaded = 0;
  private readonly slots = new Map<string, Slot>();
  private readonly sources = new Map<VertexSource, Shared>();
  /** The same records as plain arrays: the loss and restore loops walk these (no iterators). */
  private readonly sharedList: Shared[] = [];
  private readonly slotList: Slot[] = [];

  constructor(
    private readonly gl: GL2Like,
    private readonly registry: GlRegistry,
  ) {}

  /**
   * Gives a drawing node a VAO over its source's buffer, shared by every node of that source;
   * the store-to-node mapping is the runtime's. `layout` binds int instance attributes (divisor 1).
   */
  attach(nodeId: string, source: VertexSource, layout: AttributeLayout | null = null): void {
    if (this.slots.has(nodeId)) return;
    let shared = this.sources.get(source);
    if (shared === undefined) {
      shared = { source, buffer: this.registry.create("buffer"), owner: nodeId, uploaded: null };
      this.sources.set(source, shared);
      this.sharedList.push(shared);
    }
    const slot = {
      source,
      shared,
      vao: this.registry.create("vertexArray"),
      layout,
      configured: false,
    };
    this.slots.set(nodeId, slot);
    this.slotList.push(slot);
  }

  /** The node's VAO, its attributes bound on first use; null without one (no draw). */
  vao(nodeId: string): GLObject | null {
    const slot = this.slots.get(nodeId);
    if (slot === undefined) return null;
    const vao = this.registry.get(slot.vao);
    const layout = slot.layout;
    if (layout !== null && !slot.configured && vao !== null) {
      const gl = this.gl;
      gl.bindVertexArray(vao);
      gl.bindBuffer(GL.ARRAY_BUFFER, this.registry.get(slot.shared.buffer));
      for (const [at, offset, size] of layout.ints) {
        gl.enableVertexAttribArray(at);
        gl.vertexAttribIPointer(at, size, GL.INT, layout.stride * 4, offset * 4);
        gl.vertexAttribDivisor(at, 1);
      }
      slot.configured = true;
    }
    return vao;
  }

  takeUploaded(): number {
    const n = this.uploaded;
    this.uploaded = 0;
    return n;
  }

  /** On a context loss: the GPU copies are gone, so each source's next upload is a full one. */
  invalidate(): void {
    const shared = this.sharedList;
    for (let i = 0; i < shared.length; i += 1) (shared[i] as Shared).uploaded = null;
    const slots = this.slotList;
    for (let i = 0; i < slots.length; i += 1) (slots[i] as Slot).configured = false;
    this.bytes = 0;
  }

  /** After a restore: every source's ring again, in full, from its store (the CPU truth). */
  restore(): void {
    const shared = this.sharedList;
    for (let i = 0; i < shared.length; i += 1) this.full(shared[i] as Shared);
  }

  uploadSubRange(batch: RetainedBatch, from: number, to: number): void {
    const slot = this.slots.get(batch.nodeId);
    if (slot === undefined || slot.shared.owner !== batch.nodeId) return;
    const { source, shared } = slot;
    const { data, head, stride } = source;
    if (shared.uploaded !== data) {
      this.full(shared);
      return;
    }
    this.gl.bindBuffer(GL.ARRAY_BUFFER, this.registry.get(shared.buffer));
    const capacity = data.length / stride;
    const at = (head + from) % capacity;
    const first = Math.min(to - from, capacity - at);
    this.put(at, first, stride, data);
    if (first < to - from) this.put(0, to - from - first, stride, data);
  }

  private full(shared: Shared): void {
    const { data } = shared.source;
    this.gl.bindBuffer(GL.ARRAY_BUFFER, this.registry.get(shared.buffer));
    this.gl.bufferData(GL.ARRAY_BUFFER, data, GL.DYNAMIC_DRAW);
    this.bytes += data.byteLength - (shared.uploaded?.byteLength ?? 0);
    this.uploaded += data.byteLength;
    shared.uploaded = data;
  }

  private put(at: number, n: number, stride: number, data: Float32Array): void {
    this.gl.bufferSubData(GL.ARRAY_BUFFER, at * stride * 4, data, at * stride, n * stride);
    this.uploaded += n * stride * 4;
  }
}
