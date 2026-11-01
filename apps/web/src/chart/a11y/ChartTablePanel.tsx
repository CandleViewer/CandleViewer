/**
 * The chart panel's view switch (E47-S01 C2, #1316): SCR-045 opens from the panel header, at equal status with the
 * chart (E11-D04 D1), and from `Alt+T` (`chart.table_toggle`, `05` §3.2) while focus is in the panel. "Always show
 * data tables" (SCR-117) makes the table the panel's default view. The chart stays mounted while the table shows, so
 * switching back neither recreates the engine nor re-sends data.
 */
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { JSX, ReactNode } from "react";
import { useDefaultPanelView } from "../../features/a11y-preferences/consumers";
import { registerCommand } from "../../keymap/KeymapHost";
import { ChartDataTable, type ChartDataTableProps } from "./ChartDataTable";
import { SAY, VIEW_CHART, VIEW_GROUP, VIEW_TABLE, VIEW_TABLE_HINT } from "./copy";
import { politeToShell } from "./politeWriter";
import "./chartTable.css";

export const TABLE_TOGGLE_COMMAND = "chart.table_toggle";

interface PanelEntry {
  readonly root: () => HTMLElement | null;
  readonly toggle: () => void;
}

/** The mounted panels; the one holding focus takes the key. One registry handler serves them all. */
const panels = new Set<PanelEntry>();
let unregister: (() => void) | null = null;

const focusedPanel = (): PanelEntry | undefined => {
  const active = document.activeElement;
  for (const p of panels) if (active !== null && p.root()?.contains(active)) return p;
  return undefined;
};

function attach(entry: PanelEntry): () => void {
  panels.add(entry);
  unregister ??= registerCommand(
    TABLE_TOGGLE_COMMAND,
    () => focusedPanel()?.toggle(),
    () => focusedPanel() !== undefined,
  );
  return () => {
    panels.delete(entry);
    if (panels.size === 0 && unregister !== null) {
      unregister();
      unregister = null;
    }
  };
}

export interface ChartTablePanelProps extends Omit<
  ChartDataTableProps,
  "focusOnOpen" | "initialBar" | "onExit"
> {
  /** The panel's name (its region label), e.g. "BTCUSDT 1m". */
  readonly title: string;
  /** The `<Chart>` the table is the alternative of. */
  readonly chart: ReactNode;
  /** The chart's cursor bar, where the table opens; default the latest bar. */
  readonly cursorBar?: number;
  /** The panel title's heading level, from the host's outline (default 2). */
  readonly headingLevel?: 2 | 3 | 4 | 5 | 6;
}

export function ChartTablePanel(props: ChartTablePanelProps): JSX.Element {
  const { title, chart, cursorBar, headingLevel = 2, ...table } = props;
  const Heading = `h${headingLevel}` as const;
  const preferred = useDefaultPanelView();
  const [override, setOverride] = useState<"chart" | "table" | null>(null);
  const view = override ?? preferred;
  const [byKey, setByKey] = useState(false);
  const root = useRef<HTMLElement>(null);
  const chartSlot = useRef<HTMLDivElement>(null);
  const tableButton = useRef<HTMLButtonElement>(null);
  const headerId = useId();

  const show = (next: "chart" | "table", fromKey: boolean): void => {
    setByKey(fromKey);
    setOverride(next);
  };
  const toggleRef = useRef<() => void>(() => undefined);
  // The ref follows the render in an effect, so render stays pure (code lens r1 m3).
  useLayoutEffect(() => {
    toggleRef.current = () => show(view === "table" ? "chart" : "table", true);
  });

  useEffect(() => attach({ root: () => root.current, toggle: () => toggleRef.current() }), []);

  // Back on the chart by key: focus returns to the chart surface (a user action, `05` §3.4.3), said once. A chart
  // with nothing focusable leaves focus on the Table button, never on the page body (a11y lens r1 m4).
  useEffect(() => {
    if (!byKey || view !== "chart") return;
    const surface = chartSlot.current?.querySelector<HTMLElement>('[role="figure"], [tabindex]');
    (surface ?? tableButton.current)?.focus();
    (table.say ?? politeToShell)(SAY.chart);
    setByKey(false);
  }, [byKey, view, table.say]);

  return (
    <section
      ref={root}
      aria-labelledby={headerId}
      data-keymap-context="Chart"
      className="cv-chart-panel"
    >
      <header className="cv-chart-panel__header">
        <Heading id={headerId} className="cv-chart-panel__title">
          {title}
        </Heading>
        <div role="group" aria-label={VIEW_GROUP} className="cv-chart-panel__views">
          <button
            type="button"
            className="cv-chart-panel__view cv-focus-ring"
            aria-pressed={view === "chart"}
            onClick={() => show("chart", false)}
          >
            {VIEW_CHART}
          </button>
          <button
            ref={tableButton}
            type="button"
            className="cv-chart-panel__view cv-focus-ring"
            aria-pressed={view === "table"}
            aria-keyshortcuts="Alt+T"
            title={VIEW_TABLE_HINT}
            onClick={() => show("table", false)}
          >
            {VIEW_TABLE}
          </button>
        </div>
      </header>
      {/* `hidden` while the table is the shown alternative: a recorded deviation from `05` §6.1's "the mirror is never
          display:none" (code lens r1 m7); the engine host's 0x0 re-measure on return is carried to the mount. */}
      <div ref={chartSlot} hidden={view === "table"}>
        {chart}
      </div>
      {view === "table" ? (
        <ChartDataTable
          {...table}
          title={title}
          focusOnOpen={byKey}
          onExit={() => show("chart", true)}
          {...(cursorBar === undefined ? {} : { initialBar: cursorBar })}
        />
      ) : null}
    </section>
  );
}
