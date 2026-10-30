// The scene-node contract (E11-S01, 26 §3.1): nodes read the frame context and append to batches;
// they never issue GL calls. DOM-free (C-2.16).
import { DeferClass, DIRTY_ALL, type DirtyFlags } from "./dirty.js";
import type { FrameCtx } from "./frame-context.js";
import type { BatchSink } from "./pool.js";

export type NodeKind = "chart" | "time-axis" | "pane" | "price-axis" | "layer" | "content";

export interface NodeOptions {
  readonly zIndex?: number;
  /** Trading-critical (order/position lines, the DOM-mirror sync): never deferred (06 §4.4). */
  readonly critical?: boolean;
  readonly deferClass?: DeferClass;
}

export abstract class SceneNode {
  abstract readonly kind: NodeKind;
  visible = true;
  /** Order within a layer, read once at attach; ties keep insertion order (BQ-20, BQ-25). */
  readonly zIndex: number;
  dirty: DirtyFlags = DIRTY_ALL;
  readonly critical: boolean;
  readonly deferClass: DeferClass;
  /** Graph bookkeeping: parent, children in draw order, end of the subtree in the flat walk. */
  parent: SceneNode | null = null;
  readonly children: SceneNode[] = [];
  end = 0;

  constructor(
    readonly id: string,
    opts: NodeOptions = {},
  ) {
    this.zIndex = opts.zIndex ?? 0;
    this.critical = opts.critical ?? false;
    this.deferClass = opts.deferClass ?? DeferClass.NONE;
    if (!Number.isFinite(this.zIndex)) throw new RangeError(`node ${id}: zIndex must be finite`);
    if (this.critical && this.deferClass !== DeferClass.NONE) {
      throw new RangeError(`node ${id}: a critical node is never deferred (06 §4.4)`);
    }
  }

  /** Per-frame work before `collect`; may mutate only `ctx.stats`. */
  update(ctx: FrameCtx): void {
    void ctx;
  }

  /** Appends this node's batches; `true` means collected, so the graph clears its flags. */
  abstract collect(sink: BatchSink): boolean;
}

/** A node of the fixed skeleton (chart, axes, pane, layer); draws nothing yet. */
export class StructuralNode extends SceneNode {
  constructor(
    id: string,
    readonly kind: Exclude<NodeKind, "content">,
  ) {
    super(id);
  }

  collect(sink: BatchSink): boolean {
    void sink;
    return true;
  }
}

/** A node a caller adds to a layer: a series, an overlay, a drawing, a label. */
export abstract class ContentNode extends SceneNode {
  readonly kind = "content" as const;
}
