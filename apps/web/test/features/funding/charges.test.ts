// E24-S03 (#778) slice 2: the server charge per account (BQ 4), never computed, summed or shown as zero.
import { describe, expect, it, vi } from "vitest";
import { loadFundingCharges, usdtCents } from "../../../src/features/funding/charges";
import type { PositionsApi } from "../../../src/features/positions/api";

// Only the members the read uses; the rest of `Position` / `ExchangeAccount` is not read.
const estimate = (amount: string, direction: "pay" | "receive" | "none") => ({ amount, direction });
const position = (id: string, account: string, symbol: string, fe: unknown) => ({
  id,
  exchange_account_id: account,
  symbol,
  funding_estimate: fe,
});
const account = (id: string, label: string, environment: "live" | "demo" | "testnet") => ({
  id,
  label,
  environment,
});

const api = (items: unknown[], accounts: unknown[]): PositionsApi => ({
  listPositions: vi.fn(async () => ({ kind: "ok", items, aggregates: [] }) as never),
  listExchangeAccounts: vi.fn(async () => ({ kind: "ok", items: accounts }) as never),
});

const signal = new AbortController().signal;

describe("funding charge lines", () => {
  it("formats each account's server estimate on the symbol, one line per account", async () => {
    const lines = await loadFundingCharges(
      "BTCUSDT",
      signal,
      api(
        [
          position("p1", "a1", "BTCUSDT", estimate("12.39500000", "pay")),
          position("p2", "a2", "BTCUSDT", estimate("1234.00000000", "receive")),
          position("p3", "a1", "ETHUSDT", estimate("9.00000000", "pay")),
        ],
        [account("a1", "Demo 1", "demo"), account("a2", "Sub-1", "live")],
      ),
    );
    expect(lines).toEqual([
      { accountLabel: "Demo 1", env: "DEMO", direction: "pay", amountUsdt: "12.40" },
      { accountLabel: "Sub-1", env: "LIVE", direction: "receive", amountUsdt: "1,234.00" },
    ]);
  });

  it("shows no line for a null or absent estimate, a zero rate, testnet or an unknown account", async () => {
    const lines = await loadFundingCharges(
      "BTCUSDT",
      signal,
      api(
        [
          position("p1", "a1", "BTCUSDT", null),
          position("p2", "a1", "BTCUSDT", undefined),
          position("p3", "a1", "BTCUSDT", estimate("0", "none")),
          position("p4", "a3", "BTCUSDT", estimate("1.00000000", "pay")),
          position("p5", "a9", "BTCUSDT", estimate("1.00000000", "pay")),
        ],
        [account("a1", "Demo 1", "demo"), account("a3", "Test", "testnet")],
      ),
    );
    expect(lines).toEqual([]);
  });

  it("answers null when either read fails, so no line is guessed", async () => {
    const failing: PositionsApi = {
      listPositions: vi.fn(async () => ({ kind: "forbidden" }) as const),
      listExchangeAccounts: vi.fn(async () => ({ kind: "ok", items: [] }) as const),
    };
    expect(await loadFundingCharges("BTCUSDT", signal, failing)).toBeNull();
  });

  it.each([
    ["12.39500000", "12.40"],
    ["0.00400000", "0.00"],
    ["0.00500000", "0.01"],
    ["1234567.99900000", "1,234,568.00"],
    ["7", "7.00"],
  ])("%s USDT reads %s", (amount, text) => {
    expect(usdtCents(amount)).toBe(text);
  });
});
