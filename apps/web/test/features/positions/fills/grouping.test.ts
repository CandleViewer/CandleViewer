/**
 * E29-S04 (#979) grouping and the view on the goldens (E29-D02 §6.4, D02:299; E29-D03 §3.5): by
 * order inside the panel's group-by, newest first, the fills of no order by type after the
 * orders; "Show every fill"; account sections in the legs' order with a Manager's legs only; the
 * Type chips; and the two empty states (BQ-13).
 */
import { describe, expect, it } from "vitest";
import type { FillKind } from "../../../../src/features/positions/fills/model/fillRow";
import {
  accountSections,
  applyTypeFilter,
  groupFills,
  TYPE_CHIPS,
} from "../../../../src/features/positions/fills/model/grouping";
import { PROPOSED_TEXT } from "../../../../src/features/positions/fills/copy";
import {
  buildFillsView,
  typeWord,
  TYPE_WORDS,
} from "../../../../src/features/positions/fills/view";
import { MAIN, SUB1, SUB2 } from "../support/fakes";
import { GROUP_7C1E, restItems, rowsOf, snapshotBody } from "./support/fills";

const rest = rowsOf(restItems(), "rest");
const LABELS: Record<string, string> = { [MAIN]: "Main", [SUB1]: "Sub-1", [SUB2]: "Sub-2" };
const labelOf = (id: string): string | null => LABELS[id] ?? null;
const tail = (id: string): string => id.slice(-4);
const ALL = new Set<FillKind>(TYPE_CHIPS);

describe("grouped by order under the panel's group-by (account, the default)", () => {
  const groups = groupFills(rest, "account", false, labelOf);

  it("one group per account in label order, each fill once", () => {
    expect(groups.map((g) => labelOf(g.key ?? ""))).toEqual(["Main", "Sub-1", "Sub-2"]);
    expect(groups.reduce((n, g) => n + g.rows.length, 0)).toBe(rest.length);
  });

  it("orders newest first by their newest fill; an order's fills newest first, ties by id", () => {
    const [main] = groups;
    expect(main?.orders.map((o) => tail(o.orderId))).toEqual(["4c01", "a3f2", "5a01", "6d01"]);
    const board02 = main?.orders.find((o) => tail(o.orderId) === "a3f2");
    expect(board02?.rows.map((r) => tail(r.execId))).toEqual(["0007", "0006", "0005", "0004"]);
    expect(board02?.sums).toMatchObject({ fills: 4, trades: 4 });
  });

  it("the fills of no order follow the orders, grouped by type (D03:173)", () => {
    const sub2 = groups.find((g) => g.key === SUB2);
    expect(sub2?.orders.map((o) => tail(o.orderId))).toEqual(["4c03"]);
    expect(sub2?.noOrder.map((s) => [s.kind, s.rows.map((r) => tail(r.execId))])).toEqual([
      ["adl", ["0014"]],
    ]);
  });

  it("Show every fill lists the fills without order rows, newest first", () => {
    const [main] = groupFills(rest, "account", true, labelOf);
    expect(main?.orders).toEqual([]);
    expect(main?.noOrder).toEqual([]);
    const times = main?.rows.map((r) => r.tsMs) ?? [];
    expect(times).toEqual([...times].sort((a, b) => b - a));
  });
});

describe("the other group-bys keep a stable group order", () => {
  it("by symbol: one BTCUSDT group", () => {
    expect(groupFills(rest, "symbol", false).map((g) => [g.key, g.rows.length])).toEqual([
      ["BTCUSDT", rest.length],
    ]);
  });

  it("by trade group: …7c1e, then the fills of none; a WS fill's group is unknown until REST", () => {
    expect(groupFills(rest, "trade_group", false).map((g) => [g.key, g.rows.length])).toEqual([
      [GROUP_7C1E, 4],
      [null, rest.length - 4],
    ]);
    const ws = rowsOf(snapshotBody().executions, "ws");
    expect(groupFills(ws, "trade_group", false).map((g) => g.key)).toEqual([null]);
  });
});

