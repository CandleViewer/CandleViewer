// E11-S09 PR 2a through the §8 facade: `setSyncGroup` / `syncModes` (BQ-17, BQ-24 AMEND), one
// `viewportChanged` per worker frame with its `frameId` (BQ-26 AMEND), and the facade-side pane
// bound carried from PR 1a. Inline, on the fake DOM.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createChart,
  type ChartInternal,
  mintPaneKey,
  setHostEnvFactory,
} from "../../src/api/chart.js";
import { ANNOUNCE_EVENT } from "../../src/host/axis-stop.js";
import { ENGINE_SYNC_REFUSED, MAX_GROUP_MEMBERS, SyncRefused } from "../../src/sync/SyncGroup.js";
import { createSyncRegistry, type SyncRegistry } from "../../src/sync/registry.js";
import { MAX_PANE_KEY, MAX_PANES, type ToWorker } from "../../src/worker/protocol.js";
import { fakeEnv, FakeWorker } from "../worker/fake-worker.js";
import type { ChartEvents, ThemeTokens } from "../../src/index.js";
import { asHtml, fakeContainer, FakeDocument, FakeElement } from "./fake-dom.js";

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
    for (let f = 1; f <= 30; f += 1) {
      // A flood: several moves inside each of 30 frames still fire one event a frame.
      for (let k = 1; k <= 3; k += 1) chart.timeScale.setVisibleRange({ from: 0, to: f * 1e9 + k });
      nextFrame();
    }
    const ids = seen.map((v) => v.frameId);
    expect(ids.length).toBeGreaterThanOrEqual(30);
    expect(ids.every((id) => typeof id === "number")).toBe(true);
    expect(new Set(ids).size).toBe(ids.length); // one per frame
    expect(ids).toEqual([...ids].sort((a, b) => a - b));
    expect(seen.every((v) => v.syncId === undefined)).toBe(true); // local moves carry none
    chart.dispose();
  });

  it("test_viewportChanged_maps_the_origin_to_a_copied_syncId_and_numbers_a_frameless_message", () => {
    setHostEnvFactory(() => fakeEnv());
    FakeWorker.created = [];
    const view = { devicePixelRatio: 1, OffscreenCanvas: class {} };
    const doc = Object.assign(new FakeDocument(), { offscreenAvailable: true, defaultView: view });
    const box = Object.assign(new FakeElement("div", doc), { clientWidth: 400, clientHeight: 300 });
    try {
      const chart = createChart({ container: asHtml(box), theme, runMode: "worker" });
      const seen: ChartEvents["viewportChanged"][] = [];
      chart.subscribe("viewportChanged", (v) => seen.push(v));
      vi.advanceTimersByTime(0); // the fake worker receives on a timer
      const worker = FakeWorker.created.at(-1) as FakeWorker;
      const id = (worker.inbox as ToWorker[]).find((m) => m.t === "init")?.id;
      const row = { id, t: "viewport", timeStart: 1, timeEnd: 2, barSpacing: 6, pane: 0 };
      const origin = { worker: "w9", chart: 4, seq: 11 };
      worker.onmessage?.({ data: { ...row, frameId: 7, origin } });
      worker.onmessage?.({ data: row }); // an older worker: no frameId, no origin
      worker.onmessage?.({ data: row });
      expect(seen.map((v) => [v.frameId, v.syncId])).toEqual([
        [7, origin],
        [8, undefined],
        [9, undefined],
      ]);
      expect(seen[0]?.syncId).not.toBe(origin); // a copy: the worker's object may be reused
      chart.dispose();
    } finally {
      setHostEnvFactory(null);
    }
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

/** A container in `doc`, or in a fresh document (a separate realm: its own runtime and worker id). */
function sized(doc = fakeContainer().ownerDocument): FakeElement {
  const el = new FakeElement("div", doc);
  el.clientWidth = 400;
  el.clientHeight = 300;
  const view = doc.defaultView as { CustomEvent?: unknown };
  view.CustomEvent = class {
    readonly detail: unknown;
    constructor(
      readonly type: string,
      init: { detail: unknown },
    ) {
      this.detail = init.detail;
    }
  };
  return el;
}

describe("BQ-21: the facade with a sync registry", () => {
  it("test_setSyncGroup_refused_by_the_worker_rolls_the_facade_and_registry_back", () => {
    const sets: [string | null, object][] = [];
    const reg: SyncRegistry = {
      attach: () => ({
        set: (g, m) => void sets.push([g, m]),
        relay: () => undefined,
        detach: () => undefined,
      }),
      groupCount: 0,
      counters: { relayed: 0, sameWorker: 0 },
      dispose: () => undefined,
    };
    const doc = container.ownerDocument;
    const full = Array.from({ length: MAX_GROUP_MEMBERS }, () =>
      createChart({ container: asHtml(sized(doc)), theme, syncGroup: "A" }),
    );
    const chart = mount({ syncGroup: "B", syncRegistry: reg });
    const codes: string[] = [];
    chart.subscribe("error", (e) => void codes.push(e.code));
    nextFrame();
    chart.setSyncGroup("A", { levels: true }); // group A is full on this worker
    nextFrame();
    const kept = { time: true, crosshair: true, levels: false };
    expect(codes).toContain(ENGINE_SYNC_REFUSED);
    expect(sets.at(-1)).toEqual(["B", kept]);
    chart.setSyncGroup(null); // the modes the facade kept are the worker's, not the refused ones
    expect(sets.at(-1)).toEqual([null, kept]);
    for (const c of [...full, chart]) c.dispose();
  });

  it("test_a_refused_setSync_superseded_by_a_newer_one_rolls_nothing_back", () => {
    setHostEnvFactory(() => fakeEnv());
    FakeWorker.created = [];
    const sets: [string | null, object][] = [];
    const reg: SyncRegistry = {
      attach: () => ({
        set: (g, m) => void sets.push([g, m]),
        relay: () => undefined,
        detach: () => undefined,
      }),
      groupCount: 0,
      counters: { relayed: 0, sameWorker: 0 },
      dispose: () => undefined,
    };
    const view = { devicePixelRatio: 1, OffscreenCanvas: class {} };
    const doc = Object.assign(new FakeDocument(), { offscreenAvailable: true, defaultView: view });
    const box = Object.assign(new FakeElement("div", doc), { clientWidth: 400, clientHeight: 300 });
    try {
      const chart = createChart({
        container: asHtml(box),
        theme,
        runMode: "worker",
        syncRegistry: reg,
      });
      nextFrame();
      chart.setSyncGroup("A"); // refused by the worker, but its error arrives after the next one
      chart.setSyncGroup("C");
      vi.advanceTimersByTime(0); // the fake worker receives on a timer
      const worker = FakeWorker.created.at(-1) as FakeWorker;
      const reqs = (worker.inbox as ToWorker[]).flatMap((m) =>
        m.t === "command" && m.cmd.k === "setSync" ? [[m.id, m.cmd.groupId, m.cmd.req]] : [],
      );
      const [id, , req] = reqs.find((r) => r[1] === "A") ?? [];
      const refuse = (reqId: unknown) =>
        worker.onmessage?.({
          data: {
            t: "error",
            id,
            code: ENGINE_SYNC_REFUSED,
            message: "full",
            recoverable: true,
            reqId,
          },
        });
      refuse(req);
      expect(sets.at(-1)?.[0]).toBe("C"); // the worker applied "C": the facade keeps it
      const c = reqs.find((r) => r[1] === "C");
      refuse(c?.[2]);
      expect(sets.at(-1)?.[0]).toBe(null); // both refused: back to the worker's own state
      chart.dispose();
    } finally {
      setHostEnvFactory(null);
    }
  });

  it("test_two_workers_relay_a_move_and_announce_the_group_once", async () => {
    const registry = createSyncRegistry();
    const [ea, eb] = [sized(), sized()]; // two documents: two runtimes, two worker ids
    const said: string[] = [];
    for (const el of [ea, eb]) {
      el.addEventListener(ANNOUNCE_EVENT, (e) => {
        said.push((e as { detail: { text: string } }).detail.text);
      });
    }
    const opts = { theme, syncGroup: "G", syncRegistry: registry };
    const a = createChart({ container: asHtml(ea), ...opts }) as ChartInternal;
    const b = createChart({ container: asHtml(eb), ...opts }) as ChartInternal;
    await Promise.resolve();
    expect(said).toEqual(["Panes linked: time, crosshair"]);
    const seen: ChartEvents["viewportChanged"][] = [];
    b.subscribe("viewportChanged", (v) => seen.push(v));
    nextFrame();
    a.timeScale.setVisibleRange({ from: 1e9, to: 2e9 });
    nextFrame(); // a publishes, the registry relays to b's host
    nextFrame(); // b's host posts it and b's worker applies it
    nextFrame();
    const moved = seen.find((v) => v.syncId !== undefined);
    expect(moved?.timeStart).toBeCloseTo(1e9, -1);
    expect(moved?.timeEnd).toBeCloseTo(2e9, -1);
    expect(moved?.syncId?.worker).toMatch(/^i\d+$/);
    expect(registry.counters.relayed).toBeGreaterThan(0);
    a.setSyncGroup("G"); // unchanged: nothing more is said
    await Promise.resolve();
    expect(said).toHaveLength(1);
    b.dispose();
    await Promise.resolve();
    vi.advanceTimersByTime(600);
    expect(said).toEqual(["Panes linked: time, crosshair", "Panes unlinked"]);
    a.dispose();
    expect(registry.groupCount).toBe(1); // emptied at the next flush
    await Promise.resolve();
    expect(registry.groupCount).toBe(0);
  });
});
