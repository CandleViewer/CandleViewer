/**
 * The Working-orders tab's view of the store's rows (E29-S02 PR2): the panel's filter chips applied,
 * the native-stop rule fed by the positions book, and the words a row is named by.
 *
 * - **Figures** (D02 D-7, D-8): the wire's decimal as the Positions tab shows one, its trailing zeros
 *   dropped ("0.25", "63,980"), grouped with ",", the minus U+2212; never a binary double
 *   (`AGENTS.md` §5.2's decimal rule).
 * - **The chips** (D02 §9.1) narrow orders as they narrow positions: Account, Symbol and Trade group
 *   by the order's own field; Side by the order's side, and on this tab the chip says so in the
 *   order's words, "Side: Buy" / "Side: Sell" (D02:263's order side; the orchestrator's ruling: one
 *   word seen and spoken), its stored value the panel's `long` / `short`.
 * - **The native stop** (D01 D7, BQ-5): an order is one only while an open position on its account,
 *   symbol and `position_idx` depends on it, so the positions book answers that once it is read (a
 *   live snapshot or a REST read). Until then every candidate is one: a stop is never offered as
 *   cancellable when it may not be (C-2.6).
 */
import { chipLabel } from "../gridModel";
import type { FilterChip } from "../model/filters";
import { normalise, parseDecimal, toPlain } from "../model/decimal";
import type { AccountInfo } from "../model/rowMapping";
import type { PositionsSnapshot } from "../positionsStore";
import { bindProposed } from "./copy";
import { protectiveOf, type OpenPositionOf, type OrderRowModel } from "./model/orderRow";

const GROUPS = /\B(?=(\d{3})+(?!\d))/g;

/** A wire decimal as the grid shows it: "63,980", "0.25", "−1.5"; the text itself when it is none. */
export function figure(decimal: string): string {
  const parsed = parseDecimal(decimal);
  if (parsed === null) return decimal;
  const plain = toPlain(normalise(parsed));
  const negative = plain.startsWith("-");
  const [whole = "", fraction] = (negative ? plain.slice(1) : plain).split(".");
  const grouped = whole.replace(GROUPS, ",");
  return `${negative ? "−" : ""}${grouped}${fraction === undefined ? "" : `.${fraction}`}`;
}

/** An order's account as a row, a name and a toast say it: its label, else "…" and its id's last four. */
export const accountOf = (row: Pick<OrderRowModel, "accountLabel" | "accountId">): string =>
  row.accountLabel ?? `…${row.accountId.slice(-4)}`;

/**
 * An order's short name (E29-D05 N-01's form, "Select BTCUSDT Long on Main", with the order's size and
 * price, so two orders on one symbol, side and account differ): "BTCUSDT Buy 0.15 BTC at 63,950 on
 * Sub-1"; a market order's or one with no price has no "at". PROPOSED to E29-D05's owner.
 */
export function orderName(row: OrderRowModel): string {
  const qty = row.qty === null ? null : `${figure(row.qty)} ${row.baseCoin}`.trimEnd();
  const price = row.isMarket || row.price === null ? null : `at ${figure(row.price)}`;
  return [row.symbol, row.sideLabel, qty, price, `on ${accountOf(row)}`]
    .filter((part): part is string => part !== null)
    .join(" ");
}

/** A target's line in the bulk dialog (D02 §8.3: symbol, side, size, account, environment). */
export function orderLine(row: OrderRowModel, environment: string): string {
  const qty = row.qty === null ? "—" : `${figure(row.qty)} ${row.baseCoin}`.trimEnd();
  return `${row.symbol} ${row.sideLabel} ${qty} on ${accountOf(row)} · ${environment}`;
}

/** A chip's words on the Working-orders tab: a Side chip in the order's side, the others as the panel's. */
export function orderChipLabel(
  chip: FilterChip,
  accounts: ReadonlyMap<string, AccountInfo>,
): string {
  if (chip.kind !== "side") return chipLabel(chip, accounts);
  return bindProposed(
    chip.value === "short" ? "blotter.ui.chip.side_sell" : "blotter.ui.chip.side_buy",
  );
}

/** The active chips restated in this tab's words, "Account: Sub-1 · Side: Buy" (D02:380). */
export const chipsInOrderWords = (
  chips: readonly FilterChip[],
  accounts: ReadonlyMap<string, AccountInfo>,
): string => chips.map((chip) => orderChipLabel(chip, accounts)).join(" · ");

/** Whether a row passes the chips: alternatives within a kind, every kind together (D02 §9.1). */
export function passes(row: OrderRowModel, chips: readonly FilterChip[]): boolean {
  const sideChip = row.side === "buy" ? "long" : row.side === "sell" ? "short" : null;
  const fieldOf: Readonly<Record<FilterChip["kind"], string | null>> = {
    account: row.accountId,
    symbol: row.symbol,
    side: sideChip,
    trade_group: row.tradeGroupId,
  };
  const kinds = new Set(chips.map((c) => c.kind));
  return [...kinds].every((kind) =>
    chips.some((c) => c.kind === kind && c.value === fieldOf[kind]),
  );
}

const KEY_SEPARATOR = "\n";

/**
 * The book's open positions as one string ("account|symbol|idx" each, sorted), or `null` until the
 * book is read: a stable value to select from the positions store, so a mark tick, which moves no
 * position in or out, leaves it equal and re-renders nothing (code m5).
 */
export function openPositionKeys(book: Pick<PositionsSnapshot, "source" | "rows">): string | null {
  if (book.source !== "ws" && book.source !== "rest") return null;
  return book.rows
    .map((r) => `${r.accountId}|${r.symbol}|${r.positionIdx}`)
    .sort()
    .join(KEY_SEPARATOR);
}

/** The book's answer to "is a position open there?" from those keys, or `undefined` until it is read. */
export function openPositionFrom(keys: string | null): OpenPositionOf | undefined {
  if (keys === null) return undefined;
  const open = new Set(keys === "" ? [] : keys.split(KEY_SEPARATOR));
  return (accountId, symbol, positionIdx) => open.has(`${accountId}|${symbol}|${positionIdx}`);
}

/** The rows in view: the chips applied, each row's protective kind read against the book. */
export function rowsInView(
  rows: readonly OrderRowModel[],
  chips: readonly FilterChip[],
  openPosition: OpenPositionOf | undefined,
): readonly OrderRowModel[] {
  const out: OrderRowModel[] = [];
  for (const row of rows) {
    if (!passes(row, chips)) continue;
    const protective = protectiveOf(row, openPosition);
    const same = protective.kind === row.protective.kind && protective.via === row.protective.via;
    out.push(same ? row : { ...row, protective });
  }
  return out;
}
