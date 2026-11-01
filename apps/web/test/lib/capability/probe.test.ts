import { describe, expect, it, vi } from "vitest";
import { WARMUP_FRAMES, WINDOW_FRAMES } from "../../../src/lib/capability/frameProbe";
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
  return { deps, tick, unsubscribe, storage };
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
