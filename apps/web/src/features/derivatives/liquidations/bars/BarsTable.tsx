// E24-S06 (#781): the table alternative to the bars (D02 §11: Bar (UTC) · Long liquidated (USDT) · Short liquidated
// (USDT) · State). Zero and unknown are words, never blanks: an unknown bar reads "not recorded" in each cell, a zero
// bar reads "0.00" with the state "zero". The header draws the unit; each cell's accessible name carries it (D02 §11). Newest first, at most
// `TABLE_ROWS` rows (CMP-049 warns above 200 undrawn-window rows), the cut disclosed by the pane.
import type { JSX } from "react";
import { Table, type TableColumn } from "@candleviewer/ui";
import { coverageTime, notional2 } from "../ui/format";
import * as copy from "./copy";
import { barTime } from "./format";
import type { LiqBar } from "./model";

export const TABLE_ROWS = 200;

const withUnit = (text: string, unit: string): JSX.Element => (
  <>
    {text}
    <span className="cv-visually-hidden"> {unit}</span>
  </>
);

export interface BarsTableProps {
  readonly symbol: string;
  /** The interval's label for the caption, e.g. "1 h". */
  readonly interval: string;
  readonly intervalMs: number;
  /** Ascending, as built; the table shows them newest first. */
  readonly bars: readonly LiqBar[];
  readonly emptyState: JSX.Element;
  /** The host's polite region says the table's lines (E08-D07 D17): the pane's one status node, so none is drawn here. */
  readonly announce: (text: string) => void;
}

export function BarsTable({
  symbol,
  interval,
  intervalMs,
  bars,
  emptyState,
  announce,
}: BarsTableProps): JSX.Element {
  const rows = bars.slice(-TABLE_ROWS).reverse();
  const ref = rows[0]?.tMs ?? 0;
  // D02 §11: the unit is in the header AND each cell's accessible name. The cell's unit is visually hidden (the
  // header draws it), as #780's feed table does; a cell without a number reads "not recorded", with no unit
  const figure = (v: string | null): JSX.Element | string =>
    v === null ? copy.NOT_RECORDED : withUnit(notional2(v), "USDT");
  const state = (b: LiqBar): string =>
    b.partialFromMs === null
      ? copy.STATE_WORDS[b.state]
      : copy.recordedPartial(coverageTime(b.partialFromMs, ref));
  const columns: TableColumn<LiqBar>[] = [
    {
      id: "bar",
      header: copy.COL_BAR,
      minWidthEm: 8,
      cell: (b) => barTime(b.tMs, ref, intervalMs),
    },
    {
      id: "long",
      header: copy.COL_LONG,
      align: "end",
      minWidthEm: 10,
      cell: (b) => figure(b.long),
    },
    {
      id: "short",
      header: copy.COL_SHORT,
      align: "end",
      minWidthEm: 10,
      cell: (b) => figure(b.short),
    },
    { id: "state", header: copy.COL_STATE, minWidthEm: 8, cell: state },
  ];
  return (
    <Table
      columns={columns}
      rows={rows}
      rowKey={(b) => String(b.tMs)}
      caption={copy.tableCaption(symbol, interval)}
      density="compact"
      emptyState={emptyState}
      announce={announce}
    />
  );
}
