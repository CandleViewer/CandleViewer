/**
 * The four instruments the grid tests run over, read from the recorded, redacted Bybit capture
 * (`packages/fixtures/bybit/2026-10-05`, C-13.5) and mapped to `22`'s `Instrument` the way the
 * instrument-info cache serves it. Four tick sizes: 0.10, 0.01, 0.005 (not a power of ten) and
 * 0.0001. The capture's lot is 0.001 on every row, so the property tests also draw random grids.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Instrument } from "../src/index.js";

const CAPTURE = resolve(import.meta.dirname, "../../fixtures/bybit/2026-10-05/rest");

interface BybitRow {
  readonly symbol: string;
  readonly status: NonNullable<Instrument["status"]>;
  readonly priceFilter: { readonly tickSize: string };
  readonly lotSizeFilter: {
    readonly qtyStep: string;
    readonly minOrderQty: string;
    readonly maxOrderQty: string;
    readonly minNotionalValue: string;
  };
  readonly leverageFilter: { readonly maxLeverage: string };
}

function rows(file: string): Map<string, BybitRow> {
  const body = JSON.parse(readFileSync(resolve(CAPTURE, file), "utf8")) as {
    result: { list: BybitRow[] };
  };
  return new Map(body.result.list.map((row) => [row.symbol, row]));
}

export function toInstrument(row: BybitRow): Instrument {
  return {
    category: "linear",
    symbol: row.symbol,
    status: row.status,
    tick_size: row.priceFilter.tickSize,
    qty_step: row.lotSizeFilter.qtyStep,
    min_order_qty: row.lotSizeFilter.minOrderQty,
    max_order_qty: row.lotSizeFilter.maxOrderQty,
    min_notional_value: row.lotSizeFilter.minNotionalValue,
    max_leverage: row.leverageFilter.maxLeverage,
  };
}

const before = rows("instruments_before.json");
const after = rows("instruments_after.json");

function pick(map: Map<string, BybitRow>, symbol: string): Instrument {
  const row = map.get(symbol);
  if (row === undefined) throw new Error(`fixture has no ${symbol}`);
  return toInstrument(row);
}

/** BTCUSDT (tick 0.10), ETHUSDT (0.01), SOLUSDT after its tick change (0.005), LUNAUSDT (0.0001). */
export const INSTRUMENTS: readonly Instrument[] = [
  pick(before, "BTCUSDT"),
  pick(before, "ETHUSDT"),
  pick(after, "SOLUSDT"),
  pick(before, "LUNAUSDT"),
];

/** LUNAUSDT as the later capture has it: `Closed`. */
export const CLOSED_LUNA: Instrument = pick(after, "LUNAUSDT");
