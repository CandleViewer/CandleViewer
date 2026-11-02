// Public entrypoint for @candleviewer/dock (E15-T02): the dock layout tree, its operations and its
// serialisation against `22`'s LayoutGridSpec. Framework-free: no React, DOM, network or engine.
export { DOCK_ERROR_CODES, DockError, isDockError } from "./errors.js";
export type { DockErrorCode } from "./errors.js";
export { counterMinter } from "./ids.js";
export type { IdMinter } from "./ids.js";
export {
  EMPTY_TREE,
  MAX_DEPTH,
  MAX_LEAVES,
  MAX_NODES,
  SIZE_EPSILON,
  allLeaves,
  countNodes,
  depthOf,
  findNode,
  leavesOf,
} from "./model.js";
export type {
  Direction,
  DockLeaf,
  DockNode,
  DockSplit,
  DockTabset,
  DockTree,
  NodeId,
  PaneId,
  Rect,
  Size,
  Zone,
} from "./model.js";
export { MIN_FRACTION, minExtent, normalise } from "./normalise.js";
export {
  activateTab,
  applyPreset,
  close,
  equalise,
  float,
  maximise,
  move,
  redock,
  resize,
  restore,
  separatorId,
  split,
  tabify,
} from "./ops.js";
export type { OpContext } from "./ops.js";
export { NAMED_PRESETS, PRESET_CELLS, matchPreset, presetToTree, sameShape } from "./presets.js";
export type { NamedPreset, Preset } from "./presets.js";
export { fromLayout, toLayoutInput, validateGridSpec } from "./serialise.js";
export type {
  GridIssue,
  LayoutArrangement,
  PaneFields,
  ReadContext,
  StoredArrangement,
} from "./serialise.js";
export {
  ZONE_GEOMETRY,
  compactPanes,
  dropZones,
  layoutRects,
  neighbour,
  panelBoxes,
  relocate,
  resolveDirectionalMove,
  resolveDrop,
} from "./drop.js";
export type { ChooserStep, DropTarget, DropZone } from "./drop.js";
export { layoutChanged } from "./events.js";
export type { LayoutChanged, LayoutOp } from "./events.js";
