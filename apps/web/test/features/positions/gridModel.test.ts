/**
 * E29-S01 (#911) the grid's model: the model's groups and totals as CMP-114 draws them, with D02's
 * words (account headers "Main · LIVE" with the position mode, symbol and trade-group headers, the
 * totals label per environment), the FilterBar's chip words (D02:375, :380) and the state lines
 * (D02 §10.1) the tab shows and the panel says.
 */
import { describe, expect, it } from "vitest";
import {
  accountWords,
  chipLabel,
  chipsRestated,
  envWord,
  failedLines,
  filterEmptyTitle,
  gridGroups,
  gridRow,
  gridTotals,
  idStub,
  loadingLine,
  totalsLabel,
  tradeGroupLabel,
  withdrawnLine,
} from "../../../src/features/positions/gridModel";
import { groupRows, totalsOf } from "../../../src/features/positions/model/grouping";
import type { LiqReading } from "../../../src/features/positions/model/liqTier";
import {
  accountInfo,
  mapRow,
  type AccountInfo,
  type ExchangeAccount,
  type PositionRowModel,
  type WsPosition,
} from "../../../src/features/positions/model/rowMapping";
import { golden, GROUP, MAIN, SUB1, SUB2 } from "./support/fakes";

const directory = new Map(
  golden<{ items: ExchangeAccount[] }>("rest_list_exchange_accounts.json")
    .items.map(accountInfo)
    .filter((a): a is AccountInfo => a !== null)
    .map((a) => [a.id, a]),
);
const rows = golden<{ positions: WsPosition[] }>("ws_positions_contract_fields.json")
  .positions.map((p) => mapRow(p, "ws", directory))
  .filter((r): r is PositionRowModel => r !== null);
const near: LiqReading = {
  tier: "near",
  basis: "buffer",
  distancePct: "1.2",
  sharePct: "27",
  mmRatePct: null,
  mmRateStale: null,
  mmRateStaleSinceMs: null,
};

describe("the environment's words", () => {
  it("LIVE and DEMO (D02:238, :209); TESTNET PROPOSED; a dash while unknown", () => {
    expect([envWord("live"), envWord("demo"), envWord("testnet"), envWord(null)]).toEqual([
      "LIVE",
      "DEMO",
      "TESTNET",
      "—",
    ]);
    expect([totalsLabel("live"), totalsLabel("demo"), totalsLabel("testnet")]).toEqual([
      "LIVE total",
      "DEMO total",
      "TESTNET total",
    ]);
    expect(totalsLabel(null)).toBeNull();
  });
});

describe("names", () => {
  it("an id's stub, a trade group's words, an account's label else its stub", () => {
    expect(idStub(GROUP)).toBe("…0001");
    expect(tradeGroupLabel(GROUP)).toBe("Trade group …0001");
    expect(tradeGroupLabel(null)).toBe("No trade group");
    expect(accountWords(SUB1, directory)).toBe("Sub-1");
    expect(accountWords("a1000000-0000-4000-8000-000000000099", directory)).toBe("…0099");
  });
});

