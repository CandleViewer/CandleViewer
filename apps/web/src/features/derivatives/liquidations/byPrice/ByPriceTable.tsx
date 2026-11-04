// E24-S07 (#782) slice 2: the table alternative to the recorded layer (D02 §11, after #781's `BarsTable`): one row per
// served bucket, largest first as served (never re-sorted or re-bucketed), the Decimal strings grouped and never
// rounded, the unit in each header and in each cell's accessible name.
import type { JSX } from "react";
import { Table, type TableColumn } from "@candleviewer/ui";
import type { ByPriceBucket } from "./byPriceRead";
import * as copy from "./copy";
import type { ByPriceLayer } from "./model";

type Figure = "price_lo" | "price_hi" | "long_notional_usd" | "short_notional_usd";
const figure = (id: string, header: string, key: Figure): TableColumn<ByPriceBucket> => ({
  id,
  header,
  align: "end",
  minWidthEm: 9,
  cell: (b) => (
    <>
      {copy.grouped(b[key])}
      <span className="cv-visually-hidden"> USDT</span>
    </>
  ),
});

const COLUMNS: TableColumn<ByPriceBucket>[] = [
  figure("from", copy.COL_FROM, "price_lo"),
  figure("to", copy.COL_TO, "price_hi"),
  figure("long", copy.COL_LONG, "long_notional_usd"),
  figure("short", copy.COL_SHORT, "short_notional_usd"),
  {
    id: "prints",
    header: copy.COL_PRINTS,
    align: "end",
    minWidthEm: 5,
    cell: (b) => String(b.prints),
  },
];

export interface ByPriceTableProps {
  readonly layer: ByPriceLayer;
  /** The legend row's state line, or a host empty state, when there is no bucket. */
  readonly emptyState: JSX.Element;
  readonly announce?: ((text: string) => void) | undefined;
}

export function ByPriceTable({ layer, emptyState, announce }: ByPriceTableProps): JSX.Element {
  return (
    <Table
      columns={COLUMNS}
      rows={layer.buckets}
      rowKey={(b) => b.price_lo}
      caption={copy.tableCaption(layer.symbol, layer.buckets.length)}
      density="compact"
      emptyState={emptyState}
      announce={announce}
    />
  );
}
