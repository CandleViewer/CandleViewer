/**
 * E29-S01 (#911) the FilterBar's chip reducer (US-POS-006, E29-D02 §9.1): add, remove, "Clear
 * all" from two chips, normalisation and bounds, and what the chips leave in view (one kind is an
 * alternative, kinds narrow together).
 */
import { describe, expect, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import {
  applyFilters,
  MAX_CHIPS,
  normaliseChip,
  reduceFilters,
  showsClearAll,
  type FilterChip,
} from "../../../src/features/positions/model/filters";
import { mapRow, type PositionRowModel } from "../../../src/features/positions/model/rowMapping";
import { golden, GROUP, MAIN, SUB1, SUB2 } from "./support/fakes";

const rows = golden<generated.ws.Positions>("ws_positions_contract_fields.json")
  .positions.map((item) => mapRow(item, "ws", new Map()))
  .filter((r): r is PositionRowModel => r !== null);
const account = (value: string): FilterChip => ({ kind: "account", value });
const symbol = (value: string): FilterChip => ({ kind: "symbol", value });

describe("reduceFilters", () => {
  it("adds a chip once, removes it, and clears all", () => {
    let chips = reduceFilters([], { type: "add", chip: account(SUB1) });
    expect(reduceFilters(chips, { type: "add", chip: account(SUB1) })).toBe(chips); // no duplicate
    chips = reduceFilters(chips, { type: "add", chip: symbol("BTCUSDT") });
    expect(chips).toEqual([account(SUB1), symbol("BTCUSDT")]);
    expect(showsClearAll(chips)).toBe(true);
    chips = reduceFilters(chips, { type: "remove", chip: account(SUB1) });
    expect(chips).toEqual([symbol("BTCUSDT")]);
    expect(showsClearAll(chips)).toBe(false);
    expect(reduceFilters(chips, { type: "remove", chip: account(SUB2) })).toBe(chips);
    expect(reduceFilters(chips, { type: "clear" })).toEqual([]);
    const none: readonly FilterChip[] = [];
    expect(reduceFilters(none, { type: "clear" })).toBe(none);
  });

  it("normalises an account id to lower case and refuses what names nothing", () => {
    expect(normaliseChip(account(SUB1.toUpperCase()))).toEqual(account(SUB1));
    expect(normaliseChip({ kind: "trade_group", value: GROUP })).toEqual({
      kind: "trade_group",
      value: GROUP,
    });
    expect(normaliseChip({ kind: "side", value: "long" })).toEqual({ kind: "side", value: "long" });
    for (const bad of [
      account("Sub-1"),
      symbol("btcusdt"),
      { kind: "side", value: "flat" },
      { kind: "env", value: "live" }, // one environment per server (BQ-7)
      { kind: "manager", value: MAIN }, // no Manager (BQ-10)
      { kind: "symbol", value: 1 },
      null,
      "account:x",
    ]) {
      expect(normaliseChip(bad)).toBeNull();
    }
  });

  it("replace tidies a stored or linked list: valid, unique, bounded", () => {
    const many = Array.from({ length: MAX_CHIPS + 5 }, (_, i) =>
      symbol(`T${String(i).padStart(2, "0")}USDT`),
    );
    const chips = reduceFilters([], {
      type: "replace",
      chips: [...many, many[0] as FilterChip, account("bad")],
    });
    expect(chips).toHaveLength(MAX_CHIPS);
    expect(reduceFilters(chips, { type: "add", chip: symbol("XRPUSDT") })).toBe(chips);
  });
});

describe("applyFilters: filter and clear", () => {
  it("one account leaves its rows", () => {
    expect(applyFilters(rows, [account(SUB1)]).map((r) => r.symbol)).toEqual([
      "BTCUSDT",
      "ETHUSDT",
    ]);
  });

  it("chips of one kind are alternatives; kinds narrow together", () => {
    expect(applyFilters(rows, [account(SUB1), account(SUB2)])).toHaveLength(4);
    expect(
      applyFilters(rows, [account(SUB1), account(SUB2), symbol("BTCUSDT")]).map((r) => r.accountId),
    ).toEqual([SUB1, SUB2]);
    expect(applyFilters(rows, [{ kind: "side", value: "short" }]).map((r) => r.symbol)).toEqual([
      "ETHUSDT",
    ]);
    expect(
      applyFilters(rows, [{ kind: "trade_group", value: GROUP }]).map((r) => r.accountId),
    ).toEqual([MAIN, SUB1]);
  });

  it("no chip leaves every row; clearing restores them", () => {
    expect(applyFilters(rows, [])).toBe(rows);
    const chips = reduceFilters([account(MAIN)], { type: "clear" });
    expect(applyFilters(rows, chips)).toHaveLength(5);
  });
});
