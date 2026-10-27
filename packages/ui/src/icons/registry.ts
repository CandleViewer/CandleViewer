// The icon registry (E05-T06, 16-design-system-brief.md §5), cut to the base glyphs the atoms need
// (E05 #271 slice 1): every icon's canonical name, what it means, its group and where its glyph
// comes from. Sorted by name, one entry per icon; each name has exactly one component in
// `generated/`, which only `Icon` (CMP-019) reaches. The rest of the set joins in later slices.

/** An icon's group on the Penpot icon page and in Storybook. */
export type IconCategory = "navigation" | "action" | "status" | "chart" | "trading" | "rule-graph";

/**
 * Where a glyph comes from: `lucide/<glyph>`, a vendored Lucide glyph (ISC);
 * `custom/<ticket>`, a glyph drawn for CandleViewer by that design ticket.
 */
export type IconSource = `lucide/${string}` | `custom/${string}`;

export interface IconEntry {
  readonly category: IconCategory;
  readonly source: IconSource;
  /** One sentence: what the icon means where it appears (the Penpot icon page's description). */
  readonly description: string;
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
  "chevron-right": {
    category: "navigation",
    source: "lucide/chevron-right",
    description: "Goes to the next page, period or step, or opens a submenu.",
  },
  close: {
    category: "action",
    source: "lucide/x",
    description: "Closes or dismisses a panel, dialog, toast or chip, or clears an input.",
  },
  danger: {
    category: "status",
    source: "lucide/octagon-alert",
    description: "Danger: a critical or blocking condition, such as a risk lockout.",
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
  minus: {
    category: "action",
    source: "lucide/minus",
    description: "Removes an item, or decreases a value by one step.",
  },
  plus: {
    category: "action",
    source: "lucide/plus",
    description: "Adds an item, or increases a value by one step.",
  },
  unlock: {
    category: "status",
    source: "lucide/lock-open",
    description: "Unlocked: editable, or a permission or a lockout that is lifted.",
  },
  warning: {
    category: "status",
    source: "lucide/triangle-alert",
    description: "Warning: degraded, or needs attention.",
  },
} as const satisfies Readonly<Record<string, IconEntry>>;

/** Every registered icon name. */
export type IconName = keyof typeof ICONS;
