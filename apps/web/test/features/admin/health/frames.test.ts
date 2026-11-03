/**
 * E42-S06 (#1084) part 1: SCR-143's component records (E42-D05 D5, D6): words from the newer source,
 * numbers from the report, one record per changed component, the mount frame untimed [BQ-8], HL-8.
 */
import { describe, expect, it } from "vitest";
import {
  clockOf,
  foldClock,
  foldHealthFrame,
  mergeComponents,
  NO_WORDS,
  type SystemUpdate,
} from "../../../../src/features/admin/health/frames";
import type { HealthReport } from "../../../../src/features/admin/ops/opsReads";

const T = Date.parse("2026-10-22T14:02:11Z");
type Item = NonNullable<SystemUpdate["components"]>[number];
const frame = (...components: Item[]): SystemUpdate => ({ kind: "health", components });
const ok = (name: string, last_good_at = "2026-10-22T14:02:10Z"): Item =>
  ({ name, state: "healthy", last_good_at }) as const;
type Served = NonNullable<HealthReport["components"]>;
const report = (components: Served, at = T) => ({ body: { components }, at });

describe("foldHealthFrame", () => {
  it("test_fold_a_second_identical_frame_changes_nothing_for_any_record", () => {
    const mounted = foldHealthFrame(NO_WORDS, frame(ok("oms"), ok("disk")));
    expect(mounted.get("oms")).toEqual({ state: "healthy", detail: undefined });
    // A healthy component's last good time moves every probe: the same words, no new object [BQ-8].
    expect(foldHealthFrame(mounted, frame(ok("oms", "x"), ok("disk")))).toBe(mounted);
  });

  it("test_fold_a_frame_that_changes_one_component_changes_one_record", () => {
    const before = foldHealthFrame(NO_WORDS, frame(ok("oms"), ok("disk")));
    const warning = { ...ok("disk", "2026-10-22T14:01:40Z"), state: "warning", detail: "30% free" };
    const after = foldHealthFrame(before, frame(ok("oms"), warning as Item));
    expect(after.get("oms")).toBe(before.get("oms"));
    expect(after.get("disk")).toEqual({
      state: "warning",
      detail: "30% free",
      lastGoodAt: Date.parse("2026-10-22T14:01:40Z"),
    });
  });

  it("test_fold_a_named_item_it_cannot_read_has_no_word_a_gone_name_retires_a_nameless_is_ignored", () => {
    const before = foldHealthFrame(NO_WORDS, frame(ok("oms"), ok("disk")));
    const words = foldHealthFrame(
      before,
      frame(
        { name: "bars_writer", state: "healthy", detail: "not deployed" },
        { name: "oms", state: "rebooting" as "down" },
        { state: "down" },
      ),
    );
    // `oms` in a state no table knows: no word, never its last one; `disk` left the frames.
    expect([...words.entries()]).toEqual([
      ["bars_writer", { state: "not_deployed" }],
      ["oms", null],
    ]);
    expect(foldHealthFrame(words, { kind: "health" })).toBe(words);
  });
});

