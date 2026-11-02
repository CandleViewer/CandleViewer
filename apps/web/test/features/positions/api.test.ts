/** E29-S01 (#911) `positionsApi` against a stubbed `apiFetch` (no network); bodies as the server answers. */
import { afterEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import {
  MAX_ACCOUNT_IDS,
  positionsApi,
  positionsSearch,
} from "../../../src/features/positions/api";
import { golden, MAIN, SUB1 } from "./support/fakes";

const reply = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
const problem = (status: number, code: string): Response =>
  reply(status, {
    type: `https://candleviewer.local/errors/${code}`,
    title: "x",
    status,
    code,
    detail: "server detail never shown",
  });

afterEach(() => vi.clearAllMocks());

describe("positionsSearch", () => {
  it("repeats exchange_account_ids (22: explode) and sets aggregate only when asked", () => {
    expect(positionsSearch()).toBe("");
    expect(positionsSearch({ accountIds: [MAIN, SUB1], aggregate: true })).toBe(
      `?exchange_account_ids=${MAIN}&exchange_account_ids=${SUB1}&aggregate=true`,
    );
    expect(positionsSearch({ aggregate: false })).toBe("");
  });

  it("refuses more than 25 accounts (22 AccountIdsQuery.maxItems)", () => {
    expect(() =>
      positionsSearch({ accountIds: Array.from({ length: MAX_ACCOUNT_IDS + 1 }, () => MAIN) }),
    ).toThrow(RangeError);
  });
});

describe("listPositions", () => {
  it("reads the items and the aggregates (the ?aggregate=true golden)", async () => {
    const body = golden<{ items: unknown[]; aggregates: unknown[] }>(
      "rest_list_positions_aggregate.json",
    );
    apiFetch.mockResolvedValueOnce(reply(200, body));
    const abort = new AbortController();
    const out = await positionsApi.listPositions({ aggregate: true }, abort.signal);
    expect(out).toMatchObject({ kind: "ok", items: body.items, aggregates: body.aggregates });
    expect(apiFetch).toHaveBeenCalledWith("/api/v1/positions?aggregate=true", {
      signal: abort.signal,
    });
  });

  it("a body without aggregates reads as none", async () => {
    apiFetch.mockResolvedValueOnce(reply(200, { items: [] }));
    expect(await positionsApi.listPositions()).toEqual({ kind: "ok", items: [], aggregates: [] });
    expect(apiFetch).toHaveBeenCalledWith("/api/v1/positions", undefined);
  });

  it.each([
    [problem(403, "account_scope_denied"), "account_scope_denied"],
    [problem(403, "forbidden"), "forbidden"],
    [reply(403, "not json"), "forbidden"],
    [problem(400, "validation_failed"), "invalid"],
    [problem(503, "store_unavailable"), "unavailable"],
    [reply(200, { items: "x" }), "unavailable"],
    [reply(200, { items: [], aggregates: [1] }), "unavailable"],
  ])("%#: the answer reads %s, never the server's detail", async (res, kind) => {
    apiFetch.mockResolvedValueOnce(res);
    expect(await positionsApi.listPositions({ accountIds: [MAIN] })).toEqual({ kind });
  });

  it("no answer is unavailable", async () => {
    apiFetch.mockRejectedValueOnce(new TypeError("network"));
    expect(await positionsApi.listPositions()).toEqual({ kind: "unavailable" });
  });
});

describe("listExchangeAccounts", () => {
  it("follows next_cursor across pages, with the balance for the first-paint MM rate", async () => {
    apiFetch.mockResolvedValueOnce(
      reply(200, { items: [{ id: MAIN }], meta: { has_more: true, next_cursor: "c 2" } }),
    );
    apiFetch.mockResolvedValueOnce(
      reply(200, { items: [{ id: SUB1 }], meta: { has_more: false, next_cursor: null } }),
    );
    expect(await positionsApi.listExchangeAccounts()).toEqual({
      kind: "ok",
      items: [{ id: MAIN }, { id: SUB1 }],
    });
    expect(apiFetch.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/exchange-accounts?limit=500",
      "/api/v1/exchange-accounts?limit=500&cursor=c%202",
    ]);
  });

  it("stops at the page cap even when the server keeps saying has_more", async () => {
    apiFetch.mockImplementation(async () =>
      reply(200, { items: [], meta: { has_more: true, next_cursor: "again" } }),
    );
    expect(await positionsApi.listExchangeAccounts()).toEqual({ kind: "ok", items: [] });
    expect(apiFetch).toHaveBeenCalledTimes(10);
    apiFetch.mockReset();
  });

  it.each([
    [problem(403, "forbidden"), "forbidden"],
    [problem(503, "x"), "unavailable"],
    [reply(200, { meta: {} }), "unavailable"],
  ])("%#: %s", async (res, kind) => {
    apiFetch.mockResolvedValueOnce(res);
    expect(await positionsApi.listExchangeAccounts()).toEqual({ kind });
  });

  it("passes the caller's abort signal, and no answer is unavailable", async () => {
    const abort = new AbortController();
    apiFetch.mockResolvedValueOnce(reply(200, golden("rest_list_exchange_accounts.json")));
    await positionsApi.listExchangeAccounts(abort.signal);
    expect(apiFetch.mock.calls[0]?.[1]).toEqual({ signal: abort.signal });
    apiFetch.mockRejectedValueOnce(new TypeError("network"));
    expect(await positionsApi.listExchangeAccounts()).toEqual({ kind: "unavailable" });
  });
});
