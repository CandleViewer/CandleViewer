/**
 * E16-S01, SCR-140's grid (pure part): the FilterBar's fields and match (BQ-10), the search, the sort with nulls
 * last, the order kept while the page is open (D02 §9.1), a model row in CMP-177's props, D02 §5.1's Why? words,
 * the refusal words (E16-D06 §16.4) and the page deck rows against `E16-D06-copy.json`.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  AUTO_FILTER,
  DEEP_FILTERS,
  FILTER_FIELDS,
  PINNED_FILTER,
  compareRows,
  nextOrder,
  rowData,
  rowMatches,
  whyWords,
  type RowContext,
} from "../../../src/features/recorder/grid";
import type { RecorderRow } from "../../../src/features/recorder/model";
import { PAGE_DECK } from "../../../src/features/recorder/pageCopy";
import { refusalText } from "../../../src/features/recorder/refusal";
import { POLICY } from "./modelFixtures";
import { CONTEXT, D02_ROWS, NOW, row } from "./gridFixtures";

const symbols = (rows: readonly RecorderRow[]): string[] => rows.map((r) => r.symbol);
const matching = (filters: Parameters<typeof rowMatches>[1], query = ""): string[] =>
  symbols(D02_ROWS.filter((r) => rowMatches(r, filters, query)));

describe("the grid's filters and search (BQ-10)", () => {
  it("test_filters_offer_reason_state_pinned_needs_attention_and_depth_in_order", () => {
    expect(FILTER_FIELDS.map((f) => f.label)).toEqual([
      "Reason",
      "State",
      "Pinned",
      "Needs attention",
      "Depth",
    ]);
    expect(FILTER_FIELDS[0]?.options.map((o) => o.label)).toEqual(["Manual", "Auto"]);
  });

  it("test_reason_auto_matches_every_trigger_but_manual", () => {
    expect(matching([AUTO_FILTER])).toEqual(["SOLUSDT", "XRPUSDT"]);
    expect(matching([{ field: "reason", value: "manual" }])).toEqual([
      "BTCUSDT",
      "ETHUSDT",
      "ADAUSDT",
    ]);
  });

  it("test_values_of_one_field_or_and_fields_and", () => {
    const stopped = { field: "state", value: "stopped" } as const;
    expect(matching([stopped, { field: "state", value: "recording" }])).toHaveLength(5);
    expect(matching([stopped, AUTO_FILTER])).toEqual([]);
    expect(matching([PINNED_FILTER])).toEqual(["BTCUSDT"]);
    expect(matching([...DEEP_FILTERS])).toEqual(["BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT"]);
  });

  it("test_needs_attention_is_degraded_gated_silent_error_or_refused", () => {
    const rows = ["degraded", "gated", "silent", "error", "refused", "lingering", "stopping"].map(
      (state) => row(state.toUpperCase(), { state: state as RecorderRow["state"] }),
    );
    const yes = rows.filter((r) => rowMatches(r, [{ field: "attention", value: "yes" }], ""));
    expect(symbols(yes)).toEqual(["DEGRADED", "GATED", "SILENT", "ERROR", "REFUSED"]);
  });

  it("test_a_lingering_row_is_recording_to_the_state_filter", () => {
    const lingering = row("DOGEUSDT", { state: "lingering" });
    expect(rowMatches(lingering, [{ field: "state", value: "recording" }], "")).toBe(true);
  });

  it("test_search_matches_the_symbol_ignoring_case_and_outer_spaces", () => {
    expect(matching([], "  eth ")).toEqual(["ETHUSDT"]);
    expect(matching([], "usdt")).toHaveLength(5);
    expect(matching([AUTO_FILTER], "eth")).toEqual([]);
  });
});

describe("the grid's sort and order (D02 §9.1)", () => {
  it("test_sort_by_size_and_since_put_rows_without_a_value_last_either_way", () => {
    const rows = [
      ...D02_ROWS,
      row("NEWUSDT", { state: "starting", diskBytes: null, startedAt: null }),
    ];
    const size = (direction: "ascending" | "descending") =>
      symbols([...rows].sort(compareRows({ columnId: "size", direction })));
    expect(size("descending")).toEqual([
      "BTCUSDT",
      "ETHUSDT",
      "ADAUSDT",
      "XRPUSDT",
      "SOLUSDT",
      "NEWUSDT",
    ]);
    expect(size("ascending").at(-1)).toBe("NEWUSDT");
    const since = symbols(
      [...rows].sort(compareRows({ columnId: "since", direction: "ascending" })),
    );
    expect(since).toEqual(["BTCUSDT", "ETHUSDT", "ADAUSDT", "XRPUSDT", "SOLUSDT", "NEWUSDT"]);
    const name = symbols(
      [...rows].sort(compareRows({ columnId: "symbol", direction: "descending" })),
    );
    expect(name[0]).toBe("XRPUSDT");
  });

  it("test_order_is_the_servers_until_a_sort_and_nothing_re_sorts_on_new_values", () => {
    const first = nextOrder(null, D02_ROWS, undefined);
    expect(first.symbols).toEqual(symbols(D02_ROWS));
    const sorted = nextOrder(first, D02_ROWS, { columnId: "size", direction: "descending" });
    expect(sorted.symbols).toEqual(["BTCUSDT", "ETHUSDT", "ADAUSDT", "XRPUSDT", "SOLUSDT"]);
    // SOLUSDT grows past BTCUSDT: the order stays until the next explicit sort (§9.1).
    const grown = D02_ROWS.map((r) => (r.symbol === "SOLUSDT" ? { ...r, diskBytes: 9e12 } : r));
    expect(nextOrder(sorted, grown, sorted.sort)).toBe(sorted);
  });

  it("test_a_new_row_joins_the_end_and_a_row_that_left_leaves_its_place", () => {
    const first = nextOrder(null, D02_ROWS, undefined);
    const joined = nextOrder(first, [row("AAVEUSDT"), ...D02_ROWS.slice(1)], undefined);
    expect(joined.symbols).toEqual(["ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AAVEUSDT"]);
  });
});

describe("a model row as CMP-177's props (D02 §4.2)", () => {
  it("test_row_data_carries_the_cells_inputs_and_the_budget_share", () => {
    const sol = D02_ROWS[2] as RecorderRow;
    const data = rowData(sol, { ...CONTEXT, diskLevel: 1 });
    expect(data).toMatchObject({
      symbol: "SOLUSDT",
      reason: "chart_open",
      state: "recording",
      stopBlockedReason: "chart_open",
      dailyGrowthBytes: 0.11e9,
      growthEstimated: true,
      diskLevel: 1,
      symbolLimit: 20,
      graceSeconds: 1800,
      now: NOW,
    });
    expect(data?.budgetShare).toBeCloseTo(1.3e6 / 200e9);
    expect(data?.why).toContain("SOLUSDT's chart has been open since");
  });

  it("test_a_manual_row_has_no_why_and_a_row_without_a_reason_waits_for_the_frame", () => {
    expect(rowData(D02_ROWS[0] as RecorderRow, CONTEXT)?.why).toBeUndefined();
    expect(rowData(row("DOGEUSDT", { reason: null, state: "refused" }), CONTEXT)).toBeNull();
  });

  it("test_a_stopped_rows_end_is_its_last_sessions_and_its_gap_count_coverages", () => {
    const ctx: RowContext = {
      ...CONTEXT,
      stoppedAtMs: new Map([["ADAUSDT", Date.parse("2026-10-18T09:00:00Z")]]),
      gaps: new Map([["ETHUSDT", 2]]),
    };
    expect(rowData(D02_ROWS[4] as RecorderRow, ctx)?.stoppedAt).toBe("2026-10-18T09:00:00.000Z");
    expect(rowData(D02_ROWS[1] as RecorderRow, ctx)?.gapCount).toBe(2);
  });
});

describe("the Why? words (D02 §5.1)", () => {
  it("test_why_chart_names_the_open_dwell_start_grace_and_retention", () => {
    const sol = row("SOLUSDT", {
      reason: "chart_open",
      startedAt: "2026-10-20T10:14:00Z",
      retentionDays: 30,
    });
    expect(whyWords(sol, POLICY)).toBe(
      "SOLUSDT's chart has been open since 10:13 UTC; recording started 60 s later, at 10:14. It stops 30 min after the last SOLUSDT chart closes. Data is kept for 30 days.",
    );
    expect(whyWords({ ...sol, pinned: true, retentionDays: null }, POLICY)).toMatch(
      /Data is kept forever\.$/,
    );
  });

  it("test_why_position_rule_and_alert", () => {
    const xrp = row("XRPUSDT", { reason: "position_open", startedAt: "2026-10-20T09:02:00Z" });
    expect(whyWords(xrp, POLICY)).toBe(
      "XRPUSDT has an open position (since 09:02 UTC); recording continues while it is open and stops 30 min after the last reason ends.",
    );
    expect(whyWords({ ...xrp, reason: "rule_dependency" }, POLICY)).toMatch(/^A rule depends on/);
    expect(whyWords({ ...xrp, reason: "alert_dependency" }, POLICY)).toMatch(/^An alert depends/);
  });
});

describe("refusal words (E16-D06 §16.4)", () => {
  it("test_a_deck_route_reads_its_sentence_then_the_code", () => {
    const route = {
      kind: "deck",
      key: "storage.job.refused.running",
      code: "job_running",
    } as const;
    expect(refusalText({ ...route, serverTime: null }, "compact")).toBe(
      "A compaction is already running. (job_running)",
    );
  });

  it("test_the_generic_t4_is_the_outcome_then_the_code_and_no_answer_is_the_apps_words", () => {
    const t4 = { kind: "t4", code: "conflict", field: null, status: 409 } as const;
    expect(refusalText(t4, "stop")).toBe("Not stopped: the server refused it. (conflict)");
    expect(refusalText({ ...t4, code: null, status: 503 }, "add")).toBe(
      "Not started: the server refused it.",
    );
    expect(refusalText({ ...t4, code: null, status: 0 }, "add")).toBe(
      "Cannot reach the server. Try again.",
    );
  });

  it("test_the_page_deck_rows_equal_the_deck", () => {
    const file = resolve(import.meta.dirname, "../../../../../docs/design/E16/E16-D06-copy.json");
    const deck = (
      JSON.parse(readFileSync(file, "utf8")) as { strings: Record<string, { string: string }> }
    ).strings;
    for (const [key, row] of Object.entries(PAGE_DECK)) {
      expect(row.join(" · ")).toBe(deck[key]?.string);
    }
  });
});
