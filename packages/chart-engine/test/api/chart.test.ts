import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CHART_DEFAULTS, createChart, type ChartInternal } from "../../src/api/chart.js";
import type { PaneInternal, SeriesInternal } from "../../src/api/pane.js";
import type { PriceScaleState } from "../../src/api/scales.js";
import type {
  ChartEvents,
  ChartOptions,
  FootprintOptions,
  FrameStats,
  IndicatorPlugin,
  OverlayPlugin,
  ThemeTokens,
} from "../../src/index.js";
import { asHtml, canvasIn, fakeContainer, type FakeElement } from "./fake-dom.js";

const theme: ThemeTokens = {
  palette: "default",
  convention: "standard",
  colors: { "color.chart.background": "#0b0e11", "color.candle.up": "#26a69a" },
};

let container: FakeElement;

function mount(extra: Partial<ChartOptions> = {}): ChartInternal {
  return createChart({ container: asHtml(container), theme, ...extra }) as ChartInternal;
}

/** Runs the render runtime's next frame (inline mode: the page's frame callback, faked). */
const nextFrame = (): void => {
  vi.advanceTimersByTime(16);
};

const canvasOf = (c: FakeElement): FakeElement => {
  const canvas = canvasIn(c);
  if (canvas === undefined) throw new Error("no canvas mounted");
  return canvas;
};

beforeEach(() => {
  vi.useFakeTimers();
  container = fakeContainer(400, 300);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Scenario: A chart mounts and reports frame stats through the stub", () => {
  it("mounts a canvas sized to the container and filled with color.chart.background", () => {
    const chart = mount();
    const canvas = canvasOf(container);
    expect(canvas.width).toBe(800); // 400 CSS px at devicePixelRatio 2
    expect(canvas.height).toBe(600);
    expect(canvas.style["width"]).toBe("400px");
    expect(canvas.style["height"]).toBe("300px");
    expect(canvas.attributes.get("aria-hidden")).toBe("true");
    expect(chart.runMode).toBe("inline"); // the fake realm has no OffscreenCanvas
    nextFrame(); // the runtime paints on its frame (26 §3.2), not inside createChart
    expect(canvas.webgl2?.clears).toEqual(["#0b0e11"]); // GL clears to it (E11-S02)
    chart.dispose();
  });

  it("delivers a frameStats event carrying renderProfile within 1 s", () => {
    const chart = mount();
    const seen: FrameStats[] = [];
    chart.subscribe("frameStats", (s) => seen.push(s));
    expect(seen).toHaveLength(0); // createChart returned before any frame ran
    vi.advanceTimersByTime(1000);
    expect(seen).toHaveLength(1);
    expect(seen[0]?.renderProfile).toBe("full");
    expect(seen[0]).toEqual(chart.getStats());
    chart.dispose();
  });

  it("releases the probe's WebGL2 context once it has answered", () => {
    const chart = mount();
    expect(chart.getStats().renderProfile).toBe("full");
    const probe = container.ownerDocument.created[4]; // after canvas, clip, mirror and help
    expect(probe?.tagName).toBe("CANVAS");
    expect(probe?.webgl2?.lost).toBe(true);
    chart.dispose();
  });

  it("probes capabilities lazily and reports degraded-2d without WebGL2", () => {
    container.ownerDocument.webgl2Available = false;
    const chart = mount();
    const probesBefore = container.ownerDocument.created.length;
    expect(probesBefore).toBe(4); // the canvas, its clip, the mirror root and its help
    expect(chart.getStats().renderProfile).toBe("degraded-2d");
    expect(container.ownerDocument.created.length).toBe(5);
    chart.getStats();
    expect(container.ownerDocument.created.length).toBe(5); // probed once
    chart.dispose();
  });

  it("falls back to a pixel ratio of 1 and a 1 px canvas for an unsized container", () => {
    container = fakeContainer(0, 0);
    container.ownerDocument.defaultView = null;
    const chart = mount();
    expect(canvasOf(container).width).toBe(1);
    expect(canvasOf(container).height).toBe(1);
    chart.dispose();
  });

  it("clears to black when the theme lacks the background token, and survives without 2D", () => {
    const chart = mount({ theme: { ...theme, colors: {} } });
    nextFrame();
    expect(canvasOf(container).webgl2?.clears).toEqual(["#000000"]); // opaque: black
    chart.dispose();

    container = fakeContainer();
    container.ownerDocument.context2dAvailable = false;
    expect(() => {
      const c = mount();
      nextFrame();
      c.dispose();
    }).not.toThrow();
  });
});

