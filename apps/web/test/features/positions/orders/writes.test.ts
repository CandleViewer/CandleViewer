/**
 * E29-S02 PR2 (#912) the cancel writes (`createOrdersWrites`) against a fake `fetch` (no network):
 * one `Idempotency-Key` per request body, re-sent only with the identical request after a transport
 * failure, a `409 idempotency_in_flight` or a `429` (BQ-8); never an arm token (R5, C-2.6); every
 * answer a fixed kind, no server message, `detail` or `exchange_ret_code` passed on (BQ-2).
 */
import { describe, expect, it, vi } from "vitest";
import {
  createOrdersWrites,
  MAX_RESEND_WAIT_MS,
  MAX_RESENDS,
  RESEND_WAIT_MS,
  type CancelAllRequest,
} from "../../../../src/features/positions/orders/api";
import { ETH, golden, MAIN, STOP, SUB1 } from "./support/orders";

const reply = (status: number, body?: unknown, headers: Record<string, string> = {}): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status, headers });
const problem = (status: number, code: string, headers: Record<string, string> = {}): Response =>
  reply(
    status,
    { type: `https://candleviewer.local/errors/${code}`, title: "x", status, code, detail: "d" },
    headers,
  );

interface Sent {
  readonly path: string;
  readonly method: string;
  readonly headers: Headers;
  readonly body: string | null;
}

/** A writes client whose `fetch` answers from `answers` in order (a function throws: no answer). */
function writesWith(answers: readonly (Response | (() => never))[]) {
  const sent: Sent[] = [];
  const waits: number[] = [];
  let keys = 0;
  const queue = [...answers];
  const fetch = vi.fn(async (path: string, init: RequestInit): Promise<Response> => {
    sent.push({
      path,
      method: init.method ?? "GET",
      headers: new Headers(init.headers),
      body: typeof init.body === "string" ? init.body : null,
    });
    const next = queue.shift();
    if (next === undefined) throw new Error("no answer queued");
    if (typeof next === "function") next();
    return next as Response;
  });
  const writes = createOrdersWrites({
    fetch,
    newKey: () => `00000000-0000-4000-8000-${String((keys += 1)).padStart(12, "0")}`,
    sleep: async (ms) => {
      waits.push(ms);
    },
  });
  return { writes, sent, waits, fetch };
}

const drop = (): never => {
  throw new TypeError("Failed to fetch");
};
const CANCEL_ALL: CancelAllRequest = {
  exchange_account_ids: [MAIN, SUB1],
  symbol: null,
  intents: [],
  exclude_reduce_only: true,
};

