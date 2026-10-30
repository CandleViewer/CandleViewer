// Vertex buffers (E11-S02, 26 §3.3/§3.4): the batch builder's `UploadSink`. Each drawing node's
// GPU buffer mirrors its store's ring slot for slot, so a logical range [from, to) lands at the
// physical slots (head + i) mod capacity: one `bufferSubData`, two when the range wraps. A new
// backing array (the store reallocated, or the first upload) is uploaded in full (BQ-46).
import type { RetainedBatch, UploadSink } from "../scene/batch-builder.js";
import { GL, type GL2Like, type GLObject } from "./gl-types.js";
import type { GlRegistry, Handle } from "./registry.js";

/** A store's ring as the GPU sees it; read on every upload, so getters over a store fit. */
export interface VertexSource {
  /** The ring's backing floats; a new identity means it was reallocated. */
  readonly data: Float32Array;
  /** The physical slot of logical index 0. */
  readonly head: number;
  /** Floats per slot; the capacity is `data.length / stride`. */
  readonly stride: number;
}

interface Slot {
  readonly source: VertexSource;
  readonly buffer: Handle<"buffer">;
  readonly vao: Handle<"vertexArray">;
  uploaded: Float32Array | null;
}

export class GlBuffers implements UploadSink {
  /** GPU bytes held, for `gpuMemoryMbEstimate`. */
  bytes = 0;
  /** Bytes uploaded since the last `takeUploaded()`. */
  uploaded = 0;
  private readonly slots = new Map<string, Slot>();

  constructor(
    private readonly gl: GL2Like,
    private readonly registry: GlRegistry,
  ) {}

  /** Gives a drawing node its buffer and VAO; the store-to-node mapping is the runtime's. */
  attach(nodeId: string, source: VertexSource): void {
    if (this.slots.has(nodeId)) return;
    const buffer = this.registry.create("buffer");
    const vao = this.registry.create("vertexArray");
    this.slots.set(nodeId, { source, buffer, vao, uploaded: null });
  }

  /** The node's VAO; null without one, and submission skips the batch. */
  vao(nodeId: string): GLObject | null {
    const slot = this.slots.get(nodeId);
    return slot === undefined ? null : this.registry.get(slot.vao);
  }

  takeUploaded(): number {
    const n = this.uploaded;
    this.uploaded = 0;
    return n;
  }

  /** On a context loss: the GPU copies are gone, so each node's next upload is a full one. */
  invalidate(): void {
    for (const slot of this.slots.values()) slot.uploaded = null;
    this.bytes = 0;
  }

  /** After a restore: every node's ring again, in full, from its store (the CPU truth). */
  restore(): void {
    for (const slot of this.slots.values()) this.full(slot);
  }

  uploadSubRange(batch: RetainedBatch, from: number, to: number): void {
    const slot = this.slots.get(batch.nodeId);
    if (slot === undefined) return;
    const { data, head, stride } = slot.source;
    if (slot.uploaded !== data) {
      this.full(slot);
      return;
    }
    this.gl.bindBuffer(GL.ARRAY_BUFFER, this.registry.get(slot.buffer));
    const capacity = data.length / stride;
    const at = (head + from) % capacity;
    const first = Math.min(to - from, capacity - at);
    this.put(at, first, stride, data);
    if (first < to - from) this.put(0, to - from - first, stride, data);
  }

  private full(slot: Slot): void {
    const { data } = slot.source;
    this.gl.bindBuffer(GL.ARRAY_BUFFER, this.registry.get(slot.buffer));
    this.gl.bufferData(GL.ARRAY_BUFFER, data, GL.DYNAMIC_DRAW);
    this.bytes += data.byteLength - (slot.uploaded?.byteLength ?? 0);
    this.uploaded += data.byteLength;
    slot.uploaded = data;
  }

  private put(at: number, n: number, stride: number, data: Float32Array): void {
    this.gl.bufferSubData(GL.ARRAY_BUFFER, at * stride * 4, data, at * stride, n * stride);
    this.uploaded += n * stride * 4;
  }
}
