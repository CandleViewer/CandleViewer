// E11-S15 PR-2a: the paging trigger (26 §9, §7 internal constants; AC4, BQ-S15-07). The clock is
// the test's `now`: no timers, no sleep. Viewports are bar-time ranges (one unit per bar here).
import { describe, expect, it } from "vitest";
import { probeAllocations } from "../../bench/scenes/memory-sample.js";
import {
  PAGING_DEBOUNCE_MS,
  PAGING_DISTANCE_SPANS,
  PagingTrigger,
  type PagingView,
} from "../../src/memory/paging.js";

const view = (
  visibleFrom: number,
  visibleTo: number,
  loadedFrom: number,
  state: PagingView["state"] = "ok",
): PagingView => ({ visibleFrom, visibleTo, loadedFrom, state });

describe("Scenario: an evicted range is re-fetched exactly when panned back to (E11-S15 AC4)", () => {
  it("the constants are the 26 §7 figures", () => {
    expect([PAGING_DISTANCE_SPANS, PAGING_DEBOUNCE_MS]).toEqual([1, 250]);
  });

  it("asks for exactly the evicted range's bounds and lists it in loadingRanges until it lands", () => {
    const p = new PagingTrigger();
    p.evictedRange({ fromTime: 100, toTime: 199 });
    // Visible [210, 230], span 20: the evicted range ends 11 before it, within one span.
    p.viewport(0, view(210, 230, 0));
    expect(p.poll(PAGING_DEBOUNCE_MS - 1, "ok")).toBeNull();
    expect(p.poll(PAGING_DEBOUNCE_MS, "ok")).toEqual({ fromTime: 100, toTime: 199 });
    expect(p.loadingRanges).toEqual([{ fromTime: 100, toTime: 199 }]);
    expect([p.takeLoadingChanged(), p.takeLoadingChanged(), p.requests]).toEqual([true, false, 1]);
    // In flight: the same need is not asked for again.
    p.viewport(300, view(205, 225, 0));
    expect([p.pending, p.poll(10_000, "ok")]).toEqual([false, null]);
    p.landed(100, 199);
    expect([p.loadingRanges, p.evictedRanges, p.takeLoadingChanged()]).toEqual([[], [], true]);
  });

  it("a landing that covers part of an evicted range answers the request and keeps the rest", () => {
    const p = new PagingTrigger();
    p.evictedRange({ fromTime: 100, toTime: 199 });
    p.viewport(0, view(210, 230, 0));
    expect(p.poll(250, "ok")).toEqual({ fromTime: 100, toTime: 199 });
    p.landed(150, 199); // the store took only the newer half
    expect([p.loadingRanges, p.evictedRanges]).toEqual([[], [{ fromTime: 100, toTime: 150 }]]);
    p.viewport(300, view(160, 180, 0));
    expect(p.poll(550, "ok")).toEqual({ fromTime: 100, toTime: 150 });
    p.landed(120, 130); // strictly inside: split in two
    expect(p.evictedRanges).toEqual([
      { fromTime: 100, toTime: 120 },
      { fromTime: 130, toTime: 150 },
    ]);
  });

  it("a landing that overlaps a request still waiting for its debounce cancels it", () => {
    const p = new PagingTrigger();
    p.evictedRange({ fromTime: 100, toTime: 199 });
    p.viewport(0, view(210, 230, 0));
    expect(p.pending).toBe(true);
    p.landed(100, 199); // the range fills before the tick: poll must not ask for it again
    expect([p.pending, p.poll(10_000, "ok"), p.requests]).toEqual([false, null, 0]);
    // A landing elsewhere leaves the waiting request alone.
    p.evictedRange({ fromTime: 100, toTime: 199 });
    p.viewport(20_000, view(210, 230, 0));
    p.landed(500, 600);
    expect(p.pending).toBe(true);
  });

  it("with the nearest evicted range in flight, the loaded edge still pages", () => {
    const p = new PagingTrigger();
    p.evictedRange({ fromTime: 50, toTime: 59 });
    p.viewport(0, view(55, 75, 40));
    expect(p.poll(250, "ok")).toEqual({ fromTime: 50, toTime: 59 });
    p.viewport(300, view(55, 75, 40));
    expect(p.poll(550, "ok")).toEqual({ fromTime: 35, toTime: 40 });
  });

  it("prefers the evicted range nearest the visible range", () => {
    const p = new PagingTrigger();
    p.evictedRange({ fromTime: 0, toTime: 49 });
    p.evictedRange({ fromTime: 400, toTime: 409 });
    p.evictedRange({ fromTime: 60, toTime: 89 });
    p.viewport(0, view(100, 140, 0));
    expect(p.poll(250, "ok")).toEqual({ fromTime: 60, toTime: 89 });
    p.viewport(1000, view(350, 390, 0)); // the later range overlaps the reach after the view
    expect(p.poll(1250, "ok")).toEqual({ fromTime: 400, toTime: 409 });
  });
});

