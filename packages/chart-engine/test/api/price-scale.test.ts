// E11-S05 through the §8 facade (README BQ-121, BQ-124): the widened `PriceScale`, the persisted
// `PaneOptions.priceScale`, and the lock badge in the host DOM, inline on the fake DOM.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, type ChartInternal } from "../../src/api/chart.js";
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
