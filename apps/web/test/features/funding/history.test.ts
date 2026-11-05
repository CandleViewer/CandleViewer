// E24-S03 (#778) slice 1: the funding read against `22` `getFundingHistory` (§19.110) over the recorded pages.
import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import {
  fetchFundingHistory,
  fundingPath,
  isDecimal,
  MAX_PAGES,
  parseCoverage,
  parseItem,
  timeOf,
} from "../../../src/features/funding/history";
import {
  coverage,
  json,
  offContract,
  page,
  predictedItem,
  problem,
  recordedSettled,
} from "./support/fundingFixtures";

const BTC = recordedSettled("BTCUSDT_8h");
const req = (over: Partial<Parameters<typeof fetchFundingHistory>[0]> = {}) => ({
  symbol: "BTCUSDT",
  fromMs: Date.parse(BTC[0]?.t ?? ""),
  toMs: Date.parse(BTC[BTC.length - 1]?.t ?? "") + 1,
  signal: new AbortController().signal,
  ...over,
});

describe("funding history read", () => {
  beforeEach(() => apiFetch.mockReset());

  it("builds the query the contract names, the cursor only when paging", () => {
    const url = new URL(
      fundingPath({ symbol: "BTCUSDT", fromMs: 0, toMs: 1000 }, null),
      "http://x",
    );
    expect(url.pathname).toBe("/api/v1/market/funding");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      symbol: "BTCUSDT",
      from: "1970-01-01T00:00:00.000Z",
      to: "1970-01-01T00:00:01.000Z",
      limit: "500",
    });
    expect(new URL(fundingPath(req(), "c1"), "http://x").searchParams.get("cursor")).toBe("c1");
  });

  it("reads the interval from the response and never takes the predicted item as settled", async () => {
    apiFetch.mockResolvedValueOnce(
      json(200, page([...BTC, predictedItem()], { interval: 480, meta: { coverage: coverage() } })),
    );
    const out = await fetchFundingHistory(req());
    if (out.kind !== "ok") throw new Error(out.kind);
    expect(out.intervalMinutes).toBe(480);
    expect(out.settled.map((p) => p.rate)).toEqual(["0.00012", "-0.00004", "0.00008", "0.0001"]);
    expect(out.coverage?.noCoverage).toBe(false);
  });

  it("reads an absent interval and coverage as unknown, never as 8 h or covered", async () => {
    apiFetch.mockResolvedValueOnce(json(200, page(BTC)));
    const out = await fetchFundingHistory(req());
    if (out.kind !== "ok") throw new Error(out.kind);
    expect(out.intervalMinutes).toBeNull();
    expect(out.coverage).toBeNull();
  });

  it("follows next_cursor, merges pages unique by time and flags a bound that ran out", async () => {
    apiFetch
      .mockResolvedValueOnce(
        json(
          200,
          page(BTC.slice(0, 3), { interval: 480, meta: { has_more: true, next_cursor: "c1" } }),
        ),
      )
      .mockResolvedValueOnce(
        json(200, page(BTC.slice(2), { meta: { has_more: true, next_cursor: "c2" } })),
      );
    const out = await fetchFundingHistory(req({ maxPages: 2 }));
    expect(apiFetch).toHaveBeenCalledTimes(2);
    expect(apiFetch.mock.calls[1]?.[0]).toContain("cursor=c1");
    if (out.kind !== "ok") throw new Error(out.kind);
    expect(out.settled).toHaveLength(4);
    expect(out.truncated).toBe(true);
  });

  it("drops a malformed item, never coerces it", async () => {
    const bad = [
      { ...BTC[0], funding_rate: 1e-4 },
      { ...BTC[1], t: "2023-11-14 08:00:00" },
    ];
    const body = { ...page(BTC.slice(2), { interval: 480 }), items: [...bad, ...BTC.slice(2)] };
    apiFetch.mockResolvedValueOnce(offContract(body));
    const out = await fetchFundingHistory(req());
    if (out.kind !== "ok") throw new Error(out.kind);
    expect(out.settled.map((p) => p.rate)).toEqual(["0.00008", "0.0001"]);
  });

  it("takes `22`'s Decimal and RFC 3339 date-time, nothing looser", () => {
    for (const ok of ["0", "-0.0004", "63120.50", `0.${"1".repeat(40)}`])
      expect(isDecimal(ok)).toBe(true);
    for (const bad of ["1e-4", ".5", "+1", "1.", " 1", 1e-4]) expect(isDecimal(bad)).toBe(false);
    expect(timeOf("2023-11-14T08:00:00Z")).toBe(Date.UTC(2023, 10, 14, 8));
    expect(timeOf("2023-11-14T09:00:00.000+01:00")).toBe(Date.UTC(2023, 10, 14, 8));
    for (const bad of [
      "2023-11-14",
      "2023-11-14 08:00:00Z",
      "Nov 14 2023",
      "2023-11-14T08:00:00",
    ]) {
      expect(timeOf(bad)).toBeNull();
    }
  });

  it.each([
    [json(404, problem(404, "not_found")), { kind: "unavailable" }],
    [json(503, problem(503, "service_unavailable")), { status: 503, code: "service_unavailable" }],
    [new TypeError("network"), { status: null, code: null }],
    [offContract({ meta: {} }), { status: 200, code: "malformed" }],
  ])("answers unavailable on 404 and failed otherwise (%#)", async (answer, expected) => {
    if (answer instanceof Response) apiFetch.mockResolvedValueOnce(answer);
    else apiFetch.mockRejectedValueOnce(answer);
    expect(await fetchFundingHistory(req())).toEqual({ kind: "failed", ...expected });
  });

  it("aborts the call at the deadline and never starts on an aborted signal", async () => {
    let fire: (() => void) | undefined;
    const clock = { setTimeout: (run: () => void) => (fire = run), clearTimeout: vi.fn() };
    apiFetch.mockImplementationOnce(
      (_url, init) =>
        new Promise((_res, rej) =>
          init?.signal?.addEventListener("abort", () => rej(new Error("x"))),
        ),
    );
    const pending = fetchFundingHistory(req({ clock }));
    await Promise.resolve();
    fire?.();
    expect(await pending).toEqual({ kind: "failed", status: null, code: null });
    const aborted = new AbortController();
    aborted.abort();
    expect(await fetchFundingHistory(req({ signal: aborted.signal }))).toMatchObject({
      kind: "failed",
    });
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("forwards the caller's abort to the call in flight", async () => {
    const caller = new AbortController();
    let seen: AbortSignal | undefined;
    apiFetch.mockImplementationOnce((_url, init) => {
      seen = init?.signal ?? undefined;
      return new Promise((_res, rej) => seen?.addEventListener("abort", () => rej(new Error("x"))));
    });
    const pending = fetchFundingHistory(req({ signal: caller.signal }));
    await Promise.resolve();
    expect(seen?.aborted).toBe(false);
    caller.abort();
    expect(seen?.aborted).toBe(true);
    expect(await pending).toEqual({ kind: "failed", status: null, code: null });
  });

  it("stops at MAX_PAGES pages by default and says the read ran out", async () => {
    apiFetch.mockImplementation(() =>
      Promise.resolve(
        json(200, page(BTC.slice(0, 1), { meta: { has_more: true, next_cursor: "c" } })),
      ),
    );
    const out = await fetchFundingHistory(req());
    expect(MAX_PAGES).toBe(10);
    expect(apiFetch).toHaveBeenCalledTimes(10);
    expect(out).toMatchObject({ kind: "ok", truncated: true });
  });

  it("parses coverage's gaps and refuses a malformed span", () => {
    const [from, to] = [BTC[0]?.t ?? "", BTC[2]?.t ?? ""];
    const meta = {
      coverage: coverage({ no_coverage: true, covered_from: from, gaps: [{ from, to }] }),
    };
    expect(parseCoverage(meta)).toMatchObject({
      noCoverage: true,
      gaps: [{ fromMs: Date.parse(from), toMs: Date.parse(to) }],
    });
    expect(parseCoverage({ coverage: coverage({ gaps: [{ from: "x", to: "y" }] }) })).toBeNull();
    expect(parseItem({ predicted: true, funding_rate: "0.0001" })).toEqual({
      predicted: { tMs: null, rate: "0.0001", annualisedPct: null },
    });
  });
});
