/**
 * E29-S01 (#911) row mapping: the goldens the shipped mappers wrote (BQ-22) into E29-D02 §5.1's
 * row, the side as a word with " · hedge" by `position_idx`, and BQ-8's three fallbacks (margin
 * mode from the account, rPnL today "—" with its reason, R from the server else `24` §7.2 only when
 * the row carries a stop).
 */
import { describe, expect, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import {
  accountInfo,
  deriveR,
  keyOf,
  mapRow,
  type AccountInfo,
  type ExchangeAccount,
  type RestPosition,
  type WsPosition,
} from "../../../src/features/positions/model/rowMapping";
import { golden, GROUP, MAIN, SUB1, SUB2 } from "./support/fakes";

type Snapshot = generated.ws.Positions;
const accounts = new Map(
  golden<{ items: ExchangeAccount[] }>("rest_list_exchange_accounts.json")
    .items.map(accountInfo)
    .filter((a): a is AccountInfo => a !== null)
    .map((a) => [a.id, a]),
);
const wsItems = golden<Snapshot>("ws_positions_snapshot.json").positions;
const restItems = golden<{ items: RestPosition[] }>("rest_list_positions.json").items;
const extended = golden<Snapshot>("ws_positions_contract_fields.json").positions;
const mapAll = (items: readonly (WsPosition | RestPosition)[], source: "ws" | "rest") =>
  items.map((item) => mapRow(item, source, accounts));

describe("Rows render the whole book: each row's columns (D02 §5.1)", () => {
  const rows = mapAll(wsItems, "ws");

  it("maps every open position of the three fixture accounts", () => {
    expect(rows.map((r) => r?.accountLabel)).toEqual(["Main", "Sub-1", "Sub-1", "Sub-2", "Sub-2"]);
    expect(rows.map((r) => r?.key)).toEqual([
      keyOf(MAIN, "BTCUSDT", 0),
      keyOf(SUB1, "BTCUSDT", 0),
      keyOf(SUB1, "ETHUSDT", 0),
      keyOf(SUB2, "SOLUSDT", 1),
      keyOf(SUB2, "BTCUSDT", 1),
    ]);
  });

  it("states the side as a word, and hedge mode by position_idx", () => {
    expect(rows.map((r) => r?.sideLabel)).toEqual([
      "Long",
      "Long",
      "Short",
      "Long · hedge",
      "Long · hedge",
    ]);
    expect(rows.map((r) => r?.baseCoin)).toEqual(["BTC", "BTC", "ETH", "SOL", "BTC"]);
  });

  it("keeps money as the wire's decimal text", () => {
    const main = rows[0];
    expect(main).toMatchObject({
      size: "0.25",
      entry: "63980",
      mark: "64012",
      unrealisedPnl: "8",
      leverage: "10",
      liqPrice: "57901.9",
      stopLoss: "63880",
      takeProfit: null,
      environment: "live",
      source: "ws",
    });
    expect(main?.notional).toBe("16003.00"); // size × mark: the totals' exposure
  });

  it("BQ-8: margin mode from the account, rPnL today '—' with its reason, R derived from the stop", () => {
    expect(rows.map((r) => r?.marginMode)).toEqual([
      { value: "isolated", source: "account" },
      { value: "isolated", source: "account" },
      { value: "isolated", source: "account" },
      { value: "cross", source: "account" },
      { value: "cross", source: "account" },
    ]);
    expect(rows.every((r) => r?.realisedToday.value === null)).toBe(true);
    expect(rows[0]?.realisedToday).toEqual({ value: null, reason: "not_served" });
    expect(rows.map((r) => r?.r)).toEqual([
      { value: "0.3200", source: "derived" },
      { value: "0.3176", source: "derived" },
      { value: "-0.8526", source: "derived" },
      { value: "-0.9388", source: "derived" },
      { value: "-0.3800", source: "derived" },
    ]);
  });

  it("BQ-8: a frame's own margin mode, rPnL today and r_multiple win (contract-valid frames)", () => {
    const own = mapAll(extended, "ws");
    expect(
      own.map((r) => (r !== null && "source" in r.marginMode ? r.marginMode.source : null)),
    ).toEqual(["frame", "frame", "frame", "frame", "frame"]);
    expect(own.map((r) => r?.realisedToday)).toEqual([
      { value: "12.4" },
      { value: "0" },
      { value: "-18.2" },
      { value: "0" },
      { value: "0" },
    ]);
    expect(own[1]?.r).toEqual({ value: "0.3176", source: "server" });
    expect(own.map((r) => r?.tradeGroupId)).toEqual([GROUP, GROUP, null, null, null]);
  });

  it("maps the REST read to the same rows and keys", () => {
    const rest = mapAll(restItems, "rest");
    expect(rest.map((r) => r?.key)).toEqual(rows.map((r) => r?.key));
    expect(rest[0]).toMatchObject({ size: "0.250", entry: "63980.0", source: "rest" });
  });

  it("names the account by id alone when the directory does not hold it", () => {
    const row = mapRow(wsItems[0] as WsPosition, "ws", new Map());
    expect(row).toMatchObject({
      accountLabel: null,
      marginMode: { value: null },
      environment: "live",
    });
  });
});

describe("rows that name no open position", () => {
  const base = wsItems[0] as WsPosition;
  it.each([
    ["flat", { ...base, side: "flat" }],
    ["size 0", { ...base, size: "0" }],
    ["a bad id", { ...base, id: "not-a-uuid" }],
    ["a bad account", { ...base, exchange_account_id: "x" }],
    ["a spot symbol", { ...base, symbol: "BTCUSD" }],
    ["a number size", { ...base, size: 0.25 as unknown as string }],
  ])("%s is dropped", (_, item) => {
    expect(mapRow(item as WsPosition, "ws", accounts)).toBeNull();
  });

  it("reads a missing position_idx as one-way and lower-cases ids", () => {
    const rest = Object.fromEntries(Object.entries(base).filter(([key]) => key !== "position_idx"));
    const row = mapRow({ ...rest, id: base.id.toUpperCase() } as WsPosition, "ws", accounts);
    expect(row).toMatchObject({ positionIdx: 0, hedge: false, id: base.id });
  });

  it("drops a malformed money field without dropping the row", () => {
    const row = mapRow({ ...base, mark_price: "64,012" } as WsPosition, "ws", accounts);
    expect(row).toMatchObject({ mark: null, notional: null });
    expect(row?.r).toEqual({ value: null, reason: "no_price" });
  });
});

describe("deriveR (24 §7.2), signed by side", () => {
  it("a long gains R as the mark rises above the entry", () => {
    expect(deriveR("long", "100", "110", "95")).toEqual({ value: "2.0000", source: "derived" });
  });

  it("a short gains R as the mark falls", () => {
    expect(deriveR("short", "100", "90", "105")).toEqual({ value: "2.0000", source: "derived" });
    expect(deriveR("short", "100", "110", "105")).toEqual({ value: "-2.0000", source: "derived" });
  });

  it("no stop, or Bybit's 0, reads 'R unavailable: no stop price'", () => {
    expect(deriveR("long", "100", "110", null)).toEqual({ value: null, reason: "no_stop" });
    expect(deriveR("long", "100", "110", "0")).toEqual({ value: null, reason: "no_stop" });
  });

  it("no price, or a stop at the entry, gives no R", () => {
    expect(deriveR("long", null, "110", "95")).toEqual({ value: null, reason: "no_price" });
    expect(deriveR("long", "100", "110", "100")).toEqual({ value: null, reason: "zero_distance" });
  });
});

describe("accountInfo", () => {
  it("reads the label, modes and the balance's MM rate", () => {
    expect(accounts.get(SUB2)).toEqual({
      id: SUB2,
      label: "Sub-2",
      environment: "live",
      positionMode: "hedge",
      marginMode: "cross",
      mmRate: null,
    });
  });

  it("refuses an account without an id", () => {
    expect(accountInfo({ id: "x", label: "L" } as ExchangeAccount)).toBeNull();
  });
});
