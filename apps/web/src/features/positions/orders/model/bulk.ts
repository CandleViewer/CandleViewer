/**
 * S-36's Working-orders half (E29-S02 PR2; BQ-4, BQ-8; E29-D02 §8.3, §8.5): Cancel selected, Cancel
 * all in view, the per-account result and Retry failed, as plain data the dialog draws.
 *
 * - **Targets** are the rows whose own Cancel is allowed (D04 §4.1: "every target keeps its own
 *   row's gates"). **A native-stop row is never a target** (C-2.6, BQ-4): it is skipped here,
 *   before any request is built, and counted for the dialog's line; the server's
 *   `403 risk_limit_breached` (`NATIVE_STOP_REQUIRED`) stays the enforcement. A recorded
 *   take-profit is left out too: its Cancel is `setPositionTpSl`'s, which is not mounted (BQ-5).
 * - **The route** (D02 §8.3): Cancel selected sends one `cancelOrder` per target
 *   (`CancelAllRequest` takes no ids); Cancel all in view sends one `cancelAllOrders` only where its
 *   fields express the view and its selection is the targets, else one `cancelOrder` per row. That
 *   is: no Side or Trade-group chip, one Symbol chip at most, and every target a placed order in
 *   `submitted`, `triggered` or `partially_filled` that is not reduce-only (`22`'s selection with
 *   its default `exclude_reduce_only: true`, which is never sent `false`).
 * - **The result** is one line per account, every target counted in it, so nothing is silently
 *   dropped (the "Cancel-all partial failure" scenario): `BulkAccountResult` for `cancelAllOrders`,
 *   the targets' outcomes for one `cancelOrder` each, with the rows a failure left. "Retry failed"
 *   is a new request for the failed targets only, with a new key (BQ-8).
 */
import { MAX_ACCOUNT_IDS } from "../../api";
import { bindDeck } from "../../copy";
import type { FilterChip } from "../../model/filters";
import type {
  AccountCancelResult,
  CancelAllOutcome,
  CancelAllRequest,
  CancelOutcome,
  OrdersWrites,
} from "../api";
import { bindProposed } from "../copy";
import type { CancelGate } from "./gates";
import type { OrderRowModel } from "./orderRow";

export type Exclusion = "native_stop" | "recorded_take_profit" | "other";

export type BulkRoute =
  | { readonly kind: "per_row" }
  | { readonly kind: "cancel_all"; readonly request: CancelAllRequest };

export interface BulkPlan {
  readonly scope: "selected" | "all_in_view";
  /** The rows to cancel, in view order: no native-stop row is ever among them. */
  readonly targets: readonly OrderRowModel[];
  readonly excluded: Readonly<Record<Exclusion, number>>;
  readonly route: BulkRoute;
}

/** At most this many `cancelOrder` requests in flight at once: well under `22`'s 64 per caller (BQ-8). */
export const MAX_IN_FLIGHT = 4;

/** `22` `cancelAllOrders`' selection: the states it sends a cancel for. */
const CANCEL_ALL_STATES: ReadonlySet<string> = new Set([
  "submitted",
  "triggered",
  "partially_filled",
]);

/** Why a row is not a target, or `null` when it is one. */
export function exclusionOf(row: OrderRowModel, gate: CancelGate): Exclusion | null {
  if (row.protective.kind === "native_stop") return "native_stop"; // C-2.6: never sent
  if (row.protective.kind === "recorded_take_profit") return "recorded_take_profit";
  return gate.kind === "allowed" ? null : "other";
}

function partition(
  rows: readonly OrderRowModel[],
  gateOf: (row: OrderRowModel) => CancelGate,
): Pick<BulkPlan, "targets" | "excluded"> {
  const targets: OrderRowModel[] = [];
  const excluded: Record<Exclusion, number> = {
    native_stop: 0,
    recorded_take_profit: 0,
    other: 0,
  };
  for (const row of rows) {
    const why = exclusionOf(row, gateOf(row));
    if (why === null) targets.push(row);
    else excluded[why] += 1;
  }
  return { targets, excluded };
}

/** Cancel selected: the selected rows, one `cancelOrder` each. */
export function planSelected(
  rows: readonly OrderRowModel[],
  gateOf: (row: OrderRowModel) => CancelGate,
): BulkPlan {
  return { scope: "selected", ...partition(rows, gateOf), route: { kind: "per_row" } };
}

