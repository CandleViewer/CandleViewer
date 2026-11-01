// E11-S09 PR 1 through the §8 facade (#446; README BQ-1, BQ-3, BQ-4, BQ-15): `addPane` mints a
// stable key and a label, the panes reach the runtime, a removal never shifts another pane's
// address, and the shares the worker lays out are mirrored. Inline, on the fake DOM.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createChart,
  paneLabelFor,
  setHostEnvFactory,
  type ChartInternal,
} from "../../src/api/chart.js";
import type { PaneInternal } from "../../src/api/pane.js";
import type { ThemeTokens } from "../../src/index.js";
import type { ToWorker } from "../../src/worker/protocol.js";
import { FakeWorker, fakeEnv } from "../worker/fake-worker.js";
import { asHtml, FakeDocument, FakeElement, fakeContainer } from "./fake-dom.js";

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

describe("splitter state survives the API (E11-S09, BQ-11, BQ-19)", () => {
  it("test_setHeightRatio_afterAWorkerSideChange_keepsTheOtherPanesLaidOutShares", () => {
    const chart = mount();
    const a = chart.addPane({ heightRatio: 0.5 }) as PaneInternal;
    const b = chart.addPane({ heightRatio: 0.5 }) as PaneInternal;
    const c = chart.addPane({ heightRatio: 0.5 }) as PaneInternal;
    nextFrame();
    // As a splitter key does: the whole vector, outside the panes' own ratios.
    a.share = 0.5;
    b.share = 0.3;
    c.share = 0.2;
    c.setHeightRatio(0.2); // b keeps 0.3, not its stale 0.5
    nextFrame();
    expect([a, b, c].map((p) => p.share.toFixed(4))).toEqual(["0.5000", "0.3000", "0.2000"]);
    chart.dispose();
  });
});

