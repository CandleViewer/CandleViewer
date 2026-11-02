/**
 * `DockError`: the one refusal the package throws. The first eight codes are `22`'s
 * layout rule codes, so a tree the client refuses is the tree the API would refuse
 * with the same words; the rest are client-only. Codes are stable: never renamed or reused.
 */
export const DOCK_ERROR_CODES = Object.freeze([
  "tree_too_deep",
  "tree_too_large",
  "unknown_slot",
  "duplicate_leaf",
  "sizes_mismatch",
  "sizes_sum",
  "active_out_of_range",
  /** `LayoutPaneInput.slot_index` twice (`22` rule `duplicate_slot`). */
  "duplicate_slot",
  /** A node that is not a `row`, `column`, `tabset` or `leaf` of the stored shape. */
  "invalid_node",
  /** A pane kind the caller's registry does not know (E15-T02 security notes). */
  "unknown_kind",
  /** An operation named a pane or node the tree does not hold. */
  "unknown_target",
  /** An operation that cannot apply (a tab into a split, a preset with the wrong pane count). */
  "invalid_operation",
  /** A stored `grid_preset` that is neither `custom` nor a named preset (refused, never guessed). */
  "unknown_preset",
  /**
   * A layout with panes but none docked: a named preset docks its first slots and `custom` needs
   * a spec, so this package has no stored form for it; it is refused on write, never stored wrongly.
   */
  "empty_dock",
] as const);

export type DockErrorCode = (typeof DOCK_ERROR_CODES)[number];

export class DockError extends Error {
  readonly code: DockErrorCode;
  /** Field path under `grid_spec`, as the API reports it (`root.children.1.sizes`), if any. */
  readonly path: string | null;

  constructor(code: DockErrorCode, message: string, path: string | null = null) {
    super(message);
    this.name = "DockError";
    this.code = code;
    this.path = path;
  }
}

export function isDockError(value: unknown): value is DockError {
  return value instanceof DockError;
}
