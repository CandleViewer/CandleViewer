// E16-S01 slice 3: SCR-140's row model — the merge by symbol (BQ-7), the severity-first state
// (BQ-8), the T2 reasons, Silent, the summary line, the batch's phrases and the formatters. The
// clock is a fixed T0 (no timers here); the derivation is checked over every input combination.
import { describe, expect, it } from "vitest";
import {
  batchPhrase,
  buildRows,
  deriveRowState,
  firstSeen,
  formatBytes,
  formatCap,
  formatClock,
  formatDate,
  formatDayMonth,
  formatHourMinute,
  lingerCountdown,
  parseMs,
  rowChanges,
  rowStates,
  staleLine,
  stateWords,
  stopBlockedKey,
  summaryLine,
  symbolCapReached,
  t2Reason,
  updatedLine,
  type DeriveInput,
  type RecordedSymbol,
  type RecorderFrame,
  type RecorderRow,
  type RecordingState,
  type RecordingStatus,
  type RowState,
} from "../../../src/features/recorder/model";
import { D02_FRAME, LIST_TWO, POLICY, STATUS_HEALTHY, T0, modelFrame } from "./modelFixtures";

const build = (
  frame: RecorderFrame | null,
  rest: readonly RecordedSymbol[] = [],
  gated = false,
  status: RecordingStatus = STATUS_HEALTHY,
) => buildRows({ rest, status, frame, gateClosed: gated, nowMs: T0 });
const rows = (symbols: RecorderFrame["symbols"]) => build(modelFrame(symbols));
const of = (list: RecorderRow[], symbol: string): RecorderRow => {
  const row = list.find((r) => r.symbol === symbol);
  if (row === undefined) throw new Error(`no ${symbol} row`);
  return row;
};
const CTX = { nowMs: T0, maxSymbols: 20 };

describe("recorder rows (BQ-7)", () => {
  it("test_rows_merge_rest_and_status_by_symbol_with_the_refused_entry", () => {
    const list = build(null, LIST_TWO);
    expect(list.map((r) => [r.symbol, r.state, r.id])).toEqual([
      ["BTCUSDT", "recording", "e1000000-0000-4000-8000-000000000001"],
      ["ETHUSDT", "lingering", "e1000000-0000-4000-8000-000000000002"],
      ["SOLUSDT", "refused", null],
    ]);
    expect(of(list, "SOLUSDT")).toMatchObject({
      refusal: "symbol_cap",
      pinned: false,
      depth: null,
    });
    expect(of(list, "ETHUSDT").lingerUntilMs).toBe(Date.parse("2026-09-14T11:00:30Z"));
    expect(
      build(null, LIST_TWO, false, { symbols: [{ state: "recording" }] }).map((r) => r.symbol),
    ).toEqual(["BTCUSDT", "ETHUSDT"]);
  });

  it("test_rows_frame_overlays_live_fields_keeps_rest_details_and_adds_unlisted_symbols", () => {
    const list = build(
      modelFrame([
        { symbol: "BTCUSDT", state: "degraded", disk_bytes: 900 },
        { symbol: "ETHUSDT", state: "idle" }, // untracked: the REST row stands
        { symbol: "XRPUSDT", state: "starting", reason: "chart_open" },
        { symbol: "DOGEUSDT", state: "idle", refusal: "disk_pressure" },
        { symbol: "LTCUSDT", state: "idle" }, // no refusal: no row
        { symbol: "ADAUSDT", state: "recording", refusal: "lease_held" as never }, // unknown: none
      ]),
      LIST_TWO,
    );
    expect(list.map((r) => `${r.symbol}:${r.state}`)).toEqual([
      "BTCUSDT:degraded",
      "ETHUSDT:lingering",
      "XRPUSDT:starting",
      "DOGEUSDT:refused",
      "ADAUSDT:recording",
    ]);
    expect(of(list, "BTCUSDT")).toMatchObject({ diskBytes: 900, depth: 200, pinned: true });
    expect(of(list, "XRPUSDT")).toMatchObject({ id: null, reason: "chart_open", startedAt: null });
    expect(of(list, "ADAUSDT").stopBlockedReason).toBeNull();
  });
});

