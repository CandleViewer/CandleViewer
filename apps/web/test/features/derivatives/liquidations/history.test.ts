// E24-S05 (#780) slice 2: the backfill read against `22` `getLiquidations` — the query, the coverage parse, the
// cursor to a bound keeping the newest prints, and every failure as a status, never a throw.
import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import {
  DEADLINE_MS,
  fetchLiquidationHistory,
  historyPath,
  parseCoverage,
  type LiqHistoryClock,
} from "../../../../src/features/derivatives/liquidations/history";
import { burst, DESIGN, EXAMPLE, EXAMPLE_COVERAGE_WIRE, restItem, restPage } from "./liqFrames";

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const FROM = Date.parse("2026-09-14T10:00:00Z");
const TO = Date.parse("2026-09-14T11:00:00Z");
const req = (over: Partial<Parameters<typeof fetchLiquidationHistory>[0]> = {}) => ({
  symbol: "BTCUSDT",
  fromMs: FROM,
  toMs: TO,
  minNotionalUsd: null,
  keep: 1_000,
  signal: new AbortController().signal,
  ...over,
});

describe("liquidation history read", () => {
  beforeEach(() => apiFetch.mockReset());

  it("builds the query 22 names: cluster_window_ms 0, the filter and the cursor only when set", () => {
    const url = new URL(historyPath(req(), null), "http://x");
    expect(url.pathname).toBe("/api/v1/market/liquidations");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      symbol: "BTCUSDT",
      from: "2026-09-14T10:00:00.000Z",
      to: "2026-09-14T11:00:00.000Z",
      limit: "500",
      cluster_window_ms: "0",
    });
    const filtered = new URL(historyPath(req({ minNotionalUsd: "50000" }), "c1"), "http://x");
    expect(filtered.searchParams.get("min_notional_usd")).toBe("50000");
    expect(filtered.searchParams.get("cursor")).toBe("c1");
  });

  it("parses the 22 example's coverage and refuses a malformed one", () => {
    expect(parseCoverage({ coverage: EXAMPLE_COVERAGE_WIRE })).toEqual({
      firstAvailableMs: Date.parse("2026-09-01T00:00:00.250Z"),
      coveredFromMs: FROM,
      coveredToMs: TO,
      noCoverage: false,
    });
    const never = {
      first_available_ts: null,
      covered_from: null,
      covered_to: null,
      no_coverage: true,
    };
    expect(parseCoverage({ coverage: never })?.firstAvailableMs).toBeNull();
    expect(parseCoverage({ coverage: { ...never, no_coverage: "yes" } })).toBeNull();
    expect(parseCoverage({ coverage: { ...never, covered_from: "soon" } })).toBeNull();
    expect(parseCoverage({})).toBeNull();
  });

  it("reads one page into ascending prints with the coverage, counting malformed items", async () => {
    apiFetch.mockResolvedValueOnce(
      json(200, restPage([restItem(DESIGN), restItem(EXAMPLE), { ...restItem(EXAMPLE), size: 3 }])),
    );
    const out = await fetchLiquidationHistory(req());
    expect(apiFetch).toHaveBeenCalledTimes(1);
    if (out.kind !== "ok") throw new Error("not ok");
    expect(out.prints.map((p) => p.price)).toEqual(["62880.00", "82751.20"]);
    expect(out.prints[0]?.side).toBe("long");
    expect(out.coverage.noCoverage).toBe(false);
    expect(out.malformed).toBe(1);
    expect(out.truncated).toBe(false);
  });

  it("follows next_cursor to the page bound, keeping the newest `keep` prints", async () => {
    apiFetch
      .mockResolvedValueOnce(
        json(200, restPage(burst(3).map(restItem), { has_more: true, next_cursor: "c1" })),
      )
      .mockResolvedValueOnce(
        json(
          200,
          restPage(burst(3, EXAMPLE, EXAMPLE.ts_ms + 10).map(restItem), {
            has_more: true,
            next_cursor: "c2",
          }),
        ),
      );
    const out = await fetchLiquidationHistory(req({ keep: 4, maxPages: 2 }));
    expect(apiFetch).toHaveBeenCalledTimes(2);
    expect(new URL(apiFetch.mock.calls[1]?.[0] ?? "", "http://x").searchParams.get("cursor")).toBe(
      "c1",
    );
    if (out.kind !== "ok") throw new Error("not ok");
    expect(out.prints.map((p) => p.tsMs - EXAMPLE.ts_ms)).toEqual([2, 10, 11, 12]);
    expect(out.truncated).toBe(true);
  });

  it("returns the status and code of a refusal", async () => {
    apiFetch.mockResolvedValueOnce(json(503, { code: "coverage_unavailable" }));
    expect(await fetchLiquidationHistory(req())).toEqual({
      kind: "failed",
      status: 503,
      code: "coverage_unavailable",
    });
  });

  it("fails as malformed when the page lacks items or coverage", async () => {
    apiFetch.mockResolvedValueOnce(json(200, { items: [], meta: { has_more: false } }));
    expect(await fetchLiquidationHistory(req())).toEqual({
      kind: "failed",
      status: 200,
      code: "malformed",
    });
  });

  it("fails with no status on a network error, and reads nothing once aborted", async () => {
    apiFetch.mockRejectedValueOnce(new TypeError("network"));
    expect(await fetchLiquidationHistory(req())).toEqual({
      kind: "failed",
      status: null,
      code: null,
    });
    const call = new AbortController();
    call.abort();
    expect((await fetchLiquidationHistory(req({ signal: call.signal }))).kind).toBe("failed");
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("arms a deadline and clears it", async () => {
    const armed: number[] = [];
    const cleared: unknown[] = [];
    const clock: LiqHistoryClock = {
      setTimeout: (_run, ms) => (armed.push(ms), 7),
      clearTimeout: (id) => void cleared.push(id),
    };
    apiFetch.mockResolvedValueOnce(json(200, restPage([])));
    await fetchLiquidationHistory(req({ clock }));
    expect(armed).toEqual([DEADLINE_MS]);
    expect(cleared).toEqual([7]);
  });
});
