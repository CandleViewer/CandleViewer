/** E16-S05: SCR-047's decision table (E11-D04 §11.2; E16-D05 §1.5, §4), every row, and the deck per frame. */
import { describe, expect, it } from "vitest";
import * as F from "../../../src/features/chart-empty/fixtures";
import * as M from "../../../src/features/chart-empty/model";
import { ROUTE_MANIFEST } from "../../../src/routes/manifest";

type Row = Partial<M.ChartStateInput>;
const { at, OWNER, VIEWER, VIEWING_AS } = F;
const WORDS: M.ViewWords = {
  ownerOnly: "Only the owner can change recording.",
  viewAs: (user) => `Read-only while viewing as ${user}.`,
};
const empty = (row: Row): Extract<M.ChartState, { kind: "empty" }> => {
  const state = M.selectChartState(F.input(row));
  if (state.kind !== "empty") throw new Error(`expected empty, got ${state.kind}`);
  return state;
};
const view = (row: Row, access = OWNER, words = WORDS) =>
  M.emptyView(empty({ ...row, access }), words);
const ids = (row: Row, access = OWNER) => view(row, access).actions.map((a) => a.id);
const W = (from: string, to: string): Row => ({ window: { fromMs: at(from), toMs: at(to) } });
const NEVER: Row = { bars: { kind: "no_data_recorded", recordingStartedAtMs: null } };
const STARTED: Row = { bars: { kind: "no_data_recorded", recordingStartedAtMs: 5 } };
const EARLY = W("2026-08-20T00:00:00Z", "2026-08-21T00:00:00Z");
const QUIET = W("2026-09-08T00:00:00Z", "2026-09-08T01:00:00Z");
const PURGED = F.read(F.RETENTION_COVERAGE);
const RETENTION: Row = { ...W("2026-09-05T00:00:00Z", "2026-09-06T00:00:00Z"), coverage: PURGED };
const spans: [string, string][] = [["2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z"]];
const unrecorded = F.gap("2026-09-04T02:00:00Z", "2026-09-04T03:00:00Z", "never_recorded");
const NEVER_GAP: Row = { coverage: F.read(F.cov("", spans, [unrecorded])) };
const NONE: Row = { coverage: F.read(F.NEVER_COVERAGE) };

describe("selectChartState: the decision table", () => {
  it.each<[Row, string]>([
    [{ bars: { kind: "loading" } }, "loading"],
    [{ bars: { kind: "failed" } }, "bootstrap-failed"],
    [{ coverage: null }, "loading"],
    [{ coverage: F.FAILED }, "coverage-error"],
    [{ coverage: { kind: "refused_422" } }, "coverage-error"],
    [{ coverage: { kind: "forbidden" } }, "coverage-error"],
  ])("%j → %s", (row, kind) => {
    expect(M.selectChartState(F.input(row)).kind).toBe(kind);
  });

  it.each<[string, Row, string, string]>([
    ["422, null start", NEVER, "never-recorded", "1a"],
    ["no interval", NONE, "never-recorded", "1a"],
    ["a never_recorded gap", NEVER_GAP, "never-recorded", "1a"],
    ["422 with a start", STARTED, "before-start", "1b"],
    ["window before coverage", EARLY, "before-start", "1b"],
    ["window inside a gap", {}, "gap", "2"],
    ["a purge wins over 1b", { ...RETENTION, ...STARTED }, "gap-retention-purge", "2"],
    ["covered, zero bars", QUIET, "no-trades-in-window", "2"],
    ["not trading wins", { ...NEVER, instrumentStatus: "Closed" }, "not-trading", "3"],
    ["restricted wins first", { ...NEVER, roleRestricted: true }, "role-restricted", "2"],
  ])("%s → %s (%s)", (_n, row, frame, reason) => {
    const s = empty(row);
    expect([s.frame, s.reason]).toEqual([frame, reason]);
  });

  it("carries the start, the trim date and the whole gap", () => {
    expect(empty(STARTED).atMs).toBe(5);
    expect(empty(EARLY).atMs).toBe(at("2026-09-01T00:00:00Z"));
    expect(empty(RETENTION).atMs).toBe(at("2026-09-14T00:00:00Z"));
    expect(empty({}).gap?.toMs).toBe(at("2026-09-04T02:14:20Z"));
  });

  it("populated: the clipped gaps go to the engine; a failed coverage claims none", () => {
    const row: Row = {
      ...W("2026-09-04T02:20:00Z", "2026-09-04T06:00:00Z"),
      bars: { kind: "ok", count: 9 },
    };
    const ac4 = F.read(F.AC4_COVERAGE);
    const gap = { fromMs: at("2026-09-04T02:20:00Z"), toMs: at("2026-09-04T02:23:00Z") };
    expect(M.selectChartState(F.input({ ...row, coverage: ac4 }))).toEqual({
      kind: "populated",
      coverageKnown: true,
      gaps: [{ ...gap, reason: "ws_disconnect", backfilled: false }],
    });
    const failed = M.selectChartState(F.input({ ...row, coverage: F.FAILED }));
    expect(failed).toEqual({ kind: "populated", gaps: [], coverageKnown: false });
    const pending = M.selectChartState(F.input({ ...row, coverage: null }));
    expect(pending).toEqual({ kind: "populated", gaps: [], coverageKnown: true });
  });

  it("range-empty: the engine's dataState empty with bars loaded decides from coverage (26:446)", () => {
    const bars = { kind: "ok", count: 9 } as const;
    expect(empty({ bars, dataState: "empty" }).frame).toBe("gap");
    expect(empty({ ...QUIET, bars, dataState: "empty" }).frame).toBe("no-trades-in-window");
    expect(M.selectChartState(F.input({ bars, dataState: "ready" })).kind).toBe("populated");
  });
});