// BQ-8's order restated as an oracle: the first condition that holds names the row's state.
const ACTIVE = (f: DeriveInput): boolean => f.state !== "idle";
const ORDER: readonly [RowState, (f: DeriveInput, gate: boolean) => boolean][] = [
  ["refused", (f) => !ACTIVE(f) && (f.refusal === "symbol_cap" || f.refusal === "disk_pressure")],
  ["stopped", (f) => f.state === "stopped"],
  ["stopping", (f) => f.state === "stopping"],
  ["gated", (f, gate) => ACTIVE(f) && gate && f.refusal !== "position_open"],
  ["error", (f) => f.state === "error"],
  ["silent", (f) => ACTIVE(f) && f.lastEventAtMs !== null && T0 - f.lastEventAtMs > 60_000],
  ["degraded", (f) => f.state === "degraded"],
  ["starting", (f) => f.state === "starting"],
  ["lingering", (f) => ACTIVE(f) && f.lingering],
  ["recording", ACTIVE],
];
const STATES: RecordingState[] = [
  "idle",
  "starting",
  "recording",
  "degraded",
  "stopping",
  "stopped",
  "error",
];
const REFUSALS = [null, "symbol_cap", "disk_pressure", "chart_open", "position_open"] as const;

describe("row state, severity first (BQ-8)", () => {
  it("test_derive_matches_the_order_for_every_input_combination", () => {
    let cases = 0;
    for (const state of STATES)
      for (const refusal of REFUSALS)
        for (const lingering of [false, true])
          for (const lastEventAtMs of [null, T0 - 60_000, T0 - 60_001])
            for (const gate of [false, true]) {
              const f = { state, refusal, lingering, lastEventAtMs };
              const expected = ORDER.find(([, holds]) => holds(f, gate))?.[0] ?? null;
              expect(deriveRowState(f, gate, T0), JSON.stringify({ ...f, gate })).toBe(expected);
              cases += 1;
            }
    expect(cases).toBe(420);
  });

  it("test_derive_a_closed_gate_is_never_masked_by_lingering_and_never_gates_a_position", () => {
    const lingering = {
      state: "recording",
      refusal: null,
      lingering: true,
      lastEventAtMs: null,
    } as const;
    expect(deriveRowState(lingering, true, T0)).toBe("gated"); // §4.1's literal order: lingering
    expect(deriveRowState({ ...lingering, refusal: "position_open" }, true, T0)).toBe("lingering");
    const states = build(D02_FRAME, [], true).map((r) => r.state);
    expect(states).toEqual(["gated", "gated", "gated", "recording", "stopped"]);
  });
});

describe("T2 reasons (D02 §8.5)", () => {
  it("test_t2_stop_blocked_comes_from_the_refusal_and_the_reason_picks_the_key", () => {
    expect(build(D02_FRAME).map((r) => [r.symbol, r.stopBlockedReason, stopBlockedKey(r)])).toEqual(
      [
        ["BTCUSDT", null, null],
        ["ETHUSDT", null, null],
        ["SOLUSDT", "chart_open", "recorder.stop_blocked.chart_auto"],
        ["XRPUSDT", "position_open", "recorder.stop_blocked.position_auto"],
        ["ADAUSDT", null, null],
      ],
    );
    const manual = rows([
      { symbol: "XRPUSDT", state: "recording", reason: "manual", refusal: "position_open" },
    ]);
    expect(manual.map(stopBlockedKey)).toEqual(["recorder.stop_blocked.position_manual"]);
    expect(t2Reason("recorder.stop_blocked.chart_auto", "30 min")).toBe(
      "Recording stops 30 min after the last chart closes.",
    );
  });

  it("test_t2_record_again_is_blocked_once_the_active_rows_reach_max_symbols", () => {
    const at = (max_symbols: number) => build({ ...D02_FRAME, policy: { ...POLICY, max_symbols } });
    expect(of(at(4), "ADAUSDT").recordAgainBlockedReason).toBe("symbol_cap");
    expect(of(at(5), "ADAUSDT").recordAgainBlockedReason).toBeNull();
    expect(symbolCapReached(at(4), 4, "DOGEUSDT")).toBe(true);
    expect(symbolCapReached(at(4), 4, "BTCUSDT")).toBe(false); // an active symbol only gains manual
    expect(symbolCapReached(at(4), null, "DOGEUSDT")).toBe(false);
  });
});

