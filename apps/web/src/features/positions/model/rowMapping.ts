/**
 * One position row of the SCR-063 Positions tab, from a wire item (WS `23` §15.2 or REST `22`
 * `Position`) and the caller's account directory (`22` `ExchangeAccount`). Columns follow E29-D02
 * §5.1; the three the wire does not carry today take #911's BQ-8 fallbacks: margin mode from the
 * account, rPnL today "—" with a spoken reason, and R from the server's `r_multiple`, else derived
 * (`24` §7.2) only when the row carries `stop_loss`. Money stays decimal text (`decimal.ts`).
 */
import type { generated } from "@candleviewer/protocol";
import { abs, cmp, dec, div, mul, neg, parseDecimal, sub, toPlain, type Decimal } from "./decimal";

export type WsPosition = generated.ws.Positions["positions"][number];
export type RestPosition = generated.rest.components["schemas"]["Position"];
export type ExchangeAccount = generated.rest.components["schemas"]["ExchangeAccount"];
export type Environment = generated.rest.components["schemas"]["Environment"];
export type MarginMode = generated.rest.components["schemas"]["MarginMode"];
export type PositionMode = generated.rest.components["schemas"]["PositionMode"];
export type Side = "long" | "short";

/** What the panel needs of an account: `22` `ExchangeAccount`, as served. */
export interface AccountInfo {
  readonly id: string;
  readonly label: string;
  readonly environment: Environment;
  readonly positionMode: PositionMode | null;
  readonly marginMode: MarginMode | null;
  /** The cached balance's `account_mm_rate`: first paint until `wallet` serves one (BQ-11, BQ-18). */
  readonly mmRate: string | null;
}

/** Why R is "—" (D02 §5.1: spoken "R unavailable: no stop price" for `no_stop`). */
export type RUnavailable = "no_stop" | "no_price" | "zero_distance";
export type RValue =
  | { readonly value: string; readonly source: "server" | "derived" }
  | { readonly value: null; readonly reason: RUnavailable };
/** rPnL today: the frame's `realised_pnl_session`, else "—" (BQ-8; the figure is E29-S06's). */
export type RealisedToday =
  { readonly value: string } | { readonly value: null; readonly reason: "not_served" };
export type MarginValue =
  { readonly value: MarginMode; readonly source: "frame" | "account" } | { readonly value: null };

export interface PositionRowModel {
  /** `exchange_account_id|symbol|position_idx` (the ticket's store key). */
  readonly key: string;
  readonly id: string;
  readonly accountId: string;
  readonly accountLabel: string | null;
  readonly environment: Environment | null;
  readonly symbol: string;
  /** The base coin of a USDT symbol (`23` §13 `symbol`), for "0.250 BTC" (D02 §5.1). */
  readonly baseCoin: string;
  readonly side: Side;
  /** D02 §5.1: the side as a word, never colour alone. */
  readonly sideWord: "Long" | "Short";
  /** `position_idx` 1 or 2: hedge mode, which adds " · hedge" (D02 §5.1). */
  readonly hedge: boolean;
  readonly sideLabel: string;
  readonly positionIdx: 0 | 1 | 2;
  readonly size: string;
  readonly entry: string | null;
  readonly mark: string | null;
  readonly unrealisedPnl: string | null;
  readonly realisedToday: RealisedToday;
  readonly r: RValue;
  readonly leverage: string | null;
  readonly marginMode: MarginValue;
  readonly liqPrice: string | null;
  readonly stopLoss: string | null;
  readonly takeProfit: string | null;
  readonly tradeGroupId: string | null;
  /** `size × mark`, the totals' Exposure (D02 D-15, §5.2), else the wire `position_value`. */
  readonly notional: string | null;
  readonly source: "ws" | "rest";
}

/** `24` §1.5: R-multiples are kept at 4 places; the display rounds them again (D02 "+0.32"). */
export const R_SCALE = 4;

const USDT = /^([A-Z0-9]{2,20})USDT$/;
const SIDE_WORDS = { long: "Long", short: "Short" } as const;
/** D02 §5.1: hedge mode adds " · hedge" after the side word. */
export const HEDGE_SUFFIX = " · hedge";

export const keyOf = (accountId: string, symbol: string, positionIdx: number): string =>
  `${accountId}|${symbol}|${positionIdx}`;

/** A decimal string the wire may hold, kept as sent, or `null` for none or junk. */
function money(value: unknown): string | null {
  return parseDecimal(value) === null ? null : (value as string);
}

const positionIdxOf = (value: unknown): 0 | 1 | 2 => (value === 1 || value === 2 ? value : 0); // absent: one-way (Bybit's 0)

const MARGIN_MODES: readonly MarginMode[] = ["cross", "isolated", "portfolio"];
const marginOf = (value: unknown): MarginMode | null =>
  MARGIN_MODES.find((m) => m === value) ?? null;