describe("cancelOrder", () => {
  it("sends DELETE /orders/{id} with an Idempotency-Key and no arm token (R5, C-2.6)", async () => {
    const order = { id: ETH, lifecycle_state: "cancel_pending" };
    const { writes, sent } = writesWith([reply(202, order)]);
    expect(await writes.cancelOrder(ETH.toUpperCase())).toEqual({
      kind: "accepted",
      lifecycle: "cancel_pending",
    });
    expect(sent).toHaveLength(1);
    expect(sent[0]?.method).toBe("DELETE");
    expect(sent[0]?.path).toBe(`/api/v1/orders/${ETH}`);
    expect(sent[0]?.headers.get("Idempotency-Key")).toBe("00000000-0000-4000-8000-000000000001");
    expect(sent[0]?.headers.has("X-Arm-Token")).toBe(false);
    expect([...(sent[0]?.headers.keys() ?? [])]).toEqual(["idempotency-key"]);
    expect(sent[0]?.body).toBeNull();
  });

  it("a 202 with the order unknown (a 110001) is accepted, never an error (BQ-3)", async () => {
    const { writes } = writesWith([reply(202, { id: ETH, lifecycle_state: "unknown" })]);
    expect(await writes.cancelOrder(ETH)).toEqual({ kind: "accepted", lifecycle: "unknown" });
  });

  it("refuses an id that is not a UUID without sending anything", async () => {
    const { writes, fetch } = writesWith([]);
    expect(await writes.cancelOrder("../positions/close-all")).toEqual({ kind: "invalid" });
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each([
    ["native_stop", problem(403, "risk_limit_breached")],
    ["forbidden", problem(403, "account_scope_denied")],
    ["forbidden", problem(403, "view_as_read_only")],
    ["conflict", problem(409, "conflict")],
    ["conflict", problem(409, "account_unavailable")],
    ["conflict", problem(409, "idempotency_key_reuse")],
    ["exchange_refused", reply(502, { code: "exchange_error", exchange: { ret_code: 110001 } })],
    ["store_unavailable", problem(503, "store_unavailable", { "Retry-After": "1" })],
    ["unavailable", problem(503, "oms_not_ready")],
    ["not_found", problem(404, "not_found")],
    ["invalid", problem(400, "validation_failed")],
    ["unavailable", reply(501, { code: "not_implemented" })],
  ])("answers %s for a refusal, sent once and never re-sent", async (kind, res) => {
    const { writes, sent } = writesWith([res]);
    expect(await writes.cancelOrder(STOP)).toEqual({ kind });
    expect(sent).toHaveLength(1);
  });
});

describe("one Idempotency-Key per request body (BQ-8)", () => {
  it("re-sends the identical request with the same key after a 429, waiting its Retry-After", async () => {
    const { writes, sent, waits } = writesWith([
      problem(429, "rate_limited", { "Retry-After": "2" }),
      reply(202, { id: ETH, lifecycle_state: "cancel_pending" }),
    ]);
    expect((await writes.cancelOrder(ETH)).kind).toBe("accepted");
    expect(sent.map((s) => s.headers.get("Idempotency-Key"))).toEqual([
      "00000000-0000-4000-8000-000000000001",
      "00000000-0000-4000-8000-000000000001",
    ]);
    expect(waits).toEqual([2_000]);
  });

  it("re-sends with the same key after 409 idempotency_in_flight and after no answer", async () => {
    const { writes, sent, waits } = writesWith([
      problem(409, "idempotency_in_flight", { "Retry-After": "1" }),
      drop,
      reply(202, {}),
    ]);
    expect(await writes.cancelOrder(ETH)).toEqual({ kind: "accepted", lifecycle: null });
    expect(new Set(sent.map((s) => s.headers.get("Idempotency-Key"))).size).toBe(1);
    expect(sent.map((s) => s.path)).toEqual(Array(3).fill(`/api/v1/orders/${ETH}`));
    expect(waits).toEqual([1_000, RESEND_WAIT_MS]);
  });

  it(`stops after ${MAX_RESENDS} re-sends: busy, or unavailable when nothing answered`, async () => {
    const busy = writesWith([
      problem(429, "exchange_rate_limited", { "Retry-After": "60" }),
      problem(429, "exchange_rate_limited", { "Retry-After": "60" }),
      problem(429, "exchange_rate_limited", { "Retry-After": "60" }),
    ]);
    expect(await busy.writes.cancelOrder(ETH)).toEqual({ kind: "busy" });
    expect(busy.sent).toHaveLength(MAX_RESENDS + 1);
    expect(busy.waits).toEqual([MAX_RESEND_WAIT_MS, MAX_RESEND_WAIT_MS]);
    const silent = writesWith([drop, drop, drop]);
    expect(await silent.writes.cancelOrder(ETH)).toEqual({ kind: "unavailable" });
    expect(silent.sent).toHaveLength(MAX_RESENDS + 1);
  });

  it("each call is a new request with a new key: Retry failed never replays the first", async () => {
    const { writes, sent } = writesWith([reply(502, {}), reply(202, {})]);
    expect(await writes.cancelOrder(ETH)).toEqual({ kind: "exchange_refused" });
    expect((await writes.cancelOrder(ETH)).kind).toBe("accepted");
    expect(sent.map((s) => s.headers.get("Idempotency-Key"))).toEqual([
      "00000000-0000-4000-8000-000000000001",
      "00000000-0000-4000-8000-000000000002",
    ]);
  });

  it("an aborted call is not re-sent", async () => {
    const abort = new AbortController();
    const { writes, sent } = writesWith([
      () => {
        abort.abort();
        throw new DOMException("aborted", "AbortError");
      },
    ]);
    expect(await writes.cancelOrder(ETH, abort.signal)).toEqual({ kind: "unavailable" });
    expect(sent).toHaveLength(1);
  });
});

describe("cancelAllOrders", () => {
  it("posts the CancelAllRequest as sent, its own key, no arm token", async () => {
    const answer = golden("rest_cancel_all_partial.json");
    const { writes, sent } = writesWith([reply(200, answer)]);
    const out = await writes.cancelAllOrders(CANCEL_ALL);
    expect(out.kind).toBe("ok");
    expect(sent[0]?.method).toBe("POST");
    expect(sent[0]?.path).toBe("/api/v1/orders/cancel-all");
    expect(JSON.parse(sent[0]?.body ?? "null")).toEqual(CANCEL_ALL);
    expect(sent[0]?.headers.get("Content-Type")).toBe("application/json");
    expect(sent[0]?.headers.get("Idempotency-Key")).toMatch(/^0{8}-0{4}-4000-8000-0+1$/);
    expect(sent[0]?.headers.has("X-Arm-Token")).toBe(false);
  });

  it("reads each account's result for its code and retryable only, never its message (SR-E29-09)", async () => {
    const { writes } = writesWith([reply(200, golden("rest_cancel_all_partial.json"))]);
    const out = await writes.cancelAllOrders(CANCEL_ALL);
    if (out.kind !== "ok") throw new Error(out.kind);
    expect(out.results.map((r) => [r.accountId.slice(-1), r.ok, r.affected, r.code])).toEqual([
      ["1", true, 4, null],
      ["2", true, 2, null],
      ["3", false, 0, "exchange_unavailable"],
      ["4", true, 3, null],
      ["5", false, 1, "timeout"],
    ]);
    expect(JSON.stringify(out)).not.toMatch(/message|exchange_ret_code|Exchange connectivity/);
  });

  it("a whole-request refusal is one fixed kind; a 409 in flight is re-sent with its key", async () => {
    const refused = writesWith([problem(403, "account_scope_denied")]);
    expect(await refused.writes.cancelAllOrders(CANCEL_ALL)).toEqual({ kind: "forbidden" });
    const inFlight = writesWith([
      problem(409, "idempotency_in_flight", { "Retry-After": "1" }),
      reply(200, { results: [], requested: 0, succeeded: 0 }),
    ]);
    expect(await inFlight.writes.cancelAllOrders(CANCEL_ALL)).toEqual({ kind: "ok", results: [] });
    const keys = inFlight.sent.map((s) => s.headers.get("Idempotency-Key"));
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
    expect(inFlight.sent[0]?.body).toBe(inFlight.sent[1]?.body);
  });

  it("a 200 without results, or one that is not JSON, is unavailable", async () => {
    const { writes } = writesWith([reply(200, { requested: 2 }), new Response("<html>")]);
    expect(await writes.cancelAllOrders(CANCEL_ALL)).toEqual({ kind: "unavailable" });
    expect(await writes.cancelAllOrders(CANCEL_ALL)).toEqual({ kind: "unavailable" });
  });
});