/** The route of Cancel all in view: `cancelAllOrders` only where it cancels exactly the targets. */
export function routeFor(
  targets: readonly OrderRowModel[],
  chips: readonly FilterChip[],
): BulkRoute {
  const perRow: BulkRoute = { kind: "per_row" };
  if (targets.length === 0) return perRow;
  if (chips.some((c) => c.kind === "side" || c.kind === "trade_group")) return perRow;
  const symbols = chips.filter((c) => c.kind === "symbol");
  if (symbols.length > 1) return perRow;
  const selectable = (r: OrderRowModel): boolean =>
    !r.reduceOnly &&
    r.provenance === "placed" &&
    r.state.lifecycle !== null &&
    CANCEL_ALL_STATES.has(r.state.lifecycle);
  if (!targets.every(selectable)) return perRow;
  const accounts = [...new Set(targets.map((r) => r.accountId))];
  if (accounts.length > MAX_ACCOUNT_IDS) return perRow;
  return {
    kind: "cancel_all",
    request: {
      exchange_account_ids: accounts,
      symbol: symbols[0]?.value ?? null,
      intents: [],
      exclude_reduce_only: true,
    },
  };
}

/** Cancel all in view: the rows the filters leave, by the route above. */
export function planAllInView(
  rows: readonly OrderRowModel[],
  chips: readonly FilterChip[],
  gateOf: (row: OrderRowModel) => CancelGate,
): BulkPlan {
  const parts = partition(rows, gateOf);
  return { scope: "all_in_view", ...parts, route: routeFor(parts.targets, chips) };
}

/** A result line's kind: done, or the failure the deck or a PROPOSED line words. */
export type LineKind = "done" | "no_answer" | "partial" | "store" | "other";

export interface ResultLine {
  readonly accountId: string;
  readonly kind: LineKind;
  readonly cancelled: number;
  /** The rows a failure left on one `cancelOrder` each, named under the line. */
  readonly failedRows: readonly OrderRowModel[];
}

export interface BulkResult {
  readonly plan: BulkPlan;
  /** One per account with a target, in the targets' order. */
  readonly lines: readonly ResultLine[];
  /** What "Retry failed" sends, or `null` when nothing failed. */
  readonly retry:
    | { readonly kind: "cancel_all"; readonly accounts: readonly string[] }
    | { readonly kind: "per_row"; readonly rowIds: readonly string[] }
    | null;
}

/** The accounts of the targets, in their order. */
const accountsOf = (plan: BulkPlan): readonly string[] => [
  ...new Set(plan.targets.map((r) => r.accountId)),
];

/** `BulkAccountResult`'s codes for an outcome Bybit never gave (`22` `cancelAllOrders`). */
const NO_ANSWER: ReadonlySet<string> = new Set(["exchange_unavailable", "timeout"]);

function failureKind(code: string | null, cancelled: number): LineKind {
  if (code === "store_unavailable") return "store";
  if (code !== null && NO_ANSWER.has(code)) return cancelled > 0 ? "partial" : "no_answer";
  return "other";
}

/** The partial-failure reducer for `cancelAllOrders`: an account missing from `results` failed. */
export function fromCancelAll(plan: BulkPlan, outcome: CancelAllOutcome): BulkResult {
  const byAccount = new Map<string, AccountCancelResult>(
    outcome.kind === "ok" ? outcome.results.map((r) => [r.accountId, r]) : [],
  );
  const lines = accountsOf(plan).map((accountId): ResultLine => {
    const result = byAccount.get(accountId);
    if (outcome.kind !== "ok") {
      const code = outcome.kind === "store_unavailable" ? "store_unavailable" : null;
      return { accountId, kind: failureKind(code, 0), cancelled: 0, failedRows: [] };
    }
    if (result === undefined) return { accountId, kind: "no_answer", cancelled: 0, failedRows: [] };
    const kind = result.ok ? "done" : failureKind(result.code, result.affected);
    return { accountId, kind, cancelled: result.affected, failedRows: [] };
  });
  const failed = lines.filter((l) => l.kind !== "done").map((l) => l.accountId);
  return {
    plan,
    lines,
    retry: failed.length === 0 ? null : { kind: "cancel_all", accounts: failed },
  };
}

/** The partial-failure reducer for one `cancelOrder` per target, grouped by account. */
export function fromRows(plan: BulkPlan, outcomes: ReadonlyMap<string, CancelOutcome>): BulkResult {
  const lines = accountsOf(plan).map((accountId): ResultLine => {
    const mine = plan.targets.filter((r) => r.accountId === accountId);
    const failedRows = mine.filter((r) => outcomes.get(r.id)?.kind !== "accepted");
    const cancelled = mine.length - failedRows.length;
    const first = failedRows[0] === undefined ? undefined : outcomes.get(failedRows[0].id);
    if (failedRows.length === 0) return { accountId, kind: "done", cancelled, failedRows };
    const code =
      first === undefined || first.kind === "unavailable"
        ? "exchange_unavailable"
        : first.kind === "store_unavailable"
          ? "store_unavailable"
          : first.kind;
    return { accountId, kind: failureKind(code, cancelled), cancelled, failedRows };
  });
  const rowIds = lines.flatMap((l) => l.failedRows.map((r) => r.id));
  return { plan, lines, retry: rowIds.length === 0 ? null : { kind: "per_row", rowIds } };
}

