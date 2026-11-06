/**
 * E42-S06 (#1084) part 1b: SCR-143's models (E42-D05 §5.3, D2–D10): one tone per contract word, the
 * probe line where it applies, stale only after a failure (D6), what stops and what to do, D9's
 * legs, the runbook link, the clock, the overall line, the banner and the build line.
 */
import { describe, expect, it } from "vitest";
import { foldHealthFrame, NO_WORDS } from "../../../../src/features/admin/health/frames";
import type { HealthState } from "../../../../src/features/admin/health/healthStore";
import * as tiles from "../../../../src/features/admin/health/tiles";

const T = Date.parse("2026-10-22T14:02:11Z");
const IDLE = { phase: "idle", inFlight: false } as const;
const ok = (data: unknown) => ({ phase: "ok", inFlight: false, data, okAt: T });
const failed = (failure: object) => ({ ...ok(REPORT), phase: "failed", failedAt: T + 5, failure });
const page = (items: unknown[] = [], has_more = false) => ({
  items,
  meta: { has_more, count: items.length, next_cursor: has_more ? "c" : null },
});
const REPORT = {
  ...{ overall: "down", version: "1.4.0", git_sha: "abc1234", environment: "demo" },
  uptime_seconds: 93_600,
  components: [
    { name: "postgres", state: "healthy", latency_ms: 3 },
    { name: "disk", state: "warning", detail: "30% free", last_good_at: "2026-10-22T14:01:40Z" },
    { name: "bybit_rest", state: "down", latency_ms: 1_000 },
    { name: "bars_writer", state: "not_deployed" },
    { name: "new_thing", state: "healthy", latency_ms: 2 },
  ],
};
type Word = "healthy" | "degraded" | "warning" | "down";
const framed = (name: string, state: Word) =>
  foldHealthFrame(NO_WORDS, { kind: "health", components: [{ name, state }] });
type Over = Partial<Omit<HealthState, "reads">> & { reads?: Record<string, unknown> };
/** The report answered at T, both incident pages empty, the protection counters unread. */
function state({ reads, ...over }: Over = {}): HealthState {
  const all = { health: ok(REPORT), open: ok(page()), acknowledged: ok(page()), protection: IDLE };
  // Plain literals in the vetted shapes stand for the store's answers.
  const s = { words: NO_WORDS, clock: {}, denied: null, ...over, reads: { ...all, ...reads } };
  return s as unknown as HealthState;
}
const tile = (name: string, over?: Over) => tiles.tileOf(name, state(over));
const PROTECTED = { kinds: [{ machine_kind: "position_protection", degraded_machines: 0 }] };
const protectedOk = ok({ ...PROTECTED, snapshots: { status: "ok" } });

