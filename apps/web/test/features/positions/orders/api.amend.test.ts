/**
 * E29-S02 PR3a (#912) the amend's write (`amendOrder`) against a fake `fetch` (no network): one
 * field, the golden specimen's body, never a stop, nor a provenance but `placed`, nor a take-profit
 * whose provenance is unread (P3-BQ-1, D-13); `X-Arm-Token` only when the caller holds a non-empty
 * one for the write (P3-BQ-5, N5); one `Idempotency-Key` per amend, re-sent only with the
 * identical request (BQ-8), and a `409 conflict` with `Retry-After` re-sent once on its own count
 * (P3-BQ-6, C-2.10); and the amend's own kinds (`failureOf(res, op)`), the cancel's unchanged.
 */
import { describe, expect, it, vi } from "vitest";
import {
  createOrdersWrites,
  MAX_RESENDS,
  type AmendTarget,
} from "../../../../src/features/positions/orders/api";
import { ETH, golden, STOP, TP } from "./support/orders";

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
const NOT_PROTECTIVE = { kind: null, via: null } as const;
/** A placed entry: no stop, no recorded take-profit. */
const ordinary = (id = ETH): AmendTarget => ({
  id,
  protective: NOT_PROTECTIVE,
  provenance: "placed",
  intent: "entry",
  reduceOnly: false,
});
/** A reduce-only take-profit on WS alone: no read has given its provenance yet (`23` §15.1). */
const unreadTp = (): AmendTarget => ({
  id: TP,
  protective: NOT_PROTECTIVE,
  provenance: null,
  intent: "take_profit",
  reduceOnly: true,
});
const accepted = (lifecycle: string): Response =>
  reply(202, { id: ETH, lifecycle_state: lifecycle, price: "2495.00" });
const conflictOnce = (): Response => problem(409, "conflict", { "Retry-After": "1" });

