// E15-T03 perf (SCR-023, the "Budget holds at six panes" scenario): six chart members in one group,
// every axis on, a 5 s crosshair sweep (300 simulated frames, never a wait) with 4 pointer moves per frame. The
// sync work per frame (the publishes plus the one flush) stays within 4 ms. Headless fake members:
// this measures the bus, not the engine (the reference-hardware figure is E15-K01's OL-1).
// The perf project: no coverage.
import { budget, why } from "@candleviewer/config/perf-calibration";
import { describe, expect, it } from "vitest";
import { busWithFrames, joinAll } from "./fakes";

const FRAMES = 5 * 60;
const MOVES_PER_FRAME = 4;

describe("SyncBus six-pane sweep", () => {
  it("keeps sync work under 4 ms in every frame of a 5 s sweep", () => {
    const { bus, frames } = busWithFrames();
    const members = joinAll(bus, 6);
    const costs: number[] = [];
    for (let f = 0; f < FRAMES; f += 1) {
      const started = performance.now();
      for (let m = 0; m < MOVES_PER_FRAME; m += 1) {
        bus.publish("p1", { axis: "crosshair", crosshair: f * MOVES_PER_FRAME + m });
      }
      frames.run();
      costs.push(performance.now() - started);
    }
    const sorted = [...costs].sort((a, b) => a - b);
    const at = (q: number): number =>
      sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * q))] ?? 0;
    const t = sorted[sorted.length - 1] ?? 0; // the worst frame
    console.info(
      `sync six-pane sweep: p50 ${at(0.5).toFixed(4)} p95 ${at(0.95).toFixed(4)} p99 ${at(0.99).toFixed(4)} worst ${t.toFixed(4)} ms; ${why(t, 4)}`,
    );
    expect(t, why(t, 4)).toBeLessThanOrEqual(budget(4));
    expect(members[5]?.received).toHaveLength(FRAMES);
    expect(bus.devCounters().lastFrameDispatches).toBe(5);
  });
});
