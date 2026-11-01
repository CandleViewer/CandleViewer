import { describe, expect, it, vi } from "vitest";
import {
  frameSpanMs,
  MIN_WINDOW_FRAMES,
  WARMUP_FRAMES,
  WARMUP_MAX_MS,
  WINDOW_FRAMES,
  WINDOW_MAX_MS,
} from "../../../src/lib/capability/frameProbe";
import {
  CALIBRATION_PANES,
  PROBE_STORAGE_KEY,
  readCachedResult,
  startProbe,
  type ProbeDeps,
} from "../../../src/lib/capability/probe";

function memoryStorage(init: Record<string, string> = {}) {
  const m = new Map(Object.entries(init));
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: vi.fn((k: string, v: string) => void m.set(k, v)),
  };
}

function harness(msFor: (panes: number) => number, storage = memoryStorage()) {
  let listener: ((ms: number) => void) | null = null;
  let panes = 0;
  const unsubscribe = vi.fn(() => {
    listener = null;
  });
  const deps: ProbeDeps = {
    onFrame: (l) => {
      listener = l;
      return unsubscribe;
    },
    drawPanes: vi.fn((n: number) => {
      panes = n;
    }),
    storage,
    report: vi.fn(),
  };
  const tick = (frames: number) => {
    for (let i = 0; i < frames; i += 1) listener?.(msFor(panes));
  };
  return { deps, tick, unsubscribe, storage, lastPanes: () => panes };
}

const PER_WINDOW = WARMUP_FRAMES + WINDOW_FRAMES;