describe("amendOrder: one field, the golden specimen, never a stop (P3-BQ-1)", () => {
  it("sends PATCH /orders/{id} with the specimen's body, a key and no arm token", async () => {
    const { writes, sent } = writesWith([accepted("amend_pending")]);
    expect(await writes.amendOrder(ordinary(ETH.toUpperCase()), "price", "2495.00")).toEqual({
      kind: "accepted",
      lifecycle: "amend_pending",
    });
    expect(sent).toHaveLength(1);
    expect(sent[0]?.method).toBe("PATCH");
    expect(sent[0]?.path).toBe(`/api/v1/orders/${ETH}`);
    expect(JSON.parse(sent[0]?.body ?? "null")).toEqual(golden("rest_amend_order_request.json"));
    expect([...(sent[0]?.headers.keys() ?? [])]).toEqual(["content-type", "idempotency-key"]);
  });

  it("each field alone; no body carries stop_loss or take_profit (M21)", async () => {
    for (const field of ["price", "trigger_price", "qty"] as const) {
      const { writes, sent } = writesWith([accepted("amend_pending")]);
      await writes.amendOrder(ordinary(), field, "1.5");
      expect(Object.keys(JSON.parse(sent[0]?.body ?? "{}") as object)).toEqual([field]);
      expect(sent[0]?.body).not.toMatch(/stop_loss|take_profit/);
    }
  });

  it("a native stop's or a recorded take-profit's row is refused before any request (D-13, M19)", async () => {
    const { writes, fetch } = writesWith([]);
    const stop: AmendTarget = {
      ...ordinary(STOP),
      protective: { kind: "native_stop", via: "rule" },
      intent: "stop_loss",
      reduceOnly: true,
    };
    const tp: AmendTarget = {
      ...unreadTp(),
      protective: { kind: "recorded_take_profit", via: "provenance" },
      provenance: "recorded_stop",
    };
    expect(await writes.amendOrder(stop, "trigger_price", "63980.0")).toEqual({
      kind: "protected",
    });
    expect(await writes.amendOrder(tp, "price", "64850.0")).toEqual({ kind: "protected" });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("a read provenance other than placed is refused before any request, as exits.py refuses it (M1b)", async () => {
    const { writes, fetch } = writesWith([]);
    const adopted: AmendTarget = { ...ordinary(), provenance: "reconciliation" };
    // a recorded stop the book says has no position: no longer a native stop, still not placed
    const recorded: AmendTarget = {
      ...ordinary(STOP),
      provenance: "recorded_stop",
      intent: "stop_loss",
      reduceOnly: true,
    };
    expect(await writes.amendOrder(adopted, "price", "2495.00")).toEqual({
      kind: "not_amendable",
    });
    expect(await writes.amendOrder(recorded, "trigger_price", "63980.0")).toEqual({
      kind: "not_amendable",
    });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("a reduce-only take-profit whose provenance is unread is refused, fail closed; once read, sent", async () => {
    const { writes, sent } = writesWith([accepted("submitted"), accepted("submitted")]);
    expect(await writes.amendOrder(unreadTp(), "price", "64850.0")).toEqual({ kind: "protected" });
    expect(sent).toHaveLength(0);
    await writes.amendOrder({ ...unreadTp(), provenance: "placed" }, "price", "64850.0");
    await writes.amendOrder({ ...ordinary(), provenance: null }, "price", "2495.00");
    expect(sent.map((s) => s.path)).toEqual([`/api/v1/orders/${TP}`, `/api/v1/orders/${ETH}`]);
  });

  it("an id that is not a UUID, or a value that is no positive decimal, sends nothing", async () => {
    const { writes, fetch } = writesWith([]);
    expect(await writes.amendOrder(ordinary("../cancel-all"), "price", "1")).toEqual({
      kind: "invalid",
    });
    expect(await writes.amendOrder(ordinary(), "qty", "0")).toEqual({ kind: "invalid" });
    expect(await writes.amendOrder(ordinary(), "price", "1e3")).toEqual({ kind: "invalid" });
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("the arm: X-Arm-Token only on the write the caller held one for (P3-BQ-5)", () => {
  it("carries the token it was given, on every send of the request (M11)", async () => {
    const { writes, sent } = writesWith([drop, accepted("amend_pending")]);
    await writes.amendOrder(ordinary(), "price", "2495.00", { arm: "arm-token-1" });
    expect(sent.map((s) => s.headers.get("X-Arm-Token"))).toEqual(["arm-token-1", "arm-token-1"]);
  });

  it("sends none without one (M11)", async () => {
    const { writes, sent } = writesWith([accepted("amend_pending")]);
    await writes.amendOrder(ordinary(), "qty", "0.100", { arm: null });
    expect(sent[0]?.headers.has("X-Arm-Token")).toBe(false);
  });

  it("never an empty X-Arm-Token: an empty string is no token (N5)", async () => {
    const { writes, sent } = writesWith([accepted("amend_pending")]);
    await writes.amendOrder(ordinary(), "price", "2495.00", { arm: "" });
    expect(sent).toHaveLength(1);
    expect(sent[0]?.headers.has("X-Arm-Token")).toBe(false);
  });
});

describe("one key per amend; the same key and bytes only for the same request (BQ-8, C-2.10)", () => {
  it("two amends take two keys (M24)", async () => {
    const { writes, sent } = writesWith([accepted("amend_pending"), accepted("amend_pending")]);
    await writes.amendOrder(ordinary(), "price", "2495.00");
    await writes.amendOrder(ordinary(), "price", "2490.00");
    expect(new Set(sent.map((s) => s.headers.get("Idempotency-Key"))).size).toBe(2);
  });

  it("no answer, a 429 or an in-flight 409 re-send the held request, at most MAX_RESENDS", async () => {
    const { writes, sent, waits } = writesWith([
      drop,
      problem(429, "exchange_rate_limited", { "Retry-After": "2" }),
      accepted("amend_pending"),
    ]);
    expect((await writes.amendOrder(ordinary(), "price", "2495.00")).kind).toBe("accepted");
    expect(sent).toHaveLength(MAX_RESENDS + 1);
    expect(new Set(sent.map((s) => `${s.headers.get("Idempotency-Key")} ${s.body}`)).size).toBe(1);
    expect(waits).toEqual([1_000, 2_000]);
  });
});

describe("a 409 conflict with Retry-After is re-sent exactly once (P3-BQ-6)", () => {
  it("once, after its wait, with the same key and bytes (M14, M16)", async () => {
    const { writes, sent, waits } = writesWith([conflictOnce(), accepted("amend_pending")]);
    expect(await writes.amendOrder(ordinary(), "price", "2495.00", { arm: "t" })).toEqual({
      kind: "accepted",
      lifecycle: "amend_pending",
    });
    expect(sent).toHaveLength(2);
    expect(sent[1]?.headers.get("Idempotency-Key")).toBe(sent[0]?.headers.get("Idempotency-Key"));
    expect(sent[1]?.body).toBe(sent[0]?.body);
    expect(sent[1]?.headers.get("X-Arm-Token")).toBe("t");
    expect(waits).toEqual([1_000]);
  });

  it("never twice: a second conflict is the answer (M15)", async () => {
    const { writes, sent } = writesWith([conflictOnce(), conflictOnce(), accepted("x")]);
    expect(await writes.amendOrder(ordinary(), "price", "2495.00")).toEqual({ kind: "conflict" });
    expect(sent).toHaveLength(2);
  });

  it("on its own count: the transport re-sends after it are still whole", async () => {
    const { writes, sent } = writesWith([conflictOnce(), drop, drop, accepted("amend_pending")]);
    expect((await writes.amendOrder(ordinary(), "price", "2495.00")).kind).toBe("accepted");
    expect(sent).toHaveLength(2 + MAX_RESENDS);
  });

  it.each([
    ["account_unavailable", problem(409, "account_unavailable"), "conflict"],
    [
      "account_unavailable with a wait",
      problem(409, "account_unavailable", { "Retry-After": "1" }),
      "conflict",
    ],
    ["a conflict without Retry-After", problem(409, "conflict"), "conflict"],
    [
      "stop_request_in_flight",
      problem(409, "stop_request_in_flight", { "Retry-After": "1" }),
      "conflict",
    ],
    [
      "a 502",
      reply(502, { code: "exchange_error", exchange: { ret_code: 110007 } }),
      "exchange_refused",
    ],
  ] as const)("never re-sends %s (M17, M18)", async (_, res, kind) => {
    const { writes, sent } = writesWith([res, accepted("amend_pending")]);
    expect(await writes.amendOrder(ordinary(), "price", "2495.00")).toEqual({ kind });
    expect(sent).toHaveLength(1);
  });

  it("a cancel's conflict is never re-sent: the rule is the amend's alone", async () => {
    const { writes, sent } = writesWith([conflictOnce(), reply(202, { id: ETH })]);
    expect(await writes.cancelOrder(ETH)).toEqual({ kind: "conflict" });
    expect(sent).toHaveLength(1);
  });
});

describe("the amend's own kinds (failureOf per operation); fixed kinds, no exchange text", () => {
  it.each([
    ["risk", problem(403, "risk_limit_breached")],
    ["arm_refused", problem(403, "session_not_armed")],
    ["trading_disabled", problem(403, "trading_disabled")],
    ["view_as", problem(403, "view_as_read_only")],
    ["forbidden", problem(403, "insufficient_permission")],
    ["not_amendable", problem(422, "order_not_amendable")],
    ["invalid", problem(422, "validation_failed")],
    ["invalid", problem(400, "validation_failed")],
    ["conflict", problem(412, "version_conflict")],
    ["conflict", problem(409, "idempotency_key_reuse")],
    ["not_found", problem(404, "not_found")],
    ["store_unavailable", problem(503, "store_unavailable", { "Retry-After": "1" })],
    ["unavailable", reply(500, { code: "internal_error" })],
  ])("answers %s, sent once", async (kind, res) => {
    const { writes, sent } = writesWith([res]);
    expect(await writes.amendOrder(ordinary(), "price", "2495.00")).toEqual({ kind });
    expect(sent).toHaveLength(1);
  });

  it("a 502's exchange code never reaches the outcome", async () => {
    const { writes } = writesWith([
      reply(502, {
        code: "exchange_error",
        detail: "EXCHANGE-TEXT",
        exchange: { ret_code: 110007 },
      }),
    ]);
    expect(await writes.amendOrder(ordinary(), "price", "2495.00")).toEqual({
      kind: "exchange_refused",
    });
  });

  it("a 202 whose order is unknown is accepted, never an error; no answer is unavailable", async () => {
    const { writes } = writesWith([accepted("unknown")]);
    expect(await writes.amendOrder(ordinary(), "price", "2495.00")).toEqual({
      kind: "accepted",
      lifecycle: "unknown",
    });
    const silent = writesWith([drop, drop, drop]);
    expect(await silent.writes.amendOrder(ordinary(), "price", "2495.00")).toEqual({
      kind: "unavailable",
    });
  });

  it("a cancel's 403 risk_limit_breached is still the native stop's", async () => {
    const { writes } = writesWith([problem(403, "risk_limit_breached")]);
    expect(await writes.cancelOrder(STOP)).toEqual({ kind: "native_stop" });
  });
});
