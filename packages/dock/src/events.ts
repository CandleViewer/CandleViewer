/**
 * Observability (E15-T02): the package logs nothing. The app wraps each operation, times it with
 * its own clock and forwards `layoutChanged` to analytics (`layout.panel_moved`, ...).
 */
import { leavesOf, type DockTree } from "./model.js";
import { matchPreset, type Preset } from "./presets.js";

export type LayoutOp =
  | "split"
  | "move"
  | "tabify"
  | "close"
  | "resize"
  | "equalise"
  | "activate_tab"
  | "maximise"
  | "restore"
  | "float"
  | "redock"
  | "apply_preset";

export interface LayoutChanged {
  readonly op: LayoutOp;
  readonly paneCount: number;
  readonly preset: Preset;
  readonly durationMs: number;
}

/** The event for `op` that produced `tree` in `durationMs`. */
export function layoutChanged(op: LayoutOp, tree: DockTree, durationMs: number): LayoutChanged {
  const paneCount = leavesOf(tree.root).length + tree.floating.length + tree.minimised.length;
  return { op, paneCount, preset: matchPreset(tree), durationMs };
}
