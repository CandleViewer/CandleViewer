/**
 * E29-S01 (#911) row order: D01 D13 (a)'s default (env → account → symbol → side → position idx)
 * and F-04's header press (ascending, descending, default), whose order is a snapshot taken at the
 * press: later values never move a row, and a new row joins after the snapshot's rows.
 */
import { describe, expect, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import {
  accountInfo,
  mapRow,
  type AccountInfo,
  type ExchangeAccount,
  type PositionRowModel,
} from "../../../src/features/positions/model/rowMapping";
import {
  applySort,
  ariaSortOf,
  compareDefault,
  pressHeader,
  sortDefault,
} from "../../../src/features/positions/model/sort";
import { golden } from "./support/fakes";

const directory = new Map(
  golden<{ items: ExchangeAccount[] }>("rest_list_exchange_accounts.json")
    .items.map(accountInfo)
    .filter((a): a is AccountInfo => a !== null)
    .map((a) => [a.id, a]),
);
const rows = golden<generated.ws.Positions>("ws_positions_snapshot.json")
  .positions.map((item) => mapRow(item, "ws", directory))
  .filter((r): r is PositionRowModel => r !== null);
const label = (r: PositionRowModel): string => `${r.accountLabel ?? "?"} ${r.symbol}`;

describe("the default order (D01 D13 a)", () => {
  it("env → account → symbol → side → position idx", () => {
    expect(sortDefault([...rows].reverse()).map(label)).toEqual([
      "Main BTCUSDT",
      "Sub-1 BTCUSDT",
      "Sub-1 ETHUSDT",
      "Sub-2 BTCUSDT",
      "Sub-2 SOLUSDT",
    ]);
  });

  it("orders the side and the position idx last", () => {
    const base = rows[0] as PositionRowModel;
    const short = { ...base, side: "short", positionIdx: 2 } as PositionRowModel;
    const hedgeLong = { ...base, positionIdx: 1 } as PositionRowModel;
    expect(compareDefault(base, short)).toBeLessThan(0);
    expect(compareDefault(base, hedgeLong)).toBeLessThan(0);
    const demo = { ...base, environment: "demo" } as PositionRowModel;
    expect(compareDefault(base, demo)).toBeLessThan(0);
    expect(
      compareDefault({ ...base, environment: null } as PositionRowModel, demo),
    ).toBeGreaterThan(0);
  });
});

describe("F-04: the header press cycle and its snapshot", () => {
  it("ascending, then descending, then the default", () => {
    const up = pressHeader(null, "upnl", rows);
    expect(up?.direction).toBe("ascending");
    expect(applySort(rows, up).map((r) => r.unrealisedPnl)).toEqual([
      "-121.5",
      "-92",
      "-3.04",
      "2.7",
      "8",
    ]);
    const down = pressHeader(up, "upnl", rows);
    expect(down?.direction).toBe("descending");
    expect(applySort(rows, down).map((r) => r.unrealisedPnl)).toEqual([
      "8",
      "2.7",
      "-3.04",
      "-92",
      "-121.5",
    ]);
    expect(pressHeader(down, "upnl", rows)).toBeNull();
    expect(pressHeader(down, "symbol", rows)?.direction).toBe("ascending"); // another column starts over
  });

  it("is a snapshot: a later uPnL never moves a row, and a new row joins after", () => {
    const sort = pressHeader(null, "upnl", rows);
    const moved = rows.map((r) => (r.symbol === "SOLUSDT" ? { ...r, unrealisedPnl: "500" } : r));
    expect(applySort(moved, sort).map(label)).toEqual(applySort(rows, sort).map(label));
    const fresh = {
      ...(rows[0] as PositionRowModel),
      key: "new|XRPUSDT|0",
      symbol: "XRPUSDT",
      accountLabel: "Main",
    };
    expect(
      applySort([...moved, fresh], sort)
        .map(label)
        .at(-1),
    ).toBe("Main XRPUSDT");
    expect(applySort(moved.slice(1), sort)).toHaveLength(4); // a closed row just leaves
  });

  it("sorts decimals by value with the empty ones last, text by code point", () => {
    const withNull = rows.map((r, i) => (i === 0 ? { ...r, liqPrice: null } : r));
    const up = applySort(withNull, pressHeader(null, "liq_price", withNull));
    expect(up.at(-1)?.liqPrice).toBeNull();
    const down = applySort(
      withNull,
      pressHeader(pressHeader(null, "liq_price", withNull), "liq_price", withNull),
    );
    expect(down.at(-1)?.liqPrice).toBeNull();
    expect(applySort(rows, pressHeader(null, "account", rows)).map((r) => r.accountLabel)[0]).toBe(
      "Main",
    );
    for (const column of [
      "symbol",
      "side",
      "margin",
      "size",
      "entry",
      "mark",
      "r",
      "rpnl_today",
      "leverage",
    ] as const) {
      expect(applySort(rows, pressHeader(null, column, rows))).toHaveLength(5);
    }
  });

  it("the liquidation distance sorts through the panel's readings", () => {
    const distance = (r: PositionRowModel): string | null =>
      r.symbol === "SOLUSDT" ? "0.5" : "9.5";
    expect(applySort(rows, pressHeader(null, "liq_dist", rows, distance))[0]?.symbol).toBe(
      "SOLUSDT",
    );
  });

  it("aria-sort names the pressed column only", () => {
    const sort = pressHeader(null, "mark", rows);
    expect(ariaSortOf(sort, "mark")).toBe("ascending");
    expect(ariaSortOf(sort, "upnl")).toBe("none");
    expect(ariaSortOf(null, "mark")).toBe("none");
  });
});
