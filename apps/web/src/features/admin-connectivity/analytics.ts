import type { StateId } from "./states";

/**
 * `connectivity.panel_viewed` (E08-D09 §20; E08-S12 BQ-6): ids and counts only. No transport exists yet in
 * `apps/web` (G8), so the default sink does nothing and no wire is invented.
 */
export interface PanelViewedEvent {
  readonly name: "connectivity.panel_viewed";
  /** The state the page opened in. */
  readonly state: StateId;
  /** Slices that are switched on, and how many of those read `ok`. */
  readonly slicesOn: number;
  readonly slicesServed: number;
}

export interface ConnectivityAnalytics {
  panelViewed(event: PanelViewedEvent): void;
}

export const noopAnalytics: ConnectivityAnalytics = { panelViewed: () => undefined };

export function emitPanelViewed(
  port: ConnectivityAnalytics,
  state: StateId,
  slicesOn: number,
  slicesServed: number,
): void {
  port.panelViewed({ name: "connectivity.panel_viewed", state, slicesOn, slicesServed });
}
