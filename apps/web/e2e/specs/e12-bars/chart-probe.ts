import type { Locator, Page } from "@playwright/test";

// E12-Q03 chartProbe page-object. Specs read chart state only through the SCR-045 data-table
// alternative, the SCR-046 diagnostics JSON island and the CMP-199 legend, never canvas pixels.
// None of those surfaces ship in apps/web yet (blocked: E12-S07, E12-D09/CMP-220/222, E11-S14,
// E11-T07, E46-S01), so the selectors below are the PROPOSED contract and every spec using them
// is test.fixme until those land; adjust selectors in this one file then.
export const PROBE_VERSION = 1;

export class ChartProbe {
  constructor(private readonly page: Page) {}

  get dataTable(): Locator {
    return this.page.getByRole("table", { name: /chart data/i });
  }
  get dataRows(): Locator {
    return this.dataTable.getByRole("row");
  }
  get legend(): Locator {
    return this.page.getByRole("group", { name: /chart legend/i });
  }
  get diagnosticsIsland(): Locator {
    return this.page.getByTestId("chart-diagnostics-json");
  }
  async diagnostics(): Promise<{ version: number; glContextId: string }> {
    return JSON.parse((await this.diagnosticsIsland.textContent()) ?? "{}");
  }
  /** Fail-fast helper: records every kline/bar request so specs can assert absence. */
  trackMarketRequests(): string[] {
    const seen: string[] = [];
    this.page.on("request", (r) => {
      if (/\/market\/(klines|bars)/.test(r.url())) seen.push(r.url());
    });
    return seen;
  }
}