describe("account sections (SCR-078's trade-group scope, D03 §3.5, D-8)", () => {
  const legs = rest.filter((r) => r.tradeGroupId === GROUP_7C1E);

  it("follow the legs' order, each with its sums", () => {
    const sections = accountSections(legs, [SUB2, MAIN, SUB1]);
    expect(sections.map((s) => [labelOf(s.accountId), s.sums.fills])).toEqual([
      ["Sub-2", 1],
      ["Main", 2],
      ["Sub-1", 1],
    ]);
  });

  it("a Manager's rows give their legs alone: no section, count or sum of Main's", () => {
    const mine = legs.filter((r) => r.accountId !== MAIN);
    const sections = accountSections(mine, [MAIN, SUB1, SUB2]);
    expect(sections.map((s) => labelOf(s.accountId))).toEqual(["Sub-1", "Sub-2"]);
    expect(sections.reduce((n, s) => n + s.sums.fills, 0)).toBe(2);
  });
});

describe("the Type chips (D02:299)", () => {
  it("all on keeps every row; a chip hides what it names and nothing else", () => {
    expect(applyTypeFilter(rest, ALL)).toBe(rest);
    const noTrades = applyTypeFilter(rest, new Set<FillKind>(["adl"]));
    expect(noTrades.map((r) => tail(r.execId))).toEqual(["0014"]);
    const [first] = rest;
    if (first === undefined) throw new Error("golden");
    const odd = [{ ...first, type: { kind: "missing" as const } }];
    expect(applyTypeFilter(odd, new Set<FillKind>())).toEqual(odd);
  });

  it("type words: D03 §3.3's, a value the enum lacks by its raw name, none as —", () => {
    expect(TYPE_CHIPS.map((k) => TYPE_WORDS[k])).toEqual([
      "Trade",
      "ADL",
      "Liquidation",
      "Funding",
      "Settlement",
    ]);
    expect(typeWord({ kind: "other", name: "SessionSettlePnl" })).toBe("SessionSettlePnl");
    expect(typeWord({ kind: "missing" })).toBe("—");
  });
});

describe("Empty state: an explicit empty state naming the active filter", () => {
  const base = { types: ALL, groupBy: "account" as const, everyFill: false, labelOf };

  it("no fill at all is empty, never filter-empty", () => {
    expect(buildFillsView({ ...base, rows: [] })).toMatchObject({
      empty: true,
      filterEmpty: false,
      typeFilter: null,
      groups: [],
    });
  });

  it("chips that leave none are filter-empty and restate the pressed types", () => {
    const view = buildFillsView({ ...base, rows: rest, types: new Set<FillKind>(["funding"]) });
    expect(view).toMatchObject({ empty: false, filterEmpty: true, rows: [] });
    expect(view.typeFilter).toBe("Type: Funding");
  });

  it("with no chip pressed the restatement is PROPOSED's 'Type: none', never 'Type: '", () => {
    const view = buildFillsView({ ...base, rows: rest, types: new Set<FillKind>() });
    expect(view.typeFilter).toBe(PROPOSED_TEXT.typeFilterNone.string);
  });

  it("the rows the chips leave are the shown ones, newest first", () => {
    const view = buildFillsView({ ...base, rows: rest });
    expect(view.rows).toHaveLength(rest.length);
    expect(view.groups).toHaveLength(3);
  });

  it("the export takes every held fill the chips leave, the held-back new ones too (D-21)", () => {
    const [newest, ...shown] = rest; // the ADL fill, held back above the top
    const view = buildFillsView({ ...base, rows: shown, all: rest });
    expect([view.rows.length, view.exportRows.length]).toEqual([rest.length - 1, rest.length]);
    expect(view.exportRows[0]).toBe(newest);
  });

  it("the export's rows pass the chips too", () => {
    const view = buildFillsView({
      ...base,
      rows: [],
      all: rest,
      types: new Set<FillKind>(["adl"]),
    });
    expect(view.exportRows.map((r) => tail(r.execId))).toEqual(["0014"]);
  });
});
