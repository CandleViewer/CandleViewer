// The thin React binding over @candleviewer/chart-engine (26-chart-engine-design.md §8, E11-T01).
// It owns React lifecycle and option diffing only: no rendering logic, no chart data in React
// state (30-frontend-react.md "chart data never flows through React state").
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import {
  createChart,
  type Chart as ChartApi,
  type ChartEvents,
  type ChartOptions,
} from "@candleviewer/chart-engine";

/** The options a `<Chart>` takes: everything but the container, which the binding renders. */
export type ChartProps = {
  readonly options: Omit<ChartOptions, "container">;
  /** Accessible name of the chart region (05 §6.1). */
  readonly label: string;
  readonly onFrameStats?: (stats: ChartEvents["frameStats"]) => void;
  readonly children?: ReactNode;
};

/**
 * Options with no setter on `Chart`: a change to any of them recreates the chart. `theme` and
 * `density` are applied in place; nothing else (callbacks, children, label) recreates it.
 */
export const RECREATE_KEYS = [
  "runMode",
  "locale",
  "timeZone",
  "syncGroup",
  "maxBars",
  "memoryBudgetMb",
] as const satisfies readonly (keyof ChartOptions)[];

type Applied = { theme: ChartOptions["theme"]; density: ChartOptions["density"] | undefined };

const ChartContext = createContext<ChartApi | null>(null);

/** The mounted chart's API, or null before mount and after unmount. */
export function useChartApi(): ChartApi | null {
  return useContext(ChartContext);
}

export function Chart({ options, label, onFrameStats, children }: ChartProps): ReactNode {
  const containerRef = useRef<HTMLDivElement>(null);
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const onFrameStatsRef = useRef(onFrameStats);
  onFrameStatsRef.current = onFrameStats;
  const [chart, setChart] = useState<ChartApi | null>(null);
  // What the live chart was last given, so an unchanged theme or density is never re-applied.
  const applied = useRef<Applied>({ theme: options.theme, density: options.density });

  const recreateKey = JSON.stringify(RECREATE_KEYS.map((k) => options[k] ?? null));

  useEffect(() => {
    const container = containerRef.current;
    if (container === null) return undefined;
    const initial = optionsRef.current;
    const created = createChart({ ...initial, container });
    applied.current = { theme: initial.theme, density: initial.density };
    const off = created.subscribe("frameStats", (s) => onFrameStatsRef.current?.(s));
    // The chart needs the mounted container, so it is created here and published through state:
    // that costs one extra render per mount or recreate, and `<Pane>` children mount one commit
    // after the chart exists. Accepted: neither carries chart data.
    setChart(created);
    return () => {
      off();
      created.dispose();
      setChart(null);
    };
  }, [recreateKey]);

  useEffect(() => {
    if (chart === null || options.theme === applied.current.theme) return;
    applied.current = { ...applied.current, theme: options.theme };
    chart.setTheme(options.theme);
  }, [chart, options.theme]);

  useEffect(() => {
    const density = options.density;
    if (chart === null || density === undefined || density === applied.current.density) return;
    applied.current = { ...applied.current, density };
    chart.setDensity(density);
  }, [chart, options.density]);

  // `figure` + name is the stub's semantics: no live region yet. The real chart semantics
  // (E11-S13, CMP-180) revisit the role once the DOM mirror root carries content.
  return (
    <div ref={containerRef} role="figure" aria-label={label} style={{ position: "relative" }}>
      <ChartContext.Provider value={chart}>
        {chart === null ? null : children}
      </ChartContext.Provider>
    </div>
  );
}

export type PaneProps = {
  /** Share of the chart height, in (0, 1]. Changing it resizes the pane in place. */
  readonly heightRatio?: number;
  readonly children?: ReactNode;
};

/** Adds one pane to the enclosing `<Chart>` for its lifetime; renders no DOM of its own. */
export function Pane({ heightRatio, children }: PaneProps): ReactNode {
  const chart = useChartApi();
  const [pane, setPane] = useState<ReturnType<ChartApi["addPane"]> | null>(null);
  const ratioRef = useRef(heightRatio);
  ratioRef.current = heightRatio;

  useEffect(() => {
    if (chart === null) return undefined;
    const ratio = ratioRef.current;
    const created = chart.addPane(ratio === undefined ? {} : { heightRatio: ratio });
    setPane(created);
    return () => {
      created.remove();
      setPane(null);
    };
  }, [chart]);

  useEffect(() => {
    if (pane !== null && heightRatio !== undefined) pane.setHeightRatio(heightRatio);
  }, [pane, heightRatio]);

  return <>{pane === null ? null : children}</>;
}

/**
 * The latest crosshair position of the enclosing chart, or null. The engine emits at most once
 * per frame; React keeps only the last value (no per-event queue).
 */
export function useCrosshair(): ChartEvents["crosshair"] | null {
  const chart = useChartApi();
  const latest = useRef<ChartEvents["crosshair"] | null>(null);
  const subscribe = useCallback(
    (notify: () => void): (() => void) => {
      if (chart === null) return () => undefined;
      const off = chart.subscribe("crosshair", (p) => {
        latest.current = p;
        notify();
      });
      return () => {
        off();
        latest.current = null;
      };
    },
    [chart],
  );
  return useSyncExternalStore(subscribe, () => latest.current);
}
