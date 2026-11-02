/**
 * E29-S02 PR2 (#912) S-36's orders half (`model/bulk.ts`; BQ-4, BQ-8; D02 §8.3, §8.5): no native-stop
 * row is ever a target or sent (C-2.6), the route (`cancelAllOrders` only where it cancels exactly
 * the targets), the partial-failure reducer (the ticket's test plan) with the "Cancel-all partial
 * failure" scenario on the shipped mapper's 3-of-5 golden, Retry failed, and the dialog's words.
 */
import { describe, expect, it, vi } from "vitest";
import type { FilterChip } from "../../../../src/features/positions/model/filters";
import {
  createOrdersWrites,
  type CancelOutcome,
  type OrdersWrites,
} from "../../../../src/features/positions/orders/api";
import {
  countText,
  excludedLines,
  exclusionOf,
  fromRows,
  lineText,
  MAX_IN_FLIGHT,
  planAllInView,
  planSelected,
  regate,
  retryPlan,
  routeFor,
  runPlan,
  type BulkResult,
} from "../../../../src/features/positions/orders/model/bulk";
import {
  cancelGate,
  type CancelContext,
} from "../../../../src/features/positions/orders/model/gates";
import {
  mapOrder,
  type OrderConstants,
  type OrderRowModel,
} from "../../../../src/features/positions/orders/model/orderRow";
import {
  COND,
  directory,
  ENTRY,
  ETH,
  golden,
  MAIN,
  snapshotBody,
  STOP,
  SUB1,
  SUB2,
  SUB3,
  SUB4,
  TP,
  wsItem,
} from "./support/orders";

const CONTEXT: CancelContext = {
  viewAs: null,
  permissions: ["orders:write"],
  readOnlyAccounts: new Set(),
  restReachable: true,
  cancelling: new Set(),
  killSwitch: { state: "unknown" },
  lockedAccounts: new Set(),
};
const gateOf = (r: OrderRowModel) => cancelGate(r, CONTEXT);
const PLACED: OrderConstants = { createdAtMs: null, provenance: "placed", tradeGroupId: null };
const LABELS: Readonly<Record<string, string>> = {
  [MAIN]: "Main",
  [SUB1]: "Sub-1",
  [SUB2]: "Sub-2",
  [SUB3]: "Sub-3",
  [SUB4]: "Sub-4",
};
const words = (accountId: string) => ({ label: LABELS[accountId] ?? "?", environment: "LIVE" });

function row(
  id: string,
  wire: Record<string, unknown> = {},
  constants: OrderConstants = PLACED,
): OrderRowModel {
  const item = { ...wsItem(snapshotBody(), id), ...wire };
  const mapped = mapOrder(item as never, "ws", directory(), constants);
  if (mapped === null) throw new Error(`no row for ${id}`);
  return mapped;
}

/** The golden snapshot's five rows, D02 §6.2's: the take-profit, two entries, ETH and the native stop. */
const book = (): OrderRowModel[] => [
  row(TP),
  row(ENTRY),
  row(COND),
  row(ETH),
  row(STOP, {}, { ...PLACED, provenance: "recorded_stop" }),
];

/** A placed entry on `account` (the 3-of-5 golden's five accounts each hold one). */
const entryOn = (account: string, n: number): OrderRowModel =>
  row(ENTRY, {
    id: `0e000000-0000-4000-8000-0000000001${String(n).padStart(2, "0")}`,
    exchange_account_id: account,
  });

/** Writes that record every request and answer from `answer`. */
function recording(
  answer: (id: string) => CancelOutcome = () => ({
    kind: "accepted",
    lifecycle: "cancel_pending",
  }),
) {
  const cancelled: string[] = [];
  const writes: OrdersWrites = {
    cancelOrder: vi.fn(async (id: string) => {
      cancelled.push(id);
      return answer(id);
    }),
    cancelAllOrders: vi.fn(async () => ({ kind: "ok" as const, results: [] })),
  };
  return { writes, cancelled };
}

