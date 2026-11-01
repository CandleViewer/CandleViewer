// The facade carries the engine-reported `renderProfile` into its stats on `ready` and on
// `frame`, so a degraded-2d handoff is visible to `getStats()` / `frameStats` (SCR-048's trigger).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart } from "../../src/api/chart.js";
import type { FrameStats, ThemeTokens } from "../../src/index.js";
import type { ChartHostOptions } from "../../src/worker/host.js";
import type { FromWorker } from "../../src/worker/protocol.js";
import { asHtml, fakeContainer, type FakeElement } from "./fake-dom.js";

type Deliver = (msg: FromWorker) => void;
const captured: { deliver: Deliver | null } = { deliver: null };

vi.mock("../../src/worker/host.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/worker/host.js")>();
  return {
    ...actual,
    createChartHost: (o: ChartHostOptions) => {
      captured.deliver = o.listener.deliver;
      return actual.createChartHost(o);
    },
  };
});

const theme: ThemeTokens = {
  palette: "default",
  convention: "standard",
  colors: { "color.chart.background": "#0b0e11" },
};

let container: FakeElement;

beforeEach(() => {
  vi.useFakeTimers();
  container = fakeContainer(400, 300);
  captured.deliver = null;
});

afterEach(() => {
  vi.useRealTimers();
});

const frame = (renderProfile: FrameStats["renderProfile"]): FromWorker => ({
  t: "frame",
  id: 0 as never,
  runMode: "inline",
  renderProfile,
  frameTimeMs: 4,
  drawCalls: 1,
  triangles: 2,
  uploadedBytes: 0,
  gpuMemoryMbEstimate: 0,
  lod: { candles: 0, footprint: 0 },
  dpr: 1,
  backingStorePx: [400, 300],
});

describe("Scenario: the facade reports the engine's render profile after a degraded-2d handoff", () => {
  it("getStats and frameStats follow a frame that reports degraded-2d", () => {
    const chart = createChart({ container: asHtml(container), theme });
    const seen: FrameStats[] = [];
    chart.subscribe("frameStats", (s) => seen.push(s));
    vi.advanceTimersByTime(16);
    expect(chart.getStats().renderProfile).toBe("full");
    captured.deliver?.(frame("degraded-2d"));
    expect(chart.getStats().renderProfile).toBe("degraded-2d");
    expect(seen.at(-1)?.renderProfile).toBe("degraded-2d");
    chart.dispose();
  });

  it("a later ready message updates the profile even after a frame has arrived", () => {
    const chart = createChart({ container: asHtml(container), theme });
    vi.advanceTimersByTime(16);
    expect(chart.getStats().renderProfile).toBe("full");
    captured.deliver?.({
      t: "ready",
      id: 0 as never,
      runMode: "inline",
      renderProfile: "degraded-2d",
      capabilities: {} as never,
    });
    expect(chart.getStats().renderProfile).toBe("degraded-2d");
    chart.dispose();
  });
  it("returns to full when a later frame or ready reports full after a degraded-2d frame", () => {
    const chart = createChart({ container: asHtml(container), theme });
    vi.advanceTimersByTime(16);
    captured.deliver?.(frame("degraded-2d"));
    expect(chart.getStats().renderProfile).toBe("degraded-2d");
    captured.deliver?.(frame("full"));
    expect(chart.getStats().renderProfile).toBe("full");
    captured.deliver?.(frame("degraded-2d"));
    captured.deliver?.({
      t: "ready",
      id: 0 as never,
      runMode: "inline",
      renderProfile: "full",
      capabilities: {} as never,
    });
    expect(chart.getStats().renderProfile).toBe("full");
    chart.dispose();
  });
});
