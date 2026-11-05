// E24-S06 (#781) slice 1: the bars read against `22` `getMetrics` as #5341 declares it (barsFrames.ts) — the query
// (one request per side, `liquidation_notional`, `bar_type=time`, the chart's `param`), the checks at the boundary
// (side, unit, `v`), and every failure as a status, never a throw and never half a pair.
import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import {
  BARS_FILTER_SERVER_SIDE,
  fetchLiquidationBars,
  METRIC,
  metricsPath,
  parseSide,
  type BarsRequest,
} from "../../../../../src/features/derivatives/liquidations/bars/barsRead";
import { DEADLINE_MS } from "../../../../../src/features/derivatives/liquidations/historyRead";
import {
  DAY_LONG,
  DAY_SHORT,
  HOUR,
} from "../../../../../src/features/derivatives/liquidations/bars/samples";
import { NOT_COMPUTED_DETAIL } from "../../../../../src/features/derivatives/liquidations/bars/copy";
import { CONTRACT, metricsBody, wirePoints } from "./barsFrames";

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const FROM = Date.parse("2026-10-20T22:00:00Z");
const TO = Date.parse("2026-10-21T02:30:00Z");
const req = (over: Partial<BarsRequest> = {}): BarsRequest => ({
  symbol: "BTCUSDT",
  param: "60",
  fromMs: FROM,
  toMs: TO,
  minNotionalUsd: "0",
  serverThreshold: false,
  signal: new AbortController().signal,
  ...over,
});
const sideOf = (url: string): string => {
  const params = JSON.parse(new URL(url, "http://x").searchParams.get("params") ?? "{}") as Record<
    string,
    { side: string }
  >;
  return params[METRIC]?.side ?? "";
};

describe("the contract the client relies on (#5341, pinned by content)", () => {
  it("quotes the sentences of the 22 diff it was built from", () => {
    // the repo's 22 holds them only once #5341 merges; the re-pin to the merge commit swaps this for a read of 22
    expect(CONTRACT.zeroSentence).toContain('reads `"0"`');
    expect(CONTRACT.paramsSentence).toContain("`long` or `short`");
    expect(METRIC).toBe("liquidation_notional");
    expect(METRIC).not.toBe(CONTRACT.alias);
    // router-only: the pane's key for "not computed yet" is the router's sentence, pinned here like the others
    expect(NOT_COMPUTED_DETAIL).toBe(CONTRACT.notComputedDetail);
  });

  it("keeps the threshold off the wire until the server takes it (BQ-1)", () => {
    expect(BARS_FILTER_SERVER_SIDE).toBe(false);
  });
});

describe("the metrics query", () => {
  it("names the 24 §7.2 code, the time grid and the side, in the params object keyed by the code", () => {
    const url = new URL(metricsPath(req(), "short"), "http://x");
    expect(url.pathname).toBe("/api/v1/market/metrics");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      symbol: "BTCUSDT",
      metric: "liquidation_notional",
      bar_type: "time",
      param: "60",
      from: "2026-10-20T22:00:00.000Z",
      to: "2026-10-21T02:30:00.000Z",
      params: '{"liquidation_notional":{"side":"short"}}',
    });
  });

  it("sends the threshold only when the server applies it and it is non-zero", () => {
    const sent = (r: Partial<BarsRequest>): unknown =>
      JSON.parse(
        new URL(metricsPath(req(r), "long"), "http://x").searchParams.get("params") ?? "{}",
      );
    expect(sent({ minNotionalUsd: "50000" })).toEqual({ liquidation_notional: { side: "long" } });
    expect(sent({ minNotionalUsd: "50000", serverThreshold: true })).toEqual({
      liquidation_notional: { side: "long", min_notional_usd: "50000" },
    });
    expect(sent({ minNotionalUsd: "0.00", serverThreshold: true })).toEqual({
      liquidation_notional: { side: "long" },
    });
  });
});

describe("parsing a series", () => {
  const ok = (body: unknown) => parseSide(body, "long");

  it("keeps exact decimal strings and a null as null, never 0", () => {
    const body = metricsBody("long", [
      { t: "2026-10-21T00:00:00Z", v: "41210.10" },
      { t: "2026-10-21T01:00:00Z", v: "0" },
      { t: "2026-10-21T02:00:00Z", v: null },
    ]);
    const r = ok(body);
    expect(r.kind === "ok" && [...r.points.values()]).toEqual(["41210.10", "0", null]);
    expect(r.kind === "ok" && r.malformed).toBe(0);
  });

  it("counts a value that is not a decimal string (a number, an enum) and reads it as unknown", () => {
    const r = ok(
      metricsBody("long", [
        { t: "2026-10-21T00:00:00Z", v: 41210.1 },
        { t: "2026-10-21T01:00:00Z", v: "long_buildup" },
        { t: "2026-10-21T02:00:00Z", v: "7" },
      ]),
    );
    expect(r.kind === "ok" && [...r.points.values()]).toEqual([null, null, "7"]);
    expect(r.kind === "ok" && r.malformed).toBe(2);
  });

  it("counts an unreadable time and a repeated one, keeping the first", () => {
    const r = ok(
      metricsBody("long", [
        { t: "not-a-time", v: "1" },
        { t: "2026-10-21T00:00:00Z", v: "2" },
        { t: "2026-10-21T00:00:00Z", v: "3" },
      ]),
    );
    expect(r.kind === "ok" && [...r.points.values()]).toEqual(["2"]);
    expect(r.kind === "ok" && r.malformed).toBe(2);
  });

  it("refuses a series for the wrong side, the wrong unit, a missing one or a repeated one", () => {
    const pts = wirePoints(DAY_LONG);
    expect(ok(metricsBody("short", pts)).kind).toBe("failed");
    expect(ok(metricsBody("long", pts, { unit: "base_volume" })).kind).toBe("failed");
    expect(ok(metricsBody("long", pts, { metric: CONTRACT.alias })).kind).toBe("failed");
    expect(ok({ series: [] }).kind).toBe("failed");
    expect(ok(null).kind).toBe("failed");
    const twice = metricsBody("long", pts);
    expect(ok({ ...twice, series: [...twice.series, ...twice.series] }).kind).toBe("failed");
    expect(ok(metricsBody("long", pts, { points: "x" })).kind).toBe("failed");
  });
});

