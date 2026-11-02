// E15-T02 (#403) e2e-only harness API: the typed `window.__dockHarness` the GL-churn spec drives.
// Shared by the harness page (main.tsx) and the spec; nothing here is in the production bundle.

/** The README guarantee's layout operations, in the order the spec runs them. */
export const STEP_NAMES = [
  "move",
  "tabify",
  "split out",
  "preset 1+3",
  "maximise",
  "restore",
  "tab group",
  "tab switch",
  "resize",
] as const;

export type StepName = (typeof STEP_NAMES)[number];

/** The chart panes the harness docks: four, the render worker's live-context cap. */
export const PANE_IDS = ["a", "b", "c", "d"] as const;

export interface DockHarness {
  /** Runs one layout operation through the dock store, as DockGrid's own handlers do. */
  run(step: StepName): boolean;
  /** Negative control: re-keys one pane's `<Chart>`, so React mounts a new chart in it. */
  remount(paneId: string): void;
  /** The pane ids in the dock's reading order. */
  panes(): string[];
  /** Engine `error` codes seen per pane (context loss and worker loss arrive here). */
  errors(): Record<string, string[]>;
  /** The last `frameStats.renderProfile` per pane, and how many `frameStats` each has seen. */
  frames(): Record<string, { profile: string; count: number }>;
  /** The pane's chart rendered by its worker into an image: its size in bytes (liveness). */
  screenshot(paneId: string): Promise<number>;
}

/** The page-side counters the spec's init script installs before any page script runs. */
export interface GlCounters {
  offscreenTransfers: number;
  webglContexts: number;
  contextsLost: number;
  workers: number;
}

declare global {
  interface Window {
    __dockHarness?: DockHarness;
    __glCounters?: GlCounters;
  }
}
