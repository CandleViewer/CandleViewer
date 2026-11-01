/** E08-D06 §4.3, F10, §11.3: coverage and gaps of the last 90 days, from `GET /market/data-coverage`. */
import type { generated } from "@candleviewer/protocol";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { coverageView, fetchCoverage, gapText } from "../../../src/features/symbol-info/coverage";

type Coverage = generated.rest.components["schemas"]["DataCoverage"];
const COVERAGE: Coverage = {
  generated_at: "2026-11-01T10:31:02Z",
  symbol: "BTCUSDT",
  streams: [
    {
      stream: "trades",
      intervals: [
        { from: "2026-09-03T00:00:00Z", to: "2026-09-04T02:11:00Z", rows: 10, tier: "parquet" },
        { from: "2026-09-01T00:00:00Z", to: "2026-09-02T00:00:00Z", rows: 10, tier: "parquet" },
      ],
      gaps: [{ from: "2026-09-04T02:11:00Z", to: "2026-09-04T02:14:20Z", reason: "ws_disconnect" }],
    },
    {
      stream: "orderbook_delta",
      intervals: [
        { from: "2026-09-07T05:00:00Z", to: "2026-09-08T00:00:00Z", rows: 3, tier: "questdb" },
      ],
      gaps: [],
    },
    { stream: "klines", intervals: [{ from: "2026-08-01T00:00:00Z", to: "2026-08-02T00:00:00Z" }] },
  ],
};

describe("gapText (F10)", () => {
  it("rounds the start down and the end up to the minute", () => {
    expect(
      gapText(
        Date.parse("2026-09-04T02:11:00Z"),
        Date.parse("2026-09-04T02:14:20Z"),
        "ws_disconnect",
      ),
    ).toBe("4 Sep 02:11–02:15 UTC, connection lost");
    expect(
      gapText(Date.parse("2026-09-04T02:11:59Z"), Date.parse("2026-09-04T02:12:01Z"), "seq_jump"),
    ).toBe("4 Sep 02:11–02:13 UTC, order-book sequence jump");
  });

  it("repeats the day across midnight", () => {
    expect(
      gapText(
        Date.parse("2026-09-04T23:58:00Z"),
        Date.parse("2026-09-05T00:02:00Z"),
        "backend_restart",
      ),
    ).toBe("4 Sep 23:58–5 Sep 00:02 UTC, CandleViewer restarted");
  });

  it.each([
    ["retention_purge", "removed by the retention policy"],
    ["exchange_outage", "exchange outage"],
    ["never_recorded", "not recorded"],
    ["backpressure_drop", "rows dropped under write pressure"],
    ["something_new", "a gap"],
    ["toString", "a gap"],
    [undefined, "a gap"],
  ])("words reason %s as %s (an unknown reason is still a gap)", (reason, words) => {
    expect(gapText(0, 60_000, reason)).toMatch(new RegExp(`UTC, ${words}$`));
  });
});

describe("coverageView", () => {
  it("shows the earliest from per named stream, the gap count and the latest gap", () => {
    expect(coverageView(COVERAGE)).toEqual({
      asOf: "Coverage as of 10:31:02 UTC · trades can include imported days",
      streams: ["trades from 1 Sep", "order book from 7 Sep"],
      gapCount: 1,
      latestGap: "4 Sep 02:11–02:15 UTC, connection lost",
      latestGapExact: "2026-09-04T02:11:00Z–2026-09-04T02:14:20Z",
      empty: null,
    });
  });

  it("reads a window with no interval as no data and omits the gaps, never zero", () => {
    const view = coverageView({
      generated_at: "2026-11-01T10:31:02Z",
      streams: [{ stream: "trades", intervals: [], gaps: [] }],
    });
    expect(view).toMatchObject({
      empty: "No recorded data in the last 90 days",
      gapCount: null,
      latestGap: null,
      streams: [],
    });
    expect(coverageView({}).empty).toBe("No recorded data in the last 90 days");
    expect(coverageView({}).asOf).toBeNull();
  });

  it("counts gaps over every stream and picks the latest by its end", () => {
    const view = coverageView({
      streams: [
        {
          stream: "trades",
          intervals: [{ from: "2026-09-01T00:00:00Z" }],
          gaps: [
            { from: "2026-09-02T00:00:00Z", to: "2026-09-02T00:05:00Z", reason: "never_recorded" },
            { from: "2026-09-09T10:00:00Z", to: "2026-09-09T10:03:00Z" },
          ],
        },
        {
          stream: "orderbook_snapshot",
          intervals: [{ from: "2026-09-05T00:00:00Z" }],
          gaps: [{ from: "2026-09-04T00:00:00Z", to: "2026-09-04T00:01:00Z", reason: "seq_jump" }],
        },
      ],
    });
    expect(view.gapCount).toBe(3);
    expect(view.latestGap).toBe("9 Sep 10:00–10:03 UTC, a gap");
    expect(view.streams).toEqual(["trades from 1 Sep", "order book from 5 Sep"]);
  });

  it("skips a malformed time instead of guessing", () => {
    const view = coverageView({
      streams: [
        { stream: "trades", intervals: [{ from: "nope" }], gaps: [{ from: "x", to: "y" }] },
      ],
    });
    expect(view.empty).not.toBeNull();
  });
});

describe("fetchCoverage", () => {
  beforeEach(() => apiFetch.mockReset());
  afterEach(() => vi.useRealTimers());
  const json = (status: number, body: unknown): Response =>
    new Response(JSON.stringify(body), { status });
  const signal = (): AbortSignal => new AbortController().signal;

  it("asks once with the symbol and maps a 200", async () => {
    apiFetch.mockResolvedValueOnce(json(200, COVERAGE));
    const out = await fetchCoverage("BTCUSDT", signal());
    expect(out?.kind).toBe("ok");
    expect(apiFetch.mock.calls[0]?.[0]).toBe("/api/v1/market/data-coverage?symbol=BTCUSDT");
  });

  it("maps 422, 403, other statuses and a network error, each on its own", async () => {
    apiFetch
      .mockResolvedValueOnce(json(422, {}))
      .mockResolvedValueOnce(json(403, {}))
      .mockResolvedValueOnce(json(500, {}))
      .mockRejectedValueOnce(new TypeError("offline"));
    expect(await fetchCoverage("BTCUSDT", signal())).toEqual({ kind: "refused_422" });
    expect(await fetchCoverage("BTCUSDT", signal())).toEqual({ kind: "forbidden" });
    expect(await fetchCoverage("BTCUSDT", signal())).toEqual({ kind: "failed", status: 500 });
    expect(await fetchCoverage("BTCUSDT", signal())).toEqual({ kind: "failed", status: null });
  });

  it("sends nothing for a bad symbol and drops an aborted answer", async () => {
    expect(await fetchCoverage("../x", signal())).toEqual({ kind: "failed", status: null });
    expect(apiFetch).not.toHaveBeenCalled();
    const ctl = new AbortController();
    apiFetch.mockImplementationOnce(async () => {
      ctl.abort();
      return json(200, COVERAGE);
    });
    expect(await fetchCoverage("BTCUSDT", ctl.signal)).toBeNull();
  });
});
