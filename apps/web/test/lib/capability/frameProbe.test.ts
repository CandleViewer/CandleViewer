import { describe, expect, it } from "vitest";
import {
  classify,
  classifyStarved,
  describeMeasurement,
  FRAME_BUDGET_MS,
  HARD_CAP_PANES,
  HEADROOM,
  MIN_WINDOW_FRAMES,
  percentile,
  reducedTrigger,
  TRIGGER_MIN_COVERAGE,
  TRIGGER_OUTLIER_MS,
  TRIGGER_THRESHOLD_MS,
  TRIGGER_WARMUP_MS,
  TRIGGER_WINDOW_MS,
  warmWindow,
  WARMUP_MS,
  WINDOW_FRAMES,
  type FrameWindow,
} from "../../../src/lib/capability/frameProbe";

// a seeded series around `ms` (+-10 %), so the tests are deterministic
function series(ms: number, n = WINDOW_FRAMES, seed = 7): number[] {
  let s = seed;
  return Array.from({ length: n }, () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return ms * (0.9 + (0.2 * s) / 2 ** 32);
  });
}
const cal = (ms1: number, ms4: number): FrameWindow[] => [
  { paneCount: 1, frameMs: series(ms1) },
  { paneCount: 4, frameMs: series(ms4, WINDOW_FRAMES, 11) },
];

describe("classify (#371 Test plan: fast, borderline, slow, noisy)", () => {
  it("classify_fast_device_full_at_the_hard_cap", () => {
    const r = classify(cal(3, 4));
    expect(r.recommendedProfile).toBe("full");
    expect(r.recommendedMaxPanes).toBe(HARD_CAP_PANES);
    expect(r.paneCount).toBe(4);
    expect(r.sampleCount).toBe(2 * WINDOW_FRAMES);
  });

  it("classify_slow_device_reduced_below_four", () => {
    const r = classify(cal(9, 20));
    expect(r.recommendedProfile).toBe("reduced");
    expect(r.recommendedMaxPanes).toBeLessThan(4);
  });

  it("classify_device_that_fails_one_pane_recommends_zero", () => {
    const r = classify(cal(40, 90));
    expect(r.recommendedMaxPanes).toBe(0);
    expect(r.recommendedProfile).toBe("reduced");
  });

  it("classify_borderline_four_panes_full_five_not_reached", () => {
    // flat windows: p95(1) = 4.9, p95(4) = 13.6 -> fixed 2, perPane 2.9; 2 + 2.9 * 4 <= 16.6 / 1.2 < 2 + 2.9 * 5
    const flat = (ms: number, n: number): FrameWindow => ({
      paneCount: n,
      frameMs: Array(WINDOW_FRAMES).fill(ms),
    });
    const r = classify([flat(4.9, 1), flat(13.6, 4)]);
    expect(13.6 * HEADROOM).toBeLessThanOrEqual(FRAME_BUDGET_MS);
    expect(r.recommendedMaxPanes).toBe(4);
    expect(r.recommendedProfile).toBe("full");
  });

  it("classify_one_200ms_gc_spike_does_not_flip_the_result", () => {
    for (const [a, b] of [
      [3, 4],
      [4.9, 13.6],
      [9, 20],
    ] as const) {
      const clean = cal(a, b);
      const spiked = clean.map((w) => ({
        ...w,
        frameMs: w.frameMs.map((v, i) => (i === 50 ? 200 : v)),
      }));
      const r0 = classify(clean);
      const r1 = classify(spiked);
      expect(r1.recommendedProfile).toBe(r0.recommendedProfile);
      expect(Math.abs(r1.recommendedMaxPanes - r0.recommendedMaxPanes)).toBeLessThanOrEqual(1);
      expect(r1.p95FrameMs).toBeLessThan(b * 1.15);
    }
  });

  it("classify_spike_leaves_the_exact_p95_and_result_unchanged", () => {
    // 108 frames at 5 ms and 12 at 12 ms: the nearest-rank p95 is 12 (p90 would be 5, p100 the spike)
    const w = Array.from({ length: WINDOW_FRAMES }, (_, i) => (i % 10 === 9 ? 12 : 5));
    const clean = classify([{ paneCount: 4, frameMs: w }]);
    const spiked = classify([{ paneCount: 4, frameMs: w.map((v, i) => (i === 50 ? 200 : v)) }]);
    expect(clean.p95FrameMs).toBe(12);
    expect(clean.recommendedMaxPanes).toBe(Math.floor(FRAME_BUDGET_MS / HEADROOM / 3)); // 12 / 4 per pane
    expect(spiked).toEqual(clean);
  });

  it("classify_noisy_two_windows_with_no_slope_fall_back_to_the_top_window", () => {
    // one pane measured slower than four (noise): a clamped slope of 0 would promise the 16-pane cap
    const flat = (ms: number, n: number): FrameWindow => ({
      paneCount: n,
      frameMs: Array(WINDOW_FRAMES).fill(ms),
    });
    const r = classify([flat(9, 1), flat(8, 4)]);
    expect(r.recommendedMaxPanes).toBe(Math.floor(FRAME_BUDGET_MS / HEADROOM / 2)); // 8 / 4 per pane
    expect(r.recommendedMaxPanes).toBeLessThan(HARD_CAP_PANES);
  });

  it("classify_single_window_charges_the_fixed_cost_to_the_panes", () => {
    const r = classify([{ paneCount: 4, frameMs: Array(WINDOW_FRAMES).fill(8) }]);
    expect(r.recommendedMaxPanes).toBe(Math.floor(FRAME_BUDGET_MS / HEADROOM / 2));
  });

  it("classify_flat_cost_is_charged_to_the_top_window", () => {
    const flat = (ms: number, n: number): FrameWindow => ({
      paneCount: n,
      frameMs: Array(WINDOW_FRAMES).fill(ms),
    });
    expect(classify([flat(2, 1), flat(2, 4)]).recommendedMaxPanes).toBe(HARD_CAP_PANES);
    expect(classify([flat(5, 1), flat(5, 4)]).recommendedMaxPanes).toBe(11);
    // the line through the top window says 2, but one pane already missed: never at or above a miss
    expect(classify([flat(20, 1), flat(20, 4)]).recommendedMaxPanes).toBe(0);
  });

  it("classify_rejects_bad_input", () => {
    expect(() => classify([])).toThrow(RangeError);
    expect(() => classify([{ paneCount: 0, frameMs: series(3) }])).toThrow(RangeError);
    expect(() => classify([{ paneCount: 1, frameMs: series(3, MIN_WINDOW_FRAMES - 1) }])).toThrow(
      RangeError,
    );
    expect(() => classify([{ paneCount: 1, frameMs: [...series(3), Number.NaN] }])).toThrow(
      RangeError,
    );
  });
});