describe("no native-stop row is ever sent (C-2.6, BQ-4)", () => {
  it("Cancel selected over the whole book: the stop is counted out, never a target", async () => {
    const plan = planSelected(book(), gateOf);
    expect(plan.targets.map((r) => r.id)).not.toContain(STOP);
    expect(plan.excluded).toEqual({ native_stop: 1, recorded_take_profit: 0, other: 0 });
    const { writes, cancelled } = recording();
    await runPlan(plan, writes);
    expect(cancelled).toEqual([TP, ENTRY, COND, ETH]);
    expect(cancelled).not.toContain(STOP);
  });

  it("Cancel all in view: per row (a reduce-only target), and still no stop", async () => {
    const plan = planAllInView(book(), [], gateOf);
    expect(plan.route).toEqual({ kind: "per_row" });
    const { writes, cancelled } = recording();
    await runPlan(plan, writes);
    expect(cancelled).not.toContain(STOP);
    expect(writes.cancelAllOrders).not.toHaveBeenCalled();
  });

  it("a stop is skipped whatever its gate says, even one a row's own reason no longer covers", () => {
    const stop = row(STOP, {}, { ...PLACED, provenance: "recorded_stop" });
    expect(exclusionOf(stop, { kind: "allowed" })).toBe("native_stop");
    expect(exclusionOf(stop, { kind: "busy" })).toBe("native_stop");
  });

  it("an orphan stop (its position known closed) cancels like any order (D01 D7)", () => {
    const orphan = { ...row(STOP), protective: { kind: null, via: null } } as OrderRowModel;
    expect(exclusionOf(orphan, gateOf(orphan))).toBeNull();
  });

  it("a recorded take-profit is left out on its own line, never cancelOrder (BQ-5)", () => {
    const tp = row(TP, {}, { ...PLACED, provenance: "recorded_stop" });
    const plan = planSelected([tp, row(ENTRY)], gateOf);
    expect(plan.targets.map((r) => r.id)).toEqual([ENTRY]);
    expect(plan.excluded.recorded_take_profit).toBe(1);
  });

  it("rows that cannot be cancelled now are counted, not sent", () => {
    const plan = planSelected(
      [
        row(ENTRY, { lifecycle_state: "held" }),
        row(COND, { lifecycle_state: "cancel_pending" }),
        row(ETH, { lifecycle_state: "filled" }),
      ],
      gateOf,
    );
    expect(plan.targets).toEqual([]);
    expect(plan.excluded.other).toBe(3);
  });
});

describe("Confirm re-gates the plan (C-2.6, BQ-4; code M1)", () => {
  /** A stop whose position the book knows closed: an ordinary order, cancellable (D01 D7). */
  const orphan = (): OrderRowModel =>
    ({ ...row(STOP), protective: { kind: null, via: null } }) as OrderRowModel;

  it("a stop whose position opened since the press is dropped, counted, and never sent", async () => {
    const pressed = planAllInView([row(ENTRY), orphan()], [], gateOf);
    expect(pressed.targets.map((r) => r.id)).toEqual([ENTRY, STOP]);
    // the position opens while the dialog is up: the same order is a native stop now
    const now = [row(ENTRY), row(STOP, {}, { ...PLACED, provenance: "recorded_stop" })];
    const sent = regate(pressed, now, [], gateOf);
    expect(sent.targets.map((r) => r.id)).toEqual([ENTRY]);
    expect(sent.excluded).toEqual({ native_stop: 1, recorded_take_profit: 0, other: 0 });
    expect(excludedLines(sent.excluded)).toEqual([
      "1 native-stop order is not included: every position keeps a native stop.",
    ]);
    const { writes, cancelled } = recording();
    await runPlan(sent, writes);
    expect(cancelled).toEqual([ENTRY]);
  });

  it("a target that can no longer be cancelled, or has left the view, is counted with the others", () => {
    const pressed = planSelected([row(ENTRY), row(COND), row(ETH)], gateOf);
    const now = [row(ENTRY, { lifecycle_state: "held" }), row(ETH)];
    const sent = regate(pressed, now, [], gateOf);
    expect(sent.targets.map((r) => r.id)).toEqual([ETH]);
    expect(sent.excluded.other).toBe(2);
    expect(sent.scope).toBe("selected");
  });

  it("a cancel-all that lost a target goes one row at a time, naming no more than the rest", () => {
    const rows = [entryOn(MAIN, 1), entryOn(SUB1, 2)];
    const pressed = planAllInView(rows, [], gateOf);
    expect(pressed.route.kind).toBe("cancel_all");
    const sent = regate(pressed, [rows[0] as OrderRowModel], [], gateOf);
    expect(sent.route).toEqual({ kind: "per_row" });
    expect(sent.targets.map((r) => r.accountId)).toEqual([MAIN]);
  });

  it("a plan that lost nothing keeps its targets, routed again on the rows as they are now", () => {
    const rows = [entryOn(MAIN, 1), entryOn(SUB1, 2)];
    const pressed = planAllInView(rows, [], gateOf);
    expect(regate(pressed, rows, [], gateOf)).toEqual(pressed);
    // an order now amending is no longer cancel-all's to select (22): one cancelOrder each instead
    const amending = row(ENTRY, {
      id: rows[1]?.id,
      exchange_account_id: SUB1,
      lifecycle_state: "amend_pending",
    });
    const sent = regate(pressed, [entryOn(MAIN, 1), amending], [], gateOf);
    expect(sent.targets.map((r) => r.id)).toEqual(pressed.targets.map((r) => r.id));
    expect(sent.route).toEqual({ kind: "per_row" });
  });
});