describe("startProbe", () => {
  it("startProbe_calibrates_at_one_then_four_panes_stores_and_reports_once", async () => {
    const h = harness((n) => 2 + n * 0.5);
    const p = startProbe(h.deps);
    h.tick(PER_WINDOW * CALIBRATION_PANES.length + 50);
    const r = await p.result;
    expect(h.deps.drawPanes).toHaveBeenNthCalledWith(1, 1);
    expect(h.deps.drawPanes).toHaveBeenNthCalledWith(2, 4);
    expect(r.recommendedProfile).toBe("full");
    expect(h.unsubscribe).toHaveBeenCalledTimes(1);
    expect(h.deps.report).toHaveBeenCalledTimes(1);
    expect(h.deps.report).toHaveBeenCalledWith({
      name: "capability.profile_measured",
      p95FrameMs: r.p95FrameMs,
      recommendedProfile: "full",
      paneCount: 4,
    });
    expect(JSON.parse(h.storage.getItem(PROBE_STORAGE_KEY) ?? "null")).toEqual(r);
  });

  it("startProbe_warm_up_frames_are_never_classified", async () => {
    // a 500 ms cold frame at the start of each window would make any device reduced if it were kept
    let i = 0;
    const h = harness((n) => (i++ % PER_WINDOW < 3 ? 500 : 1 + n));
    const p = startProbe(h.deps);
    h.tick(PER_WINDOW * 2);
    expect((await p.result).recommendedProfile).toBe("full");
  });

  it("startProbe_slow_device_finishes_inside_the_stated_time_cap", async () => {
    // a SwiftShader-like device (160 ms per frame at one pane, 330 ms at four): 540 frames per step would be
    // about 4.4 min; the cap is two steps of WARMUP_MAX_MS + WINDOW_MAX_MS plus two frames each
    const msAt = (n: number) => (n === 1 ? 160 : 330);
    const h = harness(msAt);
    const p = startProbe(h.deps);
    let elapsed = 0;
    for (let i = 0; i < 5_000 && vi.mocked(h.deps.report).mock.calls.length === 0; i += 1) {
      elapsed += frameSpanMs(msAt(h.lastPanes()));
      h.tick(1);
    }
    const r = await p.result;
    expect(WARMUP_MAX_MS + WINDOW_MAX_MS).toBe(20_000); // the stated cap per step
    expect(elapsed).toBeLessThanOrEqual(2 * 20_000 + 4 * 330);
    expect(r.recommendedMaxPanes).toBe(0);
    expect(r.recommendedProfile).toBe("reduced");
  });

  it("startProbe_window_closes_on_time_with_enough_frames", async () => {
    // 180 ms per frame: 13 s of window holds 73 frames (>= 60), so the window closes on time, not at 120
    const h = harness(() => 180);
    const p = startProbe(h.deps);
    h.tick(400);
    const r = await p.result;
    expect(r.sampleCount).toBeGreaterThanOrEqual(2 * MIN_WINDOW_FRAMES);
    expect(r.sampleCount).toBeLessThan(2 * WINDOW_FRAMES);
    expect(r.recommendedProfile).toBe("reduced");
  });

  it("startProbe_uses_the_device_cache_without_sampling", async () => {
    const cached = {
      p95FrameMs: 30,
      recommendedMaxPanes: 2,
      recommendedProfile: "reduced",
      paneCount: 4,
      sampleCount: 240,
    };
    const h = harness(() => 1, memoryStorage({ [PROBE_STORAGE_KEY]: JSON.stringify(cached) }));
    const p = startProbe(h.deps);
    expect(await p.result).toEqual(cached);
    expect(h.deps.drawPanes).not.toHaveBeenCalled();
    expect(h.deps.report).not.toHaveBeenCalled();
    p.cancel();
  });

  it("startProbe_cancel_stops_sampling", () => {
    const h = harness(() => 1);
    const p = startProbe(h.deps);
    h.tick(10);
    p.cancel();
    expect(h.unsubscribe).toHaveBeenCalledTimes(1);
    h.tick(PER_WINDOW * 2);
    expect(h.deps.report).not.toHaveBeenCalled();
    expect(h.storage.setItem).not.toHaveBeenCalled();
  });

  it("readCachedResult_ignores_malformed_records", () => {
    expect(readCachedResult(memoryStorage())).toBeNull();
    expect(readCachedResult(memoryStorage({ [PROBE_STORAGE_KEY]: "{" }))).toBeNull();
    expect(
      readCachedResult(memoryStorage({ [PROBE_STORAGE_KEY]: '{"p95FrameMs":"x"}' })),
    ).toBeNull();
    expect(readCachedResult(memoryStorage({ [PROBE_STORAGE_KEY]: "null" }))).toBeNull();
  });

  it("readCachedResult_rejects_out_of_range_records", () => {
    const ok = {
      p95FrameMs: 9.5,
      recommendedMaxPanes: 8,
      recommendedProfile: "full",
      paneCount: 4,
      sampleCount: 240,
    };
    const read = (v: unknown) =>
      readCachedResult(memoryStorage({ [PROBE_STORAGE_KEY]: JSON.stringify(v) }));
    expect(read(ok)).toEqual(ok);
    // JSON turns NaN and Infinity into null; a hand-edited or corrupted record can still carry anything
    for (const bad of [
      { ...ok, p95FrameMs: null },
      { ...ok, p95FrameMs: -1 },
      { ...ok, recommendedMaxPanes: -5 },
      { ...ok, recommendedMaxPanes: 1e9 },
      { ...ok, recommendedMaxPanes: 2.5 },
      { ...ok, recommendedMaxPanes: 2 }, // "full" with 2 panes: the profile disagrees
      { ...ok, paneCount: 0 },
      { ...ok, paneCount: 99 },
      { ...ok, sampleCount: 0 },
    ])
      expect(read(bad), JSON.stringify(bad)).toBeNull();
    const infinite = JSON.stringify(ok).replace("9.5", "1e999"); // parses to Infinity
    expect(readCachedResult(memoryStorage({ [PROBE_STORAGE_KEY]: infinite }))).toBeNull();
  });

  it("startProbe_stores_aggregate_timing_only", async () => {
    const h = harness(() => 3);
    const p = startProbe(h.deps);
    h.tick(PER_WINDOW * 2);
    await p.result;
    const stored = JSON.parse(h.storage.getItem(PROBE_STORAGE_KEY) ?? "{}") as Record<
      string,
      unknown
    >;
    expect(Object.keys(stored).sort()).toEqual(
      [
        "p95FrameMs",
        "paneCount",
        "recommendedMaxPanes",
        "recommendedProfile",
        "sampleCount",
      ].sort(),
    );
  });
});