describe("lens round 1 (E11-S09 BQ-3, BQ-11)", () => {
  it("test_setHeightRatio_twiceInOneTick_bothWeightsHold", () => {
    const chart = mount();
    const [a, b, c] = [0, 1, 2].map(() => chart.addPane({}) as PaneInternal) as [
      PaneInternal,
      PaneInternal,
      PaneInternal,
    ];
    nextFrame();
    a.setHeightRatio(0.9);
    b.setHeightRatio(0.1); // a's 0.9 is still pending: it must not fall back to a's old share
    nextFrame();
    // Weights 0.9 / 0.1 / (c's 1/3): dfabe25d gave .435 / .130 / .435.
    expect([a, b, c].map((p) => p.share.toFixed(4))).toEqual(["0.6750", "0.0750", "0.2500"]);
    chart.dispose();
  });

  it("test_layout_postedBeforeAPendingSend_keepsThePendingWeight", () => {
    FakeWorker.created = [];
    setHostEnvFactory(() => fakeEnv());
    try {
      const doc = new FakeDocument();
      doc.offscreenAvailable = true;
      doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {} };
      const el = new FakeElement("div", doc);
      el.clientWidth = 400;
      el.clientHeight = 300;
      const chart = createChart({ container: asHtml(el), theme }) as ChartInternal;
      const [a, b] = [0, 1, 2].map(() => chart.addPane({}) as PaneInternal) as [
        PaneInternal,
        PaneInternal,
      ];
      nextFrame();
      nextFrame();
      const w = FakeWorker.created.at(-1) as FakeWorker;
      const id = (w.inbox.find((m) => (m as ToWorker).t === "init") as { id: number }).id;
      const stale = (seq?: number): void =>
        w.onmessage?.({
          data: {
            t: "layout",
            id,
            panes: [0, 1, 2].map((k) => ({
              pane: k,
              top: 92 * k,
              height: 92,
              share: k === 2 ? 1 - 2 * (1 / 3) : 1 / 3,
              collapsed: false,
            })),
            timeAxis: [276, 24],
            plotWidth: 336,
            ...(seq === undefined ? {} : { seq }),
          },
        });
      a.setHeightRatio(0.9); // seq 1
      stale(0); // posted before the worker applied seq 1: a's 0.9 stays pending
      b.setHeightRatio(0.1); // seq 2
      const sent = () => {
        vi.advanceTimersByTime(0); // the bus delivers; no frame runs, so no real layout
        return w.inbox.flatMap((m) => {
          const c = (m as Extract<ToWorker, { t: "command" }>).cmd;
          return (m as ToWorker).t === "command" && c.k === "setPaneShares" ? [c] : [];
        });
      };
      expect(sent().at(-1)).toMatchObject({
        seq: 2,
        shares: [
          [0, 0.9],
          [1, 0.1],
          [2, 1 - 2 * (1 / 3)],
        ],
      });
      stale(2); // applied: the mirror is the truth again
      b.setHeightRatio(0.2);
      expect(sent().at(-1)?.shares[0]).toEqual([0, 1 / 3]);
      chart.dispose();
    } finally {
      setHostEnvFactory(null);
    }
  });

  it("test_layout_withoutAnEcho_clearsEveryPendingWeightAndTheWorkersSharesWin", () => {
    FakeWorker.created = [];
    setHostEnvFactory(() => fakeEnv());
    try {
      const doc = new FakeDocument();
      doc.offscreenAvailable = true;
      doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {} };
      const el = new FakeElement("div", doc);
      el.clientWidth = 400;
      el.clientHeight = 300;
      const chart = createChart({ container: asHtml(el), theme }) as ChartInternal;
      const [a, b] = [0, 1, 2].map(() => chart.addPane({}) as PaneInternal) as [
        PaneInternal,
        PaneInternal,
      ];
      nextFrame();
      nextFrame();
      const w = FakeWorker.created.at(-1) as FakeWorker;
      const id = (w.inbox.find((m) => (m as ToWorker).t === "init") as { id: number }).id;
      a.setHeightRatio(0.9); // pending, seq 1
      // A worker that never echoes `seq`, after a drag of its own: 0.5 / 0.3 / 0.2.
      w.onmessage?.({
        data: {
          t: "layout",
          id,
          panes: [0.5, 0.3, 0.2].map((share, k) => ({
            pane: k,
            top: 0,
            height: 92,
            share,
            collapsed: false,
          })),
          timeAxis: [276, 24],
          plotWidth: 336,
        },
      });
      b.setHeightRatio(0.1);
      vi.advanceTimersByTime(0); // the bus delivers; no frame runs
      const last = w.inbox
        .flatMap((m) => {
          const c = (m as Extract<ToWorker, { t: "command" }>).cmd;
          return (m as ToWorker).t === "command" && c.k === "setPaneShares" ? [c] : [];
        })
        .at(-1);
      // a's pending 0.9 is gone: the worker-side share is used.
      expect(last?.shares).toEqual([
        [0, 0.5],
        [1, 0.1],
        [2, 0.2],
      ]);
      chart.dispose();
    } finally {
      setHostEnvFactory(null);
    }
  });

  it("test_layout_staleAfterARemoval_theGonePanesKeysAreNeverRetained", () => {
    FakeWorker.created = [];
    setHostEnvFactory(() => fakeEnv());
    try {
      const doc = new FakeDocument();
      doc.offscreenAvailable = true;
      doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {} };
      const el = new FakeElement("div", doc);
      el.clientWidth = 400;
      el.clientHeight = 300;
      const chart = createChart({ container: asHtml(el), theme }) as ChartInternal;
      const panes = [0, 1, 2].map(() => chart.addPane({}) as PaneInternal);
      nextFrame();
      nextFrame();
      panes[1]?.remove();
      const w = FakeWorker.created.at(-1) as FakeWorker;
      const id = (w.inbox.find((m) => (m as ToWorker).t === "init") as { id: number }).id;
      // A layout the worker posted before it saw the removal.
      w.onmessage?.({
        data: {
          t: "layout",
          id,
          panes: [
            { pane: 0, top: 0, height: 92, share: 0.34, collapsed: false },
            { pane: 1, top: 92, height: 24, share: 0.33, collapsed: true },
            { pane: 2, top: 116, height: 160, share: 0.33, collapsed: false },
          ],
          timeAxis: [276, 24],
          plotWidth: 336,
        },
      });
      w.kill();
      vi.advanceTimersByTime(1000);
      nextFrame();
      const next = FakeWorker.created.at(-1) as FakeWorker;
      expect(next).not.toBe(w);
      const cmds = next.inbox.flatMap((m) =>
        (m as ToWorker).t === "command" ? [(m as Extract<ToWorker, { t: "command" }>).cmd] : [],
      );
      const keys = cmds.flatMap((c) =>
        c.k === "setPaneCollapsed"
          ? [c.pane]
          : c.k === "setPaneShares"
            ? c.shares.map(([k]) => k)
            : [],
      );
      expect(keys.length).toBeGreaterThan(0);
      expect(keys.includes(1)).toBe(false);
      chart.dispose();
    } finally {
      setHostEnvFactory(null);
    }
  });
});
