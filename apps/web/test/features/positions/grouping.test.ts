/**
 * E29-S01 (#911, BQ-10, BQ-12) grouping and aggregation on the goldens: group rows show the
 * count, uPnL, rPnL today and, for one symbol only, the net size; one totals row with E29-D02
 * §5.2's arithmetic (exposure 34,322.66, uPnL −205.84, rPnL today +34.40 from the accounts'
 * figures); the trade-group criterion proven on contract-valid frames carrying `trade_group_id`.
 */
import { describe, expect, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import { groupRows, netSize, totalsOf } from "../../../src/features/positions/model/grouping";
import {
  accountInfo,
  mapRow,
  type AccountInfo,
  type ExchangeAccount,
  type PositionRowModel,
} from "../../../src/features/positions/model/rowMapping";
import { pressHeader } from "../../../src/features/positions/model/sort";
import { buildPositionsView } from "../../../src/features/positions/model/view";
import { golden, GROUP, MAIN, SUB1, SUB2 } from "./support/fakes";

const directory = new Map(
  golden<{ items: ExchangeAccount[] }>("rest_list_exchange_accounts.json")
    .items.map(accountInfo)
    .filter((a): a is AccountInfo => a !== null)
    .map((a) => [a.id, a]),
);
const rowsOf = (name: string): PositionRowModel[] =>
  golden<generated.ws.Positions>(name)
    .positions.map((item) => mapRow(item, "ws", directory))
    .filter((r): r is PositionRowModel => r !== null);
const rows = rowsOf("ws_positions_snapshot.json");
const extended = rowsOf("ws_positions_contract_fields.json");
/** D02 §5.2's accounts' `realised_pnl_today` (Main +37.40, Sub-1 +3.20, Sub-2 −6.20). */
const today: Record<string, string> = { [MAIN]: "37.40", [SUB1]: "3.20", [SUB2]: "-6.20" };
const realisedToday = (id: string): string | null => today[id] ?? null;
const none = (): null => null;

describe("Grouping by account (the default)", () => {
  const groups = groupRows(rows, "account", realisedToday);

  it("one group per account, in the default order", () => {
    expect(groups.map((g) => [g.key, g.count])).toEqual([
      [MAIN, 1],
      [SUB1, 2],
      [SUB2, 2],
    ]);
  });

  it("aggregates uPnL, takes the account's rPnL today, and a net size only on one symbol", () => {
    expect(groups.map((g) => g.unrealisedPnl)).toEqual(["8", "-118.8", "-95.04"]);
    expect(groups.map((g) => g.realisedToday)).toEqual(["37.40", "3.20", "-6.20"]);
    expect(groups.map((g) => g.netSize)).toEqual(["0.25", null, null]);
  });

  it("an account whose figure is not served reads '—'", () => {
    expect(groupRows(rows, "account", none).map((g) => g.realisedToday)).toEqual([
      null,
      null,
      null,
    ]);
  });
});

describe("Grouping by symbol", () => {
  const groups = groupRows(rows, "symbol", realisedToday);

  it("nets the size of one symbol across accounts (AggregatePosition.net_size)", () => {
    expect(groups.map((g) => [g.key, g.count, g.netSize, g.unrealisedPnl])).toEqual([
      ["BTCUSDT", 3, "0.43", "7.66"],
      ["ETHUSDT", 1, "-1.5", "-121.5"],
      ["SOLUSDT", 1, "20", "-92"],
    ]);
  });

  it("rPnL today sums the positions' realised_pnl_session, '—' when one is missing", () => {
    expect(groups.map((g) => g.realisedToday)).toEqual([null, null, null]);
    expect(groupRows(extended, "symbol", none).map((g) => g.realisedToday)).toEqual([
      "12.4",
      "-18.2",
      "0",
    ]);
  });
});

describe("Grouping by trade group: group rows aggregate size and PnL and expand to per-account rows", () => {
  const groups = groupRows(extended, "trade_group", none);

  it("one group per trade group, the positions with none last", () => {
    expect(groups.map((g) => [g.key, g.rows.map((r) => r.accountLabel)])).toEqual([
      [GROUP, ["Main", "Sub-1"]],
      [null, ["Sub-1", "Sub-2", "Sub-2"]],
    ]);
  });

  it("the trade group's row aggregates size and PnL", () => {
    expect(groups[0]).toMatchObject({
      count: 2,
      netSize: "0.35",
      unrealisedPnl: "10.7",
      symbols: ["BTCUSDT"],
    });
    expect(groups[1]).toMatchObject({ netSize: null, symbols: ["ETHUSDT", "SOLUSDT", "BTCUSDT"] });
  });

  it("live frames, which carry no trade_group_id yet, fall into one ungrouped group", () => {
    expect(groupRows(rows, "trade_group", none).map((g) => [g.key, g.count])).toEqual([[null, 5]]);
  });
});

describe("Rows render the whole book: the TOTAL row (D-15)", () => {
  it("counts, sums the exposure and uPnL, and takes rPnL today from the accounts", () => {
    expect(totalsOf(rows, "live", realisedToday)).toEqual({
      environment: "live",
      count: 5,
      exposure: "34322.66",
      unrealisedPnl: "-205.84",
      realisedToday: "34.40",
    });
  });

  it("never sums a size across symbols, and reads '—' for a missing account figure", () => {
    const totals = totalsOf(rows, "live", (id) => (id === SUB2 ? null : realisedToday(id)));
    expect(totals).not.toHaveProperty("size");
    expect(totals.realisedToday).toBeNull();
  });

  it("an exposure with an unpriced row is '—'", () => {
    const unpriced = { ...rows[0], mark: null, notional: null } as PositionRowModel;
    expect(totalsOf([unpriced], "live", realisedToday).exposure).toBeNull();
    expect(totalsOf([], "live", realisedToday)).toMatchObject({ count: 0, realisedToday: null });
  });

  it("netSize is null across symbols and for no rows", () => {
    expect(netSize(rows)).toBeNull();
    expect(netSize([])).toBeNull();
  });
});

describe("the view", () => {
  const base = {
    rows,
    chips: [],
    groupBy: "account" as const,
    sort: null,
    environment: "live" as const,
    realisedToday,
  };

  it("a header sort orders rows within groups and never moves a group", () => {
    const sort = pressHeader(null, "upnl", rows);
    const view = buildPositionsView({ ...base, sort });
    expect(view.groups.map((g) => g.key)).toEqual([MAIN, SUB1, SUB2]);
    expect(view.groups[1]?.rows.map((r) => r.symbol)).toEqual(["ETHUSDT", "BTCUSDT"]);
  });

  it("Empty state: no positions is empty, never filter-empty", () => {
    expect(buildPositionsView({ ...base, rows: [] })).toMatchObject({
      empty: true,
      filterEmpty: false,
      groups: [],
    });
  });

  it("filters that leave nothing are filter-empty; the totals follow the rows in view", () => {
    const view = buildPositionsView({ ...base, chips: [{ kind: "symbol", value: "XRPUSDT" }] });
    expect(view).toMatchObject({ empty: false, filterEmpty: true, rows: [] });
    const sub1 = buildPositionsView({ ...base, chips: [{ kind: "account", value: SUB1 }] });
    expect(sub1.totals).toMatchObject({ count: 2, unrealisedPnl: "-118.8", realisedToday: "3.20" });
  });
});
