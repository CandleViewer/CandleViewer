// The icon registry (E05-T06, 16-design-system-brief.md §5): every icon's canonical name, what it
// means, its group and where its glyph comes from. Sorted by name, one entry per icon, so the code
// and the Penpot icon page compare by diff. Each name has exactly one component, which
// scripts/build-icons.mjs generates into `generated/` from `source/<origin>/<name>.svg` and only
// `Icon` (CMP-019) reaches (packages/ui/README.md, "Icons"). The base set is Lucide's; the 13
// trading glyphs of brief §5 are CandleViewer's own, drawn from E05-D02 §7.12 in `source/custom/`.

/** An icon's group on the Penpot icon page and in Storybook. */
export type IconCategory = "navigation" | "action" | "status" | "chart" | "trading" | "rule-graph";

/**
 * Where a glyph comes from: `lucide/<glyph>`, a vendored Lucide glyph (ISC, its notice in
 * `source/lucide/LICENSE`); `custom/<ticket>`, a glyph drawn for CandleViewer by that ticket.
 */
export type IconSource = `lucide/${string}` | `custom/${string}`;

export interface IconEntry {
  readonly category: IconCategory;
  readonly source: IconSource;
  /** One sentence: what the icon means where it appears (the Penpot icon page's description). */
  readonly description: string;
  /**
   * Marks E05-D02 §7.12's "16 px minimum": the glyph's detail closes up at 12 px, so it is never
   * drawn at `size.icon.sm` as shipped (12 px; §6 J24). The types hold it, not the runtime: `Icon`
   * and CMP-002 `IconButton` refuse `size="sm"` for such a name (`MinimumSixteenName`). Omitted,
   * the glyph holds at every optical size. Keyed to the `sm` token, as a reduced form is: if slice
   * 1 A10 (16 / 20 / 24 px) is approved, re-key both to the 12 px size.
   */
  readonly minimumPx?: 16;
}