describe("classifyStarved (a window closed on time with too few frames)", () => {
  it("classifyStarved_with_no_earlier_window_is_zero_and_reduced", () => {
    const r = classifyStarved([], { paneCount: 1, frameMs: [300, 320, 340] });
    expect(r).toEqual({
      p95FrameMs: 340,
      recommendedMaxPanes: 0,
      recommendedProfile: "reduced",
      paneCount: 1,
      sampleCount: 3,
    });
  });

  it("classifyStarved_caps_the_earlier_answer_below_the_starved_count", () => {
    const one: FrameWindow = { paneCount: 1, frameMs: Array(WINDOW_FRAMES).fill(2) };
    const r = classifyStarved([one], { paneCount: 4, frameMs: [400] });
    expect(r.recommendedMaxPanes).toBe(3);
    expect(r.recommendedProfile).toBe("reduced");
    expect(r.sampleCount).toBe(WINDOW_FRAMES + 1);
    expect(() => classifyStarved([], { paneCount: 1, frameMs: [] })).toThrow(RangeError);
  });
});

describe("helpers", () => {
  it("percentile_is_nearest_rank_like_the_bench", () => {
    const xs = Array.from({ length: 20 }, (_, i) => i + 1);
    expect(percentile(xs, 95)).toBe(19);
    expect(percentile(xs, 50)).toBe(10);
    expect(percentile([], 95)).toBe(0);
  });

  it("warmWindow_drops_the_warm_up_by_time_and_bounds_the_window", () => {
    // 144 Hz: the run's 420 frames would be 2.9 s; the warm-up is 7 s on any refresh rate
    const hz = 144;
    const raw = Array.from({ length: (WARMUP_MS / 1000) * hz + WINDOW_FRAMES + 10 }, (_, i) => ({
      atMs: (i * 1000) / hz,
      frameMs: i,
    }));
    const w = warmWindow(4, raw);
    expect(WARMUP_MS).toBe(7_000);
    expect(w.frameMs[0]).toBe((WARMUP_MS / 1000) * hz);
    expect(w.frameMs).toHaveLength(WINDOW_FRAMES);
    expect(w.paneCount).toBe(4);
  });

  it("describeMeasurement_is_plain_text", () => {
    const base = { recommendedMaxPanes: 4, recommendedProfile: "full", sampleCount: 120 } as const;
    expect(describeMeasurement({ ...base, p95FrameMs: 24.4, paneCount: 6 })).toBe(
      "measured 24 ms per frame with 6 panes",
    );
    expect(describeMeasurement({ ...base, p95FrameMs: 3.25, paneCount: 1 })).toBe(
      "measured 3.3 ms per frame with 1 pane",
    );
  });
});

// E15-D12 BQ-10's trigger at 60 frames per second: `ms(i)` gives frame i's time
function timed(seconds: number, ms: (i: number) => number) {
  return Array.from({ length: seconds * 60 }, (_, i) => ({
    atMs: (i * 1000) / 60,
    frameMs: ms(i),
  }));
}

