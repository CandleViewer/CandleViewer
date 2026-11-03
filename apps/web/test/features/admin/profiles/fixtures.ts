/**
 * E28-S01 fixtures: the deck's labels (`Main`, `sub_001` … `sub_004`, E28-D06 hand-off §D) and the
 * US-PROF-002 figures; ids are fixed placeholders, nothing is a real account, key or balance.
 */
import type {
  AccountProfile,
  AccountProfileInput,
  ExchangeAccount,
} from "../../../../src/features/admin/profiles/api";

export const ACCOUNT_IDS = {
  main: "e28f0000-0000-4000-8000-0000000000a0",
  sub1: "e28f0000-0000-4000-8000-0000000000a1",
  sub2: "e28f0000-0000-4000-8000-0000000000a2",
  sub3: "e28f0000-0000-4000-8000-0000000000a3",
} as const;

export function account(id: string, label: string): ExchangeAccount {
  return {
    id,
    label,
    enabled: true,
    environment: "demo",
    exchange: "bybit",
    exchange_uid: "928000001",
    kind: label === "Main" ? "main" : "sub",
  } as ExchangeAccount;
}

/** A trading, risk-based profile; `patch` overrides members of `profile`. */
export function input(name: string, patch: Partial<AccountProfileInput> = {}): AccountProfileInput {
  return {
    name,
    is_default: false,
    enabled: true,
    trading_enabled: true,
    leverage: "5",
    margin_mode: "cross",
    position_mode: "one_way",
    default_time_in_force: "GTC",
    reduce_only_default: false,
    require_native_stop: true,
    slippage_tolerance_bps: 10,
    all_symbols: false,
    allowed_symbols: ["BTCUSDT", "ETHUSDT"],
    blocked_symbols: [],
    sizing: { mode: "risk_based", risk_per_trade_pct: "0.5", min_leg_notional_usd: "5" },
    stop_loss: {
      unit: "ticks",
      value: "1200",
      atr_period: 14,
      atr_multiple: "2",
      fallback_pct: "2",
    },
    take_profit_ladder: [],
    risk_caps: {
      max_position_notional_usd: "60000",
      max_daily_loss_pct: "3",
      max_open_positions: 3,
      max_concurrent_orders: 20,
      max_leverage_cap: "10",
      max_orders_per_minute: 30,
    },
    ...patch,
  } as AccountProfileInput;
}

let serial = 0;

export function stored(
  accountId: string,
  name: string,
  patch: Partial<AccountProfileInput> = {},
  extra: Partial<AccountProfile> = {},
): AccountProfile {
  serial += 1;
  return {
    id: `e28f0000-0000-4000-8000-${String(serial).padStart(12, "0")}`,
    exchange_account_id: accountId,
    environment: "demo",
    version: 2,
    created_at: "2026-10-01T09:00:00Z",
    updated_at: "2026-10-12T08:30:00Z",
    warnings: [],
    profile: input(name, patch),
    ...extra,
  };
}

export const json = (
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response =>
  new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });

/** A `403 step_up_required` body with a live challenge for class `risk_caps`. */
export const stepUpBody = (
  id = "0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d",
): Record<string, unknown> => ({
  type: "https://candleviewer.local/errors/step_up_required",
  title: "A dangerous action needs a live step-up elevation for its action class",
  status: 403,
  code: "step_up_required",
  action_class: "risk_caps",
  challenge_id: id,
  challenge_expires_at: new Date(Date.now() + 300_000).toISOString(),
  action_summary: "Delete sub_001's profile 'sub_001 0.5R'",
  target: null,
});