export const ICONS = {
  "arrow-down": {
    category: "navigation",
    source: "lucide/arrow-down",
    description: "Sorts a column descending, or moves an item down.",
  },
  "arrow-up": {
    category: "navigation",
    source: "lucide/arrow-up",
    description: "Sorts a column ascending, or moves an item up.",
  },
  "arrow-up-down": {
    category: "navigation",
    source: "lucide/arrow-up-down",
    description: "Marks a sortable column that is not sorted yet.",
  },
  calendar: {
    category: "action",
    source: "lucide/calendar",
    description: "Opens a date or date-range picker.",
  },
  cancelled: {
    category: "status",
    source: "lucide/ban",
    description: "Cancelled or not permitted, such as a cancelled order.",
  },
  "chase-limit": {
    category: "trading",
    source: "custom/E05-T06",
    description: "Limit order that follows the price.",
    minimumPx: 16,
  },
  check: {
    category: "action",
    source: "lucide/check",
    description: "Confirms, or marks an item as selected or done.",
  },
  "chevron-down": {
    category: "navigation",
    source: "lucide/chevron-down",
    description: "Expands a disclosure, or opens a select or a menu.",
  },
  "chevron-left": {
    category: "navigation",
    source: "lucide/chevron-left",
    description: "Goes to the previous page, period or step.",
  },
  "chevron-right": {
    category: "navigation",
    source: "lucide/chevron-right",
    description: "Goes to the next page, period or step, or opens a submenu.",
  },
  "chevron-up": {
    category: "navigation",
    source: "lucide/chevron-up",
    description: "Collapses an expanded disclosure.",
  },
  "chevrons-up-down": {
    category: "navigation",
    source: "lucide/chevrons-up-down",
    description: "Opens the options of a select or a combobox.",
  },
  close: {
    category: "action",
    source: "lucide/x",
    description: "Closes or dismisses a panel, dialog, toast or chip, or clears an input.",
  },
  copy: {
    category: "action",
    source: "lucide/copy",
    description: "Copies a value, such as an order id, to the clipboard.",
  },
  crosshair: {
    category: "chart",
    source: "lucide/crosshair",
    description: "The chart crosshair cursor, where drawing tools place their points.",
  },
  danger: {
    category: "status",
    source: "lucide/octagon-alert",
    description: "Danger: a critical or blocking condition, such as a risk lockout.",
  },
  delete: {
    category: "action",
    source: "lucide/trash-2",
    description: "Deletes an item, after a confirmation.",
  },
  disconnected: {
    category: "status",
    source: "lucide/unplug",
    description: "Disconnected from the exchange or the server.",
  },
  download: {
    category: "action",
    source: "lucide/download",
    description: "Downloads or exports a file.",
  },
  "drag-handle": {
    category: "action",
    source: "lucide/grip-vertical",
    description: "A drag handle that reorders a row or moves a panel.",
  },
  edit: {
    category: "action",
    source: "lucide/pencil",
    description: "Edits or renames an item.",
  },
  error: {
    category: "status",
    source: "lucide/circle-x",
    description: "Error: failed, rejected or offline.",
  },
  estimated: {
    category: "status",
    source: "custom/E05-T06",
    description: "The value is inferred, not reported by the exchange.",
  },
  "external-link": {
    category: "navigation",
    source: "lucide/external-link",
    description: "Opens a link outside the app, in the system browser.",
  },
  filter: {
    category: "action",
    source: "lucide/funnel",
    description: "Filters a list or a table.",
  },
  "flatten-all": {
    category: "trading",
    source: "custom/E05-T06",
    description: "Close every position at market.",
    minimumPx: 16,
  },
  "heatmap-convention-swap": {
    category: "chart",
    source: "custom/E05-T06",
    description: "Swap which side the heatmap colours show as bid and ask.",
    minimumPx: 16,
  },
  help: {
    category: "status",
    source: "lucide/circle-help",
    description: "Help: explains a control or opens its documentation.",
  },
  hide: {
    category: "action",
    source: "lucide/eye-off",
    description: "Hides a revealed value, such as a password or a secret.",
  },
  "iceberg-order": {
    category: "trading",
    source: "custom/E05-T06",
    description: "Order shown in visible slices with a hidden remainder.",
    minimumPx: 16,
  },
  info: {
    category: "status",
    source: "lucide/info",
    description: "Information: a neutral message or an explanation.",
  },
  lock: {
    category: "status",
    source: "lucide/lock",
    description: "Locked: read-only, or blocked by a permission or a lockout.",
  },
  maximize: {
    category: "action",
    source: "lucide/maximize-2",
    description: "Maximises a panel within the workspace.",
  },
  minimize: {
    category: "action",
    source: "lucide/minimize-2",
    description: "Restores a maximised panel to its place in the layout.",
  },
  minus: {
    category: "action",
    source: "lucide/minus",
    description: "Removes an item, or decreases a value by one step.",
  },
  "more-horizontal": {
    category: "navigation",
    source: "lucide/ellipsis",
    description: "Opens an overflow menu of further actions, as in a panel header.",
  },
  "more-vertical": {
    category: "navigation",
    source: "lucide/ellipsis-vertical",
    description: "Opens the action menu of a table or list row.",
  },
  "native-sl-shield": {
    category: "trading",
    source: "custom/E05-T06",
    description: "A native exchange stop-loss protects the position.",
    minimumPx: 16,
  },
  "node-action": {
    category: "rule-graph",
    source: "custom/E05-T06",
    description: "Rule node: what the rule does.",
  },
  "node-comment": {
    category: "rule-graph",
    source: "custom/E05-T06",
    description: "Rule node: a note outside the rule.",
  },
  "node-condition": {
    category: "rule-graph",
    source: "custom/E05-T06",
    description: "Rule node: a comparison that is true or false.",
  },
  "node-logic-gate": {
    category: "rule-graph",
    source: "custom/E05-T06",
    description: "Rule node: combines inputs (all, any, none, at least n).",
  },
  "node-trigger": {
    category: "rule-graph",
    source: "custom/E05-T06",
    description: "Rule node: what starts an evaluation.",
  },
  notifications: {
    category: "status",
    source: "lucide/bell",
    description: "Notifications and alerts, as in the notification centre.",
  },
  "one-click-arm": {
    category: "trading",
    source: "custom/E05-T06",
    description: "One-click trading is armed.",
  },
  pending: {
    category: "status",
    source: "lucide/clock",
    description: "Pending: waiting on the exchange, such as a working order.",
  },
  pin: {
    category: "action",
    source: "lucide/pin",
    description: "Pins an item in place, such as a window kept on top.",
  },
  plus: {
    category: "action",
    source: "lucide/plus",
    description: "Adds an item, or increases a value by one step.",
  },
  redo: {
    category: "action",
    source: "lucide/redo-2",
    description: "Redoes the last undone change.",
  },
  refresh: {
    category: "action",
    source: "lucide/refresh-cw",
    description: "Retries a failed action or reloads data.",
  },
  search: {
    category: "action",
    source: "lucide/search",
    description: "Searches, or filters a list by text.",
  },
  settings: {
    category: "action",
    source: "lucide/settings",
    description: "Opens the settings of a panel, a chart or the app.",
  },
  show: {
    category: "action",
    source: "lucide/eye",
    description: "Reveals a hidden value, such as a password or a secret.",
  },
  success: {
    category: "status",
    source: "lucide/circle-check",
    description: "Success: done, connected or passing.",
  },
  twap: {
    category: "trading",
    source: "custom/E05-T06",
    description: "Order split evenly over a time window.",
    minimumPx: 16,
  },
  undo: {
    category: "action",
    source: "lucide/undo-2",
    description: "Undoes the last change.",
  },
  unlock: {
    category: "status",
    source: "lucide/lock-open",
    description: "Unlocked: editable, or a permission or a lockout that is lifted.",
  },
  upload: {
    category: "action",
    source: "lucide/upload",
    description: "Uploads or imports a file.",
  },
  warning: {
    category: "status",
    source: "lucide/triangle-alert",
    description: "Warning: degraded, or needs attention.",
  },
  "zoom-in": {
    category: "chart",
    source: "lucide/zoom-in",
    description: "Zooms a chart or a scale in.",
  },
  "zoom-out": {
    category: "chart",
    source: "lucide/zoom-out",
    description: "Zooms a chart or a scale out.",
  },
} as const satisfies Readonly<Record<string, IconEntry>>;

/** Every registered icon name. */
export type IconName = keyof typeof ICONS;

/** The names whose entry carries `minimumPx: 16`, E05-D02 §7.12's "16 px minimum" glyphs. */
export type MinimumSixteenName = {
  [N in IconName]: (typeof ICONS)[N] extends { readonly minimumPx: 16 } ? N : never;
}[IconName];