describe("words, Silent, the summary and the batch's phrases", () => {
  const ada = { ...of(build(D02_FRAME), "ADAUSDT"), retentionDays: 30 };
  const stoppedAtMs = Date.parse("2026-10-18T09:00:00Z");

  // The batch says these without a date or gaps (SR-01); #484 PR 3's row detail passes both. A row's grid words are
  // CMP-177's, and a test holds their leading words equal.
  it.each<[Partial<RecorderRow>, object, string]>([
    [{}, { stoppedAtMs }, "Stopped 18 Oct · gone by 17 Nov"],
    [{ pinned: true }, { stoppedAtMs }, "Stopped 18 Oct · kept forever"],
    [{ retentionDays: null }, { stoppedAtMs }, "Stopped 18 Oct"],
    [{}, {}, "Stopped"],
    [{ state: "degraded" }, { gaps: 2 }, "Degraded · stream unhealthy · 2 gaps in 24 h"],
    [{ state: "degraded" }, {}, "Degraded · stream unhealthy"],
    [{ state: "recording", reason: "position_open" }, {}, "Recording"],
    [
      { state: "recording", reason: "position_open", stopBlockedReason: "position_open" },
      { gaps: 1 },
      "Recording · position · 1 gap in 24 h",
    ],
    [{ state: "recording", stopBlockedReason: "position_open" }, {}, "Recording · position open"],
    [
      { state: "silent", lastEventAtMs: Date.parse("2026-09-14T10:29:40Z") },
      {},
      "No writes since 10:29:40",
    ],
    [{ state: "refused", refusal: "symbol_cap" }, {}, "Not recording: 20-symbol limit reached"],
    [
      { state: "refused", refusal: "symbol_cap" },
      { maxSymbols: null },
      "Not recording: symbol limit reached",
    ],
    [{ state: "refused", refusal: "disk_pressure" }, {}, "Not recording: disk nearly full"],
    [{ state: "gated" }, {}, "Gated · data dropped"],
  ])("test_words_follow_d02_4_1 %#", (row, ctx, words) => {
    expect(stateWords({ ...ada, ...row }, { ...CTX, ...ctx })).toBe(words);
  });

  it("test_linger_counts_whole_minutes_up_then_under_a_minute_then_stopping", () => {
    expect(lingerCountdown(T0 + 23 * 60_000 + 1, T0)).toBe("stops in 24 min");
    expect(lingerCountdown(T0 + 59_999, T0)).toBe("stops in under a minute");
    expect(lingerCountdown(T0 - 1, T0)).toBe("stopping"); // 23 §15.8: never a negative count
  });

  it("test_silent_after_60_s_without_a_write", () => {
    const at = (age: number) =>
      rows([{ symbol: "XRPUSDT", state: "recording", last_event_at_ms: T0 - age }]);
    expect([at(60_000)[0]?.state, at(60_001)[0]?.state]).toEqual(["recording", "silent"]);
  });

  it("test_silent_for_a_row_that_never_wrote_counts_from_when_it_was_first_seen_a08", () => {
    const frame = modelFrame([
      { symbol: "XRPUSDT", state: "recording" }, // no `last_event_at_ms`: nothing written yet
      { symbol: "DOGEUSDT", state: "starting" }, // its initial snapshot: not yet writing
      { symbol: "BTCUSDT", state: "recording", last_event_at_ms: T0 - 1_000 },
    ]);
    const seen = firstSeen(new Map(), frame, null, T0);
    expect([...seen]).toEqual([["XRPUSDT", T0]]);
    expect(firstSeen(seen, frame, null, T0 + 5_000)).toEqual(seen); // the first sight stands
    const later = (ms: number) =>
      buildRows({ rest: [], status: null, frame, gateClosed: false, nowMs: ms, firstSeenMs: seen });
    expect(of(later(T0 + 60_000), "XRPUSDT").state).toBe("recording");
    expect(of(later(T0 + 60_001), "XRPUSDT")).toMatchObject({ state: "silent", lastEventAtMs: T0 });
    // once it writes, the server's time is the clock again
    const wrote = modelFrame([
      { symbol: "XRPUSDT", state: "recording", last_event_at_ms: T0 + 61_000 },
    ]);
    expect(firstSeen(seen, wrote, null, T0 + 62_000)).toEqual(new Map());
  });

  it("test_batch_keeps_the_gated_rows_data_dropped_a11", () => {
    expect(batchPhrase({ ...ada, symbol: "BTCUSDT", state: "gated" }, CTX)).toBe(
      "BTCUSDT gated · data dropped",
    );
    // and never a gap count or a stop's date, whatever its context carries (SR-01: state words only)
    expect(batchPhrase({ ...ada, state: "degraded" }, { ...CTX, gaps: 2, stoppedAtMs: T0 })).toBe(
      "ADAUSDT degraded",
    );
  });

  it("test_summary_counts_recording_rows_auto_ones_and_starting", () => {
    expect(summaryLine(build(D02_FRAME), "healthy")).toBe(
      "Recording 4 symbols · 2 auto-recorded · Recorder healthy",
    );
    const one = rows([
      { symbol: "XRPUSDT", state: "recording" },
      { symbol: "DOGEUSDT", state: "starting" },
    ]);
    expect(summaryLine(one, "not_deployed")).toBe(
      "Recording 1 symbol · 0 auto-recorded · Recorder not deployed · 1 starting",
    );
    expect(summaryLine([], null)).toBe("Recording 0 symbols · 0 auto-recorded");
    expect([staleLine(T0), updatedLine(T0)]).toEqual([
      "Status stale since 10:31:02 UTC",
      "updated 10:31:02 UTC",
    ]);
  });

  it("test_batch_names_changed_rows_in_the_parents_words_and_nothing_at_first_paint", () => {
    const before = build(D02_FRAME);
    const after = rows([
      { symbol: "BTCUSDT", state: "recording", pinned: true },
      { symbol: "ETHUSDT", state: "degraded" },
      { symbol: "SOLUSDT", state: "stopped", reason: "chart_open" },
      { symbol: "XRPUSDT", state: "recording", lingering: true, linger_until_ms: T0 + 24 * 60_000 },
      { symbol: "DOGEUSDT", state: "starting" },
    ]);
    expect(rowChanges(null, before, CTX)).toEqual([]);
    expect(rowChanges(rowStates(before), after, CTX)).toEqual([
      "ETHUSDT degraded",
      "SOLUSDT stopped recording",
      "XRPUSDT recording · stops in 24 min",
      "DOGEUSDT starting",
    ]);
    // a row that leaves while active names its symbol; a stopped one leaves silently
    expect(rowChanges(rowStates(after), after.slice(0, 1), CTX)).toEqual([
      "ETHUSDT stopped recording",
      "XRPUSDT stopped recording",
      "DOGEUSDT stopped recording",
    ]);
  });
});

