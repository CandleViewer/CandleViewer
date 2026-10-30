// Scene graph (E11-S01). Internal: src/index.ts re-exports none of it, as the §8 surface test
// requires (BQ-6); the test-only NullSeries is not listed.
export { DeferClass, Dirty, DIRTY_ALL, LAYER_ORDER } from "./dirty.js";
export type { DirtyFlags, LayerName } from "./dirty.js";
export { FrameContext } from "./frame-context.js";
export type { FrameCtx } from "./frame-context.js";
export { PaneNode, SceneGraph } from "./graph.js";
export { ContentNode, SceneNode, StructuralNode } from "./node.js";
export type { NodeKind, NodeOptions } from "./node.js";
export { createPickPool, ObjectPool, PooledBatchSink } from "./pool.js";
export type { BatchEntry, BatchSink, PickSlot } from "./pool.js";
