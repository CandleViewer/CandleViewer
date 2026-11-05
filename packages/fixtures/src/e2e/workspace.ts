import type { generated } from "@candleviewer/protocol";

type Schemas = generated.rest.components["schemas"];

// E15-S03 (#476) BQ-03 (b) as ruled: the seeded workspace, a documented-shape fixture in `22`'s
// `Workspace` and `Layout` shapes (`satisfies` checks every field against the generated types).
// The seed holds a `chart` pane (BQ-03 (a)): the `oi` kind stays a placeholder until its pane's
// home is ruled. No preset or template id (`22` refuses them until their stores ship, BQ-07 (c)).

/** One pane: its kind, its symbol and its interval code (`22` `PaneIntervalCode`). */
export type SeedPane = readonly [kind: Schemas["PaneKind"], symbol: string, interval?: string];

const STAMP = "2026-11-05T10:00:00.000000Z";
const PRESET = ["1x1", "1x1", "2x1", "1+3", "2x2"] as const;

export const SEEDED_WORKSPACE = {
  id: "0190a000-0000-7000-8000-0000000000e2",
  user_id: "0190a000-0000-7000-8000-0000000000e1",
  name: "Scalping",
  is_default: true,
  icon_token: "workspace.default",
  sort_order: 0,
  layout_count: 1,
  created_at: STAMP,
  updated_at: STAMP,
} as const satisfies Schemas["Workspace"];

export const SEEDED_PANES: readonly SeedPane[] = [["chart", "BTCUSDT", "time:1"]];

/** The workspace's one layout over `panes` (at most four, slot order), as `22` answers it. */
export function seededLayout(panes: readonly SeedPane[] = SEEDED_PANES): Schemas["Layout"] {
  return {
    id: "0190a000-0000-7000-8000-0000000000e3",
    workspace_id: SEEDED_WORKSPACE.id,
    name: "Layout 1",
    grid_preset: PRESET[panes.length] ?? "2x2",
    grid_spec: null,
    crosshair_sync: true,
    level_sync: false,
    symbol_sync: false,
    hotkey_slot: null,
    is_default: true,
    panes: panes.map(([kind, symbol, interval], slot) => ({
      slot_index: slot,
      pane_kind: kind,
      symbol,
      interval_code: interval ?? null,
      chart_template_id: null,
      indicator_preset_ids: [],
      pane_config: { settings: {}, sync_group: null },
      scale_mode: "auto" as const,
    })),
    created_at: STAMP,
    updated_at: STAMP,
  } satisfies Schemas["Layout"];
}