describe("reading both sides", () => {
  beforeEach(() => {
    apiFetch.mockReset();
  });
  const answer = (url: string): Response =>
    sideOf(url) === "long"
      ? json(200, metricsBody("long", wirePoints(DAY_LONG)))
      : json(200, metricsBody("short", wirePoints(DAY_SHORT)));

  it("reads long and short and returns both series on the same grid", async () => {
    apiFetch.mockImplementation((url) => Promise.resolve(answer(url)));
    const r = await fetchLiquidationBars(req());
    expect(apiFetch).toHaveBeenCalledTimes(2);
    expect(r.kind === "ok" && [...r.long.keys()]).toEqual([...DAY_LONG.keys()]);
    expect(r.kind === "ok" && [...r.short.keys()]).toEqual([...DAY_SHORT.keys()]);
    expect([...DAY_LONG.keys()].every((t) => t % HOUR === 0)).toBe(true);
  });

  it("fails as a whole when one side fails: half a pair would draw a side as zero", async () => {
    apiFetch.mockImplementation((url) =>
      Promise.resolve(
        sideOf(url) === "long" ? answer(url) : json(503, { code: "store_unavailable" }),
      ),
    );
    expect(await fetchLiquidationBars(req())).toEqual({
      kind: "failed",
      status: 503,
      code: "store_unavailable",
      detail: null,
    });
  });

  it("reports a 422 (a code the server does not compute yet) with its status", async () => {
    apiFetch.mockImplementation(() =>
      Promise.resolve(
        json(422, {
          code: "validation_failed",
          detail: "not computed by this server yet: liquidation_notional",
        }),
      ),
    );
    expect(await fetchLiquidationBars(req())).toEqual({
      kind: "failed",
      status: 422,
      code: "validation_failed",
      detail: "not computed by this server yet: liquidation_notional",
    });
  });

  it("carries an unlisted symbol's 422 detail as it is, so the pane can tell it from that one", async () => {
    apiFetch.mockImplementation(() =>
      Promise.resolve(json(422, { code: "validation_failed", detail: "BTCUSDT is not listed" })),
    );
    expect(await fetchLiquidationBars(req())).toMatchObject({
      status: 422,
      detail: "BTCUSDT is not listed",
    });
  });

  it("reports a refused body as malformed, and a network error or unreadable body without a status", async () => {
    apiFetch.mockImplementation(() => Promise.resolve(json(200, { series: [] })));
    expect(await fetchLiquidationBars(req())).toEqual({
      kind: "failed",
      status: 200,
      code: "malformed",
      detail: null,
    });
    apiFetch.mockImplementation(() => Promise.reject(new Error("offline")));
    expect(await fetchLiquidationBars(req())).toEqual({
      kind: "failed",
      status: null,
      code: null,
      detail: null,
    });
    apiFetch.mockImplementation(() => Promise.resolve(new Response("<html>", { status: 200 })));
    expect(await fetchLiquidationBars(req())).toMatchObject({ kind: "failed", status: 200 });
  });

  it("aborts both calls at the deadline, on the injected clock", async () => {
    const run: { fn: (() => void)[] } = { fn: [] };
    apiFetch.mockImplementation(
      (_url, init) =>
        new Promise((_res, rej) => {
          init?.signal?.addEventListener("abort", () => rej(new Error("aborted")));
        }),
    );
    const cleared: unknown[] = [];
    const pending = fetchLiquidationBars(
      req({
        clock: {
          setTimeout: (fn, ms) => {
            expect(ms).toBe(DEADLINE_MS);
            run.fn.push(fn);
            return run.fn.length;
          },
          clearTimeout: (id) => cleared.push(id),
        },
      }),
    );
    await Promise.resolve();
    run.fn.forEach((f) => f());
    expect(await pending).toEqual({ kind: "failed", status: null, code: null, detail: null });
    expect(cleared).toHaveLength(2);
  });

  it("does not call when the signal is already aborted", async () => {
    const ctl = new AbortController();
    ctl.abort();
    expect(await fetchLiquidationBars(req({ signal: ctl.signal }))).toEqual({
      kind: "failed",
      status: null,
      code: null,
      detail: null,
    });
    expect(apiFetch).not.toHaveBeenCalled();
  });
});
