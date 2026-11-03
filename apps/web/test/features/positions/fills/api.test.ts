/**
 * E29-S04 (#979) `fillsApi` against a stubbed `apiFetch` (no network), bodies as the shipped
 * mappers wrote them: `listExecutions`' query and pages, `getOrder?include_events=true`,
 * `getTradeGroup`, `getInstrument` and its per-symbol tick cache; every failure a fixed kind,
 * never the server's detail.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import {
  createTickCache,
  executionsSearch,
  fillsApi,
  readExecutions,
  type FillsApi,
} from "../../../../src/features/positions/fills/api";
import { MAX_ACCOUNT_IDS } from "../../../../src/features/positions/api";
import { MAIN, SUB1 } from "../support/fakes";
import { golden, GROUP_7C1E, order, ORDER_A3F2 } from "./support/fills";

const reply = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
const problem = (status: number, code: string): Response =>
  reply(status, { type: `https://candleviewer.local/errors/${code}`, status, code, detail: "x" });

afterEach(() => vi.clearAllMocks());

describe("executionsSearch", () => {
  it("repeats exchange_account_ids (22: explode) and names every filter, 500 a page by default", () => {
    expect(executionsSearch({ accountIds: [MAIN, SUB1] })).toBe(
      `?exchange_account_ids=${MAIN}&exchange_account_ids=${SUB1}&limit=500`,
    );
    expect(
      executionsSearch(
        {
          symbol: "BTCUSDT",
          orderId: ORDER_A3F2,
          tradeGroupId: GROUP_7C1E,
          from: "2026-10-22T13:58:02Z",
          to: "2026-10-22T14:03:40.001Z",
        },
        { cursor: "c 2", limit: 100 },
      ),
    ).toBe(
      `?symbol=BTCUSDT&order_id=${ORDER_A3F2}&trade_group_id=${GROUP_7C1E}&from=2026-10-22T13%3A58%3A02Z&to=2026-10-22T14%3A03%3A40.001Z&cursor=c+2&limit=100`,
    );
  });

  it("refuses more than 25 accounts and a limit outside 1 to 500", () => {
    const ids = Array.from({ length: MAX_ACCOUNT_IDS + 1 }, () => MAIN);
    expect(() => executionsSearch({ accountIds: ids })).toThrow(RangeError);
    expect(() => executionsSearch({}, { limit: 0 })).toThrow(RangeError);
    expect(() => executionsSearch({}, { limit: 501 })).toThrow(RangeError);
  });
});

describe("listExecutions", () => {
  it("reads the golden page, passing the caller's signal", async () => {
    const body = golden<{ items: unknown[] }>("rest_list_executions.json");
    apiFetch.mockResolvedValueOnce(reply(200, body));
    const abort = new AbortController();
    const out = await fillsApi.listExecutions({}, {}, abort.signal);
    expect(out).toEqual({
      kind: "ok",
      value: { items: body.items, nextCursor: null, hasMore: false },
    });
    expect(apiFetch).toHaveBeenCalledWith("/api/v1/executions?limit=500", {
      signal: abort.signal,
    });
  });

  it("a page with more names its cursor", async () => {
    apiFetch.mockResolvedValueOnce(
      reply(200, { items: [], meta: { has_more: true, next_cursor: "n", count: 0 } }),
    );
    expect(await fillsApi.listExecutions({})).toEqual({
      kind: "ok",
      value: { items: [], nextCursor: "n", hasMore: true },
    });
  });

  it.each([
    [problem(403, "account_scope_denied"), "account_scope_denied"],
    [problem(403, "forbidden"), "forbidden"],
    [reply(403, "not json"), "forbidden"],
    [problem(400, "invalid_cursor"), "invalid_cursor"],
    [problem(400, "validation_failed"), "invalid"],
    [problem(404, "not_found"), "not_found"],
    [problem(503, "store_unavailable"), "unavailable"],
    [reply(200, { items: "x", meta: {} }), "unavailable"],
    [reply(200, { items: [1], meta: {} }), "unavailable"],
    [reply(200, { items: [] }), "unavailable"],
  ])("%#: the answer reads %s, never the server's detail", async (res, kind) => {
    apiFetch.mockResolvedValueOnce(res);
    expect(await fillsApi.listExecutions({ accountIds: [MAIN] })).toEqual({ kind });
  });

  it("no answer is unavailable", async () => {
    apiFetch.mockRejectedValueOnce(new TypeError("network"));
    expect(await fillsApi.listExecutions({})).toEqual({ kind: "unavailable" });
  });
});

describe("getOrder, getTradeGroup, getInstrument", () => {
  it("getOrder asks for the events (BQ-8) and returns the body", async () => {
    apiFetch.mockResolvedValueOnce(reply(200, order("amended")));
    expect(await fillsApi.getOrder(order("amended").id ?? "")).toEqual({
      kind: "ok",
      value: order("amended"),
    });
    expect(apiFetch.mock.calls[0]?.[0]).toBe(
      `/api/v1/orders/${order("amended").id ?? ""}?include_events=true`,
    );
  });

  it("an id that is no UUID is refused before any request", async () => {
    expect(await fillsApi.getOrder("../admin")).toEqual({ kind: "invalid" });
    expect(await fillsApi.getTradeGroup("x")).toEqual({ kind: "invalid" });
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("getTradeGroup and getInstrument read their paths; 404 is not_found", async () => {
    apiFetch.mockResolvedValueOnce(problem(404, "not_found"));
    expect(await fillsApi.getTradeGroup(GROUP_7C1E)).toEqual({ kind: "not_found" });
    apiFetch.mockResolvedValueOnce(reply(200, { symbol: "BTCUSDT", tick_size: "0.1" }));
    expect(await fillsApi.getInstrument("BTC/USDT")).toMatchObject({ kind: "ok" });
    expect(apiFetch.mock.calls.map(([url]) => url)).toEqual([
      `/api/v1/trade-groups/${GROUP_7C1E}`,
      "/api/v1/instruments/BTC%2FUSDT",
    ]);
  });
});

function pagedApi(pages: number): FillsApi & { cursors: (string | undefined)[] } {
  const cursors: (string | undefined)[] = [];
  return {
    cursors,
    listExecutions: vi.fn(async (_query, page) => {
      cursors.push(page?.cursor);
      const n = cursors.length;
      return {
        kind: "ok" as const,
        value: {
          items: [{ is_paper: false, exec_id: `e${n}` }],
          nextCursor: `c${n}`,
          hasMore: n < pages,
        },
      };
    }),
    getOrder: vi.fn(),
    getTradeGroup: vi.fn(),
    getInstrument: vi.fn(),
  };
}

describe("readExecutions", () => {
  it("follows next_cursor, at most maxPages, and says whether more remain", async () => {
    const api = pagedApi(5);
    const out = await readExecutions(api, { accountIds: [MAIN] }, 2);
    expect(out).toMatchObject({ kind: "ok", value: { complete: false } });
    expect(api.cursors).toEqual([undefined, "c1"]);
    const done = await readExecutions(pagedApi(1), {}, 2);
    expect(done).toMatchObject({ kind: "ok", value: { complete: true, failure: null } });
  });

  it("a failed first page is the read's failure", async () => {
    const api = pagedApi(5);
    vi.mocked(api.listExecutions).mockResolvedValueOnce({ kind: "invalid_cursor" });
    expect(await readExecutions(api, {}, 2)).toEqual({ kind: "invalid_cursor" });
  });

  it("a failed later page keeps the pages before it: not complete, its failure named", async () => {
    const api = pagedApi(5);
    const items = [{ is_paper: false, exec_id: "e1" }];
    vi.mocked(api.listExecutions)
      .mockResolvedValueOnce({ kind: "ok", value: { items, nextCursor: "c1", hasMore: true } })
      .mockResolvedValueOnce({ kind: "unavailable" });
    expect(await readExecutions(api, {}, 3)).toEqual({
      kind: "ok",
      value: { items, complete: false, failure: "unavailable" },
    });
  });
});

describe("the tick cache (BQ-8)", () => {
  it("reads a symbol's tick once; a failed read is not kept; it holds a bounded number", async () => {
    const getInstrument = vi
      .fn<FillsApi["getInstrument"]>()
      .mockResolvedValueOnce({ kind: "unavailable" })
      .mockResolvedValue({ kind: "ok", value: { symbol: "BTCUSDT", tick_size: "0.1" } } as never);
    const tick = createTickCache({ getInstrument }, 2);
    expect(await tick("BTCUSDT")).toBeNull();
    expect(await tick("BTCUSDT")).toBe("0.1");
    expect(await tick("BTCUSDT")).toBe("0.1");
    expect(getInstrument).toHaveBeenCalledTimes(2);
    await tick("ETHUSDT");
    await tick("SOLUSDT"); // past the bound: BTCUSDT, the oldest, is read again
    await tick("BTCUSDT");
    expect(getInstrument).toHaveBeenCalledTimes(5);
  });
});