describe("the route of Cancel all in view (D02 §8.3)", () => {
  const entries = (): OrderRowModel[] => [row(ENTRY), row(COND), row(ETH)];
  it("cancelAllOrders where its fields express the view: the targets' accounts, reduce-only kept out", () => {
    expect(routeFor(entries(), [])).toEqual({
      kind: "cancel_all",
      request: {
        exchange_account_ids: [SUB1, SUB2],
        symbol: null,
        intents: [],
        exclude_reduce_only: true,
      },
    });
    const symbol: FilterChip = { kind: "symbol", value: "ETHUSDT" };
    expect(routeFor([row(ETH)], [symbol])).toMatchObject({
      request: { exchange_account_ids: [SUB2], symbol: "ETHUSDT" },
    });
  });

  it.each([
    ["a side chip", [row(ETH)], [{ kind: "side", value: "long" }]],
    ["a trade-group chip", [row(ETH)], [{ kind: "trade_group", value: SUB1 }]],
    [
      "two symbol chips",
      [row(ETH)],
      [
        { kind: "symbol", value: "ETHUSDT" },
        { kind: "symbol", value: "BTCUSDT" },
      ],
    ],
    ["a reduce-only target", [row(TP)], []],
    ["a target of unknown provenance", [row(ETH, {}, { ...PLACED, provenance: null })], []],
    ["an adopted order", [row(ETH, {}, { ...PLACED, provenance: "reconciliation" })], []],
    ["a target still sending", [row(ETH, { lifecycle_state: "submitting" })], []],
    ["nothing to cancel", [], []],
  ] as const)("one cancelOrder per row with %s", (_, targets, chips) => {
    expect(routeFor(targets, chips as readonly FilterChip[])).toEqual({ kind: "per_row" });
  });
});

