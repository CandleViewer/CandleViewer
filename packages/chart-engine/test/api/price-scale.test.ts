// E11-S05 through the §8 facade (README BQ-121, BQ-124): the widened `PriceScale`, the persisted
// `PaneOptions.priceScale`, and the lock badge in the host DOM, inline on the fake DOM.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, type ChartInternal } from "../../src/api/chart.js";
import type { PaneInternal } from "../../src/api/pane.js";
import { SCALE_BADGE_LABEL } from "../../src/host/scale-badge.js";
import type { ChartEvents, ThemeTokens } from "../../src/index.js";
import { asHtml, fakeContainer, type FakeElement } from "./fake-dom.js";

const theme: ThemeTokens = {
  palette: "default",
  convention: "standard",
  colors: {
    "color.surface.raised": "#1e2329",
    "color.border.strong": "#5e6673",
    "color.text.primary": "#eaecef",
  },
};

let container: FakeElement;
const nextFrame = (): void => void vi.advanceTimersByTime(16);
const mount = (): ChartInternal =>
  createChart({ container: asHtml(container), theme }) as ChartInternal;
const badge = (): FakeElement | undefined =>
  container.children.find((el) => el.attributes.has("data-cv-scale-badge"));

beforeEach(() => {
  vi.useFakeTimers();
  container = fakeContainer(400, 300);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the widened PriceScale (BQ-121)", () => {
  it("forwards mode, invert and options and answers getState from the renderer", () => {
    const chart = mount();
    const scale = chart.addPane({}).priceScale;
    expect(scale.getState()).toMatchObject({ mode: "linear", autoScale: true, anchorTick: null });
    scale.setMode("percent");
    scale.setInverted(true);
    scale.setOptions({ includeDrawings: true, priceOnly: true, marginTop: 0.1 });
    nextFrame();
    expect(scale.getState()).toMatchObject({
      mode: "percent",
      requestedMode: "percent",
      inverted: true,
      includeDrawings: true,
      priceOnly: true,
      marginTop: 0.1,
      marginBottom: 0.05,
    });
    scale.setMode("log"); // no price origin yet: held, the drawn mode stays (BQ-120)
    expect(scale.getState()).toMatchObject({ mode: "percent", requestedMode: "log" });
    nextFrame();
    expect(scale.getState()).toMatchObject({
      mode: "percent",
      requestedMode: "log",
      logReason: "no-price-origin",
    });
    expect(() => scale.setMode("symlog" as "log")).toThrow(RangeError);
    expect(() => scale.setOptions({ marginBottom: 0.5 })).toThrow(RangeError);
    chart.dispose();
  });

  it("applies PaneOptions.priceScale at addPane and rejects a bad one up front", () => {
    const chart = mount();
    expect(() => chart.addPane({ priceScale: { marginTop: -0.1 } })).toThrow(RangeError);
    expect(() => chart.addPane({ priceScale: { mode: "x" as "log" } })).toThrow(RangeError);
    expect(chart.panes).toHaveLength(0);
    const pane = chart.addPane({ priceScale: { mode: "indexed", inverted: true } });
    nextFrame();
    expect(pane.priceScale.getState()).toMatchObject({ mode: "indexed", inverted: true });
    // A persisted log before any bars: kept as the request, drawn once the origin arrives (D5).
    const log = chart.addPane({ priceScale: { mode: "log" } });
    nextFrame();
    expect(log.priceScale.getState()).toMatchObject({ mode: "linear", requestedMode: "log" });
    chart.dispose();
  });
});

describe("Scenario: Manual drag disengages autoscale and is reversible (the badge)", () => {
  it("a lock shows the 'Price scale locked' button; activating it restores auto-fit", () => {
    const chart = mount();
    const scale = chart.addPane({}).priceScale;
    const changes: ChartEvents["viewportChanged"][] = [];
    chart.subscribe("viewportChanged", (e) => changes.push(e));
    nextFrame();
    expect(badge()).toBeUndefined();
    scale.setAutoScale(false);
    nextFrame();
    const b = badge();
    expect(b?.tagName).toBe("BUTTON");
    expect(b?.textContent).toBe(SCALE_BADGE_LABEL);
    expect(SCALE_BADGE_LABEL).toBe("Price scale locked");
    expect(b?.style["background"]).toBe("#1e2329"); // tokens, not literals
    expect(changes.length).toBeGreaterThan(0); // the lock rides viewportChanged (C-35)
    chart.setTheme({ ...theme, colors: { ...theme.colors, "color.text.primary": "#000000" } });
    expect(b?.style["color"]).toBe("#000000");
    // Its own input never reaches the chart's router (it would read as a plot gesture).
    let reached = false;
    b?.dispatch("pointerdown", { stopPropagation: () => (reached = true) });
    expect(reached).toBe(true);
    container.ownerDocument.activeElement = b ?? null; // activated from the keyboard
    b?.dispatch("click", {}); // Enter and Space click a native button
    nextFrame();
    expect(badge()).toBeUndefined();
    expect(container.ownerDocument.activeElement).toBe(container); // not dropped to <body> (G-19)
    expect(scale.getState().autoScale).toBe(true);
    scale.setAutoScale(false);
    nextFrame();
    expect(badge()).toBe(b); // the same node comes back
    chart.dispose();
    expect(badge()).toBeUndefined();
  });
});

