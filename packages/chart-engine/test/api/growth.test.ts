// E11-S10 PR 2 on the main thread (README BQ-149, BQ-150): the canvas sits in a container-sized
// clip wrapper, a drag grows the backing store in 128 px steps whose CSS box overflows into the
// wrapper, 10 resize-free frames trim it, and an export trims first so the PNG is the exact size.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, type ChartInternal } from "../../src/api/chart.js";
import type { ThemeTokens } from "../../src/index.js";
import { DRAG_START, ResizeDragBench } from "../../bench/scenes/resize-drag.js";
import {
  asHtml,
  canvasIn,
  fakeContainer,
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
let ro: ReturnType<typeof fakeResizeObserver>;
let chart: ChartInternal;
const frames = (n: number): void => void vi.advanceTimersByTime(16 * n);
const box = (): unknown[] => {
  const c = canvasIn(container);
  return [c?.width, c?.height, c?.style["width"], c?.style["height"]];
};

beforeEach(() => {
  vi.useFakeTimers();
  container = fakeContainer(400, 300);
  const view = container.ownerDocument.defaultView as FakeView;
  view.devicePixelRatio = 1;
  ro = fakeResizeObserver();
  view.ResizeObserver = ro.ctor;
  chart = createChart({ container: asHtml(container), theme }) as ChartInternal;
  frames(1);
});

afterEach(() => {
  chart.dispose();
  vi.useRealTimers();
});

describe("BQ-150: the canvas sits in a clip wrapper laid out by the container", () => {
  it("wraps the canvas, keeps aria-hidden on it and the mirror root a sibling after it", () => {
    const [clip, mirror] = container.children;
    expect(clip?.attributes.has("data-cv-canvas-clip")).toBe(true);
    expect(clip?.style).toEqual({
      position: "relative",
      width: "100%",
      height: "100%",
      overflow: "hidden",
    });
    expect(clip?.children).toEqual([canvasIn(container)]);
    expect(canvasIn(container)?.getAttribute("aria-hidden")).toBe("true");
    expect(mirror).toBe(chart.getDomMirrorRoot() as unknown as FakeElement);
    chart.dispose();
    expect(container.children).toHaveLength(0);
  });
});

describe("Scenario: Dragging a splitter does not cause reallocation storms (chart)", () => {
  it("grows past a step, never shrinks mid-drag, and trims after 10 quiet frames", () => {
    ro.fire({ inlineSize: 420, blockSize: 300 });
    frames(1);
    expect(box()).toEqual([528, 300, "528px", "300px"]); // the CSS box is the store: clipped
    ro.fire({ inlineSize: 380, blockSize: 300 });
    frames(1);
    expect(box()).toEqual([528, 300, "528px", "300px"]);
    frames(9);
    expect(box()).toEqual([528, 300, "528px", "300px"]);
    frames(2);
    expect(box()).toEqual([380, 300, "380px", "300px"]);
  });

  it("the bench's seeded drag through the host: <= 1 realloc per 128 px, no shrink, one trim", () => {
    const widths = ResizeDragBench.widths().map((w) => w - DRAG_START.width + 400);
    let [store, reallocs, shrinks] = [400, 0, 0];
    const watch = (): void => {
      const w = Number(box()[0]);
      if (w !== store) [reallocs, shrinks] = [reallocs + 1, shrinks + (w < store ? 1 : 0)];
      store = w;
    };
    for (const w of widths) {
      ro.fire({ inlineSize: w, blockSize: 300 });
      frames(1);
      watch();
    }
    expect([reallocs > 0, reallocs <= Math.ceil((Math.max(...widths) - 400) / 128)]).toEqual([
      true,
      true,
    ]);
    expect(shrinks).toBe(0);
    frames(11);
    watch();
    expect([store, shrinks]).toEqual([widths.at(-1), 1]); // the one trim, after the drag
  });

  it("an export trims first, so the PNG is the exact size", async () => {
    ro.fire({ inlineSize: 420, blockSize: 310 });
    frames(1);
    expect(box()).toEqual([528, 428, "528px", "428px"]);
    const canvas = canvasIn(container) as FakeElement;
    const encoded: number[][] = [];
    const blob = new Blob(["png"]);
    canvas.toBlob = (cb) => {
      encoded.push([canvas.width, canvas.height]);
      cb(blob);
    };
    const png = chart.takeScreenshot();
    await vi.runOnlyPendingTimersAsync();
    await expect(png).resolves.toBe(blob);
    expect(encoded).toEqual([[420, 310]]);
    expect(box()).toEqual([420, 310, "420px", "310px"]);
  });
});