describe("partial-failure reducer", () => {
  it("Cancel-all partial failure: 3 of 5 accounts; each failing account has its reason", async () => {
    const rows = [MAIN, SUB1, SUB2, SUB3, SUB4].map((a, i) => entryOn(a, i + 1));
    const plan = planAllInView(rows, [], gateOf);
    expect(plan.route.kind).toBe("cancel_all");
    const fetch = vi.fn(
      async () => new Response(JSON.stringify(golden("rest_cancel_all_partial.json"))),
    );
    const result = await runPlan(plan, createOrdersWrites({ fetch }));
    expect(result.lines.map((l) => lineText(l, words(l.accountId)))).toEqual([
      "Cancelled 4 on Main · LIVE",
      "Cancelled 2 on Sub-1 · LIVE",
      // exchange_unavailable, retryable false: that order unknown, never re-sent (22)
      "Sub-2 · LIVE: not confirmed — check its orders on Bybit",
      "Cancelled 3 on Sub-3 · LIVE",
      // timeout, retryable true: one cancelled by the deadline, the rest never called open
      "Sub-4 · LIVE: cancelled 1, then Bybit stopped answering — try again",
    ]);
    // nothing silently dropped: one line per account the request named
    expect(result.lines).toHaveLength(5);
    // Retry failed sends the retryable account alone (code m3)
    expect(result.retry).toEqual({ kind: "cancel_all", accounts: [SUB4] });
    expect(JSON.stringify(result)).not.toMatch(/Exchange connectivity|deadline/);
  });

  it("an account the answer leaves out is not known; a whole-request failure covers every account", async () => {
    const rows = [entryOn(MAIN, 1), entryOn(SUB1, 2)];
    const plan = planAllInView(rows, [], gateOf);
    const partial: OrdersWrites = {
      cancelOrder: vi.fn(),
      cancelAllOrders: async () => ({
        kind: "ok",
        results: [{ accountId: MAIN, ok: true, affected: 1, code: null, retryable: false }],
      }),
    };
    const out = await runPlan(plan, partial);
    expect(out.lines.map((l) => l.kind)).toEqual(["done", "unconfirmed"]);
    expect(out.retry).toBeNull();
    const whole = async (kind: string) =>
      runPlan(plan, { cancelOrder: vi.fn(), cancelAllOrders: async () => ({ kind }) as never });
    // nothing sent, a retry may go: the store read failed, or a 429
    const store = await whole("store_unavailable");
    expect(store.lines.map((l) => l.kind)).toEqual(["store", "store"]);
    expect(store.retry).toEqual({ kind: "cancel_all", accounts: [MAIN, SUB1] });
    expect((await whole("busy")).lines.map((l) => l.kind)).toEqual(["other", "other"]);
    // refused before anything was sent: the refusal's line, never retried
    const scope = await whole("account_scope");
    expect(scope.lines.map((l) => lineText(l, words(l.accountId)))).toEqual([
      "Main · LIVE: nothing cancelled — the request was refused",
      "Sub-1 · LIVE: nothing cancelled — the request was refused",
    ]);
    expect(scope.retry).toBeNull();
    // no answer from CandleViewer's server: not known, never "Bybit did not answer"
    const silent = await whole("unavailable");
    expect(silent.lines.map((l) => lineText(l, words(l.accountId)))).toEqual([
      "Main · LIVE: not confirmed — check its orders on Bybit",
      "Sub-1 · LIVE: not confirmed — check its orders on Bybit",
    ]);
    expect(silent.retry).toBeNull();
  });

  it.each([
    [
      "store_unavailable",
      0,
      true,
      "store",
      "Sub-1 · LIVE: nothing cancelled — CandleViewer could not read its orders",
    ],
    ["store_unavailable", 2, true, "other", "Sub-1 · LIVE: not all cancelled — try again"],
    ["exchange_rate_limited", 0, true, "other", "Sub-1 · LIVE: not all cancelled — try again"],
    ["oms_not_ready", 0, true, "other", "Sub-1 · LIVE: not all cancelled — try again"],
    ["timeout", 0, true, "no_answer", "Sub-1 · LIVE: Bybit did not answer — nothing cancelled"],
    [
      "timeout",
      2,
      true,
      "partial",
      "Sub-1 · LIVE: cancelled 2, then Bybit stopped answering — try again",
    ],
    [
      "exchange_unavailable",
      0,
      false,
      "unconfirmed",
      "Sub-1 · LIVE: not confirmed — check its orders on Bybit",
    ],
    [
      "conflict",
      2,
      false,
      "refused",
      "Sub-1 · LIVE: not all cancelled — check its orders on Bybit",
    ],
    [
      "exchange_error",
      0,
      false,
      "refused",
      "Sub-1 · LIVE: not all cancelled — check its orders on Bybit",
    ],
    [
      "account_unavailable",
      0,
      false,
      "refused",
      "Sub-1 · LIVE: not all cancelled — check its orders on Bybit",
    ],
  ] as const)(
    "the code %s with %s cancelled, retryable %s, reads %s",
    async (code, affected, retryable, kind, text) => {
      const plan = planAllInView([entryOn(SUB1, 1)], [], gateOf);
      const writes: OrdersWrites = {
        cancelOrder: vi.fn(),
        cancelAllOrders: async () => ({
          kind: "ok",
          results: [{ accountId: SUB1, ok: false, affected, code, retryable }],
        }),
      };
      const result = await runPlan(plan, writes);
      const [line] = result.lines;
      expect(line?.kind).toBe(kind);
      expect(line === undefined ? null : lineText(line, words(SUB1))).toBe(text);
      // Retry failed sends a retryable account again, never another (code m3)
      expect(result.retry).toEqual(retryable ? { kind: "cancel_all", accounts: [SUB1] } : null);
    },
  );

  it("one cancelOrder per row: grouped by account, the failed rows named, the retryable kept for Retry failed", () => {
    const rows = [row(ENTRY), row(COND), row(ETH)];
    const plan = planSelected(rows, gateOf);
    const outcomes = new Map<string, CancelOutcome>([
      [ENTRY, { kind: "accepted", lifecycle: "cancel_pending" }],
      [COND, { kind: "busy" }],
      [ETH, { kind: "exchange_refused" }],
    ]);
    const result = fromRows(plan, outcomes);
    expect(result.lines.map((l) => [l.accountId, l.kind, l.cancelled])).toEqual([
      [SUB1, "other", 1],
      [SUB2, "refused", 0],
    ]);
    expect(result.lines.flatMap((l) => l.failedRows.map((r) => r.id))).toEqual([COND, ETH]);
    // the 429 sent nothing and may go again; Bybit's refusal would meet the same answer
    expect(result.retry).toEqual({ kind: "per_row", rowIds: [COND] });
  });

  it("a row nobody answered, or one a 110001 left unknown, is not confirmed, never cancelled (code m2)", () => {
    const plan = planSelected([row(ENTRY), row(COND), row(ETH)], gateOf);
    const result = fromRows(
      plan,
      new Map<string, CancelOutcome>([
        [ENTRY, { kind: "accepted", lifecycle: "unknown" }],
        [COND, { kind: "accepted", lifecycle: "cancel_pending" }],
        [ETH, { kind: "unavailable" }],
      ]),
    );
    expect(result.lines.map((l) => [l.kind, l.cancelled])).toEqual([
      ["unconfirmed", 1],
      ["unconfirmed", 0],
    ]);
    expect(result.lines.map((l) => lineText(l, words(l.accountId)))).toEqual([
      "Sub-1 · LIVE: not confirmed — check its orders on Bybit",
      "Sub-2 · LIVE: not confirmed — check its orders on Bybit",
    ]);
    expect(result.lines.flatMap((l) => l.failedRows.map((r) => r.id))).toEqual([ENTRY, ETH]);
    expect(result.retry).toBeNull(); // an outcome not known is never sent again
  });

  it("every row accepted is done on every account, and nothing is left to retry", () => {
    const plan = planSelected([row(ENTRY), row(ETH)], gateOf);
    const accepted: CancelOutcome = { kind: "accepted", lifecycle: null };
    const result = fromRows(
      plan,
      new Map([
        [ENTRY, accepted],
        [ETH, accepted],
      ]),
    );
    expect(result.lines.map((l) => lineText(l, words(l.accountId)))).toEqual([
      "Cancelled 1 on Sub-1 · LIVE",
      "Cancelled 1 on Sub-2 · LIVE",
    ]);
    expect(result.retry).toBeNull();
  });
});

