// The batch builder (E11-S01 PR3, 26 §3.1/§3.2): one batch per drawing node, retained across frames
// and patched in place from each frame's collect entries and the stores' mutation ranges, so a pan
// (TRANSFORM only) uploads nothing. DOM- and GL-free: uploads go to an injected sink (E11-S02).
import type { MutationRange } from "../model/counters.js";
import type { SceneGraph } from "./graph.js";
import type { SceneNode } from "./node.js";
import { type BatchEntry, makeEntry, ObjectPool, type PooledBatchSink } from "./pool.js";

/** The node's last entry, its walk position (layer, then node) and a pending upload [lo, hi). */
export interface RetainedBatch extends BatchEntry {
  layer: number;
  seq: number;
  lo: number;
  hi: number;
}

/**
 * Where sub-range uploads go: E11-S02's `bufferSubData`; a counting fake until then (BQ-S12).
 * [from, to) are logical store indices after the rebase; a reallocation forces a full upload (BQ-46).
 */
export interface UploadSink {
  uploadSubRange(batch: RetainedBatch, from: number, to: number): void;
}

const makeBatch = (): RetainedBatch => ({ ...makeEntry(), layer: 0, seq: 0, lo: 0, hi: 0 });

/** Draw order: layer, then program, then texture, then walk (zIndex) order (BQ-42). */
const before = (a: RetainedBatch, b: RetainedBatch): boolean => {
  if (a.layer !== b.layer) return a.layer < b.layer;
  if (a.program !== b.program) return a.program < b.program;
  return a.texture !== b.texture ? a.texture < b.texture : a.seq < b.seq;
};

export class BatchBuilder {
  /** Never released: a batch lives as long as its node, so `created` counts batches. */
  readonly pool = new ObjectPool(makeBatch, () => undefined, 16);
  /** This frame's draw list: `drawList[0, drawCount)`, the visible batches in draw order. */
  readonly drawList: RetainedBatch[] = [];
  drawCount = 0;
  uploads = 0; // sub-range uploads issued: the pan scenario's bufferSubData count
  private readonly byNode = new Map<string, RetainedBatch>();
  private readonly sorted: RetainedBatch[] = [];
  private resort = false;
  private walkSeen = -1; // the graph rebuild the walk positions were read at; -1 forces a read

  constructor(
    private readonly graph: SceneGraph,
    private readonly uploader: UploadSink,
  ) {}

  /** Records a store mutation for the node's batch, uploaded once at the next `build` (BQ-46). */
  patch(nodeId: string, r: MutationRange): void {
    const b = this.byNode.get(nodeId);
    if (b === undefined) return; // a new batch uploads in full on its first build
    if (r.op === "replace") b.lo = b.hi = 0; // a snapshot: only its own range
    if (b.lo < b.hi && r.indexShift > 0) {
      const shift = r.op === "prepend" ? r.indexShift : -r.indexShift; // 26 §3.3's rebase
      b.lo = Math.max(0, b.lo + shift);
      b.hi = Math.max(0, b.hi + shift);
    }
    b.lo = b.lo < b.hi ? Math.min(b.lo, r.from) : r.from;
    b.hi = Math.max(b.hi, r.to);
  }

  /** Merges this frame's collect entries, flushes pending uploads, re-forms the draw list. */
  build(sink: PooledBatchSink): void {
    for (let i = 0; i < sink.length; i += 1) this.merge(sink.at(i));
    const sorted = this.sorted;
    if (this.graph.rebuilds !== this.walkSeen) this.place();
    for (let i = 1; this.resort && i < sorted.length; i += 1) {
      const b = sorted[i] as RetainedBatch; // insertion sort: in place, near-sorted input
      let j = i;
      for (; j > 0 && before(b, sorted[j - 1] as RetainedBatch); j -= 1) {
        sorted[j] = sorted[j - 1] as RetainedBatch;
      }
      sorted[j] = b;
    }
    this.resort = false;
    this.drawCount = 0;
    for (let i = 0; i < sorted.length; i += 1) {
      const b = sorted[i] as RetainedBatch;
      if (b.lo < b.hi) {
        this.uploader.uploadSubRange(b, b.lo, b.hi);
        this.uploads += 1;
        b.lo = b.hi = 0;
      }
      if (b.count > 0 && this.shown(b.nodeId)) this.drawList[this.drawCount++] = b;
    }
  }

  private merge(e: BatchEntry): void {
    let b = this.byNode.get(e.nodeId);
    if (b === undefined) {
      b = this.pool.acquire();
      [b.nodeId, b.lo, b.hi] = [e.nodeId, e.first, e.first + e.count]; // first build: all of it
      this.byNode.set(e.nodeId, b);
      this.sorted.push(b);
      this.drawList.push(b);
      this.walkSeen = -1;
    } else if (b.program !== e.program || b.texture !== e.texture) this.resort = true;
    b.program = e.program; // per frame: plain stores, no destructuring temporaries
    b.texture = e.texture;
    b.first = e.first;
    b.count = e.count;
  }

  private place(): void {
    this.walkSeen = this.graph.rebuilds;
    for (let i = 0; i < this.sorted.length; i += 1) {
      const b = this.sorted[i] as RetainedBatch;
      const node = this.graph.get(b.nodeId);
      [b.seq, b.layer] = [node?.start ?? -1, node?.parent?.start ?? -1];
    }
    this.resort = true;
  }

  /** The node and every ancestor visible: a hidden node or pane keeps its batch, undrawn. */
  private shown(id: string): boolean {
    let node: SceneNode | null = this.graph.get(id) ?? null;
    for (; node !== null; node = node.parent) if (!node.visible) return false;
    return this.graph.get(id) !== undefined;
  }
}