describe("mergeComponents", () => {
  it("test_merge_keeps_server_order_then_frame_only_names_and_numbers_from_the_report_alone", () => {
    const words = foldHealthFrame(
      NO_WORDS,
      frame(
        ok("postgres"),
        { name: "oms", state: "degraded", detail: "reconciliation pending" },
        ok("new_thing"),
      ),
    );
    const rest = report([
      { name: "postgres", state: "healthy", latency_ms: 3, latency_unit: "ms" },
      { name: "oms", state: "healthy", latency_ms: 7, latency_unit: "ms" },
    ]);
    expect(mergeComponents(rest, words, T + 1_000)).toEqual([
      {
        name: "postgres",
        source: "frame",
        state: "healthy",
        wordAt: T + 1_000,
        latencyMs: 3,
        latencyAt: T,
      },
      {
        name: "oms",
        source: "frame",
        state: "degraded",
        detail: "reconciliation pending",
        wordAt: T + 1_000,
        latencyMs: 7,
        latencyAt: T,
      },
      { name: "new_thing", source: "frame", state: "healthy", wordAt: T + 1_000 },
    ]);
  });

  it("test_merge_a_report_newer_than_the_frames_or_than_the_mount_frame_gives_the_words", () => {
    const mounted = foldHealthFrame(NO_WORDS, frame({ name: "oms", state: "down" }));
    const rest = report([{ name: "oms", state: "healthy" }], T + 5_000);
    const merged = mergeComponents(rest, mounted, undefined)[0];
    expect(merged).toMatchObject({ source: "report", state: "healthy" });
    const stamped = foldHealthFrame(NO_WORDS, frame({ name: "oms", state: "down" }));
    expect(mergeComponents(rest, stamped, T)[0]).toMatchObject({
      source: "report",
      wordAt: T + 5_000,
    });
  });

  it("test_merge_a_frame_seen_after_the_report_wins_though_its_words_did_not_change", () => {
    const down = frame({ name: "oms", state: "down" });
    const first = foldHealthFrame(NO_WORDS, down);
    const rest = report([{ name: "oms", state: "healthy" }], T + 1_000);
    const again = foldHealthFrame(first, down);
    expect(again).toBe(first);
    const merged = mergeComponents(rest, again, T + 2_000)[0];
    expect(merged).toMatchObject({ source: "frame", state: "down", wordAt: T + 2_000 });
  });

  it("test_merge_a_frame_seen_at_the_reports_own_answer_time_gives_the_words", () => {
    const words = foldHealthFrame(NO_WORDS, frame({ name: "oms", state: "down" }));
    const rest = report([{ name: "oms", state: "healthy" }], T);
    // D5: frames win "at or after" the report answered; a tie is the frames'.
    expect(mergeComponents(rest, words, T)[0]).toMatchObject({
      source: "frame",
      state: "down",
      wordAt: T,
    });
    expect(mergeComponents(rest, words, T - 1)[0]).toMatchObject({ source: "report" });
  });

  it("test_merge_an_unchanged_healthy_record_reads_the_newest_frame_seen_not_its_first", () => {
    const words = foldHealthFrame(NO_WORDS, frame(ok("oms")));
    const first = mergeComponents(undefined, words, T)[0];
    const second = mergeComponents(
      undefined,
      foldHealthFrame(words, frame(ok("oms"))),
      T + 1_000,
    )[0];
    expect([first?.wordAt, second?.wordAt]).toEqual([T, T + 1_000]);
    // The words held at mount, no frame since: no time; the report's words: its answer time.
    expect(mergeComponents(undefined, words, undefined)[0]?.wordAt).toBeUndefined();
    const rest = report([{ name: "oms", state: "healthy" }], T + 5_000);
    expect(mergeComponents(rest, words, T)[0]).toMatchObject({
      source: "report",
      wordAt: T + 5_000,
    });
  });

  it("test_merge_a_name_the_newer_frame_could_not_read_reads_not_received_over_an_older_report", () => {
    const words = foldHealthFrame(NO_WORDS, frame({ name: "oms", state: "x" as "down" }));
    // Neither the older report's word nor its number: the record stays, so its tile does (A-d01).
    const unread = { name: "oms", source: "frame", state: "not_received", wordAt: T + 1_000 };
    const older = report([{ name: "oms", state: "healthy", latency_ms: 7, latency_unit: "ms" }]);
    expect(mergeComponents(older, words, T + 1_000)).toEqual([unread]);
    expect(mergeComponents(undefined, words, T + 1_000)).toEqual([unread]);
    const later = report([{ name: "oms", state: "healthy" }], T + 2_000);
    expect(mergeComponents(later, words, T + 1_000)[0]).toMatchObject({ source: "report" });
  });

  it("test_merge_a_name_the_newer_frame_drops_reads_not_received_never_the_older_reports_word", () => {
    const words = foldHealthFrame(NO_WORDS, frame(ok("oms")));
    const served: Served = [
      { name: "oms", state: "healthy" },
      { name: "postgres", state: "degraded", detail: "slow", latency_ms: 3, latency_unit: "ms" },
    ];
    // The newest frame is the truth (BQ-8): its silence is no word, its tile stays (A-d01).
    expect(mergeComponents(report(served), words, T + 1_000)[1]).toEqual({
      name: "postgres",
      source: "frame",
      state: "not_received",
      wordAt: T + 1_000,
    });
    expect(mergeComponents(report(served, T + 2_000), words, T + 1_000)[1]).toMatchObject({
      source: "report",
      state: "degraded",
    });
  });

  it("test_merge_a_name_the_newer_report_no_longer_lists_reads_not_received_never_the_older_frames_word", () => {
    const words = foldHealthFrame(NO_WORDS, frame(ok("oms"), ok("gone")));
    const rest = report([{ name: "oms", state: "healthy" }], T + 2_000);
    const gone = { name: "gone", source: "report", state: "not_received", wordAt: T + 2_000 };
    // The report answered after the newest frame (or the held-at-mount one): its silence is no word.
    expect(mergeComponents(rest, words, T + 1_000)[1]).toEqual(gone);
    expect(mergeComponents(rest, words, undefined)[1]).toEqual(gone);
    // A frame seen at or after the answer is newer: its word stands.
    expect(mergeComponents(rest, words, T + 2_000)[1]).toMatchObject({
      source: "frame",
      state: "healthy",
    });
    // No report yet: the frames' names stand alone.
    expect(mergeComponents(undefined, words, T)[1]).toMatchObject({ source: "frame" });
  });

  it("test_merge_a_reported_name_with_no_readable_state_reads_not_received_never_an_older_frame", () => {
    const words = foldHealthFrame(NO_WORDS, frame(ok("oms")));
    const unread = report([{ name: "oms", latency_ms: 7, latency_unit: "ms" }], T + 1_000);
    const record = { name: "oms", source: "report", state: "not_received", wordAt: T + 1_000 };
    expect(mergeComponents(unread, NO_WORDS, undefined)).toEqual([record]);
    expect(mergeComponents(unread, words, T)).toEqual([record]);
    expect(mergeComponents(unread, words, T + 2_000)[0]).toMatchObject({
      source: "frame",
      state: "healthy",
    });
  });
});

