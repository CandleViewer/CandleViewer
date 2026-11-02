/**
 * One fill of the Fills tab and the SCR-078 drawer (E29-S04 #979), from a WS `executions` item
 * (`23` §15.3) or a REST `Execution` (`22`), so a fill reads the same whichever source brought it
 * (BQ-9). The two wire forms differ, and the row hides it:
 *
 * - **Time.** WS `ts_ms`; REST `ts`, RFC 3339 to the microsecond, cut to its millisecond as the
 *   server's `epoch_ms` floors it, so both copies sort and read alike.
 * - **Decimals** are normalised: WS writes `"0.1"` and `"63410"` (`money_text`), REST the stored
 *   scale (`"0.100"`, `"63410.0"`). A cell pads to the instrument's precision when it shows one.
 * - **Members the wire may leave out** read "—" with their reason, never 0, "Trade" or an assumed
 *   coin (D03 D-9, BQ-11): no fee, an empty coin, no liquidity flag, no type, no order (REST only:
 *   WS requires `order_id`, D03 G20). WS carries no trade group (`undefined`: unknown, unlike REST's
 *   `null`, none) and REST no environment; a later copy of the fill supplies them (`fillsStore.ts`).
 * - **The fee** is the wire's, positive when paid (`oms/execution.py`: "both < 0 for a rebate"), and
 *   the cell shows its cash effect, −fee (BQ-11, D03 OQ-8's default).
 *
 * A malformed item (no account, exec id, price, qty or time) is dropped, never guessed.
 */
import type { generated } from "@candleviewer/protocol";
import { neg, normalise, parseDecimal, toPlain } from "../../model/decimal";
import { isUuid, type Environment } from "../../model/rowMapping";

export type WsExecution = generated.ws.Executions["executions"][number];
export type RestExecution = generated.rest.components["schemas"]["Execution"];

/** D03 §3.3's five type words' kinds; `other` is a value the wire's enum lacks, `missing` none. */
export type FillKind = "trade" | "adl" | "liquidation" | "funding" | "settlement";
export type FillType =
  | { readonly kind: FillKind }
  | { readonly kind: "other"; readonly name: string }
  | { readonly kind: "missing" };

const KINDS: Readonly<Record<string, FillKind>> = {
  Trade: "trade",
  AdlTrade: "adl",
  BustTrade: "liquidation",
  Funding: "funding",
  Settle: "settlement",
};

/** The kinds that are trades: they carry a side and a liquidity flag and count in the averages. */
export const TRADE_KINDS: ReadonlySet<string> = new Set<FillKind>(["trade", "adl", "liquidation"]);

export interface FillRowModel {
  /** `exchange_account_id|exec_id`: the database's key (`21` `ux_exec_id`) and the dedupe key. */
  readonly key: string;
  readonly id: string;
  readonly execId: string;
  readonly accountId: string;
  /** `null`: a fill of no order (funding, ADL, liquidation, settlement; REST only). */
  readonly orderId: string | null;
  /** `null` none; `undefined` the source does not carry it (WS). */
  readonly tradeGroupId: string | null | undefined;
  readonly symbol: string;
  /** The base coin of a USDT symbol, the Qty unit ("Qty (BTC)", D03 §3.3). */
  readonly baseCoin: string;
  readonly side: "buy" | "sell";
  readonly type: FillType;
  /** The wire's `exec_type` as sent, for the CSV (D03 §3.8: as the contract carries it). */
  readonly execType: string | null;
  readonly price: string;
  readonly qty: string;
  readonly value: string | null;
  /** The wire's fee, positive when paid; `null` when not reported. */
  readonly fee: string | null;
  /** Its cash effect, −fee: what the cell shows ("−3.49 USDT" paid, "+0.84 USDT" received). */
  readonly feeCash: string | null;
  /** `null` when absent or empty: "fee currency not reported" (D03 §3.6). */
  readonly feeCoin: string | null;
  readonly feeRate: string | null;
  /** `null` when not reported. */
  readonly maker: boolean | null;
  readonly closedPnl: string | null;
  readonly tsMs: number;
  /** WS only; `undefined` until a WS copy brings it. */
  readonly environment: Environment | undefined;
  readonly isPaper: boolean;
  readonly source: "ws" | "rest";
}

const USDT = /^([A-Z0-9]{2,20})USDT$/;
const RFC3339 = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/;
const ENVIRONMENTS: readonly Environment[] = ["live", "demo", "testnet"];

export const keyOfFill = (accountId: string, execId: string): string => `${accountId}|${execId}`;

/** A wire decimal without trailing zeros, or `null` for none or junk. */
export function plain(value: unknown): string | null {
  const d = parseDecimal(value);
  return d === null ? null : toPlain(normalise(d));
}

