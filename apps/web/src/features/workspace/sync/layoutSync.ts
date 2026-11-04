/**
 * The bus against the stored layout (BQ-07): only fields already in `22`. The three layout flags
 * apply to every group (one set per layout, E15-D06 §5.2): `symbol_sync` is the symbol axis,
 * `crosshair_sync` the crosshair, `level_sync` the drawings axis (price levels only). Interval and
 * time range have no stored field (D06 G-2): they live in memory, off unless the caller holds them
 * on, until E15-S04's contract PR. Each pane's group is `pane_config.sync_group`.
 */
import type { PaneFields } from "@candleviewer/dock";
import type { generated } from "@candleviewer/protocol";
import type { SyncBus } from "./syncBus";
import { SYNC_GROUPS, type SyncAxes, type SyncGroupId } from "./types";

type Schemas = generated.rest.components["schemas"];
export type LayoutSyncFlags = Pick<
  Schemas["Layout"],
  "crosshair_sync" | "symbol_sync" | "level_sync"
>;
/** The two axes with no stored field (G-2), held by the caller between saves. */
export type UnstoredAxes = Pick<SyncAxes, "interval" | "timeRange">;

/** D06 §5.2: interval and time range off while they cannot be stored. */
export const UNSTORED_OFF: UnstoredAxes = { interval: false, timeRange: false };

export function axesFromLayout(
  flags: LayoutSyncFlags,
  unstored: UnstoredAxes = UNSTORED_OFF,
): SyncAxes {
  return {
    // Stored values are untrusted: only `true` reads as on, so a non-boolean flag reads as off.
    symbol: flags.symbol_sync === true,
    interval: unstored.interval,
    crosshair: flags.crosshair_sync === true,
    timeRange: unstored.timeRange,
    drawings: flags.level_sync === true,
  };
}

/** A pure single-set mapping: how the per-group axes collapse to one stored set is G-1's open question. */
export function axesToLayout(axes: SyncAxes): LayoutSyncFlags {
  return { symbol_sync: axes.symbol, crosshair_sync: axes.crosshair, level_sync: axes.drawings };
}

/** Gives every group the layout's flags. */
export function applyLayoutAxes(
  bus: SyncBus,
  flags: LayoutSyncFlags,
  unstored?: UnstoredAxes,
): void {
  const axes = axesFromLayout(flags, unstored);
  for (const group of SYNC_GROUPS) bus.setAxes(group, axes);
}

/** A pane's stored group; anything but `A`, `B` or `C` reads as no group (stored data is untrusted). */
export function groupOfPane(fields: PaneFields | undefined): SyncGroupId | null {
  const group: unknown = fields?.pane_config?.sync_group;
  return (SYNC_GROUPS as readonly unknown[]).includes(group) ? (group as SyncGroupId) : null;
}

/** `fields` with its group set (or cleared), every other `pane_config` key kept. `sync_group` null
 * and omitted both mean "not synced" (`22`) and stay as they were: clearing a pane that has no
 * `sync_group` key changes nothing, so a save does not add a key that was not there. */
export function withGroup(fields: PaneFields, group: SyncGroupId | null): PaneFields {
  if (group === null && !Object.hasOwn(fields.pane_config ?? {}, "sync_group")) return fields;
  return { ...fields, pane_config: { ...fields.pane_config, sync_group: group } };
}

/** Every pane's group from `fromLayout`'s pane map; panes with none are absent. */
export function groupsFromPanes(panes: ReadonlyMap<string, PaneFields>): Map<string, SyncGroupId> {
  const groups = new Map<string, SyncGroupId>();
  for (const [paneId, fields] of panes) {
    const group = groupOfPane(fields);
    if (group !== null) groups.set(paneId, group);
  }
  return groups;
}

/** The pane map for `toLayoutInput` with each pane's group written from `groups`. */
export function panesWithGroups(
  panes: ReadonlyMap<string, PaneFields>,
  groups: ReadonlyMap<string, SyncGroupId>,
): Map<string, PaneFields> {
  const out = new Map<string, PaneFields>();
  for (const [paneId, fields] of panes)
    out.set(paneId, withGroup(fields, groups.get(paneId) ?? null));
  return out;
}
