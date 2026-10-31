// E16-S01 slice 3: SCR-140's disk card keyed on `level` (E16-D02 §3, §8.3), checked against the
// figures the boards draw (01 running, 04 paused, 05 disk warning, 06 disk critical) and `22`'s
// `usage` example; F-07's level-change phrase and the level-3 banner, its cause inferred as level 2's.
import { describe, expect, it } from "vitest";
import {
  diskCard,
  diskFacts,
  levelChange,
  levelThreeBanner,
  type DiskFacts,
  type RecorderPolicy,
} from "../../../src/features/recorder/model";
import { POLICY, STORAGE_USAGE, T0, modelFrame } from "./modelFixtures";

const facts = (over: Partial<DiskFacts> = {}): DiskFacts => ({
  level: 0,
  usedBytes: 61.4e9,
  capBytes: 200e9,
  growthBytesPerDay: 0.93e9,
  projectedFullAtMs: null,
  freeBytes: null,
  gateClosed: false,
  volumeRefused: false,
  accelerateRetention: false,
  ...over,
});
const DAY = 86_400_000;
/** The oldest row started two days before T0: history enough to measure growth. */
const card = (
  over: Partial<DiskFacts> = {},
  policy: RecorderPolicy | null = POLICY,
  nothing = false,
  historySinceMs: number | null = T0 - 2 * DAY,
) => diskCard(facts(over), policy, nothing, T0, historySinceMs);
const SCALE =
  "80 % warning · 90 % auto-record pauses · 95 % recording stops (open positions keep writing)";
const SUGGESTED = ["Shorten retention", "Reduce depth", "Unpin"];

