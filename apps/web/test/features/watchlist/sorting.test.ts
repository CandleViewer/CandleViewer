/** E08-S08 (#4702): SCR-100's sort (E08-D07 D5): manual order by default; Symbol A–Z; live columns by value. */
import { describe, expect, it } from "vitest";
import {
  decodeSort,
  encodeSort,
  isLiveColumn,
  ranked,
  sortValue,
} from "../../../src/features/watchlist/sorting";
import type { TickerEntry } from "../../../src/features/watchlist/ticker/tickerStore";
import { tickerValues } from "../../../src/features/watchlist/ticker/tickerValues";
import { restItem, streamItem } from "./support";

const entryOf = (item = streamItem(0)): TickerEntry => {
  const values = tickerValues(item);
  if (values === null) throw new Error("no values");
  return { values, receivedAtMs: 0, freshAtMs: 0 };
};
const ENTRIES: Readonly<Record<string, TickerEntry>> = {
  BTCUSDT: entryOf(streamItem(0)),
  ETHUSDT: entryOf(restItem("ETHUSDT")),
  SOLUSDT: entryOf(restItem("SOLUSDT")),
};
const read = (symbol: string): TickerEntry | undefined => ENTRIES[symbol];
const LIST = ["SOLUSDT", "XRPUSDT", "BTCUSDT", "ETHUSDT"];

describe("ranked", () => {
  it("keeps the manual order without a sort", () => {
    expect(ranked(LIST, null, read)).toBe(LIST);
  });

  it("sorts Symbol A–Z, and Z–A descending", () => {
    expect(ranked(LIST, { columnId: "symbol", direction: "ascending" }, read)).toEqual([
      "BTCUSDT",
      "ETHUSDT",
      "SOLUSDT",
      "XRPUSDT",
    ]);
    expect(ranked(LIST, { columnId: "symbol", direction: "descending" }, read)[0]).toBe("XRPUSDT");
  });

  it("sorts a live column by its value, a row with none last whichever the direction", () => {
    const up = ranked(LIST, { columnId: "last", direction: "ascending" }, read);
    expect(up).toEqual(["SOLUSDT", "ETHUSDT", "BTCUSDT", "XRPUSDT"]);
    const down = ranked(LIST, { columnId: "last", direction: "descending" }, read);
    expect(down).toEqual(["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]);
  });

  it("keeps the manual order between ties and for columns with no order of their own", () => {
    const none = (): undefined => undefined;
    expect(ranked(LIST, { columnId: "last", direction: "descending" }, none)).toEqual(LIST);
    expect(ranked(LIST, { columnId: "rec", direction: "ascending" }, read)).toBe(LIST);
  });
});

describe("sortValue", () => {
  it("reads each live column's value; OI Δ has no baseline yet", () => {
    const btc = ENTRIES["BTCUSDT"];
    const values = btc?.values;
    const cases: [string, number | undefined][] = [
      ["last", values?.lastPrice],
      ["chg_24h_pct", values?.pctChange24h],
      ["turnover_24h", values?.turnover24h],
      ["funding_rate", values?.fundingRate],
      ["next_funding", values?.nextFundingTimeMs],
      ["spread_bps", values?.spreadBps],
      ["volume_24h", values?.volume24h],
      ["open_interest_value", values?.openInterestValue],
      ["mark_price", values?.markPrice],
      ["index_price", values?.indexPrice],
      ["bid1_price", values?.bid1Price],
      ["ask1_price", values?.ask1Price],
      ["high_24h", values?.high24h],
      ["low_24h", values?.low24h],
      ["oi_chg_24h_pct", undefined],
    ];
    for (const [column, value] of cases) expect(sortValue(column, btc)).toBe(value);
    expect(sortValue("last", undefined)).toBeUndefined();
  });

  it("calls every column live but Symbol, Rec and Status", () => {
    expect(["symbol", "rec", "status"].map(isLiveColumn)).toEqual([false, false, false]);
    expect(isLiveColumn("chg_24h_pct")).toBe(true);
  });
});

describe("the pane setting's form", () => {
  it("round-trips a sort, and reads nothing else as one", () => {
    const sort = { columnId: "chg_24h_pct", direction: "descending" } as const;
    expect(decodeSort(encodeSort(sort))).toEqual(sort);
    expect(encodeSort(null)).toBe("");
    expect(decodeSort("")).toBeNull();
    expect(decodeSort(undefined)).toBeNull();
    expect(decodeSort("last:sideways")).toBeNull();
  });
});
