// E17-T04 S3b (23 6.1.1): a heatmap resize is re-derived on every event and sent once, 400 ms after
// it settles, and only if the derived bucket differs from the one the server holds.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CTL_DEBOUNCE_MS, createCtlDebouncer } from "../../../src/lib/ws/policy/ctlDebouncer";
import { selectHeatmapBucket } from "../../../src/lib/ws/protocol/heatmapBucket";

const KEY = "heatmap.BTCUSDT";
const ETH = "heatmap.ETHUSDT";
/** At the shipped window of 900 s: 1 190 css px derives 1 000 ms, 595 px derives 5 000 ms (6.1.1); the ladder boundary is 1 080 px. */
const geometry = (cssWidth: number) => ({ windowSeconds: 900, cssWidth, dpr: 1 });
let emitted: string[]; // `key bucket`, one per ctl
let debouncer: ReturnType<typeof createCtlDebouncer>;

beforeEach(() => {
  vi.useFakeTimers();
  emitted = [];
  debouncer = createCtlDebouncer({ emit: (key, bucket) => emitted.push(`${key} ${bucket}`) });
  debouncer.activate(KEY, 1000); // what the sub carried and sub_ok echoed
});
afterEach(() => vi.useRealTimers());

describe("ctl debounce (6.1.1)", () => {
  it("Heatmap bucket is derived and debounced", () => {
    expect(CTL_DEBOUNCE_MS).toBe(400); // 6.1.1: "debounced by 400 ms"
    // 20 resize events, 10 ms apart, drag the pane from 1 190 px across the 1 080 px boundary to 601 px
    for (let i = 0; i < 20; i += 1) {
      if (i > 0) vi.advanceTimersByTime(10);
      debouncer.resize(KEY, geometry(1190 - i * 31));
    }
    const [wide, narrow] = [1190, 601].map((width) => selectHeatmapBucket(geometry(width)));
    expect([wide, narrow]).toEqual([1000, 5000]);
    expect(emitted).toEqual([]); // not one ctl per resize event
    vi.advanceTimersByTime(399);
    expect(emitted).toEqual([]);
    vi.advanceTimersByTime(1); // 400 ms after the last event
    expect(emitted).toEqual([`${KEY} 5000`]);
    vi.advanceTimersByTime(60_000);
    expect(emitted).toHaveLength(1);
  });

  it("sends nothing while the derived bucket is unchanged, and starts no timer for it", () => {
    for (const width of [1190, 1150, 1100, 1190, 1085]) debouncer.resize(KEY, geometry(width));
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(800);
    expect(emitted).toEqual([]);
  });

  it("sends nothing when the drag ends back on the bucket the server holds", () => {
    debouncer.resize(KEY, geometry(595));
    vi.advanceTimersByTime(300);
    debouncer.resize(KEY, geometry(1190));
    expect(vi.getTimerCount()).toBe(0); // the pending change was cancelled, not just outvoted
    vi.advanceTimersByTime(800);
    expect(emitted).toEqual([]);
  });

  it("sends each settled change once, and a repeat of the active bucket not at all", () => {
    debouncer.resize(KEY, geometry(595));
    vi.advanceTimersByTime(400);
    debouncer.resize(KEY, geometry(600)); // still 5 000 ms
    debouncer.resize(KEY, geometry(1190));
    vi.advanceTimersByTime(400);
    expect(emitted).toEqual([`${KEY} 5000`, `${KEY} 1000`]);
  });

  it("sends nothing for a bucket the server already holds by the time it settles (ctl_ok effective)", () => {
    debouncer.resize(KEY, geometry(595));
    debouncer.activate(KEY, 5000);
    vi.advanceTimersByTime(400);
    expect(emitted).toEqual([]);
  });

  it("keeps keys apart, and forget drops a pending change", () => {
    debouncer.activate(ETH, 1000);
    debouncer.activate("heatmap.SOLUSDT", 1000);
    for (const key of [KEY, ETH, "heatmap.SOLUSDT"]) debouncer.resize(key, geometry(595));
    debouncer.forget("heatmap.SOLUSDT");
    vi.advanceTimersByTime(400);
    expect(emitted).toEqual([`${KEY} 5000`, `${ETH} 5000`]);
  });
});