describe("gridGroups", () => {
  it("account headers read 'Main · LIVE' with the position mode and the marker; rows carry their reading", () => {
    const groups = gridGroups({
      groups: groupRows(rows, "account", () => null),
      accounts: directory,
      liq: new Map([[rows[2]?.key ?? "", near]]),
      environment: "live",
      markerOf: (id) => (id === SUB2 ? "marker" : undefined),
    });
    expect(groups.map((g) => [g.label, g.positionMode, g.marker])).toEqual([
      ["Main · LIVE", "one-way", undefined],
      ["Sub-1 · LIVE", "one-way", undefined],
      ["Sub-2 · LIVE", "hedge", "marker"],
    ]);
    expect(groups[1]?.rows.map((r) => r.liq.tier)).toEqual(["none", "near"]);
    expect(groups[1]?.rows[0]?.liq).toEqual({ tier: "none", distancePct: null });
  });

  it("an account the directory does not name reads its stub and the session's environment", () => {
    const stray = {
      ...(rows[0] as PositionRowModel),
      accountId: "a1000000-0000-4000-8000-000000000099",
    };
    const [group] = gridGroups({
      groups: groupRows([stray], "account", () => null),
      accounts: directory,
      liq: new Map(),
      environment: "demo",
    });
    expect(group?.label).toBe("…0099 · DEMO");
    expect(group).not.toHaveProperty("positionMode");
  });

  it("symbol and trade-group headers read their key; the positions with none read 'No trade group'", () => {
    const bySymbol = gridGroups({
      groups: groupRows(rows, "symbol", () => null),
      accounts: directory,
      liq: new Map(),
      environment: "live",
    });
    expect(bySymbol.map((g) => g.label)).toEqual(["BTCUSDT", "ETHUSDT", "SOLUSDT"]);
    const byGroup = gridGroups({
      groups: groupRows(rows, "trade_group", () => null),
      accounts: directory,
      liq: new Map(),
      environment: "live",
    });
    expect(byGroup.map((g) => [g.label, g.count, g.netSize])).toEqual([
      ["Trade group …0001", 2, "0.35"],
      ["No trade group", 3, null],
    ]);
  });
});

describe("gridTotals", () => {
  it("one labelled row of the model's figures; none while empty or the environment is unknown", () => {
    const totals = totalsOf(rows, "live", () => null);
    expect(gridTotals(totals, "live")).toEqual({
      label: "LIVE total",
      count: 5,
      exposure: totals.exposure,
      unrealisedPnl: totals.unrealisedPnl,
      realisedToday: totals.realisedToday,
    });
    expect(gridTotals(totals, null)).toBeUndefined();
    expect(
      gridTotals(
        totalsOf([], "live", () => null),
        "live",
      ),
    ).toBeUndefined();
  });

  it("gridRow puts the reading beside the model's row", () => {
    const row = rows[0] as PositionRowModel;
    expect(gridRow(row, near)).toEqual({ ...row, liq: near });
  });
});

describe("chip words (D02:375, :380)", () => {
  it("Account, Symbol, Side and a trade group's stub", () => {
    expect(chipLabel({ kind: "account", value: MAIN }, directory)).toBe("Account: Main");
    expect(chipLabel({ kind: "symbol", value: "SOLUSDT" }, directory)).toBe("Symbol: SOLUSDT");
    expect(chipLabel({ kind: "side", value: "short" }, directory)).toBe("Side: Short");
    expect(chipLabel({ kind: "side", value: "long" }, directory)).toBe("Side: Long");
    expect(chipLabel({ kind: "trade_group", value: GROUP }, directory)).toBe("Trade group: …0001");
    expect(
      chipsRestated(
        [
          { kind: "account", value: SUB1 },
          { kind: "symbol", value: "SOLUSDT" },
        ],
        directory,
      ),
    ).toBe("Account: Sub-1 · Symbol: SOLUSDT");
  });
});

describe("the state lines (D02 §10.1)", () => {
  const accounts = [...directory.values()];

  it("Loading and Could not load per account; one panel line while the directory is unknown", () => {
    expect(accounts.map(loadingLine)).toEqual([
      "Loading Main · LIVE…",
      "Loading Sub-1 · LIVE…",
      "Loading Sub-2 · LIVE…",
    ]);
    expect(failedLines(accounts.slice(0, 2), "live")).toEqual([
      "Could not load Main · LIVE",
      "Could not load Sub-1 · LIVE",
    ]);
    expect(failedLines([], "demo")).toEqual(["Could not load Positions · DEMO"]);
  });

  it("an account withdrawn by its label, else its stub; filter-empty's singular is PROPOSED", () => {
    expect(withdrawnLine({ accountId: SUB2, label: "Sub-2" }, directory)).toBe(
      "No longer shown — access to Sub-2 was withdrawn.",
    );
    expect(withdrawnLine({ accountId: SUB2, label: null }, new Map())).toBe(
      "No longer shown — access to …0003 was withdrawn.",
    );
    expect(filterEmptyTitle(1)).toBe("No rows match 1 filter");
    expect(filterEmptyTitle(2)).toBe("No rows match 2 filters");
  });
});