describe("SCR-143's tile models", () => {
  it("test_tiles_one_tone_per_contract_word_and_a_probe_line_only_where_it_applies", () => {
    expect(tile("postgres")).toMatchObject({
      ...{ label: "Postgres (postgres)", href: "?component=postgres", anchor: "health-postgres" },
      ...{ tone: "ok", stateWord: "healthy", probe: true, value: 3, asOf: T, state: "ready" },
    });
    expect(tile("disk")).toMatchObject({ tone: "warning", stateWord: "warning", probe: false });
    expect(tile("bybit_rest")).toMatchObject({ tone: "danger", stateWord: "down", probe: false });
    expect(tile("bars_writer")).toMatchObject({ tone: "neutral", stateWord: "Not built yet" });
    expect(tile("new_thing")).toMatchObject({ label: "new_thing", value: 2 });
    expect(tile("postgres", { reads: { health: { ...ok(REPORT), phase: "idle" } } })?.state).toBe(
      "loading",
    );
  });

  it("test_tiles_a_fault_says_what_stops_and_what_to_do_and_safe_only_with_every_leg", () => {
    expect(tile("disk")).toMatchObject({
      stopsWorking: "recording stops at 95 %",
      hint: "Free space on the server's data disk, or shorten retention in Recorder & storage.",
      lastGoodAt: Date.parse("2026-10-22T14:01:40Z"),
      stillSafe: false,
    });
    expect(tile("postgres")).toMatchObject({ stopsWorking: undefined, hint: undefined });
    const reads = { protection: protectedOk };
    // The report is the newer source (the frame was held at mount) and must list `oms` itself.
    const served = {
      ...REPORT,
      components: [...REPORT.components, { name: "oms", state: "healthy" }],
    };
    const words = framed("oms", "healthy");
    expect(tile("disk", { words, reads: { ...reads, health: ok(served) } })?.stillSafe).toBe(true);
  });

  it("test_tiles_d9_withholds_when_a_newer_frame_downs_oms_or_names_it_in_an_unknown_state", () => {
    const served = [...REPORT.components, { name: "oms", state: "healthy" }];
    const reads = { health: ok({ ...REPORT, components: served }), protection: protectedOk };
    expect(tile("disk", { reads })?.stillSafe).toBe(true);
    // The frame's words changed before the report answered; the frame was seen after it.
    const down = framed("oms", "down");
    expect(tile("disk", { reads, words: down, framesSeenAt: T + 1_000 })?.stillSafe).toBe(false);
    const unknown = framed("oms", "exploded" as Word);
    expect(tile("disk", { reads, words: unknown, framesSeenAt: T + 1_000 })?.stillSafe).toBe(false);
    expect(tile("oms", { reads, words: unknown, framesSeenAt: T + 1_000 })).toMatchObject({
      ...{ tone: "neutral", stateWord: "— not received", probe: false, value: undefined },
      stillSafe: false,
    });
  });

  it("test_tiles_d9_withholds_when_a_newer_frame_no_longer_lists_oms", () => {
    const served = [...REPORT.components, { name: "oms", state: "healthy" }];
    const reads = { health: ok({ ...REPORT, components: served }), protection: protectedOk };
    const words = framed("postgres", "healthy");
    expect(tile("disk", { reads, words, framesSeenAt: T - 1_000 })?.stillSafe).toBe(true);
    expect(tile("disk", { reads, words, framesSeenAt: T + 1_000 })?.stillSafe).toBe(false);
  });

  it("test_tiles_a_word_not_received_is_a_neutral_tile_neither_down_nor_healthy", () => {
    const words = framed("bybit_rest", "exploded" as Word);
    const s = state({ words, framesSeenAt: T + 1_000 });
    expect(tiles.tileOf("bybit_rest", s)).toMatchObject({
      ...{ tone: "neutral", stateWord: "— not received", value: undefined },
      ...{ stopsWorking: undefined, hint: undefined, lastGoodAt: undefined },
    });
    expect(tiles.pageLines(s).banner).toBeUndefined();
    expect(tiles.voiceStates(s)).toContainEqual({
      ...{ name: "bybit_rest", label: "Bybit REST", state: "not_received" },
    });
  });

  it("test_tiles_a_newer_frame_gives_the_word_and_the_number_keeps_its_own_as_of", () => {
    const words = framed("postgres", "degraded");
    const model = tile("postgres", { words, framesSeenAt: T + 1_000 });
    expect(model).toMatchObject({
      ...{ stateWord: "degraded", framesAsOf: true, value: 3, valueAsOf: T },
      stopsWorking: "saving may be slow.",
    });
    // The frame's "as of" is the page's leaf: a later frame with the same words, the same model.
    expect(model?.asOf).toBeUndefined();
    expect(tile("postgres", { words, framesSeenAt: T + 2_000 })).toEqual(model);
  });

  it("test_tiles_stale_only_after_a_failed_read_and_a_frames_word_once_the_transport_dropped", () => {
    expect(tile("x", { words: framed("x", "healthy"), droppedAt: T })?.staleSince).toBeUndefined();
    const health = failed({ reason: "timeout" });
    expect(tile("postgres", { reads: { health } })).toMatchObject({
      staleSince: T + 5,
      retry: true,
    });
    expect(tile("disk", { reads: { health } })?.staleSince).toBe(T + 5);
    const words = framed("x", "healthy");
    const seen = { words, framesSeenAt: T + 1 }; // newer than the report: `x` is the frame's
    expect(tile("x", { ...seen, droppedAt: T + 2, reads: { health } })?.staleSince).toBe(T + 2);
    const cold = { ...IDLE, phase: "failed", failedAt: T + 5, failure: { reason: "timeout" } };
    expect(tile("x", { words, reads: { health: cold } })).toMatchObject({
      ...{ value: null, staleSince: undefined, retry: true },
    });
  });

  it("test_tiles_a_runbook_links_only_a_same_origin_path", () => {
    const runbook = (runbook_ref: string) =>
      tile("disk", { reads: { open: ok(page([{ component: "disk", runbook_ref }])) } })
        ?.runbookHref;
    expect(runbook("/docs/runbooks/disk.md#free")).toBe("/docs/runbooks/disk.md#free");
    for (const ref of ["https://x.example/r", "//x.example/r", "/\\x.example", "javascript:x"]) {
      expect(runbook(ref)).toBeUndefined();
    }
  });

  it("test_tiles_the_clock_reads_not_measured_its_offset_or_a_drift_with_its_hint", () => {
    expect(tiles.clockTile(state()).stateWord).toBe("not measured (time sync not deployed)");
    const offset = state({ reads: { health: ok({ ...REPORT, clock_offset_ms: 2_300 }) } });
    expect(tiles.clockTile(offset)).toMatchObject({
      tone: "ok",
      stateWord: "offset 2 300 ms · ok",
    });
    expect(tiles.clockTile(state({ clock: { driftAt: T, driftMs: 2_300 } }))).toMatchObject({
      tone: "danger",
      stateWord:
        "DRIFT — offset 2 300 ms — order entry halts until time sync recovers (Bybit 10002).",
      hint: expect.stringContaining("time sync"),
    });
  });
});

