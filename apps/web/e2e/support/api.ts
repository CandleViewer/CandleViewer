import type { Page } from "@playwright/test";
import type { generated } from "@candleviewer/protocol";
import { json } from "@candleviewer/fixtures/e2e/stubs";

// The stubs moved to `@candleviewer/fixtures/e2e` (E10-Q02) so the Electron suite can use them too; this
// path stays so the existing specs import them unchanged.
export * from "@candleviewer/fixtures/e2e/stubs";

type Schemas = generated.rest.components["schemas"];

/** Answers `GET` to `path` with `body`; any other method goes on (as the fixtures' own `stubGet`). */
async function stubGet(page: Page, path: string, body: () => unknown): Promise<void> {
  await page.route(
    (url) => url.pathname === path,
    (r) => (r.request().method() === "GET" ? r.fulfill(json(body())) : r.fallback()),
  );
}

/**
 * SCR-100 on R-111 (E08-S08): `GET /watchlists` as 22 `listWatchlists` answers it, with one list whose id is the a11y
 * collectors' path segment (`/watchlist/x`), and `GET /instruments` (`listInstruments`, one page) with the Trading
 * instruments it holds, so the page is audited populated, not as its error state. No ticker frame: the rows read as
 * the client holds no value.
 */
export async function stubWatchlists(page: Page): Promise<void> {
  const symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"];
  const watchlist: Schemas["Watchlist"] = {
    id: "x",
    name: "Majors",
    symbols,
    columns: [],
    version: 1,
    created_at: "2026-10-30T10:00:00Z",
    updated_at: "2026-10-30T10:00:00Z",
  };
  await stubGet(page, "/api/v1/watchlists", () => ({ items: [watchlist] }));
  const instrument = (symbol: string): Schemas["Instrument"] => ({
    symbol,
    category: "linear",
    status: "Trading",
    price_scale: 2,
    tick_size: "0.01",
    qty_step: "0.001",
  });
  await stubGet(page, "/api/v1/instruments", () => ({
    items: symbols.map(instrument),
    meta: {
      next_cursor: null,
      has_more: false,
      count: symbols.length,
      cache_age_s: 1,
      stale_since: null,
    },
  }));
}
