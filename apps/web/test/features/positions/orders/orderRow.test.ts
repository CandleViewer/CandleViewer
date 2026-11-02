/**
 * E29-S02 (#912) the row model: BQ-7's state (every `lifecycle_state` and `state` value, null and
 * an unknown string), Type · Purpose, BQ-17's trigger words, the flags, Parent, the age formatter
 * and BQ-5's native-stop classification, read against E29-D02 §6.2's fixture rows as the shipped
 * mappers serve them (the goldens).
 */
import { describe, expect, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import {
  constantsOf,
  derivedDirection,
  flagsWords,
  formatAge,
  LIFECYCLE_OF_STATE,
  mapOrder,
  NO_CONSTANTS,
  parentWords,
  priceLabel,
  protectiveOf,
  resolveState,
  sideGlyph,
  sideWords,
  stateLabel,
  tifWords,
  triggerLabel,
  triggerWords,
  typeWords,
  type AlgoKind,
  type LifecycleState,
  type OrderRowModel,
  type OrderState,
  type RestOrder,
  type WsOrder,
} from "../../../../src/features/positions/orders/model/orderRow";
import { repoFile } from "../../../lib/ws/support/schemaHarness";
import {
  BRACKET,
  COND,
  directory,
  ENTRY,
  ETH,
  golden,
  HELD,
  MAIN,
  restOpen,
  snapshotBody,
  STOP,
  SUB1,
  SUB2,
  TP,
  UNTRACKED,
  wsItem,
  type OrdersBody,
} from "./support/orders";

type Schemas = generated.rest.components["schemas"];
const LIFECYCLES: readonly LifecycleState[] = [
  "draft",
  "validated",
  "submitting",
  "submitted",
  "triggered",
  "partially_filled",
  "cancel_pending",
  "amend_pending",
  "unknown",
  "quarantined",
  "untracked",
  "held",
  "filled",
  "cancelled",
  "rejected",
  "expired",
  "killed",
] satisfies readonly Schemas["OrderLifecycleState"][];
const STATES = Object.keys(LIFECYCLE_OF_STATE) as OrderState[];

/** D01 D2's word for each B1 state (D01:177–191), as the Gherkin's vocabulary row reads it. */
const WORDS: Readonly<Record<LifecycleState, string | null>> = {
  draft: null,
  validated: null,
  submitting: "Sending",
  submitted: "Working",
  triggered: "Triggered",
  partially_filled: "Partial",
  cancel_pending: "Cancelling",
  amend_pending: "Amending",
  unknown: "Unknown — checking",
  quarantined: "Quarantined",
  untracked: "Untracked — not placed by CandleViewer",
  held: "Held — owner review",
  filled: "Filled",
  cancelled: "Cancelled",
  rejected: "Rejected",
  expired: "Expired",
  killed: "Killed (kill switch)",
};

/** READ_AT of the generator: the snapshot read's start (2026-10-31T14:02:11Z). */
const READ_AT = Date.UTC(2026, 9, 31, 14, 2, 11);
const NOW = READ_AT;
const dir = directory();
const rest = new Map(restOpen().map((o) => [o.id, o]));
const constantsFor = (id: string) => {
  const order = rest.get(id);
  return order === undefined ? NO_CONSTANTS : constantsOf(order);
};
const snapshot = snapshotBody();
const wsRow = (id: string, body: OrdersBody = snapshot): OrderRowModel => {
  const row = mapOrder(wsItem(body, id), "ws", dir, constantsFor(id));
  if (row === null) throw new Error(`unmapped ${id}`);
  return row;
};

describe("the state (BQ-7): lifecycle_state, else state through 24 §8.2, else not reported", () => {
  it("LIFECYCLE_OF_STATE is 24 §8.2's table, one to one", () => {
    const doc = repoFile("docs/plan/24-internal-schemas.md");
    const pairs = [...doc.matchAll(/^\| `([a-z_]+)`\s+\| `([a-z_]+)`\s+\|$/gm)].map((m) => [
      m[2],
      m[1],
    ]);
    expect(Object.fromEntries(pairs)).toEqual(LIFECYCLE_OF_STATE);
    expect(new Set(Object.values(LIFECYCLE_OF_STATE)).size).toBe(17);
  });

  it.each(LIFECYCLES)("lifecycle_state %s reads its D01 D2 word", (chart) => {
    const state = resolveState(chart, "accepted");
    expect(state.from).toBe("lifecycle_state");
    expect(state.lifecycle).toBe(chart);
    const word = WORDS[chart];
    if (word === null) expect(state.hidden).toBe(true);
    else expect(state.word).toBe(word);
  });

  it.each(STATES)("with a null lifecycle_state, state %s is mapped through 24 §8.2", (stored) => {
    for (const lifecycle of [null, undefined]) {
      const state = resolveState(lifecycle, stored);
      expect(state.from).toBe("state");
      expect(state.lifecycle).toBe(LIFECYCLE_OF_STATE[stored]);
    }
  });

  it("the two `submitted` are different states: the stored one is Sending, the chart's Working", () => {
    expect(resolveState(null, "submitted").word).toBe("Sending");
    expect(resolveState("submitted", null).word).toBe("Working");
    expect(resolveState(null, "accepted").word).toBe("Working");
  });

  it.each([
    ["both null", null, null],
    ["an unknown state", null, "suspended"],
    ["an unknown lifecycle_state, whatever state says", "paused", "filled"],
    ["a number", 3, 4],
  ])("%s reads 'Working — state not reported', live (23 §15.1)", (_, lifecycle, stored) => {
    const state = resolveState(lifecycle, stored);
    expect(state).toEqual({
      lifecycle: null,
      from: "none",
      word: "Working — state not reported",
      family: "active",
      terminal: false,
      hidden: false,
    });
  });

  it("families: in flight, checking, critical, untracked and the five terminal states", () => {
    const family = (chart: LifecycleState) => resolveState(chart, null).family;
    expect(
      ["submitting", "cancel_pending", "amend_pending"].map((c) => family(c as LifecycleState)),
    ).toEqual(["in_flight", "in_flight", "in_flight"]);
    expect(family("unknown")).toBe("checking");
    expect([family("held"), family("quarantined")]).toEqual(["critical", "critical"]);
    expect(family("untracked")).toBe("untracked");
    const terminal = LIFECYCLES.filter((c) => resolveState(c, null).terminal);
    expect(terminal).toEqual(["filled", "cancelled", "rejected", "expired", "killed"]);
  });

  it("Partial carries its figures: 0.050/0.150 at the cell's lot", () => {
    const entry = wsRow(ENTRY);
    expect(stateLabel(entry)).toBe("Partial 0.05/0.15");
    expect(stateLabel(entry, (d) => Number.parseFloat(d).toFixed(3))).toBe("Partial 0.050/0.150");
    expect(stateLabel(wsRow(TP))).toBe("Working");
  });
});

describe("Rows carry the full order vocabulary", () => {
  it("each row shows account, symbol, side, type, quantity, filled quantity, price, trigger, TIF, flags, age and its parent", () => {
    // as the tab shows it: the topic's row with REST's creation constants (BQ-6)
    const r = wsRow(ENTRY);
    expect({
      account: r.accountLabel,
      symbol: r.symbol,
      side: r.sideLabel,
      type: r.typeLabel,
      qty: r.qty,
      filled: r.filledQty,
      price: priceLabel(r),
      trigger: triggerLabel(r),
      tif: r.tifLabel,
      flags: r.flagsLabel,
      age: formatAge(r.createdAtMs, NOW),
      parent: r.parentLabel,
      state: stateLabel(r),
    }).toEqual({
      account: "Sub-1",
      symbol: "BTCUSDT",
      side: "Buy",
      type: "Limit · Entry",
      qty: "0.15",
      filled: "0.05",
      price: "63950",
      trigger: "—",
      tif: "GTC",
      flags: "—",
      age: "4 m",
      parent: "#7c1e",
      state: "Partial 0.05/0.15",
    });
    expect(r.tradeGroupId).toBe("0c000000-0000-4000-8000-000000000001");
    expect(r.sideGlyph).toBe("▲"); // drawn before the word, apart from it (D02:263)
  });

  it("a REST row alone names the leg: the REST mapper serves no parent_order_id today", () => {
    const row = mapOrder(rest.get(ENTRY) as RestOrder, "rest", dir, constantsFor(ENTRY));
    expect(rest.get(ENTRY)).not.toHaveProperty("parent_order_id");
    expect(row).toMatchObject({ parentLabel: "Group leg", qty: "0.150", filledQty: "0.050" });
    expect(stateLabel(row as OrderRowModel)).toBe("Partial 0.050/0.150");
  });

  it("D02 §6.2's rows, as the topic serves them", () => {
    const tp = wsRow(TP);
    expect([tp.sideGlyph, tp.sideLabel, tp.typeLabel, tp.flagsLabel, priceLabel(tp)]).toEqual([
      "▼",
      "Sell",
      "Limit · Take profit",
      "Reduce-only",
      "64800",
    ]);
    expect(formatAge(tp.createdAtMs, NOW)).toBe("1 h 12 m");
    expect(wsRow(ETH).tifLabel).toBe("Post-only");
    expect(formatAge(wsRow(ETH).createdAtMs, NOW)).toBe("38 s");
    const cond = wsRow(COND);
    expect([triggerLabel(cond), cond.conditional, formatAge(cond.createdAtMs, NOW)]).toEqual([
      "Last rises to 64500",
      true,
      "9 m",
    ]);
    const stop = wsRow(STOP);
    expect([stop.typeLabel, priceLabel(stop), stop.flagsLabel]).toEqual([
      "Market · Stop loss",
      "Market",
      "Reduce-only · Close on trigger",
    ]);
    expect(formatAge(stop.createdAtMs, NOW)).toBe("2 h 05 m");
  });

  it("without REST's constants the topic gives no Age and no provenance (WS sends neither)", () => {
    const bare = mapOrder(wsItem(snapshot, TP), "ws", dir);
    expect(bare?.createdAtMs).toBeNull();
    expect(formatAge(bare?.createdAtMs ?? null, NOW)).toBe("—");
    expect(bare?.provenance).toBeNull();
  });

  it("the account's label and environment come from the directory; an unknown account keeps its row", () => {
    expect(wsRow(TP)).toMatchObject({ accountId: MAIN, accountLabel: "Main", environment: "live" });
    const foreign = mapOrder(wsItem(snapshot, TP), "ws", new Map());
    expect(foreign).toMatchObject({ accountLabel: null, environment: "live", baseCoin: "BTC" });
  });

  it("an item naming no order is dropped, never guessed", () => {
    const item = wsItem(snapshot, TP);
    for (const bad of [
      { ...item, id: "not-a-uuid" },
      { ...item, exchange_account_id: 7 },
      { ...item, symbol: undefined },
    ]) {
      expect(mapOrder(bad as unknown as WsOrder, "ws", dir)).toBeNull();
    }
  });

  it("the row carries no reject text, the exchange's or the OMS's (BQ-2, SR-E29-09)", () => {
    const item = { ...wsItem(snapshot, TP), rejected_reason: "EXCHANGE-TEXT-110017" };
    expect(JSON.stringify(mapOrder(item, "ws", dir))).not.toContain("EXCHANGE-TEXT");
  });
});

describe("Conditional orders are separated: the trigger in words (BQ-17)", () => {
  it("a recorded stop pushed with no direction takes it from its closing side", () => {
    const stop = wsRow(STOP);
    expect(wsItem(snapshot, STOP).trigger_direction).toBeNull();
    expect(stop.trigger).toEqual({
      price: "63950",
      source: "MarkPrice",
      direction: "fall",
      derived: true,
    });
    expect(triggerLabel(stop)).toBe("Mark falls to 63950");
    expect(triggerLabel(stop, (d) => `${Number.parseInt(d, 10).toLocaleString("en-US")}.0`)).toBe(
      "Mark falls to 63,950.0",
    );
  });

  it.each([
    ["stop_loss", "sell", "fall"],
    ["stop_loss", "buy", "rise"],
    ["take_profit", "sell", "rise"],
    ["take_profit", "buy", "fall"],
  ] as const)("a reduce-only %s on the %s side %ss", (intent, side, direction) => {
    expect(derivedDirection(intent, side, true)).toBe(direction);
    expect(derivedDirection(intent, side, false)).toBeNull();
  });

  it("an entry's null direction is not derived: the PROPOSED undirected words (G-W3)", () => {
    expect(derivedDirection("entry", "buy", true)).toBeNull();
    const trigger = {
      price: "64500",
      source: "LastPrice",
      direction: null,
      derived: false,
    } as const;
    expect(triggerWords(trigger)).toBe("Last reaches 64500");
  });

  it("a sent direction wins, and the source words are D02:269's, E30-D02:243's or PROPOSED", () => {
    const item: WsOrder = { ...wsItem(snapshot, STOP), trigger_direction: "rise" };
    expect(mapOrder(item, "ws", dir)?.trigger).toMatchObject({ direction: "rise", derived: false });
    expect(
      triggerWords({ price: "1", source: "IndexPrice", direction: "rise", derived: false }),
    ).toBe("Index rises to 1");
    expect(triggerWords({ price: "1", source: null, direction: "fall", derived: false })).toBe(
      "Price falls to 1",
    );
    expect(triggerWords({ price: "1", source: null, direction: null, derived: false })).toBe(
      "Price reaches 1",
    );
  });

  it("a zero trigger price is Bybit's none: no trigger, so the Working section", () => {
    const item: WsOrder = { ...wsItem(snapshot, TP), trigger_price: "0" };
    const row = mapOrder(item, "ws", dir);
    expect(row?.trigger).toBeNull();
    expect(row?.conditional).toBe(false);
    expect(triggerLabel(row as OrderRowModel)).toBe("—");
  });

  it("a triggered order leaves the Conditional section", () => {
    const item: WsOrder = {
      ...wsItem(snapshot, COND),
      lifecycle_state: "triggered",
      state: "triggered",
    };
    expect(mapOrder(item, "ws", dir)?.conditional).toBe(false);
  });
});

describe("Type · Purpose, flags, TIF, side and price words (D02 §6.1)", () => {
  it.each([
    ["limit", "take_profit", "Limit · Take profit"],
    ["market", "stop_loss", "Market · Stop loss"],
    ["limit", "entry", "Limit · Entry"],
    ["limit", "scale_in", "Limit · Scale-in"],
    ["market", "algo_child", "Market · Algo child"],
    [undefined, "flatten", "Flatten"],
    ["limit", undefined, "Limit"],
    [undefined, "a-new-intent", "—"],
  ])("%s + %s reads %s", (type, intent, words) => {
    expect(typeWords(type, intent)).toBe(words);
  });

  it("flags and TIF", () => {
    expect(flagsWords(false, false)).toBe("—");
    expect(flagsWords(false, true)).toBe("Close on trigger");
    expect(flagsWords(true, true)).toBe("Reduce-only · Close on trigger");
    expect(["GTC", "IOC", "FOK", "PostOnly"].map((t) => tifWords(t as "GTC"))).toEqual([
      "GTC",
      "IOC",
      "FOK",
      "Post-only",
    ]);
    expect(tifWords(null)).toBe("—");
  });

  it("the side is a word with its glyph apart; an unknown side reads — with no glyph", () => {
    expect([sideWords("buy"), sideGlyph("buy")]).toEqual(["Buy", "▲"]);
    expect([sideWords("sell"), sideGlyph("sell")]).toEqual(["Sell", "▼"]);
    expect([sideWords(null), sideGlyph(null)]).toEqual(["—", null]);
  });

  it("a market order's price reads Market; a limit with none reads —", () => {
    expect(priceLabel({ price: null, isMarket: true })).toBe("Market");
    expect(priceLabel({ price: null, isMarket: false })).toBe("—");
    expect(priceLabel({ price: "2500", isMarket: false }, (d) => `${d}.00`)).toBe("2500.00");
  });
});

describe("Parent (D02:273; BQ-6: no kind word while the kind is unknown)", () => {
  it("a bracket child with the contract-valid kind, and without it", () => {
    const fields = golden<OrdersBody>("ws_orders_contract_fields.json");
    expect(wsRow(ENTRY, fields).parentLabel).toBe("Bracket · #7c1e");
    expect(wsRow(ENTRY).parentLabel).toBe("#7c1e");
    expect(wsRow(ENTRY, fields).tradeGroupId).toBe("0c000000-0000-4000-8000-000000000001");
  });

  it("a TWAP reads as D02:273 draws it", () => {
    expect(
      parentWords({ kind: "parent", id: "a04f0000-0000-4000-8000-000000000001", algo: "twap" }),
    ).toBe("TWAP · #a04f");
  });

  it("every kind the contract names has its word: D02:273's, E30's tab labels, the PROPOSED OCO", () => {
    const fields = golden<OrdersBody>("ws_orders_contract_fields.json");
    const words = [
      ["bracket", "Bracket"],
      ["twap", "TWAP"],
      ["iceberg", "Iceberg"],
      ["chase", "Chase"],
      ["scaled", "Scaled"],
      ["oco", "OCO"],
    ] as const satisfies readonly (readonly [AlgoKind, string])[];
    for (const [algo, word] of words) {
      expect(parentWords({ kind: "parent", id: BRACKET, algo })).toBe(`${word} · #7c1e`);
      const item: WsOrder = { ...wsItem(fields, ENTRY), algo_kind: algo };
      const row = mapOrder(item, "ws", dir, constantsFor(ENTRY));
      expect(row?.parentLabel).toBe(`${word} · #7c1e`);
    }
  });

  it("a parent of kind none, or of no kind, shows the short id alone; a group leg and none read as D02:273", () => {
    expect(parentWords({ kind: "parent", id: BRACKET, algo: "none" })).toBe("#7c1e");
    expect(parentWords({ kind: "parent", id: BRACKET, algo: null })).toBe("#7c1e");
    expect(parentWords({ kind: "leg", id: BRACKET, algo: null })).toBe("Group leg");
    expect(parentWords(null)).toBe("—");
    expect(wsRow(TP).parentLabel).toBe("—");
  });
});

describe("the age formatter (D02:272)", () => {
  it.each([
    [0, "0 s"],
    [38, "38 s"],
    [59, "59 s"],
    [60, "1 m"],
    [4 * 60 + 59, "4 m"],
    [59 * 60 + 59, "59 m"],
    [3600, "1 h 00 m"],
    [3600 + 12 * 60, "1 h 12 m"],
    [2 * 3600 + 5 * 60 + 59, "2 h 05 m"],
    [26 * 3600, "26 h 00 m"],
  ])("%i s reads %s", (seconds, words) => {
    expect(formatAge(NOW - seconds * 1000, NOW)).toBe(words);
  });

  it("unknown reads —, and a creation time ahead of the clock reads 0 s", () => {
    expect(formatAge(null, NOW)).toBe("—");
    expect(formatAge(NOW + 5_000, NOW)).toBe("0 s");
  });
});

describe("the native-stop row (BQ-5)", () => {
  it("REST's recorded_stop names Sub-2's stop; WS alone falls back to D01 D7's rule", () => {
    expect(wsRow(STOP).protective).toEqual({ kind: "native_stop", via: "provenance" });
    expect(mapOrder(wsItem(snapshot, STOP), "ws", dir)?.protective).toEqual({
      kind: "native_stop",
      via: "rule",
    });
  });

  it("a recorded take profit is its own kind; a plain take profit is no protective row", () => {
    const row = wsRow(STOP);
    expect(protectiveOf({ ...row, intent: "take_profit" })).toEqual({
      kind: "recorded_take_profit",
      via: "provenance",
    });
    expect(wsRow(TP).protective).toEqual({ kind: null, via: null });
  });

  it("D01 D7: a stop not on the exchange, or not reduce-only, is no native stop", () => {
    const rule = { ...wsRow(STOP), provenance: null };
    expect(protectiveOf(rule).kind).toBe("native_stop");
    expect(protectiveOf({ ...rule, exchangeOrderId: null }).kind).toBeNull();
    expect(protectiveOf({ ...rule, reduceOnly: false }).kind).toBeNull();
  });

  it("an orphan stop, whose position is flat, cancels like any order; unknown, one is assumed (C-2.6)", () => {
    const row = wsRow(STOP);
    const flat = (): boolean => false;
    expect(protectiveOf(row, flat).kind).toBeNull();
    expect(protectiveOf({ ...row, provenance: null }, flat).kind).toBeNull();
    expect(
      protectiveOf(
        row,
        (account, symbol, idx) => account === SUB2 && symbol === "BTCUSDT" && idx === 1,
      ).kind,
    ).toBe("native_stop");
  });
});

describe("REST's creation constants (BQ-6)", () => {
  it("created_at, provenance and the trade group, read once per order", () => {
    const held = rest.get(HELD) as RestOrder;
    expect(constantsOf(held)).toEqual({
      createdAtMs: Date.parse(held.created_at ?? ""),
      provenance: "placed",
      tradeGroupId: null,
    });
    expect(constantsOf(rest.get(UNTRACKED) as RestOrder).provenance).toBe("reconciliation");
    expect(constantsOf({ ...held, created_at: "not a time" } as RestOrder).createdAtMs).toBeNull();
    expect(mapOrder(held, "rest", dir, constantsOf(held))?.state.word).toBe("Held — owner review");
  });

  it("a held row's Sub-1 sibling: the untracked order reads its own word", () => {
    const untracked = rest.get(UNTRACKED) as RestOrder;
    expect(mapOrder(untracked, "rest", dir)).toMatchObject({
      accountId: SUB1,
      state: { word: "Untracked — not placed by CandleViewer", family: "untracked" },
    });
  });
});
