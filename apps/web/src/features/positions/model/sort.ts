/**
 * Row order on the Positions tab (E29-S01 #911).
 *
 * - **Default (D01 D13 a):** environment → account → symbol → side → position idx, until
 *   `opened_at` ships (D01 OQ-9). Stable, so a live update never moves a row.
 * - **A header press (F-04, D05 §5.2, PROPOSED):** ascending, then descending, then the default
 *   again. The order is a snapshot taken at the press (D02 §5.5, D01 D13 b: a live re-sort waits),
 *   so later values never move rows; a row that arrives after the press joins in the default order
 *   after the snapshot's rows. Sorting applies within groups (D02 §5.5).
 */
import { cmp, parseDecimal } from "./decimal";
import type { PositionRowModel } from "./rowMapping";

export type SortColumn =
  | "account"
  | "symbol"
  | "side"
  | "size"
  | "entry"
  | "mark"
  | "upnl"
  | "r"
  | "rpnl_today"
  | "liq_price"
  | "liq_dist"
  | "leverage"
  | "margin";

export type SortDirection = "ascending" | "descending";

export interface SortState {
  readonly column: SortColumn;
  readonly direction: SortDirection;
  /** The row keys in the order the press found them. */
  readonly order: readonly string[];
}

/** A row's liquidation distance, which the panel computes beside the row (`liqTier.ts`). */
export type DistanceOf = (row: PositionRowModel) => string | null;

const text = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
const ENV_RANK = { live: 0, demo: 1, testnet: 2 } as const;
const SIDE_RANK = { long: 0, short: 1 } as const;

/** D01 D13 (a): env → account (label, then id) → symbol → side → position idx. */
export function compareDefault(a: PositionRowModel, b: PositionRowModel): number {
  const env = (r: PositionRowModel): number =>
    r.environment === null ? 3 : ENV_RANK[r.environment];
  return (
    env(a) - env(b) ||
    text(a.accountLabel ?? "￿", b.accountLabel ?? "￿") ||
    text(a.accountId, b.accountId) ||
    text(a.symbol, b.symbol) ||
    SIDE_RANK[a.side] - SIDE_RANK[b.side] ||
    a.positionIdx - b.positionIdx
  );
}

export function sortDefault(rows: readonly PositionRowModel[]): readonly PositionRowModel[] {
  return [...rows].sort(compareDefault);
}

/** A decimal column: numeric order, a row without a value last whatever the direction. */
function byDecimal(
  pick: (row: PositionRowModel) => string | null,
): (a: PositionRowModel, b: PositionRowModel, dir: 1 | -1) => number {
  return (a, b, dir) => {
    const x = parseDecimal(pick(a));
    const y = parseDecimal(pick(b));
    if (x === null || y === null) return x === null ? (y === null ? 0 : 1) : -1;
    return cmp(x, y) * dir;
  };
}

function byText(
  pick: (row: PositionRowModel) => string,
): (a: PositionRowModel, b: PositionRowModel, dir: 1 | -1) => number {
  return (a, b, dir) => text(pick(a), pick(b)) * dir;
}

function comparator(
  column: SortColumn,
  distance: DistanceOf,
): (a: PositionRowModel, b: PositionRowModel, dir: 1 | -1) => number {
  switch (column) {
    case "account":
      return byText((r) => r.accountLabel ?? r.accountId);
    case "symbol":
      return byText((r) => r.symbol);
    case "side":
      return byText((r) => r.sideLabel);
    case "margin":
      return byText((r) => r.marginMode.value ?? "￿");
    case "size":
      return byDecimal((r) => r.size);
    case "entry":
      return byDecimal((r) => r.entry);
    case "mark":
      return byDecimal((r) => r.mark);
    case "upnl":
      return byDecimal((r) => r.unrealisedPnl);
    case "r":
      return byDecimal((r) => r.r.value);
    case "rpnl_today":
      return byDecimal((r) => r.realisedToday.value);
    case "liq_price":
      return byDecimal((r) => r.liqPrice);
    case "liq_dist":
      return byDecimal(distance);
    case "leverage":
      return byDecimal((r) => r.leverage);
  }
}

/**
 * F-04's cycle on a header press: a new column starts ascending, the same column goes to
 * descending, then back to the default (`null`). The order of `rows` is captured now.
 */
export function pressHeader(
  current: SortState | null,
  column: SortColumn,
  rows: readonly PositionRowModel[],
  distance: DistanceOf = () => null,
): SortState | null {
  let direction: SortDirection;
  if (current === null || current.column !== column) direction = "ascending";
  else if (current.direction === "ascending") direction = "descending";
  else return null;
  const compare = comparator(column, distance);
  const dir = direction === "ascending" ? 1 : -1;
  const order = [...rows]
    .sort((a, b) => compare(a, b, dir) || compareDefault(a, b))
    .map((r) => r.key);
  return { column, direction, order };
}

/** The rows in the snapshot's order, then the rows it did not see, in the default order. */
export function applySort(
  rows: readonly PositionRowModel[],
  sort: SortState | null,
): readonly PositionRowModel[] {
  if (sort === null) return sortDefault(rows);
  const rank = new Map(sort.order.map((key, i) => [key, i]));
  const seen = rows.filter((r) => rank.has(r.key));
  const fresh = rows.filter((r) => !rank.has(r.key)).sort(compareDefault);
  seen.sort((a, b) => (rank.get(a.key) ?? 0) - (rank.get(b.key) ?? 0));
  return [...seen, ...fresh];
}

/** `aria-sort` for a column header (D02 D-1; `05` §6.3). */
export function ariaSortOf(
  sort: SortState | null,
  column: SortColumn,
): "ascending" | "descending" | "none" {
  return sort !== null && sort.column === column ? sort.direction : "none";
}
