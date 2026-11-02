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
      "Sub-2 · LIVE: Bybit did not answer — nothing cancelled",
      "Cancelled 3 on Sub-3 · LIVE",
      "Sub-4 · LIVE: cancelled 1, then Bybit stopped answering — the rest are still open",
    ]);
    // nothing silently dropped: one line per account the request named
    expect(result.lines).toHaveLength(5);
    expect(result.retry).toEqual({ kind: "cancel_all", accounts: [SUB2, SUB4] });
    expect(JSON.stringify(result)).not.toMatch(/Exchange connectivity|deadline/);
  });

  it("an account the answer leaves out failed; a whole-request failure fails every account", async () => {
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
    expect(out.lines.map((l) => l.kind)).toEqual(["done", "no_answer"]);
    const refused: OrdersWrites = {
      cancelOrder: vi.fn(),
      cancelAllOrders: async () => ({ kind: "store_unavailable" }),
    };
    expect((await runPlan(plan, refused)).lines.map((l) => l.kind)).toEqual(["store", "store"]);
    const busy: OrdersWrites = {
      cancelOrder: vi.fn(),
      cancelAllOrders: async () => ({ kind: "busy" }),
    };
    expect((await runPlan(plan, busy)).lines.map((l) => l.kind)).toEqual(["other", "other"]);
  });

  it.each([
    [
      "store_unavailable",
      0,
      "store",
      "Sub-1 · LIVE: nothing cancelled — CandleViewer could not read its orders",
    ],
    ["exchange_rate_limited", 0, "other", "Sub-1 · LIVE: not all cancelled — try again"],
    ["conflict", 2, "other", "Sub-1 · LIVE: not all cancelled — try again"],
    ["timeout", 0, "no_answer", "Sub-1 · LIVE: Bybit did not answer — nothing cancelled"],
  ] as const)("the code %s with %s cancelled reads %s", async (code, affected, kind, text) => {
    const plan = planAllInView([entryOn(SUB1, 1)], [], gateOf);
    const writes: OrdersWrites = {
      cancelOrder: vi.fn(),
      cancelAllOrders: async () => ({
        kind: "ok",
        results: [{ accountId: SUB1, ok: false, affected, code, retryable: false }],
      }),
    };
    const [line] = (await runPlan(plan, writes)).lines;
    expect(line?.kind).toBe(kind);
    expect(line === undefined ? null : lineText(line, words(SUB1))).toBe(text);
  });

  it("one cancelOrder per row: grouped by account, the failed rows kept for Retry failed", () => {
    const rows = [row(ENTRY), row(COND), row(ETH)];
    const plan = planSelected(rows, gateOf);
    const outcomes = new Map<string, CancelOutcome>([
      [ENTRY, { kind: "accepted", lifecycle: "cancel_pending" }],
      [COND, { kind: "unavailable" }],
      [ETH, { kind: "exchange_refused" }],
    ]);
    const result = fromRows(plan, outcomes);
    expect(result.lines.map((l) => [l.accountId, l.kind, l.cancelled])).toEqual([
      [SUB1, "partial", 1],
      [SUB2, "other", 0],
    ]);
    expect(result.lines.flatMap((l) => l.failedRows.map((r) => r.id))).toEqual([COND, ETH]);
    expect(result.retry).toEqual({ kind: "per_row", rowIds: [COND, ETH] });
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
  it("per row: the failed rows as they are now, gated again", async () => {
    const plan = planSelected([row(ENTRY), row(COND), row(ETH)], gateOf);
    const first = fromRows(
      plan,
      new Map<string, CancelOutcome>([
        [ENTRY, { kind: "accepted", lifecycle: null }],
        [COND, { kind: "busy" }],
        [ETH, { kind: "unavailable" }],
      ]),
    );
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
      "2 take-profits are not included: each is cleared with its stop.",
      "3 orders are not included: they can't be cancelled now.",
    ]);
    expect(excludedLines({ native_stop: 0, recorded_take_profit: 1, other: 1 })).toEqual([
      "1 take-profit is not included: it is cleared with its stop.",
      "1 order is not included: it can't be cancelled now.",
    ]);
    expect(excludedLines({ native_stop: 0, recorded_take_profit: 0, other: 0 })).toEqual([]);
  });
});
