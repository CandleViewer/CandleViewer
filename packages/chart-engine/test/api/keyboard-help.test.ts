// E11-S04 PR 2: reduced motion follows the app's resolved mode both ways (BQ-104, C-22) and the
// keyboard help says so (BQ-105), on the fake DOM. The worker side is in runtime-input.test.ts.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart } from "../../src/api/chart.js";
import {
  KEY_HELP,
  readReducedMotion,
  REDUCED_MOTION_HELP,
  THEME_CHANGE_EVENT,
  watchMotion,
} from "../../src/host/motion.js";
import { createChartHost } from "../../src/worker/host.js";
import type { ToWorker } from "../../src/worker/protocol.js";
import { fakeEnv, FakeWorker } from "../worker/fake-worker.js";
import { asHtml, fakeContainer, FakeDocument, FakeElement } from "./fake-dom.js";

const asDoc = (d: FakeDocument): Document => d as unknown as Document;
const help = (root: FakeElement): FakeElement | undefined =>
  root.children.find((c) => c.attributes.has("data-cv-keyboard-help"));
const theme = (doc: FakeDocument, detail: unknown): boolean =>
  doc.dispatch(THEME_CHANGE_EVENT, { detail });

describe("Scenario: Inertia respects reduced-motion settings (the help text and the source)", () => {
  it("reads data-motion at mount and follows themechange both ways, once per change", () => {
    const doc = new FakeDocument();
    const root = new FakeElement("div", doc);
    expect(readReducedMotion(asDoc(doc))).toBe(false);
    doc.documentElement.setAttribute("data-motion", "reduce");
    const reduce = readReducedMotion(asDoc(doc));
    const seen: boolean[] = [];
    const detach = watchMotion(asDoc(doc), asHtml(root), reduce, (r) => void seen.push(r));
    expect(help(root)?.textContent).toBe(`${KEY_HELP} ${REDUCED_MOTION_HELP}`);
    theme(doc, { motion: "reduce" }); // no change
    theme(doc, { theme: "dark" }); // no motion field
    theme(doc, null);
    theme(doc, { motion: "safe" }); // the in-app override wins the other way too (C-22)
    expect(help(root)?.textContent).toBe(KEY_HELP);
    theme(doc, { motion: "reduce" });
    expect(seen).toEqual([false, true]);
    detach();
    expect([doc.listeners.get(THEME_CHANGE_EVENT)?.size, help(root)]).toEqual([0, undefined]);
  });

  it("the chart mounts the help in its DOM mirror and drops the listener on dispose", () => {
    vi.useFakeTimers();
    const container = fakeContainer(400, 300);
    const doc = container.ownerDocument;
    doc.documentElement.setAttribute("data-motion", "reduce");
    const chart = createChart({
      container: asHtml(container),
      theme: { palette: "default", convention: "standard", colors: {} },
    });
    const root = chart.getDomMirrorRoot() as unknown as FakeElement;
    expect(help(root)?.textContent).toContain(REDUCED_MOTION_HELP);
    theme(doc, { motion: "safe" });
    expect(help(root)?.textContent).not.toContain("Inertia");
    chart.dispose();
    expect(doc.listeners.get(THEME_CHANGE_EVENT)?.size).toBe(0);
    vi.useRealTimers();
  });
});

describe("the host carries the mode in init and posts setMotion (BQ-104)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWorker.created = [];
  });
  afterEach(() => vi.useRealTimers());

  it("init.reducedMotion at mount; a change is a command, not a retained one", () => {
    const doc = new FakeDocument();
    doc.offscreenAvailable = true;
    doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {} };
    const host = createChartHost({
      realm: doc,
      runMode: "worker",
      env: fakeEnv({ requestFrame: () => undefined }),
      canvas: () => asHtml(doc.createElement("canvas")) as HTMLCanvasElement,
      replaceCanvas: () => asHtml(doc.createElement("canvas")) as HTMLCanvasElement,
      dpr: 1,
      theme: {},
      syncGroup: null,
      bench: false,
      reducedMotion: true,
      listener: {
        deliver: () => undefined,
        lost: () => undefined,
        restored: () => undefined,
        resync: () => undefined,
      },
    });
    host.command({ k: "setMotion", reduce: false });
    vi.advanceTimersByTime(1);
    const inbox = (FakeWorker.created.at(-1)?.inbox ?? []) as ToWorker[];
    const init = inbox.find((m) => m.t === "init");
    expect(init !== undefined && "reducedMotion" in init && init.reducedMotion).toBe(true);
    expect(inbox.filter((m) => m.t === "command").map((m) => m.t === "command" && m.cmd)).toEqual([
      { k: "setMotion", reduce: false },
    ]);
    host.dispose();
  });
});