describe("createChart facade", () => {
  it("returns synchronously with the §8 defaults resolved", () => {
    const chart = mount();
    expect(chart.density).toBe(CHART_DEFAULTS.density);
    expect(chart.panes).toEqual([]);
    expect(chart.getVisibleWindow()).toBeNull();
    expect(chart.getFocusedUnit()).toBeNull();
    chart.dispose();
  });

  it("rejects non-positive maxBars and memoryBudgetMb before mounting anything", () => {
    expect(() => mount({ maxBars: 0 })).toThrow(RangeError);
    expect(() => mount({ memoryBudgetMb: 1.5 })).toThrow(RangeError);
    expect(container.children).toHaveLength(0);
    expect(() => mount({ maxBars: 10, memoryBudgetMb: 64 }).dispose()).not.toThrow();
  });

  it("mounts a DOM mirror root in the container for keyboard focus", () => {
    const chart = mount();
    const root = chart.getDomMirrorRoot() as unknown as FakeElement;
    expect(root.parent).toBe(container);
    expect(root.attributes.has("data-cv-dom-mirror")).toBe(true);
    expect(root.style["clipPath"]).toBe("inset(50%)");
    chart.dispose();
  });

  it("repaints on setTheme and records density", () => {
    const chart = mount();
    chart.setTheme({ ...theme, colors: { "color.chart.background": "#ffffff" } });
    chart.setDensity("dense");
    nextFrame();
    expect(canvasOf(container).webgl2?.clears.at(-1)).toBe("#ffffff");
    expect(chart.theme.colors["color.chart.background"]).toBe("#ffffff");
    expect(chart.density).toBe("dense");
    chart.dispose();
  });

  it("subscribe returns a working Unsubscribe", () => {
    const chart = mount();
    const a = vi.fn();
    const b = vi.fn();
    const offA = chart.subscribe("frameStats", a);
    chart.subscribe("frameStats", b);
    offA();
    offA(); // idempotent
    vi.advanceTimersByTime(1000);
    expect(a).not.toHaveBeenCalled();
    expect(b).toHaveBeenCalledTimes(1);
    chart.dispose();
  });

  it("takeScreenshot resolves the canvas PNG and rejects when encoding fails", async () => {
    const chart = mount();
    const blob = new Blob(["png"]);
    canvasOf(container).blob = blob;
    await expect(chart.takeScreenshot({ scale: 1 })).resolves.toBe(blob);
    canvasOf(container).blob = null;
    await expect(chart.takeScreenshot()).rejects.toThrow(/could not be encoded/);
    chart.dispose();
    await expect(chart.takeScreenshot()).rejects.toThrow(/disposed/);
  });

  it("time scale stores a valid visible range and rejects an inverted one", () => {
    const chart = mount();
    expect(chart.timeScale.getVisibleRange()).toBeNull();
    chart.timeScale.setVisibleRange({ from: 1, to: 2 });
    expect(chart.timeScale.getVisibleRange()).toEqual({ from: 1, to: 2 });
    expect(() => chart.timeScale.setVisibleRange({ from: 2, to: 2 })).toThrow(RangeError);
    expect(() => chart.timeScale.setVisibleRange({ from: Number.NaN, to: 2 })).toThrow(RangeError);
    chart.dispose();
  });

  it("the scales answer the runtime's clamped range and the first pane's tick window (E11-S03)", () => {
    const chart = mount();
    const pane = chart.addPane({});
    chart.timeScale.setVisibleRange({ from: 0, to: 1 }); // far below one 200 px-wide bar
    nextFrame();
    const range = chart.timeScale.getVisibleRange();
    expect((range?.to ?? 0) - (range?.from ?? 0)).toBeGreaterThan(1); // barSpacing <= 200 px
    expect(pane.priceScale.getVisibleRange()).toEqual({ low: 0, high: 1 });
    chart.dispose();
  });
});

describe("dispose", () => {
  it("unmounts the canvas and mirror, drops listeners and pending frames, and is idempotent", () => {
    const chart = mount();
    const cb = vi.fn();
    chart.subscribe("frameStats", cb);
    chart.addPane({});
    chart.dispose();
    chart.dispose();
    vi.advanceTimersByTime(1000);
    expect(cb).not.toHaveBeenCalled();
    expect(container.children).toHaveLength(0);
    expect(chart.disposed).toBe(true);
    expect(chart.panes).toEqual([]);
  });

  it("turns later calls into no-ops or errors", () => {
    const chart = mount();
    chart.dispose();
    expect(() => chart.addPane({})).toThrow(/disposed/);
    const off = chart.subscribe("crosshair", vi.fn());
    expect(() => off()).not.toThrow();
    chart.setTheme({ ...theme, colors: {} });
    chart.setDensity("compact");
    expect(chart.theme).toBe(theme);
    expect(chart.density).toBe("comfortable");
  });
});