describe("emptyView: the deck per frame and viewer (D05 §4)", () => {
  it("never-recorded: the Owner's CTA; the sentence form for others, view-as first", () => {
    const v = view(NEVER);
    expect(v.heading).toBe("History starts when you record BTCUSDT — recording has not begun yet.");
    expect(v.description).toBe(
      "Nothing is missing or broken: CandleViewer keeps only what it records.",
    );
    expect([v.variant, v.glyph, v.live]).toEqual(["recording-not-started", "calendar", true]);
    expect(ids(NEVER)).toEqual(["record", "learn_more"]);
    expect([ids(NEVER, VIEWER), ids(NEVER, VIEWING_AS)]).toEqual([["learn_more"], ["learn_more"]]);
    expect(view(NEVER, VIEWER).description).toMatch(
      /records\. Only the owner can change recording\.$/,
    );
    expect(view(NEVER, VIEWING_AS).description).toMatch(/Read-only while viewing as alex\.$/);
  });

  const STARTED_AT: Row = {
    bars: { kind: "no_data_recorded", recordingStartedAtMs: at("2026-09-01T08:00:00Z") },
  };
  it.each<[string, Row, string]>([
    [
      "before-start",
      STARTED_AT,
      "History starts 2026-09-01 08:00 UTC — recording began then. Nothing is missing or broken: CandleViewer keeps only what it records.",
    ],
    [
      "gap-ws-disconnect",
      {},
      "No bars for BTCUSDT 1m between 02:11 and 02:14 UTC. Recording was interrupted (connection to the exchange lost).",
    ],
    [
      "gap-retention-purge",
      RETENTION,
      "BTCUSDT history before 2026-09-14 was removed by the retention policy. Older data was removed by the retention policy (30 days).",
    ],
    [
      "no-trades-in-window",
      QUIET,
      "No bars for BTCUSDT 1m in this window. No trades were recorded in this window.",
    ],
    [
      "not-trading",
      { instrumentStatus: "PreLaunch" },
      "BTCUSDT is not trading on Bybit. Not trading yet — status: Pre-launch. No live data will arrive.",
    ],
    [
      "role-restricted",
      { roleRestricted: true },
      "No bars for BTCUSDT 1m in this window. Recording status restricted",
    ],
  ])("%s: heading, then cause", (_n, row, words) => {
    const v = view(row);
    expect(`${v.heading} ${v.description}`).toBe(words);
  });

  it("the actions per frame (exits never gated)", () => {
    const exits = ["go_latest", "show_coverage"];
    const rows: Row[] = [STARTED_AT, {}, RETENTION, QUIET, { instrumentStatus: "Closed" }];
    expect(rows.map((row) => ids(row, VIEWER))).toEqual([
      ["go_recorded", "show_coverage"],
      exits,
      exits,
      exits,
      ["open_symbol", "switch_symbol"],
    ]);
    expect(ids({ roleRestricted: true })).toEqual(["show_coverage"]);
  });

  it("not trading: status_reason first, else the listed words or the fallback; the panel heading", () => {
    expect(view({ instrumentStatus: "Settling" }).description).toBe(
      "Status: Settling. No live data will arrive.",
    );
    const said = view({ instrumentStatus: "Closed", statusReason: "Delisted by Bybit." });
    expect(said.description).toBe("Delisted by Bybit. No live data will arrive.");
    const panel = view({ roleRestricted: true }, OWNER, { ...WORDS, panel: true });
    expect(panel.heading).toBe("No history is available for BTCUSDT here.");
  });

  it("the live sentence only while Trading; retention stays recording-not-started (BQ-7)", () => {
    const live = (row: Row): boolean => view(row).live;
    expect([live({}), live({ instrumentStatus: "Closed" })]).toEqual([true, false]);
    expect(live({ ...NEVER, instrumentStatus: null })).toBe(false);
    expect(live({ roleRestricted: true, instrumentStatus: "Closed" })).toBe(false);
    expect([view(RETENTION).variant, view({}).variant]).toEqual([
      "recording-not-started",
      "no-data",
    ]);
  });

  it("the /admin/** link is the Owner's: dropped without admin:read and while viewing as", () => {
    const href = "/admin/recorder";
    expect(view(RETENTION).link).toEqual({
      id: "retention_policy",
      label: "Retention policy",
      href,
    });
    expect([view(RETENTION, VIEWER).link, view(RETENTION, VIEWING_AS).link]).toEqual([null, null]);
    expect(view({ ...RETENTION, retentionDays: 7 }).description).toMatch(/\(7 days\)/);
  });
});