describe("Retry failed (BQ-8): a new request for the failed targets only", () => {
  it("per row: the retryable failed rows as they are now, gated again", async () => {
    const plan = planSelected([row(ENTRY), row(COND), row(ETH)], gateOf);
    const first = fromRows(
      plan,
      new Map<string, CancelOutcome>([
        [ENTRY, { kind: "accepted", lifecycle: null }],
        [COND, { kind: "busy" }],
        [ETH, { kind: "store_unavailable" }],
      ]),
    );
    expect(first.retry).toEqual({ kind: "per_row", rowIds: [COND, ETH] });
    // ETH has gone unknown since: it is counted out of the retry, not sent
    const now = [row(COND), row(ETH, { lifecycle_state: "unknown" })];
    const again = retryPlan(first, now, [], gateOf);
    expect(again?.targets.map((r) => r.id)).toEqual([COND]);
    expect(again?.excluded.other).toBe(1);
    const { writes, cancelled } = recording();
    if (again !== null) await runPlan(again, writes);
    expect(cancelled).toEqual([COND]);
  });

  it("cancel-all: the failed accounts alone, a new request", () => {
    const rows = [MAIN, SUB1, SUB2, SUB3, SUB4].map((a, i) => entryOn(a, i + 1));
    const first: BulkResult = {
      plan: planAllInView(rows, [], gateOf),
      lines: [],
      retry: { kind: "cancel_all", accounts: [SUB2, SUB4] },
    };
    const again = retryPlan(first, rows, [], gateOf);
    expect(again?.route).toMatchObject({
      kind: "cancel_all",
      request: { exchange_account_ids: [SUB2, SUB4], exclude_reduce_only: true },
    });
    expect(retryPlan({ ...first, retry: null }, rows, [], gateOf)).toBeNull();
  });
});

