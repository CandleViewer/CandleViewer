/**
 * CMP-196 MultiChartLinker: the non-visual hook binding a DockGrid pane to its sync group. It joins
 * on mount, leaves on unmount, and leaves then joins on a group or member change; it holds no state,
 * so it causes no render of its own. Modes are the group's (the stored layout flags, given by
 * `setAxes`), never a per-pane prop, and the linked panes are the bus's roster.
 */
import { useEffect } from "react";
import { useSyncBus } from "./SyncBusProvider";
import type { SyncGroupId, SyncMember } from "./types";

export interface MultiChartLinkerProps {
  /** `pane_config.sync_group`; null leaves any group. */
  readonly groupId: SyncGroupId | null;
  /** The pane's adapter; null until the pane's chart exists. Keep it stable across renders. */
  readonly member: SyncMember | null;
}

export function useMultiChartLinker({ groupId, member }: MultiChartLinkerProps): void {
  const bus = useSyncBus();
  useEffect(() => {
    if (bus === null || member === null || groupId === null) return undefined;
    return bus.join(member, groupId);
  }, [bus, member, groupId]);
}
