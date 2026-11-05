// E11-S09 PR 2a through the §8 facade: `setSyncGroup` / `syncModes` (BQ-17, BQ-24 AMEND), one
// `viewportChanged` per worker frame with its `frameId` (BQ-26 AMEND), and the facade-side pane
// bound carried from PR 1a. Inline, on the fake DOM.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, type ChartInternal, mintPaneKey } from "../../src/api/chart.js";
import { SyncRefused } from "../../src/sync/SyncGroup.js";
import { MAX_PANE_KEY, MAX_PANES } from "../../src/worker/protocol.js";
import type { ChartEvents, ThemeTokens } from "../../src/index.js";
import { asHtml, fakeContainer, type FakeElement } from "./fake-dom.js";

const theme: ThemeTokens = {
  palette: "default",
  convention: "standard",
  colors: { "color.surface.raised": "#1e2329", "color.text.primary": "#eaecef" },
};

let container: FakeElement;
const nextFrame = (): void => void vi.advanceTimersByTime(16);
const mount = (extra: object = {}): ChartInternal =>
  createChart({ container: asHtml(container), theme, ...extra }) as ChartInternal;

beforeEach(() => {
  vi.useFakeTimers();
  container = fakeContainer(400, 300);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("BQ-26: viewportChanged once per chart per frame", () => {
  it("test_viewportChanged_with_several_panes_fires_once_per_frame_with_a_frameId", () => {
    const chart = mount();
    const seen: ChartEvents["viewportChanged"][] = [];
    chart.subscribe("viewportChanged", (v) => seen.push(v));
    for (let i = 0; i < 4; i += 1) chart.addPane({});
    nextFrame();
    chart.timeScale.setVisibleRange({ from: 0, to: 1e9 });
    nextFrame();
    chart.timeScale.setVisibleRange({ from: 0, to: 2e9 });
    nextFrame();
    const ids = seen.map((v) => v.frameId);
    expect(ids.every((id) => typeof id === "number")).toBe(true);
    expect(new Set(ids).size).toBe(ids.length); // one per frame
    expect(ids).toEqual([...ids].sort((a, b) => a - b));
    expect(seen.every((v) => v.syncId === undefined)).toBe(true); // local moves carry none
    chart.dispose();
  });
});

describe("BQ-17 / BQ-24: sync modes", () => {
  it("test_setSyncGroup_scale_true_is_refused_never_ignored", () => {
    const chart = mount({ syncGroup: "A" });
    expect(() => chart.setSyncGroup("A", { scale: true })).toThrow(SyncRefused);
    chart.setSyncGroup("B", { crosshair: false, levels: true });
    chart.setSyncGroup(null);
    expect(() => chart.setSyncGroup("x".repeat(129))).toThrow(RangeError);
    for (const bad of ["", "a b", "a/b"]) expect(() => chart.setSyncGroup(bad)).toThrow(RangeError);
    expect(() => mount({ syncGroup: "" })).toThrow(RangeError);
    chart.dispose();
  });

  it("test_createChart_syncModes_scale_true_is_refused_before_mounting", () => {
    expect(() => mount({ syncModes: { scale: true } })).toThrow(SyncRefused);
    expect(container.children).toHaveLength(0);
    const chart = mount({ syncGroup: "A", syncModes: { crosshair: false } });
    nextFrame();
    chart.dispose();
  });
});

describe("PR 1a carry: the facade-side pane bound", () => {
  it("test_addPane_the_65th_pane_is_refused_and_not_kept", () => {
    const chart = mount();
    for (let i = 0; i < MAX_PANES; i += 1) chart.addPane({});
    expect(() => chart.addPane({})).toThrow(/at most 64 panes/);
    expect(chart.panes).toHaveLength(MAX_PANES);
    chart.dispose();
  });

  it("test_addPane_past_the_last_pane_key_is_refused_before_sending", () => {
    // addPane mints through this before it sends or keeps anything (65,536 real adds are slow).
    expect(mintPaneKey(0)).toBe(0);
    expect(mintPaneKey(MAX_PANE_KEY)).toBe(MAX_PANE_KEY);
    expect(() => mintPaneKey(MAX_PANE_KEY + 1)).toThrow(/at most 65536 pane keys/);
    const chart = mount();
    chart.removePane(chart.addPane({}).id);
    expect(chart.addPane({}).id).toBe("pane-2"); // a removed key is not reused
    chart.dispose();
  });
});
