// E11-S10 PR 1 on the main thread (README BQ-145, BQ-146, BQ-156, BQ-157): the device-pixel box
// observer and the re-armed resolution query feed one coalesced resize; a hidden container is a
// legal 0×0, never a decode error; chaos cycles leak nothing; focus never moves on a resize.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, type ChartInternal } from "../../src/api/chart.js";
import { GLBackend } from "../../src/gl/backend.js";
import { PROGRAM } from "../../src/gl/program-cache.js";
import { watchSize } from "../../src/host/resize.js";
import type { ChartEvents, ThemeTokens } from "../../src/index.js";
import { SceneGraph } from "../../src/scene/index.js";
import { NullSeries } from "../../src/scene/null-series.js";
import {
  asHtml,
  canvasesIn,
  canvasIn,
  fakeContainer,
  fakeMatchMedia,
  fakeResizeObserver,
  type FakeElement,
  type FakeView,
} from "./fake-dom.js";

const theme: ThemeTokens = {
  palette: "default",
  convention: "standard",
  colors: { "color.chart.background": "#0b0e11" },
};

let container: FakeElement;
let view: FakeView;

beforeEach(() => {
  vi.useFakeTimers();
  container = fakeContainer(400, 300);
  view = container.ownerDocument.defaultView as FakeView;
  view.devicePixelRatio = 1;
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const sizes = (): [number, number, number][] => {
  const seen: [number, number, number][] = [];
  const unwatch = watchSize(asHtml(container), { resize: (w, h, d) => seen.push([w, h, d]) });
  sizes.unwatch = unwatch;
  return seen;
};
sizes.unwatch = (): void => undefined;

describe("Scenario: Moving to a different-DPI monitor re-renders correctly (detection)", () => {
  it("observes the device-pixel-content-box and sends backing / dpr", () => {
    const ro = fakeResizeObserver();
    view.ResizeObserver = ro.ctor;
    view.devicePixelRatio = 1.25;
    const seen = sizes();
    expect(ro.observed).toEqual([{ box: "device-pixel-content-box" }]);
    ro.fire({ inlineSize: 501, blockSize: 375 });
    expect(seen).toEqual([[501 / 1.25, 375 / 1.25, 1.25]]);
    // A monitor move at the same CSS size: only the device box changes, and it is seen.
    view.devicePixelRatio = 2;
    ro.fire({ inlineSize: 800, blockSize: 600 });
    expect(seen.at(-1)).toEqual([400, 300, 2]);
    sizes.unwatch();
    expect(ro.observed).toEqual([]);
  });

  it("falls back to the content box and round(css * dpr) without the device box", () => {
    const ro = fakeResizeObserver(false);
    view.ResizeObserver = ro.ctor;
    view.devicePixelRatio = 1.25;
    container.clientWidth = 321;
    const seen = sizes();
    expect(ro.observed).toEqual([null]);
    ro.fire();
    expect(seen).toEqual([[401 / 1.25, 375 / 1.25, 1.25]]);
    sizes.unwatch();
  });

  it("re-arms the resolution listener after each change, for the new ratio", () => {
    const queries = fakeMatchMedia(view);
    const seen = sizes();
    expect(queries.map((q) => q.media)).toEqual(["(resolution: 1dppx)"]);
    view.devicePixelRatio = 2;
    queries[0]?.change();
    view.devicePixelRatio = 1.25;
    queries[1]?.change();
    expect(queries.map((q) => q.media)).toEqual([
      "(resolution: 1dppx)",
      "(resolution: 2dppx)",
      "(resolution: 1.25dppx)",
    ]);
    expect(queries.map((q) => q.listeners.size)).toEqual([0, 0, 1]); // once each
    expect(seen).toEqual([
      [400, 300, 2],
      [400, 300, 1.25],
    ]);
    sizes.unwatch();
    expect(queries[2]?.listeners.size).toBe(0);
  });

  it("the query path re-observes and sizes from the fresh entry, not clientWidth", () => {
    const ro = fakeResizeObserver();
    view.ResizeObserver = ro.ctor;
    const queries = fakeMatchMedia(view);
    container.clientWidth = 420; // the padding box: 10 px padding each side
    const seen = sizes();
    ro.fire({ inlineSize: 400, blockSize: 300 }, { inlineSize: 400, blockSize: 300 });
    view.devicePixelRatio = 1.5;
    ro.now = [
      { inlineSize: 600, blockSize: 450 },
      { inlineSize: 400, blockSize: 300 },
    ];
    queries[0]?.change();
    expect(seen.at(-1)).toEqual([400, 300, 1.5]);
    expect(ro.observed).toEqual([{ box: "device-pixel-content-box" }]); // disconnected first
    expect(queries[1]?.media).toBe("(resolution: 1.5dppx)");
    view.devicePixelRatio = 0; // degenerate: the query arms for the same guarded ratio
    queries[1]?.change();
    expect(queries[2]?.media).toBe("(resolution: 1dppx)");
    sizes.unwatch();
  });

  it("a zoom on a fluid container (CSS box moves, device box does not) sizes right", () => {
    const ro = fakeResizeObserver();
    view.ResizeObserver = ro.ctor;
    const queries = fakeMatchMedia(view);
    const chart = createChart({ container: asHtml(container), theme }) as ChartInternal;
    ro.fire({ inlineSize: 400, blockSize: 300 }, { inlineSize: 400, blockSize: 300 });
    vi.advanceTimersByTime(16);
    // Browser zoom to 200 %: the container still fills 400 × 300 device px, now 200 × 150 CSS px.
    // The device box is unchanged, so the observer sends nothing unless it is re-observed.
    view.devicePixelRatio = 2;
    ro.now = [
      { inlineSize: 400, blockSize: 300 },
      { inlineSize: 200, blockSize: 150 },
    ];
    queries.at(-1)?.change();
    vi.advanceTimersByTime(16 * 12); // past the settle trim
    const canvas = canvasIn(container);
    expect([canvas?.width, canvas?.height, canvas?.style["width"]]).toEqual([400, 300, "200px"]);
    chart.dispose();
  });

  it("a container mounted hidden sends 0 at once, as no observer entry comes (BQ-147)", () => {
    view.ResizeObserver = fakeResizeObserver().ctor;
    container.clientWidth = 0;
    container.clientHeight = 0;
    expect(sizes()).toEqual([[0, 0, 1]]);
    sizes.unwatch();
  });

  it("is inert in a realm without a view, an observer or matchMedia", () => {
    expect(sizes()).toEqual([]);
    sizes.unwatch();
    container.ownerDocument.defaultView = null;
    expect(() => watchSize(asHtml(container), { resize: () => undefined })()).not.toThrow();
  });

  it("a DPR change reaches the worker as one resize per frame, the backing store resized", () => {
    const ro = fakeResizeObserver();
    view.ResizeObserver = ro.ctor;
    const queries = fakeMatchMedia(view);
    const chart = createChart({ container: asHtml(container), theme }) as ChartInternal;
    vi.advanceTimersByTime(16);
    view.devicePixelRatio = 2;
    queries.at(-1)?.change();
    ro.fire({ inlineSize: 800, blockSize: 600 });
    vi.advanceTimersByTime(16);
    const canvas = canvasIn(container);
    expect([canvas?.width, canvas?.height, canvas?.style["width"]]).toEqual([800, 600, "400px"]);
    chart.dispose();
    expect(queries.at(-1)?.listeners.size).toBe(0);
  });
});

describe("Scenario: A zero-size container does not crash or burn CPU (chart)", () => {
  function chaos(): {
    chart: ChartInternal;
    errors: unknown[];
    ro: ReturnType<typeof fakeResizeObserver>;
  } {
    const ro = fakeResizeObserver();
    view.ResizeObserver = ro.ctor;
    const chart = createChart({ container: asHtml(container), theme }) as ChartInternal;
    const errors: unknown[] = [];
    chart.subscribe("error", (e: ChartEvents["error"]) => errors.push(e));
    vi.advanceTimersByTime(16);
    return { chart, errors, ro };
  }

  it("display:none (a 0×0 observer entry) posts no ENGINE_DECODE_ERROR (BQ-147 regression)", () => {
    const { chart, errors, ro } = chaos();
    ro.fire({ inlineSize: 0, blockSize: 0 });
    vi.advanceTimersByTime(48);
    expect(errors).toEqual([]);
    chart.dispose();
  });

  it("BQ-156: 100 hide/show cycles and 50 DPR flips: no throw, no error, nothing leaks", () => {
    const queries = fakeMatchMedia(view);
    // A retained batch with its own buffer, VAO and program, so the live count is not 0.
    const graphs = vi.spyOn(SceneGraph.prototype, "addPane");
    const backends = vi.spyOn(GLBackend.prototype, "submit");
    const { chart, errors, ro } = chaos();
    const series = Object.assign(new NullSeries("main/s"), { program: PROGRAM.quad, count: 2 });
    (graphs.mock.contexts[0] as SceneGraph).addNode("main", "series", series);
    const backend = backends.mock.contexts[0] as GLBackend;
    backend.attach(series.id, { data: new Float32Array(16), head: 0, stride: 8 });
    ro.fire({ inlineSize: 401, blockSize: 300 });
    vi.advanceTimersByTime(32);
    const canvas = canvasIn(container);
    const alive = canvas?.webgl2?.alive.size;
    expect(alive).toBeGreaterThanOrEqual(3);
    expect(backend.trace.draws).toBeGreaterThan(0);
    for (let i = 0; i < 100; i += 1) {
      ro.fire({ inlineSize: 0, blockSize: 0 });
      vi.advanceTimersByTime(16);
      ro.fire({ inlineSize: 400, blockSize: 300 });
      vi.advanceTimersByTime(16);
    }
    // Each flip is a real DPR change: the re-observed entry carries the new device box.
    const marks = vi.spyOn(SceneGraph.prototype, "markResize");
    for (let i = 0; i < 50; i += 1) {
      const dpr = i % 2 === 0 ? 2 : 1;
      view.devicePixelRatio = dpr;
      ro.now = [
        { inlineSize: 400 * dpr, blockSize: 300 * dpr },
        { inlineSize: 400, blockSize: 300 },
      ];
      queries.at(-1)?.change();
      vi.advanceTimersByTime(16);
    }
    // The runtime's DPR branch marks every pane once per flip (an argument-less markResize).
    expect(marks.mock.calls.filter((c) => c.length === 0)).toHaveLength(50);
    expect(errors).toEqual([]);
    expect(canvas?.webgl2?.alive.size).toBe(alive);
    expect(queries).toHaveLength(51); // re-armed exactly once per change
    expect(queries.reduce((n, q) => n + q.listeners.size, 0)).toBe(1);
    expect(canvasesIn(container)).toHaveLength(1);
    chart.dispose();
  });
});

describe("BQ-157: a resize or DPR change never moves keyboard focus", () => {
  it("keeps document.activeElement and the mirror in place", () => {
    const ro = fakeResizeObserver();
    view.ResizeObserver = ro.ctor;
    const chart = createChart({ container: asHtml(container), theme }) as ChartInternal;
    const mirror = chart.getDomMirrorRoot() as unknown as FakeElement;
    mirror.focus();
    view.devicePixelRatio = 2;
    ro.fire({ inlineSize: 600, blockSize: 400 });
    vi.advanceTimersByTime(32);
    expect(container.ownerDocument.activeElement).toBe(mirror);
    expect(mirror.parent).toBe(container);
    chart.dispose();
  });
});