describe("Paging trigger: the loaded edge, the debounce and the guards (26 §9)", () => {
  it("asks for [visibleFrom - 1 span, loadedFrom] once the view is within one span of the edge", () => {
    const p = new PagingTrigger();
    p.viewport(0, view(130, 150, 100)); // reach 110 >= 100: not yet
    expect(p.pending).toBe(false);
    p.viewport(10, view(119, 139, 100)); // reach 99 < 100
    expect(p.poll(260, "ok")).toEqual({ fromTime: 99, toTime: 100 });
  });

  it("an edge page is answered by a prepend ending before loadedFrom (the landed contract)", () => {
    const p = new PagingTrigger();
    p.viewport(0, view(119, 139, 100));
    expect(p.poll(250, "ok")).toEqual({ fromTime: 99, toTime: 100 });
    p.landed(99, 99); // the oldest and newest prepended bar, both before the old edge
    expect([p.loadingRanges, p.takeLoadingChanged()]).toEqual([[], true]);
  });

  it("debounces trailing: three viewports in 200 ms give one emit 250 ms after the last", () => {
    const p = new PagingTrigger();
    p.viewport(0, view(110, 130, 100));
    p.viewport(100, view(108, 128, 100));
    p.viewport(200, view(105, 125, 100));
    expect([p.poll(250, "ok"), p.poll(449, "ok")]).toEqual([null, null]);
    expect(p.poll(450, "ok")).toEqual({ fromTime: 85, toTime: 100 });
    expect([p.poll(10_000, "ok"), p.requests]).toEqual([null, 1]);
  });

  it("is cancelled when the range is covered again before it fires", () => {
    const p = new PagingTrigger();
    p.viewport(0, view(110, 130, 100));
    p.viewport(100, view(110, 130, 50)); // a prepend landed: the edge moved out of reach
    expect([p.pending, p.poll(1000, "ok")]).toEqual([false, null]);
  });

  it("emits nothing before recorded history, and clamps a page to it", () => {
    const p = new PagingTrigger();
    p.setRecordedFrom(100);
    p.viewport(0, view(100, 120, 100));
    expect(p.pending).toBe(false);
    p.viewport(0, view(105, 125, 103));
    expect(p.poll(250, "ok")).toEqual({ fromTime: 100, toTime: 103 });
    p.setRecordedFrom(Number.NaN); // unknown again: no lower clamp
    p.viewport(1000, view(10, 30, 20));
    expect(p.poll(1250, "ok")).toEqual({ fromTime: -10, toTime: 20 });
  });

  it("emits nothing while the governor is over, and over cancels a pending request", () => {
    const p = new PagingTrigger();
    p.evictedRange({ fromTime: 0, toTime: 9 });
    p.viewport(0, view(12, 22, 10, "over"));
    expect(p.pending).toBe(false);
    p.viewport(0, view(12, 22, 10, "pressure"));
    expect(p.pending).toBe(true);
    expect([p.poll(250, "over"), p.pending, p.poll(500, "ok")]).toEqual([null, false, null]);
  });

  it("a different range is asked for while another is in flight", () => {
    const p = new PagingTrigger();
    p.viewport(0, view(110, 130, 100));
    expect(p.poll(250, "ok")).toEqual({ fromTime: 90, toTime: 100 });
    p.viewport(300, view(60, 100, 100));
    expect(p.poll(550, "ok")).toEqual({ fromTime: 20, toTime: 100 });
    expect(p.loadingRanges).toHaveLength(2);
    p.landed(20, 100);
    expect(p.loadingRanges).toEqual([]);
  });

  it("ignores degenerate viewports and nothing loaded", () => {
    const p = new PagingTrigger();
    for (const v of [
      view(10, 10, 100),
      view(20, 10, 100),
      view(Number.NaN, 10, 100),
      view(0, Infinity, 100),
      view(0, 10, Infinity),
    ]) {
      p.viewport(0, v);
      expect(p.pending).toBe(false);
    }
  });

  it("reset forgets the in-flight and evicted ranges (snapshot setData, symbol change)", () => {
    const p = new PagingTrigger();
    p.evictedRange({ fromTime: 0, toTime: 9 });
    p.viewport(0, view(12, 22, 10));
    p.poll(250, "ok");
    p.takeLoadingChanged();
    p.viewport(300, view(5, 15, 10));
    p.reset();
    expect([p.loadingRanges, p.evictedRanges, p.pending, p.takeLoadingChanged()]).toEqual([
      [],
      [],
      false,
      true,
    ]);
    p.reset();
    expect(p.takeLoadingChanged()).toBe(false);
  });

  it("a viewport update allocates nothing", () => {
    const p = new PagingTrigger();
    p.evictedRange({ fromTime: 0, toTime: 9 });
    const views = [view(12, 22, 10), view(110, 130, 100), view(500, 520, 100)];
    const calls = probeAllocations(() => {
      for (let i = 0; i < 10_000; i += 1) p.viewport(i, views[i % 3] as PagingView);
    });
    expect(calls).toBe(0);
  });
});
