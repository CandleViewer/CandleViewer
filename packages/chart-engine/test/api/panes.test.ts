// E11-S09 PR 1 through the §8 facade (#446; README BQ-1, BQ-3, BQ-4, BQ-15): `addPane` mints a
// stable key and a label, the panes reach the runtime, a removal never shifts another pane's
// address, and the shares the worker lays out are mirrored. Inline, on the fake DOM.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, paneLabelFor, type ChartInternal } from "../../src/api/chart.js";
import type { PaneInternal } from "../../src/api/pane.js";
import type { ThemeTokens } from "../../src/index.js";
import { asHtml, fakeContainer, type FakeElement } from "./fake-dom.js";

const theme: ThemeTokens = { palette: "default", convention: "standard", colors: {} };

let container: FakeElement;
const nextFrame = (): void => void vi.advanceTimersByTime(16);
const mount = (): ChartInternal =>
  createChart({ container: asHtml(container), theme }) as ChartInternal;

beforeEach(() => {
  vi.useFakeTimers();
  container = fakeContainer(400, 300);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the pane stack through the facade", () => {
  it("test_addPane_threePanes_stableKeysDefaultLabelsAndMirroredShares", () => {
    const chart = mount();
    const a = chart.addPane({ heightRatio: 0.6 }) as PaneInternal;
    const b = chart.addPane({ heightRatio: 0.2, label: "Volume pane" }) as PaneInternal;
    const c = chart.addPane({ heightRatio: 0.2 }) as PaneInternal;
    expect([a, b, c].map((p) => [p.key, p.label])).toEqual([
      [0, "Price pane"],
      [1, "Volume pane"],
      [2, "Pane 3"],
    ]);
    expect(Number.isNaN(a.share)).toBe(true); // nothing laid out yet
    nextFrame();
    expect([a, b, c].map((p) => p.share.toFixed(6))).toEqual(["0.600000", "0.200000", "0.200000"]);
    expect(a.share + b.share + c.share).toBe(1);
    b.setHeightRatio(0.6); // the whole vector goes out: 0.6 / 0.6 / 0.2
    nextFrame();
    expect([a, b, c].map((p) => p.share.toFixed(4))).toEqual(["0.4286", "0.4286", "0.1429"]);
    chart.dispose();
  });

  it("test_removePane_secondOfThree_theThirdKeepsItsAddressAndTheSharesRenormalise", () => {
    const chart = mount();
    const a = chart.addPane({}) as PaneInternal;
    const b = chart.addPane({}) as PaneInternal;
    const c = chart.addPane({}) as PaneInternal;
    nextFrame();
    b.remove();
    c.priceScale.setInverted(true); // BQ-1: key 2, not index 1
    nextFrame();
    expect(c.priceScale.getState().inverted).toBe(true);
    expect(a.priceScale.getState().inverted).toBe(false);
    expect([a.share, c.share]).toEqual([0.5, 0.5]);
    const d = chart.addPane({}) as PaneInternal;
    expect(d.key).toBe(3); // keys are never reused
    expect(d.label).toBe(paneLabelFor(3));
    chart.dispose();
  });

  it("test_addPane_badLabel_rejectedUpFrontAndNoPaneAdded", () => {
    const chart = mount();
    expect(() => chart.addPane({ label: 7 as unknown as string })).toThrow(RangeError);
    expect(() => chart.addPane({ label: "x".repeat(121) })).toThrow(RangeError);
    expect(chart.panes).toHaveLength(0);
    expect((chart.addPane({ label: "" }) as PaneInternal).key).toBe(0);
    chart.dispose();
  });
});
