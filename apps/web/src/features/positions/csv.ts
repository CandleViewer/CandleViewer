/**
 * CSV export of the Positions tab (E29-S01 #911; E29-D02 D-21, BQ-17): the rows that match the
 * filters (all of them, not the rendered window), in the visible column order, decimals raw (as the
 * wire sends them, no `+`, no grouping, ASCII minus), text cells guarded against formula injection.
 * Client-side only: it writes no audit record and emits no analytics event (`grid.exported` is not in
 * `24` §15.5 and no export endpoint exists, D04-G5, D04-G9; the gap is recorded on #911), and the
 * file is a convenience, never an audit substitute (the ticket's security note). RFC 4180: CRLF
 * lines, a field quoted when it holds a quote, a comma or a line break.
 */
import { parseDecimal } from "./model/decimal";
import type { LiqReading } from "./model/liqTier";
import type { PositionRowModel } from "./model/rowMapping";

export interface CsvColumn<R> {
  readonly header: string;
  /** A `number` cell is written raw when `parseDecimal` reads it; anything else is guarded text. */
  readonly kind: "text" | "number";
  readonly value: (row: R) => string | null;
}

/** D-21 names `=`, `+`, `-` and `@`; a tab and a carriage return start a formula too (OWASP). */
const FORMULA_START = /^[=+\-@\t\r]/;

/** A text cell that a spreadsheet would read as a formula, prefixed with `'` (D-21). */
export function guardCell(text: string): string {
  return FORMULA_START.test(text) ? `'${text}` : text;
}

function quote(text: string): string {
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function cell<R>(column: CsvColumn<R>, row: R): string {
  const raw = column.value(row);
  if (raw === null) return "";
  if (column.kind === "number" && parseDecimal(raw) !== null) return raw; // numbers stay numbers
  return quote(guardCell(raw));
}

/** The CSV text of `rows` under `columns` (header line first). */
export function toCsv<R>(rows: readonly R[], columns: readonly CsvColumn<R>[]): string {
  const lines = [columns.map((c) => quote(guardCell(c.header))).join(",")];
  for (const row of rows) lines.push(columns.map((c) => cell(c, row)).join(","));
  return `${lines.join("\r\n")}\r\n`;
}

/** D02 §5.1's margin words. */
const MARGIN_WORDS = { isolated: "Isolated", cross: "Cross", portfolio: "Portfolio" } as const;

export type PositionColumnId =
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
  | "margin"
  | "take_profit"
  | "notional"
  | "position_idx"
  | "trade_group";

/**
 * The Positions columns by id, each with E29-D02 §5.1's header (D02:174–196; the SL column waits
 * for `native_stop_present`, BQ-9, and Env for a mixed view, BQ-7).
 */
export function positionCsvColumns(
  liq: ReadonlyMap<string, LiqReading>,
): Readonly<Record<PositionColumnId, CsvColumn<PositionRowModel>>> {
  return {
    account: { header: "Account", kind: "text", value: (r) => r.accountLabel ?? r.accountId },
    symbol: { header: "Symbol", kind: "text", value: (r) => r.symbol },
    side: { header: "Side", kind: "text", value: (r) => r.sideLabel },
    size: { header: "Size", kind: "number", value: (r) => r.size },
    entry: { header: "Entry (USDT)", kind: "number", value: (r) => r.entry },
    mark: { header: "Mark (USDT)", kind: "number", value: (r) => r.mark },
    upnl: { header: "uPnL (USDT)", kind: "number", value: (r) => r.unrealisedPnl },
    r: { header: "R", kind: "number", value: (r) => r.r.value },
    rpnl_today: {
      header: "rPnL today (USDT)",
      kind: "number",
      value: (r) => r.realisedToday.value,
    },
    liq_price: { header: "Liq price (USDT)", kind: "number", value: (r) => r.liqPrice },
    liq_dist: {
      header: "Liq dist. %",
      kind: "number",
      value: (r) => liq.get(r.key)?.distancePct ?? null,
    },
    leverage: { header: "Lev", kind: "number", value: (r) => r.leverage },
    margin: {
      header: "Margin",
      kind: "text",
      value: (r) => (r.marginMode.value === null ? null : MARGIN_WORDS[r.marginMode.value]),
    },
    take_profit: { header: "TP", kind: "number", value: (r) => r.takeProfit },
    notional: { header: "Notional", kind: "number", value: (r) => r.notional },
    position_idx: { header: "Pos. idx", kind: "number", value: (r) => String(r.positionIdx) },
    trade_group: { header: "Trade group", kind: "text", value: (r) => r.tradeGroupId },
  };
}

/** The export of the rows in view, in the visible column order (`ids`); unknown ids are skipped. */
export function exportPositionsCsv(
  rows: readonly PositionRowModel[],
  ids: readonly string[],
  liq: ReadonlyMap<string, LiqReading>,
): string {
  const catalogue = positionCsvColumns(liq);
  const columns = ids
    .filter((id): id is PositionColumnId => Object.hasOwn(catalogue, id))
    .map((id) => catalogue[id]);
  return toCsv(rows, columns);
}