describe("runPlan", () => {
  it(`keeps at most ${MAX_IN_FLIGHT} cancelOrder requests in flight (22: 64 per caller)`, async () => {
    const rows = Array.from({ length: 10 }, (_, i) => entryOn(SUB1, i + 1));
    let open = 0;
    let peak = 0;
    const writes: OrdersWrites = {
      cancelOrder: async () => {
        open += 1;
        peak = Math.max(peak, open);
        await Promise.resolve();
        open -= 1;
        return { kind: "accepted", lifecycle: null };
      },
      cancelAllOrders: vi.fn(),
    };
    const result = await runPlan(planSelected(rows, gateOf), writes);
    expect(peak).toBe(MAX_IN_FLIGHT);
    expect(result.lines).toEqual([
      { accountId: SUB1, kind: "done", cancelled: 10, failedRows: [] },
    ]);
  });

  it("a confirmed plan runs to its end: no send carries an abort signal (N-M1)", async () => {
    const accepted: CancelOutcome = { kind: "accepted", lifecycle: null };
    const cancelOrder = vi.fn<OrdersWrites["cancelOrder"]>(async () => accepted);
    const cancelAllOrders = vi.fn<OrdersWrites["cancelAllOrders"]>(async () => ({
      kind: "ok",
      results: [],
    }));
    const rows = Array.from({ length: 6 }, (_, i) => entryOn(SUB1, i + 1));
    await runPlan(planSelected(rows, gateOf), { cancelOrder, cancelAllOrders });
    await runPlan(planAllInView(rows, [], gateOf), { cancelOrder, cancelAllOrders });
    expect(cancelOrder).toHaveBeenCalledTimes(6);
    expect(cancelAllOrders).toHaveBeenCalledTimes(1);
    const signals = [...cancelOrder.mock.calls, ...cancelAllOrders.mock.calls].map((c) => c[1]);
    expect(signals).toEqual(Array.from({ length: 7 }, () => undefined));
  });

  it("an empty plan sends nothing", async () => {
    const { writes, cancelled } = recording();
    const result = await runPlan(planSelected([row(STOP)], gateOf), writes);
    expect(cancelled).toEqual([]);
    expect(result.lines).toEqual([]);
  });
});

describe("the dialog's words", () => {
  it("counts per account, singular and plural (PROPOSED, BQ-9)", () => {
    expect(countText(2, words(SUB1))).toBe("2 orders on Sub-1 · LIVE");
    expect(countText(1, words(SUB1))).toBe("1 order on Sub-1 · LIVE");
  });

  it("the rows left out, the native stop's the deck's own line (D02:349)", () => {
    expect(excludedLines({ native_stop: 1, recorded_take_profit: 0, other: 0 })).toEqual([
      "1 native-stop order is not included: every position keeps a native stop.",
    ]);
    expect(excludedLines({ native_stop: 2, recorded_take_profit: 2, other: 3 })).toEqual([
      "2 native-stop orders are not included: every position keeps a native stop.",
      "2 take-profits are not included: each is managed with its stop.",
      "3 orders are not included: they can't be cancelled now.",
    ]);
    expect(excludedLines({ native_stop: 0, recorded_take_profit: 1, other: 1 })).toEqual([
      "1 take-profit is not included: it is managed with its stop.",
      "1 order is not included: it can't be cancelled now.",
    ]);
    expect(excludedLines({ native_stop: 0, recorded_take_profit: 0, other: 0 })).toEqual([]);
  });
});
