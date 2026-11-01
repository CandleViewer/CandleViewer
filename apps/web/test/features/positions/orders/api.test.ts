/** E29-S02 (#912) `ordersApi`'s reads against a stubbed `apiFetch` (no network), bodies as the server answers. */
import { afterEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { MAX_ACCOUNT_IDS } from "../../../../src/features/positions/api";
import {
  MAX_PAGES,
  ordersApi,
  ordersSearch,
  PAGE,
} from "../../../../src/features/positions/orders/api";
import { exchangeAccounts, golden, MAIN, SUB1 } from "./support/orders";

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
const page = (items: unknown[], next: string | null) =>
  reply(200, { items, meta: { next_cursor: next, has_more: next !== null, count: items.length } });

afterEach(() => vi.clearAllMocks());

describe("ordersSearch", () => {
  it("asks for the open set, a page of 500, and repeats exchange_account_ids (22: explode)", () => {
    expect(PAGE).toBe(500);
    expect(ordersSearch({ openOnly: true })).toBe("?open_only=true&limit=500");
    expect(ordersSearch({ accountIds: [MAIN, SUB1], openOnly: true }, "c-2")).toBe(
      `?exchange_account_ids=${MAIN}&exchange_account_ids=${SUB1}&open_only=true&limit=500&cursor=c-2`,
    );
    expect(ordersSearch()).toBe("?limit=500");
  });

  it("refuses more than 25 accounts (22 AccountIdsQuery.maxItems)", () => {
    expect(() =>
      ordersSearch({ accountIds: Array.from({ length: MAX_ACCOUNT_IDS + 1 }, () => MAIN) }),
    ).toThrow(RangeError);
  });
});

describe("listOrders", () => {
  it("reads the open orders, held and untracked included (the golden)", async () => {
    const body = golden<{ items: unknown[] }>("rest_list_orders_open.json");
    apiFetch.mockResolvedValueOnce(reply(200, body));
    const abort = new AbortController();
    const out = await ordersApi.listOrders({ openOnly: true }, abort.signal);
    expect(out).toEqual({ kind: "ok", items: body.items, truncated: false });
    expect(apiFetch).toHaveBeenCalledWith("/api/v1/orders?open_only=true&limit=500", {
      signal: abort.signal,
    });
  });

  it("follows the cursor, and stops at MAX_PAGES (bounded, C-2.18)", async () => {
    apiFetch.mockResolvedValueOnce(page([{ id: "1" }], "c-1"));
    apiFetch.mockResolvedValueOnce(page([{ id: "2" }], null));
    expect(await ordersApi.listOrders()).toEqual({
      kind: "ok",
      items: [{ id: "1" }, { id: "2" }],
      truncated: false,
    });
    expect(apiFetch.mock.calls[1]?.[0]).toBe("/api/v1/orders?limit=500&cursor=c-1");
    expect(apiFetch.mock.calls[1]?.[1]).toBeUndefined();
    apiFetch.mockReset();
    apiFetch.mockImplementation(async () => page([{ id: "x" }], "again"));
    const capped = await ordersApi.listOrders();
    expect(capped).toMatchObject({ kind: "ok", truncated: true });
    expect(apiFetch).toHaveBeenCalledTimes(MAX_PAGES);
  });

  it.each([
    [problem(403, "account_scope_denied"), "account_scope_denied"],
    [problem(403, "forbidden"), "forbidden"],
    [reply(403, "not json"), "forbidden"],
    [problem(400, "validation_failed"), "invalid"],
    [problem(503, "store_unavailable"), "unavailable"],
    [problem(401, "unauthenticated"), "unavailable"],
    [reply(200, { items: "nope" }), "unavailable"],
    [reply(200, { items: [1] }), "unavailable"],
  ])("answers a fixed kind, never the server's detail (%#)", async (response, kind) => {
    apiFetch.mockResolvedValueOnce(response);
    expect(await ordersApi.listOrders({ openOnly: true })).toEqual({ kind });
  });

  it("a fetch that throws (an abort, the network) is unavailable", async () => {
    apiFetch.mockRejectedValueOnce(new DOMException("aborted", "AbortError"));
    expect(await ordersApi.listOrders()).toEqual({ kind: "unavailable" });
  });
});

describe("listExchangeAccounts", () => {
  it("is the Positions tab's directory read", async () => {
    apiFetch.mockResolvedValueOnce(
      reply(200, { items: exchangeAccounts(), meta: { next_cursor: null, has_more: false } }),
    );
    expect(await ordersApi.listExchangeAccounts()).toEqual({
      kind: "ok",
      items: exchangeAccounts(),
    });
    expect(apiFetch.mock.calls[0]?.[0]).toBe("/api/v1/exchange-accounts?limit=500");
  });
});