/** Sends a plan: no request for an empty one, `MAX_IN_FLIGHT` at once on the per-row route. */
export async function runPlan(
  plan: BulkPlan,
  writes: OrdersWrites,
  signal?: AbortSignal,
): Promise<BulkResult> {
  if (plan.route.kind === "cancel_all") {
    return fromCancelAll(plan, await writes.cancelAllOrders(plan.route.request, signal));
  }
  const outcomes = new Map<string, CancelOutcome>();
  let next = 0;
  const worker = async (): Promise<void> => {
    while (next < plan.targets.length) {
      const row = plan.targets[next];
      next += 1;
      if (row !== undefined) outcomes.set(row.id, await writes.cancelOrder(row.id, signal));
    }
  };
  const lanes = Math.min(MAX_IN_FLIGHT, plan.targets.length);
  await Promise.all(Array.from({ length: lanes }, worker));
  return fromRows(plan, outcomes);
}

/**
 * "Retry failed" (BQ-8): a new plan of the failed targets only, read from the rows in view as they
 * are now and gated again; a cancel-all's retry is planned over the failed accounts' rows alone, so
 * its request names those accounts and no other.
 */
export function retryPlan(
  result: BulkResult,
  rows: readonly OrderRowModel[],
  chips: readonly FilterChip[],
  gateOf: (row: OrderRowModel) => CancelGate,
): BulkPlan | null {
  const retry = result.retry;
  if (retry === null) return null;
  if (retry.kind === "per_row") {
    const ids = new Set(retry.rowIds);
    const plan = planSelected(
      rows.filter((r) => ids.has(r.id)),
      gateOf,
    );
    return { ...plan, scope: result.plan.scope };
  }
  const accounts = new Set(retry.accounts);
  return planAllInView(
    rows.filter((r) => accounts.has(r.accountId)),
    chips,
    gateOf,
  );
}

/** The words an account's line takes: its label and its environment's word. */
export interface AccountWords {
  readonly label: string;
  readonly environment: string;
}

/** A result line in the deck's words, else a PROPOSED line's (BQ-9): never a server message. */
export function lineText(line: ResultLine, words: AccountWords): string {
  const who = { label: words.label, environment: words.environment };
  switch (line.kind) {
    case "done":
      return bindDeck("blotter.ui.result.done", {
        "4": String(line.cancelled),
        Main: who.label,
        LIVE: who.environment,
      });
    case "no_answer":
      return bindDeck("blotter.ui.result.failed", { "Sub-1": who.label, LIVE: who.environment });
    case "partial":
      return bindProposed("blotter.ui.result.failed_partial", {
        "Sub-4": who.label,
        LIVE: who.environment,
        "1": String(line.cancelled),
      });
    case "store":
      return bindProposed("blotter.ui.result.failed_store", {
        "Sub-2": who.label,
        LIVE: who.environment,
      });
    case "other":
      return bindProposed("blotter.ui.result.failed_other", {
        "Sub-2": who.label,
        LIVE: who.environment,
      });
  }
}

/** The dialog's count of an account's targets, "2 orders on Sub-1 · LIVE". */
export function countText(count: number, words: AccountWords): string {
  const who = { "Sub-1": words.label, LIVE: words.environment };
  return count === 1
    ? bindProposed("blotter.ui.bulk.count_orders.one", who)
    : bindProposed("blotter.ui.bulk.count_orders", {
        "2": String(count),
        "Sub-1": words.label,
        LIVE: words.environment,
      });
}

/** The dialog's lines for the rows left out, native stops first (D02 §8.3, §8.5). */
export function excludedLines(excluded: BulkPlan["excluded"]): readonly string[] {
  const lines: string[] = [];
  const n = excluded.native_stop;
  if (n > 0)
    lines.push(
      n === 1
        ? bindDeck("blotter.ui.bulk.excluded", { "1": "1" })
        : bindProposed("blotter.ui.bulk.excluded#2", { "2": String(n) }),
    );
  const tp = excluded.recorded_take_profit;
  if (tp > 0)
    lines.push(
      tp === 1
        ? bindProposed("blotter.ui.bulk.recorded_tp_excluded", { "1": "1" })
        : bindProposed("blotter.ui.bulk.recorded_tp_excluded#2", { "2": String(tp) }),
    );
  const other = excluded.other;
  if (other > 0)
    lines.push(
      other === 1
        ? bindProposed("blotter.ui.bulk.other_excluded", { "1": "1" })
        : bindProposed("blotter.ui.bulk.other_excluded#2", { "2": String(other) }),
    );
  return lines;
}
