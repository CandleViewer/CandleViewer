/**
 * Sync observability names (E15-T03 Observability, A-7): defined here, emitted by E15-S04's UI, never
 * by the bus. And CMP-196's announcement copy (`15` CMP-196 A11y), said by the bus once per change.
 */
import { SYNC_AXES, type SyncAxes, type SyncAxis, type SyncGroupId } from "./types";

export const SYNC_EVENTS = {
  groupJoined: "sync.panel_joined_group",
  groupLeft: "sync.panel_left_group",
  axisToggled: "sync.axis_toggled",
} as const;

/** The axis words in SCR-023's switch order; the drawings axis is "levels" (CMP-196's word). */
const AXIS_WORDS: Readonly<Record<SyncAxis, string>> = {
  symbol: "symbol",
  interval: "interval",
  crosshair: "crosshair",
  timeRange: "time range",
  drawings: "levels",
};

/** "Panes linked in sync group A: crosshair, levels."; null when no axis is on. */
export function linkedAnnouncement(group: SyncGroupId, axes: SyncAxes): string | null {
  const on = SYNC_AXES.filter((axis) => axes[axis]).map((axis) => AXIS_WORDS[axis]);
  return on.length === 0 ? null : `Panes linked in sync group ${group}: ${on.join(", ")}.`;
}

/** Said when a linked group stops being linked (PROPOSED copy, README). */
export const unlinkedAnnouncement = (group: SyncGroupId): string =>
  `Panes in sync group ${group} are no longer linked.`;