describe("what is not a resize", () => {
  it("ignores a geometry that is not a size, so a hide and a show re-snapshot nothing", () => {
    // a `display: none` pane is 0 x 0: derived, that would be 5 000 ms (or 500 for a bad window)
    const notSizes = [
      { cssWidth: 0 },
      { cssWidth: Number.NaN },
      { cssWidth: Infinity },
      { cssWidth: -5 },
    ];
    for (const bad of [
      ...notSizes,
      { dpr: 0 },
      { dpr: Number.NaN },
      { windowSeconds: 0 },
      { windowSeconds: Number.NaN },
    ]) {
      debouncer.resize(KEY, { ...geometry(1190), ...bad });
    }
    expect(vi.getTimerCount()).toBe(0);
    debouncer.resize(KEY, geometry(1190)); // shown again: the bucket the server still holds
    vi.advanceTimersByTime(800);
    expect(emitted).toEqual([]);
  });

  it("lets a user-set bucket through without a geometry (rule 1)", () => {
    debouncer.resize(KEY, { windowSeconds: 900, cssWidth: 0, dpr: 1, userBucketMs: 250 });
    vi.advanceTimersByTime(400);
    expect(emitted).toEqual([`${KEY} 250`]);
  });

  it("ignores a key the server has not confirmed or that was forgotten, and everything after dispose", () => {
    debouncer.resize(ETH, geometry(595)); // never activated
    debouncer.forget(KEY);
    debouncer.resize(KEY, geometry(595)); // a late ResizeObserver callback for a released topic
    expect(vi.getTimerCount()).toBe(0);
    debouncer.activate(KEY, 1000); // subscribed again
    debouncer.resize(KEY, geometry(595));
    vi.advanceTimersByTime(400);
    expect(emitted).toEqual([`${KEY} 5000`]);
    debouncer.dispose();
    debouncer.resize(KEY, geometry(1190)); // its baseline went with it: 1 000 would differ from 5 000
    debouncer.activate(ETH, 1000); // a stopped client cannot be revived
    debouncer.resize(ETH, geometry(595));
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(800);
    expect(emitted).toHaveLength(1);
  });
});

describe("failures and teardown", () => {
  it("leaves the baseline alone when emit throws, so the next resize sends the bucket again", () => {
    let fail = true;
    const flaky = createCtlDebouncer({
      emit: (key, bucket) => {
        if (fail) throw new Error("boom");
        emitted.push(`${key} ${bucket}`);
      },
    });
    flaky.activate(KEY, 1000);
    flaky.resize(KEY, geometry(595));
    expect(() => vi.advanceTimersByTime(400)).toThrow("boom");
    fail = false;
    flaky.resize(KEY, geometry(595)); // the same geometry: still 5 000, and the server never got it
    vi.advanceTimersByTime(400);
    expect(emitted).toEqual([`${KEY} 5000`]);
  });

  it("dispose() drops every pending change", () => {
    debouncer.activate(ETH, 1000);
    debouncer.resize(KEY, geometry(595));
    debouncer.resize(ETH, geometry(595));
    debouncer.dispose();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(800);
    expect(emitted).toEqual([]);
  });

  it("runs on the timers it is given, never the platform's, and never clears a handle that was not set", () => {
    const timers = {
      setTimeout: vi.fn(() => 9),
      clearTimeout: vi.fn((handle: unknown) => {
        if (handle === undefined) throw new Error("clearTimeout(undefined)");
      }),
    };
    const injected = createCtlDebouncer({ emit: vi.fn(), timers });
    injected.activate(KEY, 1000);
    injected.resize(KEY, geometry(595)); // the first resize has no timer to clear
    expect(timers.setTimeout).toHaveBeenCalledWith(expect.any(Function), 400);
    expect(vi.getTimerCount()).toBe(0); // nothing reached the platform's timers
    injected.forget("heatmap.UNKNOWN"); // nothing to clear
    injected.activate(ETH, 1000);
    injected.forget(ETH); // a key with no pending change
    injected.dispose();
    expect(timers.clearTimeout).toHaveBeenCalledWith(9);
  });
});
