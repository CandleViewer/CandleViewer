/**
 * Grouping and aggregates on the Positions tab (E29-S01 #911; BQ-10, BQ-12; E29-D02 §5.5, D-15).
 *
 * - **Group by** account (default), symbol or trade group: one generic reducer, each group a row
 *   that expands to its positions. No Manager: no served source maps accounts to managers yet
 *   (BQ-10); the trade group is the frame's `trade_group_id`, which no producer sends yet (E29-T09
 *   owns it), so live rows group under "no trade group" until it does.
 * - **A group row** shows the count, uPnL, rPnL today and, only when every position in it is on
 *   one symbol, the net size (`22` `AggregatePosition.net_size`: the signed sum, long positive).
 *   rPnL today on an account group is the account's `realised_pnl_today` (`wallet`, D-15), never a
 *   sum of the column; on any other group it is the sum of the positions' `realised_pnl_session`.
 * - **One totals row** per environment (D-15; one environment per server, BQ-7): the count, the
 *   exposure (Σ size × mark), uPnL and rPnL today; never a size summed across symbols.
 *
 * A sum is `null` (shown "—") as soon as one member lacks its value: no figure is ever partial.
 */
import { add, mul, neg, parseDecimal, toPlain, ZERO, type Decimal } from "./decimal";
import type { Environment, PositionRowModel } from "./rowMapping";
import { sortDefault } from "./sort";

export type GroupBy = "account" | "symbol" | "trade_group";
export const GROUP_BYS: readonly GroupBy[] = ["account", "symbol", "trade_group"];

export interface GroupModel {
  readonly by: GroupBy;
  /** The account id, the symbol, or the trade-group id; `null`: positions with no trade group. */
  readonly key: string | null;
  readonly rows: readonly PositionRowModel[];
  readonly count: number;
  readonly unrealisedPnl: string | null;
  readonly realisedToday: string | null;
  /** Only for a group on one symbol. */
  readonly netSize: string | null;
  readonly symbols: readonly string[];
}

export interface TotalsModel {
  readonly environment: Environment | null;
  readonly count: number;
  readonly exposure: string | null;
  readonly unrealisedPnl: string | null;
  readonly realisedToday: string | null;
}

/** An account's `wallet` `realised_pnl_today`, or `null` while none is served (`23` §15.4). */
export type AccountRealisedToday = (accountId: string) => string | null;

/** Σ of decimals, `null` when any is missing or unreadable. */
function total(values: readonly (string | null)[]): string | null {
  let acc: Decimal = ZERO;
  for (const value of values) {
    const d = parseDecimal(value);
    if (d === null) return null;
    acc = add(acc, d);
  }
  return toPlain(acc);
}

/** The signed net size of rows on one symbol (`AggregatePosition.net_size`), else `null`. */
export function netSize(rows: readonly PositionRowModel[]): string | null {
  if (rows.length === 0 || new Set(rows.map((r) => r.symbol)).size !== 1) return null;
  let acc: Decimal = ZERO;
  for (const row of rows) {
    const size = parseDecimal(row.size);
    if (size === null) return null;
    acc = add(acc, row.side === "long" ? size : neg(size));
  }
  return toPlain(acc);
}

function keyOfGroup(row: PositionRowModel, by: GroupBy): string | null {
  switch (by) {
    case "account":
      return row.accountId;
    case "symbol":
      return row.symbol;
    case "trade_group":
      return row.tradeGroupId;
  }
}

/**
 * The groups of `rows` (already filtered and sorted: each group keeps that order, as sorting is
 * within groups, D02 §5.5). The groups themselves keep the default order (D01 D13 a), so a header
 * press never moves a group; the positions with no trade group come last.
 */
export function groupRows(
  rows: readonly PositionRowModel[],
  by: GroupBy,
  realisedToday: AccountRealisedToday,
): readonly GroupModel[] {
  const groups = new Map<string | null, PositionRowModel[]>();
  for (const row of rows) {
    const key = keyOfGroup(row, by);
    const list = groups.get(key);
    if (list === undefined) groups.set(key, [row]);
    else list.push(row);
  }
  const ordered = sortDefault(rows).map((row) => keyOfGroup(row, by));
  const keys: (string | null)[] = [...new Set(ordered)].filter((key) => key !== null);
  if (groups.has(null)) keys.push(null); // positions with no trade group, last
  return keys.map((key) => {
    const members = groups.get(key) ?? [];
    return {
      by,
      key,
      rows: members,
      count: members.length,
      unrealisedPnl: total(members.map((r) => r.unrealisedPnl)),
      realisedToday:
        by === "account" && key !== null
          ? realisedToday(key)
          : total(members.map((r) => r.realisedToday.value)),
      netSize: netSize(members),
      symbols: [...new Set(members.map((r) => r.symbol))],
    };
  });
}

/** Σ size × mark over the rows, `null` when a row has no notional (D02 §5.2's "Exposure"). */
function exposure(rows: readonly PositionRowModel[]): string | null {
  let acc: Decimal = ZERO;
  for (const row of rows) {
    const size = parseDecimal(row.size);
    const mark = parseDecimal(row.mark);
    const notional = size !== null && mark !== null ? mul(size, mark) : parseDecimal(row.notional);
    if (notional === null) return null;
    acc = add(acc, notional);
  }
  return toPlain(acc);
}

/**
 * The one totals row over `rows` (the rows in view): rPnL today sums the accounts' own figures
 * (D-15: "the column never sums to them"), each account once.
 */
export function totalsOf(
  rows: readonly PositionRowModel[],
  environment: Environment | null,
  realisedToday: AccountRealisedToday,
): TotalsModel {
  const accounts = [...new Set(rows.map((r) => r.accountId))];
  return {
    environment,
    count: rows.length,
    exposure: exposure(rows),
    unrealisedPnl: total(rows.map((r) => r.unrealisedPnl)),
    realisedToday: rows.length === 0 ? null : total(accounts.map(realisedToday)),
  };
}
