/**
 * The per-screen trap-detection limit N (E47-Q03 BQ-07 (a), PROPOSED pending the Q01 dry run).
 *
 * Derivation: a healthy screen returns to its first stop after exactly as many Tabs as it has tab stops, and
 * the committed accessibility-tree baseline (tools/a11y/tree-snapshots/<id>.txt) lists every focusable node.
 * N = ceil(1.5 x focusable nodes) + 10:
 *   - the 1.5 factor covers stops the tree does not show one-to-one (composite widgets, portalled popovers,
 *     skip links that only render on focus);
 *   - the +10 covers shell chrome that a screen's baseline may not yet include;
 *   - there is no ceiling: a fixed one would make a legitimately dense screen (SCR-060 order grid) fail as a trap.
 * The G004 collector's fixed MAX_TABS = 80 stays as the legacy bound there; this budget replaces it only
 * for the a11y-nav project, per screen, so a trap on a small screen is found in a handful of presses.
 */
const FOCUSABLE =
  /^\s*-\s+(button|link|textbox|searchbox|checkbox|radio|switch|combobox|slider|spinbutton|tab|menuitem|menuitemcheckbox|menuitemradio|option|treeitem)\b/;

export const TRAP_FACTOR = 1.5;
export const TRAP_SLACK = 10;

/** Count the focusable nodes in an ARIA snapshot (disabled controls are not tab stops). */
export function focusableCount(tree: string): number {
  return tree.split("\n").filter((l) => FOCUSABLE.test(l) && !/\[disabled\]/.test(l)).length;
}

export function trapBudget(tree: string): number {
  return Math.ceil(focusableCount(tree) * TRAP_FACTOR) + TRAP_SLACK;
}