describe("E11-S09: panes reach the worker under stable keys (BQ-1 to BQ-5)", () => {
  it("mirrors the normalised shares; each pane's scale is its own; one viewportChanged a frame", () => {
    const chart = mount();
    const seen: unknown[] = [];
    chart.subscribe("viewportChanged", (v) => seen.push(v));
    const [a, b, c] = [{}, {}, { heightRatio: 0.5 }].map((o) => chart.addPane(o) as PaneInternal);
    nextFrame();
    expect([a, b, c].map((p) => p?.heightRatio)).toEqual([0.25, 0.25, 0.5]);
    b?.setHeightRatio(0.4); // the others rescale into 0.6 (a stays over the 48 px minimum)
    nextFrame();
    const near = (xs: number[]): unknown[] => xs.map((x) => expect.closeTo(x, 12));
    expect([a, b, c].map((p) => p?.heightRatio)).toEqual(near([0.2, 0.4, 0.4]));
    seen.length = 0;
    c?.priceScale.setMode("percent");
    nextFrame();
    expect([a, c].map((p) => p?.priceScale.getState().mode)).toEqual(["linear", "percent"]);
    expect(seen).toHaveLength(1);
    b?.remove(); // the worker drops key 1; the others keep theirs
    nextFrame();
    expect([a, c].map((p) => p?.heightRatio)).toEqual(near([1 / 3, 2 / 3]));
    chart.dispose();
  });

  it("removing the first pane still emits one viewportChanged a frame; a stub keeps its ratio", () => {
    const chart = mount();
    const seen: unknown[] = [];
    chart.subscribe("viewportChanged", (v) => seen.push(v));
    const [a, b, c] = [{}, {}, {}].map((o) => chart.addPane(o) as PaneInternal);
    nextFrame();
    a?.remove(); // key 0: the worker's slot 0 takes key 1, no keyless row remains
    nextFrame();
    seen.length = 0;
    b?.priceScale.setMode("percent");
    nextFrame();
    expect(seen).toHaveLength(1);
    c?.setHeightRatio(0.05); // under the 48 px minimum: c folds to the stub
    nextFrame();
    expect([b?.collapsed, c?.collapsed]).toEqual([false, true]);
    expect(c?.heightRatio).toBeGreaterThan(0); // (0, 1] holds while collapsed
    chart.dispose();
  });

  it("re-maps every handle from the layout after a removal; no handle keeps a dead slot (BQ-11a)", () => {
    // Ruling R58 (BQ-11a rider): the re-key is announced on the layout that follows the removal.
    const chart = mount();
    const [a, b, c] = [{}, {}, {}].map((o) => chart.addPane(o) as PaneInternal);
    nextFrame();
    const map = (): unknown[] => [a, b, c].map((p) => [p?.key, p?.slot]);
    expect(map()).toEqual([
      [0, 0],
      [1, 1],
      [2, 2],
    ]);
    a?.remove(); // key 0 while others remain: slot 0 takes key 1, slot 1 key 2, slot 2 is dead
    nextFrame();
    expect(map()).toEqual([
      [0, -1],
      [1, 0],
      [2, 1],
    ]);
    expect(chart.panes.map((p) => (p as PaneInternal).slot)).toEqual([0, 1]);
    c?.remove();
    nextFrame();
    expect(map()).toEqual([
      [0, -1],
      [1, 0],
      [2, -1],
    ]);
    // A React StrictMode re-mount: the effect's cleanup removes the sole pane (its slot goes
    // keyless), the re-run adds one, and the layout after it gives the new key slot 0.
    b?.remove();
    const d = chart.addPane({}) as PaneInternal;
    expect(d.slot).toBe(-1); // not laid out until its layout arrives
    nextFrame();
    expect([b?.slot, d.key, d.slot]).toEqual([-1, 3, 0]);
    chart.dispose();
  });
});
