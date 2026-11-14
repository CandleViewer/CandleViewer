/**
 * E11-Q05 (#517): the chart surfaces under audit (docs/qa/a11y/e11-q05-chart-engine-audit.md §2)
 * and the harness states the a11y collectors visit. The harness is an e2e-only entry
 * (`index.html` here, built by its own `vite.config.ts`), never part of the app bundle
 * (`test/e2e-a11y-chart-harness.test.ts` pins that). `shipped: false` marks a surface that is not
 * built on `main`: it is recorded "not built, not assessed". The list is static (nothing detects a
 * surface landing); PR-2 re-checks each entry against `main` before its run (plan §0).
 */
export interface ChartSurface {
  readonly id: string;
  readonly screen: string;
  readonly shipped: boolean;
  /** The harness states that mount it; empty until the harness renders the surface. */
  readonly states: readonly string[];
}

export const CHART_SURFACES: readonly ChartSurface[] = [
  { id: "S1", screen: "SCR-030", shipped: true, states: ["mirror", "mirror-off"] },
  { id: "S2", screen: "SCR-045", shipped: true, states: [] },
  { id: "S3", screen: "SCR-043", shipped: true, states: [] },
  { id: "S4", screen: "SCR-031", shipped: false, states: [] },
  { id: "S5", screen: "SCR-046", shipped: true, states: [] },
  { id: "S6", screen: "SCR-048", shipped: true, states: [] },
  { id: "S7", screen: "SCR-047", shipped: false, states: [] },
  { id: "S8", screen: "SCR-044", shipped: false, states: [] },
  { id: "S9", screen: "SCR-049", shipped: false, states: [] },
];

/** Toggles the audit depends on that are not built on `main` (plan §7, critic gap 7). */
export const CHART_TOGGLES = [
  { id: "reduce-announcements", shipped: false },
  { id: "dom-mirror-option", shipped: false },
] as const;

export const HARNESS_PORT = process.env["A11Y_HARNESS_PORT"] ?? "4174";
export const HARNESS_ORIGIN = `http://127.0.0.1:${HARNESS_PORT}`;

/** One collector screen per harness state, keyed `<screen>-<state>` (a file-name-safe id). */
export const CHART_SCREENS: readonly { readonly id: string; readonly path: string }[] =
  CHART_SURFACES.flatMap((s) =>
    s.states.map((state) => ({
      id: `${s.screen}-${state}`,
      path: `${HARNESS_ORIGIN}/?state=${state}`,
    })),
  );
