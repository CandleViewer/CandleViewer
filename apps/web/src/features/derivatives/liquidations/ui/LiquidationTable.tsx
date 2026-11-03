// E24-S05 (#780) slice 1: the feed is the table (D02 §11, D03 S54-41 / S54-66; the ticket's "the accessible
// alternative is the primary structure"). CMP-049 in grid mode (the APG grid: ↑ / ↓ move rows), at most 40 rows
// drawn whatever the print rate, newest on top. The side cell is the word with its ▲ / ▼ glyph, so colour is
// never the only signal; each number keeps its unit in its accessible name.
// TODO(#780): the D02 §6 bucket rows ("600 prints · avg …") and the Prints column (BQ 5, ruled 6612481277: display
// aggregates of served prints) follow outside PR 1's line budget.
// TODO(slice 3, #780): `Enter` on a row moves the crosshair (`liquidation.print_clicked`).
import type { JSX } from "react";
import { Table, type TableColumn } from "@candleviewer/ui";
import type { HeldPrint } from "../ring";
import { SIDE_GLYPHS, SIDE_WORDS } from "../side";
import * as copy from "./copy";
import { feedTimeIn, groupedDecimal, notional2 } from "./format";

/** A number drawn with its unit read after it (D02 §11: the unit in each cell's accessible name). */
const withUnit = (text: string, unit: string): JSX.Element => (
  <>
    {text}
    <span className="cv-visually-hidden"> {unit}</span>
  </>
);

export interface LiquidationTableProps {
  readonly symbol: string;
  readonly baseUnit: string;
  /** Newest first; the caller bounds them. */
  readonly rows: readonly HeldPrint[];
  readonly emptyState: JSX.Element;
}

export function LiquidationTable({
  symbol,
  baseUnit,
  rows,
  emptyState,
}: LiquidationTableProps): JSX.Element {
  const ref = rows[0]?.tsMs ?? 0; // a row from another UTC day than the newest carries its date (PROPOSED)
  const columns: TableColumn<HeldPrint>[] = [
    { id: "time", header: copy.COL_TIME, minWidthEm: 6, cell: (r) => feedTimeIn(r.tsMs, ref) },
    {
      id: "side",
      header: copy.COL_SIDE,
      minWidthEm: 10,
      cell: (r) => (
        <span className="cv-liq-side">
          {SIDE_WORDS[r.side]}{" "}
          <span className="cv-liq-side__glyph" aria-hidden="true">
            {SIDE_GLYPHS[r.side]}
          </span>
        </span>
      ),
    },
    {
      id: "size",
      header: copy.colSize(baseUnit),
      align: "end",
      minWidthEm: 7,
      cell: (r) => withUnit(groupedDecimal(r.size), baseUnit),
    },
    {
      id: "price",
      header: copy.COL_PRICE,
      align: "end",
      minWidthEm: 9,
      cell: (r) => withUnit(groupedDecimal(r.price), "USDT"),
    },
    {
      id: "notional",
      header: copy.COL_NOTIONAL,
      align: "end",
      minWidthEm: 10,
      cell: (r) =>
        r.notionalUsd === null ? copy.NO_NOTIONAL : withUnit(notional2(r.notionalUsd), "USDT"),
    },
    {
      // D04 F-5 proposes "Cluster (prints)" for the header (A-3, to the D05 copy deck); D02 §11's "×N" until then
      id: "cluster",
      header: copy.COL_CLUSTER,
      align: "end",
      minWidthEm: 4,
      cell: (r) => `×${String(r.clusterSize)}`,
    },
  ];
  return (
    <Table
      grid
      columns={columns}
      rows={rows}
      rowKey={(r) => String(r.seq)}
      caption={copy.tableCaption(symbol)}
      density="compact"
      emptyState={emptyState}
    />
  );
}
