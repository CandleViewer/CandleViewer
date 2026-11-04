import type { Locator, Page } from "@playwright/test";
import { VIEW_CHART, VIEW_GROUP, VIEW_TABLE } from "../../../src/chart/a11y/copy";

// E12-Q03 (#419) chartProbe page-object. Specs read chart state only through the SCR-045 data table,
// the SCR-046 diagnostics island and the CMP-199 legend, never canvas pixels. Every locator is a role
// plus an accessible name; each name is imported from the feature's copy module where one ships on
// `main` (SCR-045, E47-S01), and is otherwise the E12-D12 copy-deck string, cited by its deck id, in
// `COPY` below, so a copy change is a one-line edit here and never in a spec.
export const PROBE_VERSION = 1;

/**
 * E12-D12 copy-deck strings for surfaces with no copy module on `main` yet. Each entry names its deck
 * id; when the feature ships its own copy module, the entry becomes an import of it.
 */
export const COPY = {
  /** d04:S-1 — SCR-041's dialog name for the first chart. */
  quickSwitcher: /^Change symbol and interval, Chart 1$/u,
  /** d05:W-1 — the CMP-222 group on the chart toolbar. */
  chartType: "Chart type",
  /** d05:W-1 — CMP-220's bar-mode control. */
  barMode: "Bar mode",
  /** d05:W-2 — the CMP-222 options, in toolbar order. */
  seriesTypes: ["Candles", "Bars (OHLC)", "Hollow candles", "Line", "Area", "Baseline"] as const,
  heikinAshi: "Heikin-Ashi",
  /** d03:C-33 — the partial-history marker's sentence head. */
  recordingStart: /^Bars start where recording started/u,
  /** d03:C-22 — the message line after a cancelled build. */
  buildCancelled: /^Build of .+ cancelled at \d+ %; showing .+\.$/u,
  /** d05:W-5 — the Heikin-Ashi plus footprint guard's two choices. */
  keepType: /^Keep /u,
  haTurnFootprintOff: "Use Heikin-Ashi, turn footprint off",
  /** d08:W-3 — SCR-047 naming the first available timestamp. */
  historyStarts: /^History starts \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC — recording began then\.$/u,
  /** d08:W-13 — SCR-048's data-feed cause. */
  feedFailed: /^Couldn't load BTCUSDT 1m from the exchange feed\.$/u,
  retry: /^Retry/u,
} as const;

export interface Diagnostics {
  readonly version: number;
  readonly glContextId: string;
}

export class ChartProbe {
  constructor(
    private readonly page: Page,
    /** The panel's region name: SCR-045's caption head, e.g. "BTCUSDT 1m". */
    readonly title: string,
  ) {}

  /** The chart panel (`ChartTablePanel`): a region named by its heading. */
  get panel(): Locator {
    return this.page.getByRole("region", { name: this.title, exact: true });
  }
  get viewGroup(): Locator {
    return this.panel.getByRole("group", { name: VIEW_GROUP });
  }
  get chartButton(): Locator {
    return this.viewGroup.getByRole("button", { name: VIEW_CHART, exact: true });
  }
  get tableButton(): Locator {
    return this.viewGroup.getByRole("button", { name: VIEW_TABLE, exact: true });
  }
  /** SCR-045: a grid named by its caption, "<title> — N bars loaded". */
  get dataTable(): Locator {
    return this.panel.getByRole("grid", { name: new RegExp(`^${escape(this.title)} — `, "u") });
  }
  /** The grid's rows in the window it renders (the header row first). */
  get rows(): Locator {
    return this.dataTable.getByRole("row");
  }
  /** The row of the bar opening at `time`, as SCR-045's time column writes it. */
  barRow(time: string): Locator {
    return this.rows.filter({ has: this.page.getByRole("rowheader", { name: time }) });
  }
  get legend(): Locator {
    return this.panel.getByRole("group", { name: /chart legend/iu });
  }
  get chartType(): Locator {
    return this.page.getByRole("radiogroup", { name: COPY.chartType });
  }
  seriesType(name: string): Locator {
    return this.chartType.getByRole("radio", { name, exact: true });
  }
  get quickSwitcher(): Locator {
    return this.page.getByRole("dialog", { name: COPY.quickSwitcher });
  }
  /** SCR-046's versioned JSON island (test builds only; `probe-absent.spec.ts` guards production). */
  get diagnosticsIsland(): Locator {
    return this.page.getByTestId("chart-diagnostics-json");
  }

  /** The bar count the caption states ("N bars loaded"), not the windowed row count. */
  async barsLoaded(): Promise<number> {
    const name = (await this.dataTable.getAttribute("aria-label")) ?? (await captionOf(this));
    const m = /— ([\d,]+) bars loaded$/u.exec(name);
    if (m?.[1] === undefined) throw new Error(`no bar count in the SCR-045 caption: ${name}`);
    return Number(m[1].replaceAll(",", ""));
  }

  /** Opens SCR-045 from the keyboard (Alt+T, `chart.table_toggle`) with focus in the panel. */
  async openTableByKey(): Promise<void> {
    await this.tableButton.focus();
    await this.page.keyboard.press("Alt+T");
  }

  async diagnostics(): Promise<Diagnostics> {
    const raw: unknown = JSON.parse((await this.diagnosticsIsland.textContent()) ?? "null");
    if (!isDiagnostics(raw)) throw new Error("SCR-046 island is not the v1 probe shape");
    if (raw.version !== PROBE_VERSION) {
      throw new Error(`SCR-046 probe v${raw.version}; this suite reads v${PROBE_VERSION}`);
    }
    return raw;
  }
}

async function captionOf(probe: ChartProbe): Promise<string> {
  return (await probe.dataTable.locator("caption").textContent()) ?? "";
}

function isDiagnostics(v: unknown): v is Diagnostics {
  if (typeof v !== "object" || v === null) return false;
  const o = v as Record<string, unknown>;
  return typeof o["version"] === "number" && typeof o["glContextId"] === "string";
}

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
}