describe("reducedTrigger (E15-D12 BQ-10, calibrated by E15-K01 §9)", () => {
  it("reducedTrigger_holds_the_ruled_values", () => {
    expect([
      TRIGGER_THRESHOLD_MS,
      TRIGGER_WINDOW_MS,
      TRIGGER_WARMUP_MS,
      TRIGGER_OUTLIER_MS,
    ]).toEqual([18.2, 60_000, 10_000, 200]);
  });

  it("reducedTrigger_slow_device_fires_after_a_full_window", () => {
    const r = reducedTrigger(timed(71, () => 25));
    expect(r.fired).toBe(true);
    expect(r.p95FrameMs).toBe(25);
  });

  it("reducedTrigger_fast_device_never_fires", () => {
    expect(reducedTrigger(timed(71, (i) => 8 + (i % 5))).fired).toBe(false);
  });

  it("reducedTrigger_waits_for_a_full_window_after_the_warm_up", () => {
    const r = reducedTrigger(timed(65, () => 40));
    expect(r.fired).toBe(false);
    expect(r.p95FrameMs).toBeNull();
  });

  it("reducedTrigger_ignores_a_slow_warm_up", () => {
    expect(reducedTrigger(timed(71, (i) => (i < 9 * 60 ? 90 : 9))).fired).toBe(false);
  });

  it("reducedTrigger_drops_200ms_gc_spikes", () => {
    // one 250 ms frame every 2 s is 0.8 % of the frames: kept, they would set nothing; dropped, nothing fires
    const r = reducedTrigger(timed(71, (i) => (i % 120 === 0 ? 250 : 9)));
    expect(r.fired).toBe(false);
    expect(r.p95FrameMs).toBe(9);
  });

  it("reducedTrigger_device_slower_than_200ms_still_fires", () => {
    // every frame is over 200 ms: a run, not an isolated outlier, so nothing is dropped (E15-K01 §9 T3)
    const frames = Array.from({ length: 300 }, (_, i) => ({ atMs: i * 250, frameMs: 250 }));
    const r = reducedTrigger(frames);
    expect(r.fired).toBe(true);
    expect(r.p95FrameMs).toBe(250);
  });

  it("reducedTrigger_a_hidden_gap_does_not_make_a_full_window", () => {
    // 2 s of slow frames after the warm-up, then the window hidden for 60 s, then 10 slow frames: the span is
    // over 60 s but the frames cover under a second of it
    const before = Array.from({ length: 120 }, (_, i) => ({
      atMs: TRIGGER_WARMUP_MS + (i * 1000) / 60,
      frameMs: 25,
    }));
    const after = Array.from({ length: 10 }, (_, i) => ({
      atMs: TRIGGER_WARMUP_MS + 62_000 + (i * 1000) / 60,
      frameMs: 25,
    }));
    const r = reducedTrigger([...before, ...after]);
    expect(TRIGGER_MIN_COVERAGE).toBe(0.5);
    expect(r.fired).toBe(false);
    expect(r.p95FrameMs).toBeNull();
  });

  it("reducedTrigger_newest_slow_frame_waits_for_its_neighbour", () => {
    const base = timed(71, () => 9);
    const end = base[base.length - 1]?.atMs ?? 0;
    const at = (k: number, frameMs: number) => ({ atMs: end + (k * 1000) / 60, frameMs });
    // a slow newest frame after a fast one is undecided: left out
    expect(reducedTrigger([...base, at(1, 250)]).frameCount).toBe(reducedTrigger(base).frameCount);
    // its slow neighbour arrives: a run, both kept, as two fast frames would be
    const two = reducedTrigger([...base, at(1, 250), at(2, 250)]);
    expect(two.frameCount).toBe(reducedTrigger([...base, at(1, 9), at(2, 9)]).frameCount);
  });

  it("reducedTrigger_trimmed_series_gives_the_full_series_result", () => {
    // the E15-S08 trim rule (frameProbe.ts, E15-K01 §11.3): from the second-newest frame's atMs minus the
    // window, plus the two frames before; seeded slow frames, isolated and in runs, around the boundary
    let s = 371;
    const rnd = () => (s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32;
    const frames = timed(80, () => (rnd() < 0.08 ? 250 : 15 + rnd() * 6));
    for (let end = 72 * 60; end <= frames.length; end += 37) {
      const full = frames.slice(0, end);
      const cut = (full[full.length - 2]?.atMs ?? 0) - TRIGGER_WINDOW_MS;
      const from = Math.max(0, full.findIndex((f) => f.atMs >= cut) - 2);
      expect(reducedTrigger(full.slice(from))).toEqual(reducedTrigger(full));
    }
  });

  it("reducedTrigger_borderline_is_strictly_above", () => {
    expect(reducedTrigger(timed(71, () => TRIGGER_THRESHOLD_MS)).fired).toBe(false);
  });
});