/** R (`24` §7.2): `(mark − entry) / |entry − stop|`, signed by side; `null` with the reason. */
export function deriveR(
  side: Side,
  entry: string | null,
  mark: string | null,
  stop: string | null,
): RValue {
  const s = parseDecimal(stop);
  if (s === null || s.units <= 0n) return { value: null, reason: "no_stop" }; // Bybit's 0 is none
  const e = parseDecimal(entry);
  const m = parseDecimal(mark);
  if (e === null || m === null) return { value: null, reason: "no_price" };
  const risk = abs(sub(e, s));
  const move: Decimal = side === "long" ? sub(m, e) : neg(sub(m, e));
  const r = div(move, risk, R_SCALE);
  return r === null
    ? { value: null, reason: "zero_distance" }
    : { value: toPlain(r), source: "derived" };
}

/** The wire item's fields both feeds share; `null` for a flat row, which leaves the view. */
interface Common {
  readonly id: unknown;
  readonly exchange_account_id: unknown;
  readonly symbol: unknown;
  readonly side: unknown;
  readonly position_idx?: unknown;
  readonly size: unknown;
  readonly avg_price?: unknown;
  readonly mark_price?: unknown;
  readonly position_value?: unknown;
  readonly leverage?: unknown;
  readonly margin_mode?: unknown;
  readonly unrealised_pnl?: unknown;
  readonly realised_pnl_session?: unknown;
  readonly liq_price?: unknown;
  readonly take_profit?: unknown;
  readonly stop_loss?: unknown;
  readonly trade_group_id?: unknown;
  readonly r_multiple?: unknown;
  readonly environment?: unknown;
}

const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
export const isUuid = (value: unknown): value is string =>
  typeof value === "string" && UUID.test(value);

const ENVIRONMENTS: readonly Environment[] = ["live", "demo", "testnet"];

/**
 * The row of a wire item, or `null` when it names no open position (flat, size 0, or unreadable:
 * a malformed item is dropped, never guessed). `accounts` resolves the label and the BQ-8 margin
 * mode; an account it does not hold keeps its row with a `null` label (the server scoped it).
 */
export function mapRow(
  item: WsPosition | RestPosition,
  source: "ws" | "rest",
  accounts: ReadonlyMap<string, AccountInfo>,
): PositionRowModel | null {
  const wire = item as Common;
  const size = parseDecimal(wire.size);
  const symbol = typeof wire.symbol === "string" ? USDT.exec(wire.symbol) : null;
  const side = wire.side === "long" || wire.side === "short" ? wire.side : null;
  if (!isUuid(wire.id) || !isUuid(wire.exchange_account_id) || symbol === null) return null;
  if (side === null || size === null || cmp(size, dec("0")) <= 0) return null;
  const accountId = wire.exchange_account_id.toLowerCase();
  const account = accounts.get(accountId);
  const positionIdx = positionIdxOf(wire.position_idx);
  const entry = money(wire.avg_price);
  const mark = money(wire.mark_price);
  const stopLoss = money(wire.stop_loss);
  const served = money(wire.r_multiple);
  const rpnl = money(wire.realised_pnl_session);
  const frameMargin = marginOf(wire.margin_mode);
  const accountMargin = account?.marginMode ?? null;
  const markDec = parseDecimal(mark);
  const notional = markDec === null ? money(wire.position_value) : toPlain(mul(size, markDec));
  const hedge = positionIdx !== 0;
  const environment = ENVIRONMENTS.find((e) => e === wire.environment) ?? account?.environment;
  return {
    key: keyOf(accountId, symbol[0], positionIdx),
    id: wire.id.toLowerCase(),
    accountId,
    accountLabel: account?.label ?? null,
    environment: environment ?? null,
    symbol: symbol[0],
    baseCoin: symbol[1] ?? "",
    side,
    sideWord: SIDE_WORDS[side],
    hedge,
    sideLabel: hedge ? `${SIDE_WORDS[side]}${HEDGE_SUFFIX}` : SIDE_WORDS[side],
    positionIdx,
    size: wire.size as string,
    entry,
    mark,
    unrealisedPnl: money(wire.unrealised_pnl),
    realisedToday: rpnl === null ? { value: null, reason: "not_served" } : { value: rpnl },
    r: served === null ? deriveR(side, entry, mark, stopLoss) : { value: served, source: "server" },
    leverage: money(wire.leverage),
    marginMode:
      frameMargin !== null
        ? { value: frameMargin, source: "frame" }
        : accountMargin !== null
          ? { value: accountMargin, source: "account" }
          : { value: null },
    liqPrice: money(wire.liq_price),
    stopLoss,
    takeProfit: money(wire.take_profit),
    tradeGroupId: isUuid(wire.trade_group_id) ? wire.trade_group_id.toLowerCase() : null,
    notional,
    source,
  };
}

/** `22` `ExchangeAccount` as the panel reads it; `null` for an item without an id or a label. */
export function accountInfo(account: ExchangeAccount): AccountInfo | null {
  if (!isUuid(account.id) || typeof account.label !== "string") return null;
  return {
    id: account.id.toLowerCase(),
    label: account.label,
    environment: account.environment,
    positionMode: account.position_mode ?? null,
    marginMode: marginOf(account.margin_mode),
    mmRate: money(account.balance?.account_mm_rate),
  };
}
