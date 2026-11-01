// E11-S09 PR 2 (#446 BQ-17, BQ-21) through the §8 facade: `ChartOptions.syncGroup` and
// `setSyncGroup` reach the worker as `setSync`, the group state is announced once per change
// under `chart:sync`, bad ids and modes throw, and a group spanning two links (a worker chart
// and an inline one) is relayed with its origin kept.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, setHostEnvFactory } from "../../src/api/chart.js";
import { ANNOUNCE_EVENT } from "../../src/host/axis-stop.js";
import { SYNC_ANNOUNCE_KEY } from "../../src/sync/registry.js";
import type { Command, ToWorker } from "../../src/worker/protocol.js";
import { fakeEnv, FakeWorker } from "../worker/fake-worker.js";
import { asHtml, FakeDocument, FakeElement } from "./fake-dom.js";

const theme = { palette: "default", convention: "standard", colors: {} } as const;
const frames = (n = 1): void => void vi.advanceTimersByTime(16 * n);

class Announce {
  readonly detail: unknown;
  constructor(
    readonly type: string,
    init: { detail: unknown },
  ) {
    this.detail = init.detail;
  }
}

/** A worker-capable document whose containers can build the announce event. */
function page(): { doc: FakeDocument; box: (said: unknown[]) => FakeElement } {
  const doc = new FakeDocument();
  doc.offscreenAvailable = true;
  doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {}, CustomEvent: Announce };
  const box = (said: unknown[]): FakeElement => {
    const c = new FakeElement("div", doc);
    c.clientWidth = 400;
    c.clientHeight = 200;
    c.addEventListener(ANNOUNCE_EVENT, (e) => said.push((e as { detail: unknown }).detail));
    return c;
  };
  return { doc, box };
}

const setSyncs = (w: FakeWorker): Command[] =>
  (w.inbox as ToWorker[]).flatMap((m) =>
    m.t === "command" && m.cmd.k === "setSync" ? [m.cmd] : [],
  );
const text = (said: unknown[]): string[] => said.map((d) => (d as { text: string }).text);

beforeEach(() => {
  vi.useFakeTimers();
  FakeWorker.created = [];
  setHostEnvFactory(() => fakeEnv());
});

afterEach(() => {
  setHostEnvFactory(null);
  vi.useRealTimers();
});

describe("Scenario: Sync state announced once (through the facade)", () => {
  it("test_syncGroupOption_andSetSyncGroup_sendSetSync_andAnnounceOncePerChange", () => {
    const { box } = page();
    const saidA: unknown[] = [];
    const saidB: unknown[] = [];
    const a = createChart({ container: asHtml(box(saidA)), theme, syncGroup: "g" });
    const b = createChart({
      container: asHtml(box(saidB)),
      theme,
      syncGroup: "g",
      syncModes: { crosshair: false },
    });
    frames(2);
    const w = FakeWorker.created.at(-1) as FakeWorker;
    expect(FakeWorker.created).toHaveLength(1); // one worker: relay stays off
    expect(setSyncs(w)).toEqual([
      {
        k: "setSync",
        groupId: "g",
        modes: { time: true, crosshair: true, levels: false },
        relay: false,
      },
      {
        k: "setSync",
        groupId: "g",
        modes: { time: true, crosshair: false, levels: false },
        relay: false,
      },
    ]);
    expect(saidB).toEqual([
      { politeness: "polite", text: "Panes linked: time, crosshair", key: SYNC_ANNOUNCE_KEY },
    ]);
    b.setSyncGroup("g", { levels: true });
    a.setSyncGroup("g", { levels: true }); // the same group state: nothing said
    frames(40);
    expect(text(saidB)).toEqual([
      "Panes linked: time, crosshair",
      "Panes linked: time, crosshair, levels",
    ]);
    expect(saidA).toEqual([]);
    a.setSyncGroup(null);
    frames(40);
    expect(text(saidA)).toEqual(["Panes unlinked"]);
    expect(setSyncs(w).at(-1)).toMatchObject({ groupId: null });
    expect(() => a.setSyncGroup("")).toThrow(RangeError);
    expect(() => a.setSyncGroup("x".repeat(121))).toThrow(RangeError);
    expect(() => a.setSyncGroup("g", { time: "yes" } as never)).toThrow(RangeError);
    const bad = { container: asHtml(box([])), theme, syncGroup: 7 } as never;
    expect(() => createChart(bad)).toThrow(RangeError);
    a.dispose();
    a.setSyncGroup("g"); // disposed: a no-op
    b.dispose();
  });
});

describe("BQ-21: a group across two links relays through the registry", () => {
  it("test_workerAndInlineCharts_relayOn_workerSyncReachesTheInlineChart", () => {
    const { box } = page();
    const a = createChart({ container: asHtml(box([])), theme, syncGroup: "g" });
    const b = createChart({ container: asHtml(box([])), theme, syncGroup: "g", runMode: "inline" });
    frames(3);
    const w = FakeWorker.created.at(-1) as FakeWorker;
    expect(setSyncs(w).at(-1)).toMatchObject({ groupId: "g", relay: true });
    const init = (w.inbox as ToWorker[]).find((m) => m.t === "init");
    const worker = init?.t === "init" ? init.config.workerId : undefined;
    const ranges: [number, number][] = [];
    b.subscribe("viewportChanged", (v) => void ranges.push([v.timeStart, v.timeEnd]));
    const origin = { worker: worker ?? "", chart: 1, seq: 1 };
    w.onmessage?.({
      data: { t: "sync", id: 1, groupId: "g", timeRange: [6e9, 9e9], origin },
    });
    frames(3);
    expect(ranges.at(-1)?.[0]).toBeGreaterThan(0); // the inline chart took the relayed range
    expect((w.inbox as ToWorker[]).filter((m) => m.t === "sync")).toEqual([]); // never back
    a.dispose();
    b.dispose();
  });
});