/** `23` §13 `epochMs`, or REST's RFC 3339 cut to its millisecond (the server's `epoch_ms`). */
export function fillTime(item: { readonly ts_ms?: unknown; readonly ts?: unknown }): number | null {
  const ms = item.ts_ms;
  if (typeof ms === "number") return Number.isSafeInteger(ms) && ms >= 0 ? ms : null;
  const match = typeof item.ts === "string" ? RFC3339.exec(item.ts) : null;
  if (match === null) return null;
  const [, base = "", fraction = "", zone = "Z"] = match;
  const parsed = Date.parse(`${base}.${fraction.padEnd(3, "0").slice(0, 3)}${zone}`);
  return Number.isNaN(parsed) || parsed < 0 ? null : parsed;
}

function typeOf(value: unknown): FillType {
  if (typeof value !== "string" || value === "") return { kind: "missing" };
  const kind = KINDS[value];
  return kind === undefined ? { kind: "other", name: value } : { kind };
}

/** The row of a wire item, or `null` for one that names no readable fill. */
export function mapFill(
  item: WsExecution | RestExecution,
  source: "ws" | "rest",
): FillRowModel | null {
  const wire = item as Readonly<Record<string, unknown>>;
  const account = wire["exchange_account_id"];
  const execId = wire["exec_id"];
  const symbol = typeof wire["symbol"] === "string" ? USDT.exec(wire["symbol"]) : null;
  const side = wire["side"] === "buy" || wire["side"] === "sell" ? wire["side"] : null;
  const price = plain(wire["exec_price"]);
  const qty = plain(wire["exec_qty"]);
  const tsMs = fillTime(wire);
  if (!isUuid(account) || typeof execId !== "string" || execId === "" || symbol === null)
    return null;
  if (!isUuid(wire["id"]) || side === null || price === null || qty === null || tsMs === null)
    return null;
  const accountId = account.toLowerCase();
  const order = wire["order_id"];
  const group = wire["trade_group_id"];
  const fee = plain(wire["fee"]);
  const feeDec = parseDecimal(fee);
  const coin = wire["fee_coin"];
  const maker = wire["is_maker"];
  return {
    key: keyOfFill(accountId, execId),
    id: wire["id"].toLowerCase(),
    execId,
    accountId,
    orderId: isUuid(order) ? order.toLowerCase() : null,
    tradeGroupId: isUuid(group) ? group.toLowerCase() : group === null ? null : undefined,
    symbol: symbol[0],
    baseCoin: symbol[1] ?? "",
    side,
    type: typeOf(wire["exec_type"]),
    execType: typeof wire["exec_type"] === "string" ? wire["exec_type"] : null,
    price,
    qty,
    value: plain(wire["exec_value"]),
    fee,
    feeCash: feeDec === null ? null : toPlain(neg(feeDec)),
    feeCoin: typeof coin === "string" && coin !== "" ? coin : null,
    feeRate: plain(wire["fee_rate"]),
    maker: typeof maker === "boolean" ? maker : null,
    closedPnl: plain(wire["exec_pnl"]),
    tsMs,
    environment: ENVIRONMENTS.find((e) => e === wire["environment"]),
    isPaper: wire["is_paper"] === true,
    source,
  };
}

/**
 * The same fill from a second source: the first copy wins (BQ-9: one stored row, so the members
 * both carry agree), and a member only the second carries is taken from it (REST's trade group,
 * WS's environment). Returns `first` itself when nothing is added.
 */
export function mergeFill(first: FillRowModel, second: FillRowModel): FillRowModel {
  const group = first.tradeGroupId === undefined ? second.tradeGroupId : first.tradeGroupId;
  const environment = first.environment ?? second.environment;
  if (group === first.tradeGroupId && environment === first.environment) return first;
  return { ...first, tradeGroupId: group, environment };
}

/** Newest first: `tsMs`, then `id`, descending (the server's keyset, `exec_ts` then `id`). */
export function newestFirst(a: FillRowModel, b: FillRowModel): number {
  return b.tsMs - a.tsMs || (a.id < b.id ? 1 : a.id > b.id ? -1 : 0);
}

const isTradeKind = (row: FillRowModel): boolean => TRADE_KINDS.has(row.type.kind);

/** Side shows "—" for funding and settlement (D03 §3.3); `null` then. */
export const sideShown = (row: FillRowModel): "buy" | "sell" | null =>
  row.type.kind === "funding" || row.type.kind === "settlement" ? null : row.side;

/** The Liquidity cell (D03 §3.3, §3.6): a trade's flag, "—" for any other type, or not reported. */
export type Liquidity = "maker" | "taker" | "not_a_trade" | "not_reported";

export function liquidityOf(row: FillRowModel): Liquidity {
  if (!isTradeKind(row)) return "not_a_trade";
  return row.maker === null ? "not_reported" : row.maker ? "maker" : "taker";
}

/** D03 §1.4's stubs: an order "…a3f2" (its last four), an exec id "7f3c9a1e…" (its first eight). */
export const tailStub = (id: string): string => `…${id.slice(-4)}`;
export const headStub = (id: string): string => (id.length > 8 ? `${id.slice(0, 8)}…` : id);
