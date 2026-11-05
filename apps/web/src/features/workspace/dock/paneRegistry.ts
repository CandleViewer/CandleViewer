/**
 * The pane registry (E15-T02): `kind` -> the component a docked panel mounts. DockGrid imports no
 * panel; panels register here, so E11/E13/E18+ plug in without DockGrid knowing them. A kind not in
 * the registry is never mounted (a tampered or imported layout cannot name a component), and
 * `fromLayout` refuses it before that through `minimums`.
 */
import type { ComponentType } from "react";

/** What every registered panel is given. */
export interface PaneProps {
  readonly paneId: string;
  /**
   * False once the panel has been a hidden tab for 30 s (SCR-020): drop live subscriptions, keep
   * the instance, its canvas and its GL context.
   */
  readonly subscribed: boolean;
}

export interface PaneEntry {
  /** The kind word: the handle is "Move {label}", the close button "Close {label}". */
  readonly label: string;
  readonly component: ComponentType<PaneProps>;
  /** Compact-view thresholds in px (E15-D04 D04-D-5). */
  readonly minWidth: number;
  readonly minHeight: number;
  /** SCR-024's reason ("Needs a recorded symbol", "Owner only"): the kind shows, never mounts. */
  readonly disabledReason?: string;
}

export interface PaneRegistry {
  register(kind: string, entry: PaneEntry): void;
  get(kind: string): PaneEntry | undefined;
  /** For `fromLayout`: a kind's minimums, or null for a kind this registry does not know. */
  minimums(kind: string): { minWidth: number; minHeight: number } | null;
}

export function createPaneRegistry(): PaneRegistry {
  const entries = new Map<string, PaneEntry>();
  return {
    register: (kind, entry) => void entries.set(kind, entry),
    get: (kind) => entries.get(kind),
    minimums: (kind) => {
      const entry = entries.get(kind);
      return entry === undefined ? null : { minWidth: entry.minWidth, minHeight: entry.minHeight };
    },
  };
}

/** The placeholder body for a kind whose panel has not landed: an empty canvas area. */
export function PlaceholderPanel(): null {
  return null;
}

/**
 * Compact minimums by kind (E15-D04 D04-D-5: widths E15-D02's chart 328, DOM 380, tape 232,
 * Positions 300; heights 168 for a chart, 120 for the rest); other kinds take the tape's, the
 * smallest drawn.
 */
const MINIMUMS: Readonly<Record<string, readonly [number, number]>> = {
  chart: [328, 168],
  dom: [380, 120],
  tape: [232, 120],
  positions: [300, 120],
};

/** `22` `PaneKind`, each with its kind word. */
const KINDS: Readonly<Record<string, string>> = {
  chart: "Chart",
  dom: "DOM",
  tape: "Tape",
  profile: "Profile",
  cvd: "CVD",
  oi: "OI",
  deep_stats: "Deep Stats",
  regime: "Regime",
  positions: "Positions",
  journal: "Journal",
  watchlist: "Watchlist",
  alerts: "Alerts",
  scanner: "Scanner",
};

/** Every `PaneKind` on the placeholder panel: the kinds' own panels replace them as they land. */
export function createDefaultPaneRegistry(): PaneRegistry {
  const registry = createPaneRegistry();
  for (const [kind, label] of Object.entries(KINDS)) {
    const [minWidth, minHeight] = MINIMUMS[kind] ?? [232, 120];
    registry.register(kind, { label, component: PlaceholderPanel, minWidth, minHeight });
  }
  return registry;
}