describe("disk card (D02 §8.3)", () => {
  it("test_disk_level0_growing_prints_the_projection_formula_board01", () => {
    expect(card()).toEqual({
      level: 0,
      tone: "primary",
      headline: "Growing · auto-record pauses in about 128 days",
      meter: { value: 61.4e9, max: 200e9, text: "61.4 GB of 200 GB (31 %)" },
      lines: [
        "Projection: (90 % × 200 GB − 61.4 GB) ÷ 0.93 GB/day ≈ 128 days. Growth: 7-day trend. In 30 days: about 89 GB.",
      ],
      scale: SCALE,
      suggested: [],
    });
  });

  it("test_disk_level0_steady_too_early_nothing_and_the_named_wall", () => {
    expect(card({ growthBytesPerDay: 0 })).toMatchObject({
      headline: "Steady · usage is not growing",
      lines: ["Usage is not growing, so there is no projection."],
    });
    // A-5309-03: the server folds "not measured yet" into a growth of 0, so under an hour of history it is
    // too early, never Steady; with no started row there is no history at all.
    for (const since of [T0 - 59 * 60_000, null]) {
      expect(card({ growthBytesPerDay: 0 }, POLICY, false, since)).toMatchObject({
        headline: "Too early to project",
        lines: ["Less than 1 h of history."],
      });
    }
    expect(card({ growthBytesPerDay: 0 }, POLICY, false, T0 - 60 * 60_000).headline).toBe(
      "Steady · usage is not growing",
    );
    expect(card({ growthBytesPerDay: null })).toMatchObject({
      headline: "Too early to project",
      lines: ["Less than 1 h of history."],
    });
    expect(card({ usedBytes: 0 }, POLICY, true)).toMatchObject({
      headline: "Nothing recorded",
      meter: { value: 0, max: 200e9, text: "0 GB of 200 GB." },
      lines: [],
    });
    const wall = { projectedFullAtMs: T0 + 40 * 86_400_000, freeBytes: 500e9 };
    expect(card(wall, null).headline).toBe("Growing · the budget is full in about 40 days");
    expect(card({ ...wall, freeBytes: 100e9 }, null).headline).toBe(
      "Growing · the disk volume is full in about 40 days",
    );
    // Without the policy no runway can be stated, but growth is measured: Growing, never "too early".
    expect(card({}, null)).toMatchObject({ headline: "Growing", lines: [] });
  });

  it("test_disk_level1_near_limit_board05", () => {
    expect(card({ level: 1, usedBytes: 161e9, growthBytesPerDay: 0.95e9 })).toEqual({
      level: 1,
      tone: "warning",
      headline: "Near limit · auto-record pauses in about 20 days · clears below 75 %",
      meter: {
        value: 161e9,
        max: 200e9,
        text: "Recording budget 80.5 % used (161.0 GB of 200 GB)",
      },
      lines: ["It clears once usage is below 75 % and the runway is more than 8 days."],
      scale: SCALE,
      suggested: SUGGESTED,
    });
    // no runway yet: the clause goes, never a "{d}"
    expect(card({ level: 1, usedBytes: 161e9, growthBytesPerDay: null }).headline).toBe(
      "Near limit · clears below 75 %",
    );
  });

  it("test_disk_level2_paused_by_the_budget_or_the_volume_board04", () => {
    const paused = card({
      level: 2,
      usedBytes: 181e9,
      growthBytesPerDay: 0.82e9,
      accelerateRetention: true,
    });
    expect(paused).toMatchObject({
      tone: "warning",
      headline:
        "Auto-record paused · resumes below 85 % of the budget with 20 % of the volume free",
      meter: { text: "Recording budget 90.5 % used (181.0 GB of 200 GB)" },
      lines: [
        "New chart-open symbols are not recorded; symbols you added, open positions, rules and alerts keep recording. Recording stops at 95 % in about 11 days.",
        "Retention is accelerated until the budget is below 75 % and the volume has 25 % free.",
      ],
      suggested: SUGGESTED,
    });
    expect(card({ level: 2, usedBytes: 100e9 }).headline).toBe(
      "Auto-record paused · the disk volume has less than 15 % free",
    );
  });

  it("test_disk_level3_stopped_and_its_banner_board06", () => {
    const halted = facts({ level: 3, usedBytes: 190.4e9, gateClosed: true });
    expect(diskCard(halted, POLICY, false, T0)).toMatchObject({
      tone: "danger",
      headline: "Recording stopped · resumes below 90 % with 10 % of the volume free",
      meter: { text: "95.2 % used (190.4 GB of 200 GB)" },
      lines: [
        "Open positions keep recording; other symbols' data is dropped and recorded as gaps.",
      ],
      suggested: [],
    });
    expect(levelThreeBanner(halted, POLICY)).toBe(
      "Recording stopped: the recording budget is 95 % used (190.4 GB of 200 GB). Data for symbols without an open position is being dropped and recorded as gaps; open positions keep recording. Free space to resume: purge data, shorten retention or raise the budget.",
    );
    // C-8 (PROPOSED): a refused volume does not resume by freeing space
    const refused = { ...halted, volumeRefused: true };
    expect(diskCard(refused, POLICY, false, T0).headline).toBe("Recording stopped");
    expect(levelThreeBanner(refused, POLICY)).toMatch(
      /^Recording stopped: the recording volume was refused when the server started\./,
    );
    expect(levelThreeBanner(refused, POLICY)).not.toContain("Free space");
  });

  it("test_disk_level3_by_the_volume_names_its_free_space_and_never_the_budget_a04", () => {
    // 24 §13.4.1: under 5 % free halts too; the budget's share is below its release point, as level 2 infers.
    const volume = facts({ level: 3, usedBytes: 80e9, gateClosed: true });
    expect(levelThreeBanner(volume, POLICY)).toBe(
      "Recording stopped: the disk volume has less than 5 % free. Data for symbols without an open position is being dropped and recorded as gaps; open positions keep recording. Free space to resume: purge data or shorten retention.",
    );
    // at or above the release point the budget is the cause; without a policy no share can be judged
    const budget = facts({ level: 3, usedBytes: 180e9, gateClosed: true });
    expect(levelThreeBanner(budget, POLICY)).toMatch(/^Recording stopped: the recording budget/);
    expect(levelThreeBanner(volume, null)).toMatch(/^Recording stopped: the recording budget/);
  });

  it("test_disk_without_a_policy_keeps_the_state_word_and_states_no_threshold", () => {
    const cards = ([1, 2, 3] as const).map((level) => card({ level, usedBytes: 181e9 }, null));
    expect(cards.map((c) => [c.headline, c.lines, c.scale])).toEqual([
      ["Near limit", [], null],
      ["Auto-record paused", [], null],
      [
        "Recording stopped",
        ["Open positions keep recording; other symbols' data is dropped and recorded as gaps."],
        null,
      ],
    ]);
  });

  it("test_disk_facts_take_the_frame_over_rest_and_rest_tiers_without_postgres", () => {
    const rest = diskFacts(STORAGE_USAGE, null);
    expect(rest).toMatchObject({
      level: 0,
      usedBytes: 1_188e9,
      capBytes: 2_000e9,
      gateClosed: false,
    });
    expect(diskCard(rest, POLICY, false, T0)).toMatchObject({
      headline: "Growing · auto-record pauses in about 422 days",
      meter: { text: "1,188.0 GB of 2,000 GB (59 %)" },
    });
    const storage = {
      used_bytes: 5e9,
      level: 3,
      write_gate: "closed",
      write_gate_reason: "volume_refused",
      projected_full_at_ms: null,
    } as const;
    expect(diskFacts(STORAGE_USAGE, modelFrame([], storage))).toMatchObject({
      level: 3,
      usedBytes: 5e9,
      projectedFullAtMs: null, // the frame's "none" wins over REST's date
      gateClosed: true,
      volumeRefused: true,
    });
    expect(diskFacts(null, null)).toMatchObject({ level: 0, usedBytes: null, capBytes: null });
  });

  it("test_disk_a_level_change_enters_the_batch_once_level3_is_the_alert_f07", () => {
    const near = card({ level: 1, usedBytes: 161e9, growthBytesPerDay: 0.95e9 });
    expect(levelChange(null, near)).toBeNull();
    expect(levelChange(1, near)).toBeNull();
    expect(levelChange(0, near)).toBe(near.headline);
    expect(levelChange(2, card({ level: 3, usedBytes: 190.4e9 }))).toBeNull();
    expect(levelChange(3, card({ level: 0 }))).toBe(
      "Growing · auto-record pauses in about 128 days",
    );
  });
});
