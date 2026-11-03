/**
 * Grouping on the Fills tab and in SCR-078 (E29-S04 #979; E29-D02 §6.4, D02:299; E29-D03 §3.5).
 *
 * - **The Type filter:** D02:299's toggle chips (Trade, ADL, Liquidation, Funding, Settlement, all
 *   on) hide rows by type. A row of a type no chip names (another value, or none reported) is
 *   always kept: a chip hides what it names, never what nobody chose to hide.
 * - **Under the panel's group-by** (account by default, symbol, trade group): groups in a stable
 *   order, so an arriving fill never moves a group (account by label then id, symbol by name, trade
 *   group by id, and no trade group last). A WS fill whose trade group is not known yet groups as
 *   none until REST says (`fillRow.ts`).
 * - **By order** (the default, D01 D14): one order row per order, newest first by its newest fill,
 *   its fills newest first beneath it, with the order's running sums (BQ-7); then the fills of no
 *   order, by type in the chips' order (D03:173, :177). **"Show every fill"** lists the fills
 *   without their order rows, newest first.
 * - **Account sections** (a trade group in SCR-078, D03 §3.5): one per leg's account, in the legs'
 *   order, each with its sums; only the accounts the session holds rows of appear (D-8).
 */
import type { GroupBy } from "../../model/grouping";
import { sumFills, type FillSums } from "./aggregate";
import { newestFirst, type FillKind, type FillRowModel } from "./fillRow";

/** D02:299's chips, in order. */
export const TYPE_CHIPS: readonly FillKind[] = [
  "trade",
  "adl",
  "liquidation",
  "funding",
  "settlement",
];

/** The rows a chip set leaves; `on` holds the chips that are pressed. */
export function applyTypeFilter(
  rows: readonly FillRowModel[],
  on: ReadonlySet<FillKind>,
): readonly FillRowModel[] {
  if (TYPE_CHIPS.every((kind) => on.has(kind))) return rows;
  return rows.filter((row) => {
    const kind = row.type.kind;
    return kind === "other" || kind === "missing" || on.has(kind);
  });
}

export interface OrderRow {
  readonly orderId: string;
  /** Newest first. */
  readonly rows: readonly FillRowModel[];
  readonly sums: FillSums;
}

export interface TypeSection {
  /** A kind, or `other` / `missing` for the rows no chip names. */
  readonly kind: FillKind | "other" | "missing";
  readonly rows: readonly FillRowModel[];
  readonly sums: FillSums;
}

export interface FillsGroup {
  readonly by: GroupBy;
  /** The account id, the symbol, or the trade-group id; `null`: no trade group. */
  readonly key: string | null;
  /** By order: the order rows; empty under "Show every fill". */
  readonly orders: readonly OrderRow[];
  /** By order: the fills of no order, by type; empty under "Show every fill". */
  readonly noOrder: readonly TypeSection[];
  /** Every fill of the group, newest first: the flat list "Show every fill" shows. */
  readonly rows: readonly FillRowModel[];
  readonly sums: FillSums;
}

const text = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

function keyOf(row: FillRowModel, by: GroupBy): string | null {
  if (by === "account") return row.accountId;
  if (by === "symbol") return row.symbol;
  return row.tradeGroupId ?? null;
}

const SECTION_ORDER: readonly TypeSection["kind"][] = [...TYPE_CHIPS, "other", "missing"];

/** `rows` by order, newest first, then the fills of no order by type. */
export function byOrder(rows: readonly FillRowModel[]): {
  readonly orders: readonly OrderRow[];
  readonly noOrder: readonly TypeSection[];
} {
  const orders = new Map<string, { head: FillRowModel; rows: FillRowModel[] }>();
  const loose = new Map<TypeSection["kind"], FillRowModel[]>();
  for (const row of rows) {
    if (row.orderId === null) {
      const list = loose.get(row.type.kind) ?? [];
      list.push(row);
      loose.set(row.type.kind, list);
      continue;
    }
    const held = orders.get(row.orderId);
    if (held === undefined) orders.set(row.orderId, { head: row, rows: [row] });
    else {
      held.rows.push(row);
      if (newestFirst(row, held.head) < 0) held.head = row;
    }
  }
  // newest fill first; ties by order id, so the order is total
  const ordered = [...orders.entries()]
    .sort(([a, x], [b, y]) => newestFirst(x.head, y.head) || text(a, b))
    .map(([orderId, held]) => {
      const sorted = [...held.rows].sort(newestFirst);
      return { orderId, rows: sorted, sums: sumFills(sorted) };
    });
  const noOrder = SECTION_ORDER.flatMap((kind) => {
    const list = loose.get(kind);
    if (list === undefined) return [];
    return [{ kind, rows: [...list].sort(newestFirst), sums: sumFills(list) }];
  });
  return { orders: ordered, noOrder };
}

/**
 * The groups of `rows` under the panel's group-by. `labelOf` orders account groups by label
 * (D01 D13 a's default order, as the Positions tab's); `everyFill` is D02:299's switch.
 */
export function groupFills(
  rows: readonly FillRowModel[],
  by: GroupBy,
  everyFill: boolean,
  labelOf: (accountId: string) => string | null = () => null,
): readonly FillsGroup[] {
  const groups = new Map<string | null, FillRowModel[]>();
  for (const row of [...rows].sort(newestFirst)) {
    const key = keyOf(row, by);
    const list = groups.get(key);
    if (list === undefined) groups.set(key, [row]);
    else list.push(row);
  }
  const keys = [...groups.keys()].sort((a, b) => {
    if (a === null || b === null) return a === null ? (b === null ? 0 : 1) : -1;
    if (by !== "account") return text(a, b);
    return text(labelOf(a) ?? "￿", labelOf(b) ?? "￿") || text(a, b);
  });
  return keys.map((key) => {
    const members = groups.get(key) ?? [];
    const split = everyFill ? { orders: [], noOrder: [] } : byOrder(members);
    return { by, key, ...split, rows: members, sums: sumFills(members) };
  });
}

export interface AccountSection {
  readonly accountId: string;
  readonly rows: readonly FillRowModel[];
  readonly sums: FillSums;
}

/**
 * D03 §3.5: one section per account that holds fills, in `legOrder` (the trade group's legs), any
 * other after them by id. Built from the rows alone, so a Manager's sections, sums and counts are
 * their legs' (D-8): no leg outside the session's scope is counted or named.
 */
export function accountSections(
  rows: readonly FillRowModel[],
  legOrder: readonly string[] = [],
): readonly AccountSection[] {
  const sections = new Map<string, FillRowModel[]>();
  for (const row of [...rows].sort(newestFirst)) {
    const list = sections.get(row.accountId);
    if (list === undefined) sections.set(row.accountId, [row]);
    else list.push(row);
  }
  const rank = (id: string): number => {
    const at = legOrder.indexOf(id);
    return at < 0 ? legOrder.length : at;
  };
  return [...sections.keys()]
    .sort((a, b) => rank(a) - rank(b) || text(a, b))
    .map((accountId) => {
      const list = sections.get(accountId) ?? [];
      return { accountId, rows: list, sums: sumFills(list) };
    });
}
