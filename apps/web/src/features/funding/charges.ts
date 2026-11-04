// E24-S03 (#778) slice 2: the charge lines (BQ 4): the server's `Position.funding_estimate` on the account-scoped
// `GET /positions` (C-12.4), never computed, summed or annualised; no estimate or account means no line, never 0.
import type { FundingCharge } from "@candleviewer/ui";
import { positionsApi, type PositionsApi } from "../positions/api";

/** `listPositions` items carry every symbol in scope; this read keeps the pane's own. */
export async function loadFundingCharges(
  symbol: string,
  signal: AbortSignal,
  api: PositionsApi = positionsApi,
): Promise<readonly FundingCharge[] | null> {
  const [positions, accounts] = await Promise.all([
    api.listPositions({}, signal),
    api.listExchangeAccounts(signal),
  ]);
  if (positions.kind !== "ok" || accounts.kind !== "ok") return null;
  const byId = new Map(accounts.items.map((a) => [a.id, a] as const));
  const lines: FundingCharge[] = [];
  for (const p of positions.items) {
    const estimate = p.funding_estimate;
    const account = byId.get(p.exchange_account_id);
    if (p.symbol !== symbol || estimate === null || estimate === undefined) continue;
    if (estimate.direction === "none" || account === undefined) continue;
    // PROPOSED: a testnet account has no DEMO / LIVE word in D02 §5.2, so it shows no line
    if (account.environment === "testnet") continue;
    lines.push({
      accountLabel: account.label,
      env: account.environment === "live" ? "LIVE" : "DEMO",
      direction: estimate.direction,
      amountUsdt: usdtCents(estimate.amount),
    });
  }
  return lines;
}

/** PROPOSED (D02 draws "12.40"): the 8 dp amount at two decimals, half-up on its digits, comma-grouped. */
export function usdtCents(amount: string): string {
  const [int = "0", frac = ""] = amount.replace(/^-/, "").split(".");
  const digits = `${frac}000`;
  const cents = BigInt(`${int}${digits.slice(0, 2)}`) + (Number(digits[2]) >= 5 ? 1n : 0n);
  const whole = String(cents / 100n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${whole}.${String(cents % 100n).padStart(2, "0")}`;
}