/** mulberry32: a small seeded PRNG, so a failing case names its seed and replays exactly. */
function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4_294_967_296;
  };
}

describe("formatters (D02 §1, §8; UTC)", () => {
  it("test_format_matches_the_boards", () => {
    expect([34.8e9, 11e9, 1.3e6, 1_188e9].map(formatBytes)).toEqual([
      "34.8 GB",
      "11.0 GB",
      "1.3 MB",
      "1,188.0 GB",
    ]);
    expect([200e9, 2_000e9, 61.4e9].map(formatCap)).toEqual(["200 GB", "2,000 GB", "61.4 GB"]);
    // A-5309-10: what would print as 1,000.0 MB is 1.0 GB
    expect([999_949_999, 999_950_000, 999_960_000].map(formatBytes)).toEqual([
      "999.9 MB",
      "1.0 GB",
      "1.0 GB",
    ]);
    expect([formatClock, formatHourMinute, formatDate, formatDayMonth].map((f) => f(T0))).toEqual([
      "10:31:02",
      "10:31",
      "2026-09-14",
      "14 Sep",
    ]);
    expect([parseMs("2026-09-14T10:31:02Z"), parseMs("not a time"), parseMs(null)]).toEqual([
      T0,
      null,
      null,
    ]);
    // A-5309-10: a finite epoch past `Date`'s range is no time, never a RangeError
    const far = 9e15;
    expect([formatClock, formatHourMinute, formatDate, formatDayMonth].map((f) => f(far))).toEqual([
      "—",
      "—",
      "—",
      "—",
    ]);
  });

  it("test_format_bytes_keep_one_decimal_and_a_unit_for_any_size_seeded", () => {
    for (let seed = 1; seed <= 200; seed += 1) {
      const rand = mulberry32(seed);
      const bytes = Math.floor(rand() * 10 ** (1 + rand() * 13));
      const text = formatBytes(bytes);
      expect(text, `seed ${seed}`).toMatch(/^\d{1,3}(,\d{3})*\.\d (GB|MB)$/);
      const unit = text.endsWith("GB") ? 1e9 : 1e6;
      const shown = Number(text.replace(/,| GB| MB/g, "")) * unit;
      expect(Math.abs(shown - bytes), `seed ${seed}`).toBeLessThanOrEqual(0.05 * unit + 1);
    }
  });
});