describe("clockOf (HL-8)", () => {
  const health = (clock_offset_ms?: number): SystemUpdate =>
    clock_offset_ms === undefined ? { kind: "health" } : { kind: "health", clock_offset_ms };

  it("test_clock_reads_not_measured_then_the_reports_offset_then_the_frames", () => {
    expect(clockOf({}, undefined)).toEqual({ kind: "not_measured" });
    expect(clockOf({}, { body: { clock_offset_ms: null }, at: T })).toEqual({
      kind: "not_measured",
    });
    expect(clockOf({}, { body: { clock_offset_ms: 4 }, at: T })).toEqual({
      kind: "ok",
      offsetMs: 4,
      at: T,
    });
    const seen = foldClock({}, health(6), T + 1_000);
    expect(clockOf(seen, undefined)).toEqual({ kind: "ok", offsetMs: 6, at: T + 1_000 });
    expect(foldClock(seen, health(6), T + 2_000)).toMatchObject({ offsetAt: T + 1_000 });
  });

  it("test_clock_a_drift_notice_holds_until_a_later_offset_and_one_held_at_mount_never", () => {
    const drift: SystemUpdate = { kind: "clock_drift", clock_offset_ms: 2_300 };
    expect(foldClock({}, drift, undefined)).toEqual({});
    const drifting = foldClock(foldClock({}, health(4), T), drift, T + 1_000);
    expect(clockOf(drifting, undefined)).toEqual({ kind: "drift", offsetMs: 2_300, at: T + 1_000 });
    expect(clockOf(foldClock(drifting, health(4), T + 2_000), undefined)).toMatchObject({
      kind: "ok",
    });
  });
});
