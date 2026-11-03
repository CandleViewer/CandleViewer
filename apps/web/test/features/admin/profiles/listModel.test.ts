/**
 * E28-S01 (#971): SCR-130's rows from served profiles only (E28-D02 §5.1, D5): each account's default
 * first, its alternates nested after it; the symbol state, warnings and trading words are the deck's
 * words for served fields (the empty allow-list allows nothing: the 2026-10-25 ruling, D11).
 */
import { describe, expect, it } from "vitest";
import {
  buildRows,
  changedText,
  sizingText,
  symbolsText,
  warningText,
} from "../../../../src/features/admin/profiles/listModel";
import { PROFILES_COPY as C } from "../../../../src/features/admin/profiles/copy";
import { editorPath, newProfilePath } from "../../../../src/features/admin/profiles/paths";
import { ACCOUNT_IDS, account, input, stored } from "./fixtures";

const main = account(ACCOUNT_IDS.main, "Main");
const sub1 = account(ACCOUNT_IDS.sub1, "sub_001");
const sub2 = account(ACCOUNT_IDS.sub2, "sub_002");

describe("buildRows", () => {
  it("test_rows_put_each_default_first_and_nest_its_alternates_by_name", () => {
    const def = stored(ACCOUNT_IDS.main, "Main default", { is_default: true });
    const zeta = stored(ACCOUNT_IDS.main, "Main zeta");
    const alpha = stored(ACCOUNT_IDS.main, "Main 0.5R");
    const rows = buildRows([main], new Map([[main.id, [zeta, def, alpha]]]));
    expect(rows.map((r) => r.profileText)).toEqual([
      "Main default (v2) · default",
      "alternates: Main 0.5R (v2)",
      "alternates: Main zeta (v2)",
    ]);
    expect(rows.map((r) => r.leadsAccount)).toEqual([true, false, false]);
  });

  it("test_an_account_the_server_answered_404_for_has_no_row", () => {
    const rows = buildRows(
      [main, sub1],
      new Map([[sub1.id, [stored(ACCOUNT_IDS.sub1, "sub_001", { is_default: true })]]]),
    );
    expect(rows.map((r) => r.accountLabel)).toEqual(["sub_001"]);
  });

  it("test_a_row_reads_every_value_as_served_with_its_unit", () => {
    const [row] = buildRows(
      [sub1],
      new Map([[sub1.id, [stored(ACCOUNT_IDS.sub1, "sub_001", { is_default: true })]]]),
    );
    expect(row).toMatchObject({
      environment: "DEMO",
      trading: "on",
      symbols: "2 allowed",
      leverage: "5x",
      sizing: "Risk-based 0.5 %",
      dailyLoss: "3 %",
      maxPosition: "60000 USDT",
      changed: "v2 · changed 2026-10-12 UTC",
      notes: [],
    });
  });

  it("test_all_symbols_warning_is_the_served_code_in_words_not_a_colour", () => {
    const p = stored(
      ACCOUNT_IDS.sub2,
      "sub_002",
      { all_symbols: true, allowed_symbols: [] },
      { warnings: [{ code: "all_symbols", estimated: false, message: "served words" }] },
    );
    const [row] = buildRows([sub2], new Map([[sub2.id, [p]]]));
    expect(row?.symbols).toBe(C.allSymbols);
    expect(row?.notes).toEqual(["(!) Allows all symbols - consider restricting"]);
  });

  it("test_an_empty_allow_list_allows_no_symbol_and_trading_off_lists_the_caps", () => {
    const p = stored(
      ACCOUNT_IDS.sub2,
      "sub_002",
      { allowed_symbols: [], trading_enabled: false },
      { warnings: [{ code: "no_symbols", estimated: false, message: "no symbol" }] },
    );
    const [row] = buildRows([sub2], new Map([[sub2.id, [p]]]));
    expect(row?.symbols).toBe("Allows no symbol yet");
    expect(row?.trading).toBe("off");
    expect(row?.notes).toEqual([C.tradingOff]);
  });

  it("test_a_disabled_profile_reads_trading_off_without_cd3", () => {
    const [row] = buildRows(
      [sub1],
      new Map([[sub1.id, [stored(ACCOUNT_IDS.sub1, "sub_001", { enabled: false })]]]),
    );
    expect(row?.trading).toBe("off");
    expect(row?.notes).toEqual([]);
  });
});

describe("cell words", () => {
  it("test_sizing_text_names_the_mode_and_its_one_amount", () => {
    const sized = (sizing: object): string =>
      sizingText(input("x", { sizing } as Parameters<typeof input>[1]));
    expect(sized({ mode: "risk_based", risk_per_trade_usd: "50", min_leg_notional_usd: "0" })).toBe(
      "Risk-based 50 USDT",
    );
    expect(sized({ mode: "fixed_notional", notional_usd: "1000", min_leg_notional_usd: "0" })).toBe(
      "Fixed notional 1000 USDT",
    );
    expect(sized({ mode: "pct_equity", pct: "1", min_leg_notional_usd: "0" })).toBe(
      "% of equity 1 %",
    );
    expect(sized({ mode: "fixed_qty", qty: "0.01", min_leg_notional_usd: "0" })).toBe(
      "Fixed qty 0.01",
    );
    expect(sized({ mode: "fixed_qty", min_leg_notional_usd: "0" })).toBe("Fixed qty");
  });

  it("test_caps_absent_read_no_cap_and_both_halves_join", () => {
    const none = stored(ACCOUNT_IDS.sub1, "a", { risk_caps: { max_orders_per_minute: 30 } });
    const both = stored(ACCOUNT_IDS.sub1, "b", {
      risk_caps: { max_daily_loss_pct: "3", max_daily_loss_usd: "1000", max_orders_per_minute: 30 },
    });
    const rows = buildRows([sub1], new Map([[sub1.id, [none, both]]]));
    expect(rows.map((r) => [r.dailyLoss, r.maxPosition])).toEqual([
      [C.noCap, C.noCap],
      ["3 % · 1000 USDT", C.noCap],
    ]);
  });

  it("test_symbols_text_counts_entries_patterns_included", () => {
    expect(symbolsText(input("x", { allowed_symbols: ["*USDT"] }))).toBe("1 allowed");
  });

  it("test_a_warning_the_client_does_not_know_reads_its_served_message", () => {
    const w = { code: "stop_beyond_liquidation", estimated: true, message: "served" } as const;
    expect(warningText(w)).toBe("served");
  });

  it("test_an_unreadable_date_is_never_guessed", () => {
    expect(changedText(stored(ACCOUNT_IDS.sub1, "x", {}, { updated_at: "soon", version: 4 }))).toBe(
      "v4",
    );
  });
});

describe("paths and flag", () => {
  it("test_editor_paths_carry_the_account_in_the_query", () => {
    expect(editorPath({ id: "p 1", exchange_account_id: "a1" })).toBe(
      "/admin/profiles/p%201?account=a1",
    );
    expect(newProfilePath("a1")).toBe("/admin/profiles/new?account=a1");
    expect(newProfilePath("a1", "p1")).toBe("/admin/profiles/new?account=a1&from=p1");
  });
});
