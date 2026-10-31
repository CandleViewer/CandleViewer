/**
 * SCR-100's ports to what is not built yet, each with a default that does nothing it cannot do (pre-rulings 1 and 2):
 *
 * - The sync group (E15-S04): activation sets the symbol of the pane's sync group (E08-D07 D11); until the mechanism
 *   exists the default sets nothing and names no group.
 * - The pane host (E15): "Open in new chart" and "Send to panel ▸" need panes to open or send to; without a host the
 *   row menu offers neither.
 * - The pane settings (`watchlist_id`, `watchlist_sort`, E08-D07 D35; owner E15, C-6): a local store behind the port
 *   until the pane-settings store exists, held for the session.
 */

export interface SyncGroupPort {
  /** The group's letter ("A"), for the active row's "Shows in group A"; `null` while the pane has none. */
  readonly name: string | null;
  setSymbol(symbol: string): void;
}

export const NO_SYNC_GROUP: SyncGroupPort = { name: null, setSymbol: () => undefined };

export interface PanelTarget {
  readonly id: string;
  readonly name: string;
}

export interface PanelHostPort {
  readonly openInNewChart?: (symbol: string) => void;
  readonly panels?: () => readonly PanelTarget[];
  readonly sendToPanel?: (symbol: string, panelId: string) => void;
}

export const NO_PANEL_HOST: PanelHostPort = {};

/** A watchlist pane's settings (D35): flat string values, as `22`'s pane settings hold them. */
export interface WatchlistPaneSettings {
  readonly watchlist_id?: string;
  readonly watchlist_sort?: string;
}

export interface PaneSettingsPort {
  read(paneId: string): WatchlistPaneSettings;
  write(paneId: string, patch: WatchlistPaneSettings): void;
}

/** The interim store: in memory, for the session. */
export function createLocalPaneSettings(): PaneSettingsPort {
  const panes = new Map<string, WatchlistPaneSettings>();
  return {
    read: (paneId) => panes.get(paneId) ?? {},
    write(paneId, patch) {
      panes.set(paneId, { ...panes.get(paneId), ...patch });
    },
  };
}

/** The app's one interim store. */
export const localPaneSettings: PaneSettingsPort = createLocalPaneSettings();