describe("panes and series", () => {
  const fpOptions: FootprintOptions = {
    cellType: "bid-ask",
    displayMode: "box",
    imbalanceRatio: 3,
    imbalanceStack: 3,
    noiseFilter: 0,
    textLod: "auto",
    colorScale: "delta",
  };
  const overlay = {} as OverlayPlugin;
  const indicator = {} as IndicatorPlugin;

  it("adds, lists and removes panes by id or by handle", () => {
    const chart = mount();
    const a = chart.addPane({ heightRatio: 0.6 }) as PaneInternal;
    const b = chart.addPane({}) as PaneInternal;
    expect(a.id).not.toBe(b.id);
    expect(a.heightRatio).toBe(0.6);
    expect(b.heightRatio).toBe(1);
    expect(chart.panes.map((p) => p.id)).toEqual([a.id, b.id]);
    chart.removePane(a.id);
    chart.removePane(a.id); // unknown id: no-op
    expect(a.removed).toBe(true);
    b.remove();
    b.remove();
    expect(chart.panes).toEqual([]);
    chart.dispose();
  });

  it("validates height ratios", () => {
    const chart = mount();
    expect(() => chart.addPane({ heightRatio: 0 })).toThrow(RangeError);
    const pane = chart.addPane({}) as PaneInternal;
    pane.setHeightRatio(0.25);
    expect(pane.heightRatio).toBe(0.25);
    expect(() => pane.setHeightRatio(1.5)).toThrow(RangeError);
    expect(() => pane.setHeightRatio(Number.NaN)).toThrow(RangeError);
    chart.dispose();
  });

  it("series handles record options, visibility and removal", () => {
    const chart = mount();
    const pane = chart.addPane({}) as PaneInternal;
    const fp = pane.addSeries("footprint", fpOptions) as SeriesInternal<"footprint">;
    expect(fp.type).toBe("footprint");
    expect(pane.seriesCount).toBe(1);
    fp.setOptions({ textLod: "never" });
    expect(fp.options).toEqual({ ...fpOptions, textLod: "never" });
    fp.setVisible(false);
    expect(fp.visible).toBe(false);
    const candles = pane.addSeries("candles", { upColorToken: "u", downColorToken: "d" });
    const data = {
      time: new Float64Array(1),
      open: new Int32Array(1),
      high: new Int32Array(1),
      low: new Int32Array(1),
      close: new Int32Array(1),
      volume: new Float32Array(1),
      priceOrigin: 0,
      tickSize: 0.1,
    };
    expect(() => {
      candles.setData(data);
      candles.append(data);
      candles.prependHistory(data);
    }).not.toThrow();
    fp.remove();
    expect(pane.seriesCount).toBe(1);
    expect(pane.priceScale.getVisibleRange()).toBeNull();
    chart.dispose();
  });

  it("overlay and indicator handles are inert stubs", () => {
    const chart = mount();
    const pane = chart.addPane({});
    const o = pane.addOverlay(overlay);
    const i = pane.addIndicator(indicator, { length: 14 });
    expect(() => {
      o.setOptions({});
      o.remove();
      i.setParams({ length: 20 });
      i.remove();
    }).not.toThrow();
    chart.dispose();
  });

  it("refuses work on a removed pane or a disposed chart", () => {
    const chart = mount();
    const pane = chart.addPane({});
    pane.remove();
    expect(() => pane.addSeries("histogram", { colorToken: "x" })).toThrow(/removed/);
    const other = chart.addPane({});
    chart.dispose();
    expect(() => other.addOverlay(overlay)).toThrow(/disposed/);
  });

  it("price scale toggles auto-scale", () => {
    const chart = mount();
    const scale = chart.addPane({}).priceScale as PriceScaleState;
    expect(scale.autoScale).toBe(true);
    scale.setAutoScale(false);
    expect(scale.autoScale).toBe(false);
    chart.dispose();
  });
});

describe("Scenario: Context loss recovers within the R1 exit budget (the facade)", () => {
  it("forwards details on ENGINE_CONTEXT_LOST only (BQ-64)", () => {
    const chart = mount();
    const seen: ChartEvents["error"][] = [];
    chart.subscribe("error", (e) => seen.push(e));
    nextFrame();
    const canvas = canvasOf(container);
    canvas.webgl2?.loseContext();
    canvas.dispatch("webglcontextlost", { preventDefault: () => undefined });
    canvas.webgl2?.restoreContext();
    canvas.dispatch("webglcontextrestored", {});
    nextFrame();
    expect(seen).toEqual([
      {
        code: "ENGINE_CONTEXT_LOST",
        message: "Graphics context lost: restoring, attempt 1 of 3, next try in 1 s",
        recoverable: true,
        details: { attempt: 1, maxAttempts: 3, nextTryMs: 1000 },
      },
      { code: "ENGINE_CONTEXT_RESTORED", message: expect.any(String), recoverable: true },
    ]);
    chart.dispose();
  });
});
