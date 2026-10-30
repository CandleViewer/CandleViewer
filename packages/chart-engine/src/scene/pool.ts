// Object pools for per-frame structures (E11-S01, 26 §3.2 rule 4). `created` grows only when a
// pool runs dry: that is the allocation counter the zero-allocation tests read (BQ-S10).

export class ObjectPool<T> {
  private readonly items: T[] = [];
  private used = 0;
  created = 0;

  constructor(
    private readonly factory: () => T,
    private readonly reset: (item: T) => void,
    prewarm = 0,
  ) {
    while (this.created < prewarm) this.grow();
  }

  get inUse(): number {
    return this.used;
  }

  acquire(): T {
    if (this.used === this.items.length) this.grow();
    this.used += 1;
    return this.items[this.used - 1] as T; // grow() filled this slot
  }

  /** Takes every object back; they are handed out again in the same order. */
  releaseAll(): void {
    for (let i = 0; i < this.used; i += 1) this.reset(this.items[i] as T);
    this.used = 0;
  }

  private grow(): void {
    this.items.push(this.factory());
    this.created += 1;
  }
}

/** A draw-batch entry; the batch builder sorts them by program, then texture (26 §3.1). */
export interface BatchEntry {
  nodeId: string;
  program: number;
  texture: number;
  first: number;
  count: number;
}

/** A pooled hit-test slot (26 §3.9); not §8's public `PickResult` (`pickAt`'s, BQ-25). */
export interface PickSlot {
  nodeId: string;
  index: number;
  distancePx: number;
}

/** What `collect` appends to; nodes never issue GL calls. */
export interface BatchSink {
  /** A cleared, pooled entry appended to this frame's list, for the caller to fill in. */
  append(): BatchEntry;
}

const clearEntry = (e: BatchEntry): void => {
  e.nodeId = "";
  e.program = e.texture = e.first = e.count = 0;
};

const makeEntry = (): BatchEntry => ({ nodeId: "", program: 0, texture: 0, first: 0, count: 0 });

/** A `BatchSink` over a pool: this frame's entries, in append order. */
export class PooledBatchSink implements BatchSink {
  constructor(
    prewarm = 64,
    readonly pool = new ObjectPool(makeEntry, clearEntry, prewarm),
  ) {}

  append(): BatchEntry {
    return this.pool.acquire();
  }

  reset(): void {
    this.pool.releaseAll();
  }
}

const clearPick = (p: PickSlot): void => {
  p.nodeId = "";
  p.index = -1;
  p.distancePx = 0;
};

export const createPickPool = (prewarm = 8): ObjectPool<PickSlot> =>
  new ObjectPool<PickSlot>(() => ({ nodeId: "", index: -1, distancePx: 0 }), clearPick, prewarm);