describe("helpers", () => {
  it("accessOf reads permissions, never a role name; recordHref is the registry's R-340", () => {
    expect(M.accessOf(["recording:write", "admin:read"], null)).toEqual(OWNER);
    expect(M.accessOf(["marketdata:read"], null)).toEqual(VIEWER);
    const r340 = ROUTE_MANIFEST.find((e) => e.id === "R-340");
    expect([M.RECORDER_ROUTE, M.recordHref()]).toEqual(["R-340", r340?.path]);
  });

  const started = Date.parse("2026-09-01T08:00:00Z");
  it.each<[number, unknown, number | null | "none"]>([
    [422, { code: "no_data_recorded", recording_started_at: "2026-09-01T08:00:00Z" }, started],
    [422, { code: "no_data_recorded", recording_started_at: null }, null],
    [422, { code: "no_data_recorded", recording_started_at: "x" }, null],
    [422, { code: "bar_window_too_large" }, "none"],
    [400, { code: "no_data_recorded" }, "none"],
    [422, null, "none"],
    [422, { code: 7 }, "none"],
  ])("noDataRecorded %i %j → %s", (status, body, ms) => {
    const want = ms === "none" ? null : { kind: "no_data_recorded", recordingStartedAtMs: ms };
    expect(M.noDataRecorded(status, body)).toEqual(want);
  });

  it.each<[Row, object]>([
    [NEVER, { reason: "not_recorded" }],
    [{}, { reason: "no_data_in_range", cause: "ws_disconnect" }],
    [{ instrumentStatus: "Closed" }, { reason: "symbol_delisted" }],
  ])("chart.empty_state_shown %j", (row, event) => {
    expect(M.chartAnalytics(empty(row))).toEqual(event);
  });
});