describe("SCR-143's lines", () => {
  it("test_lines_the_overall_line_reads_the_newer_source_and_hl15_its_own", () => {
    expect(tiles.overallLine(state())).toBe("Overall: down · as of 14:02:11");
    expect(tiles.overallLine(state({ overall: { word: "degraded", at: T + 1_000 } }))).toBe(
      "Overall: degraded · as of 14:02:12 (last health frame)",
    );
    const mounted = state({ reads: { health: IDLE }, overall: { word: "healthy" } });
    expect(tiles.overallLine(mounted)).toBe("Overall: healthy (last health frame)");
    const health = failed({ status: 503, code: "audit_unavailable" });
    expect(tiles.overallLine(state({ reads: { health } }))).toBe(
      "Unavailable — the audit log can't record the read",
    );
  });

  it("test_lines_the_banner_the_incidents_count_the_build_and_the_failed_report", () => {
    expect(tiles.pageLines(state())).toMatchObject({
      incidents: "Incidents (0 open)",
      banner: { title: "Down: Bybit REST. Each tile says what stops working.", safe: false },
      build: "1.4.0 · abc1234 · demo · up 1 d 2 h",
      report: undefined,
    });
    const more = state({ reads: { open: ok(page([{ component: "x" }], true)) } });
    expect(tiles.pageLines(more).incidents).toBe("Incidents (1+ open)");
    const health = { ...failed({ reason: "timeout" }), answers: 2 };
    expect(tiles.pageLines(state({ reads: { health } })).report).toEqual({
      text: "Health report unavailable — no answer in 3 s. Showing live states only.",
      ...{ answers: 2, busy: false },
    });
    const notBuilt = state({ reads: { health: { ...IDLE, phase: "not_built" } } });
    expect(tiles.pageLines(notBuilt).probesNotDeployed).toBe(true);
  });

  it("test_lines_d9_legs_miss_each_read_that_did_not_answer_ok", () => {
    const s = state({ reads: { acknowledged: { ...IDLE, phase: "failed" } } });
    expect(tiles.legsOf(s, tiles.componentsOf(s))).toEqual({
      ...{ oms: undefined, open: page(), acknowledged: undefined, protection: undefined },
    });
  });
});
