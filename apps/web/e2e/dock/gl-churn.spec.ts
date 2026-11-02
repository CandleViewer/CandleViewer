import type { AddressInfo } from "node:net";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { build, preview, type PreviewServer } from "vite";
import { guardContextEgress, type EgressGuard } from "@candleviewer/fixtures/e2e";
import { PANE_IDS, STEP_NAMES, type GlCounters } from "./harness/api";
import { HARNESS_OUT } from "./harness/vite.config";

// E15-T02 (#403) "zero WebGL context creations per layout operation", level 3 of 3 (after the
// dock package's property test and the jsdom GL-churn test): in real Chromium, DockGrid with four
// real `<Chart>` panes (render worker + OffscreenCanvas) goes through every layout operation the
// packages/dock README guarantee names, and no canvas is transferred again, no WebGL context is
// created, none is lost, and every pane keeps its canvas node. A negative control re-keys one
// pane's chart and proves the counters see a recreation. The harness page is e2e-only: built here
// into the git-ignored test-results/ and previewed on a loopback port, never in `dist/`.

const HARNESS_CONFIG = resolve(import.meta.dirname, "harness/vite.config.ts");

/** SwiftShader is slower than a GPU: the engine's frame-budget warning says nothing about churn. */
const TOLERATED_ERRORS = new Set(["ENGINE_FRAME_BUDGET_EXCEEDED"]);

let server: PreviewServer;
let origin: string;

test.beforeAll(async ({ browserName }, workerInfo) => {
  test.setTimeout(120_000);
  expect(browserName).toBe("chromium");
  // One output folder per worker: a retry or a repeat in another worker never empties this one.
  const outDir = `${HARNESS_OUT}-${workerInfo.workerIndex}`;
  await build({ configFile: HARNESS_CONFIG, build: { outDir } });
  server = await preview({ configFile: HARNESS_CONFIG, build: { outDir }, preview: { port: 0 } });
  const address = server.httpServer.address() as AddressInfo;
  origin = `http://127.0.0.1:${address.port}`;
});

test.afterAll(async () => {
  await server?.close();
});

/** Wraps the canvas entry points before any page script runs (the page's realm only). */
function installCounters(): void {
  const counters: GlCounters = {
    offscreenTransfers: 0,
    webglContexts: 0,
    contextsLost: 0,
    workers: 0,
  };
  window.__glCounters = counters;
  const proto = HTMLCanvasElement.prototype;
  const transfer = proto.transferControlToOffscreen;
  proto.transferControlToOffscreen = function (this: HTMLCanvasElement): OffscreenCanvas {
    counters.offscreenTransfers += 1;
    return transfer.call(this);
  };
  const getContext = proto.getContext as (...args: unknown[]) => unknown;
  const counted = function (this: HTMLCanvasElement, ...args: unknown[]): unknown {
    if (typeof args[0] === "string" && args[0].startsWith("webgl")) counters.webglContexts += 1;
    return getContext.apply(this, args);
  };
  proto.getContext = counted as typeof proto.getContext;
  document.addEventListener("webglcontextlost", () => void (counters.contextsLost += 1), true);
  const NativeWorker = window.Worker;
  window.Worker = class extends NativeWorker {
    constructor(url: string | URL, options?: WorkerOptions) {
      super(url, options);
      counters.workers += 1;
    }
  };
}

const counters = (page: Page): Promise<GlCounters> =>
  page.evaluate(() => {
    if (window.__glCounters === undefined) throw new Error("counters not installed");
    return { ...window.__glCounters };
  });

/** Two animation frames: React has committed and the engine has had a frame to react. */
const settle = (page: Page): Promise<void> =>
  page.evaluate(
    () =>
      new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done()))),
  );

/** Tags each pane's chart canvas so a later read can check it is the same node. */
const tagCanvases = (page: Page): Promise<number> =>
  page.evaluate(() => {
    const nodes = document.querySelectorAll<HTMLCanvasElement>(
      "[data-harness-pane] canvas[data-cv-chart-canvas]",
    );
    const keep = new Map<string, HTMLCanvasElement>();
    for (const c of nodes) {
      const pane = c.closest<HTMLElement>("[data-harness-pane]")?.dataset["harnessPane"];
      if (pane !== undefined) keep.set(pane, c);
    }
    Reflect.set(window, "__canvasesBefore", keep);
    return keep.size;
  });

/** The panes whose chart canvas is no longer the node tagged by `tagCanvases`. */
const replacedCanvases = (page: Page): Promise<string[]> =>
  page.evaluate(() => {
    const keep = Reflect.get(window, "__canvasesBefore") as Map<string, HTMLCanvasElement>;
    const out: string[] = [];
    for (const [pane, canvas] of keep) {
      const now = document.querySelector(
        `[data-harness-pane="${pane}"] canvas[data-cv-chart-canvas]`,
      );
      if (now !== canvas || !canvas.isConnected) out.push(pane);
    }
    return out;
  });

/** Visible panes (mounted in a dock slot) whose box has no area: a docked chart must fill its cell. */
const emptyVisiblePanes = (page: Page): Promise<string[]> =>
  page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>(".cv-dock-slot [data-harness-pane]")]
      .filter((el) => {
        const box = el.getBoundingClientRect();
        return box.width < 1 || box.height < 1;
      })
      .map((el) => el.dataset["harnessPane"] ?? ""),
  );

let egress: EgressGuard;

async function mountHarness(page: Page): Promise<GlCounters> {
  egress = await guardContextEgress(page.context());
  await page.addInitScript(installCounters);
  await page.goto(`${origin}/index.html`);
  await page.waitForFunction(() => window.__dockHarness !== undefined);
  // Every pane has drawn at least once: the charts are live before anything is counted.
  await expect
    .poll(() => page.evaluate(() => Object.keys(window.__dockHarness?.frames() ?? {}).length))
    .toBe(PANE_IDS.length);
  await settle(page);
  expect(await tagCanvases(page)).toBe(PANE_IDS.length);
  return counters(page);
}

test.afterEach(() => {
  expect(egress.hits()).toEqual([]);
});

test("every layout operation: zero offscreen transfers, zero WebGL contexts, zero losses, same canvases", async ({
  page,
}) => {
  const mounted = await mountHarness(page);
  // One transfer per chart pane: each canvas went to the render worker once.
  expect(mounted.offscreenTransfers).toBe(PANE_IDS.length);
  expect(mounted.contextsLost).toBe(0);
  const profiles = await page.evaluate(() => window.__dockHarness?.frames());
  test
    .info()
    .annotations.push(
      { type: "after mount", description: JSON.stringify(mounted) },
      { type: "render profiles", description: JSON.stringify(profiles) },
    );

  for (const step of STEP_NAMES) {
    expect(await page.evaluate((s) => window.__dockHarness?.run(s), step), step).toBe(true);
    await settle(page);
    expect({ step, ...(await counters(page)) }).toEqual({ step, ...mounted });
    expect(await replacedCanvases(page), step).toEqual([]);
    expect(await emptyVisiblePanes(page), step).toEqual([]);
  }

  // A window resize too: every visible pane's container changes size.
  await page.setViewportSize({ width: 900, height: 600 });
  await settle(page);
  expect({ step: "viewport resize", ...(await counters(page)) }).toEqual({
    step: "viewport resize",
    ...mounted,
  });
  expect(await replacedCanvases(page)).toEqual([]);
  // The charts are still alive: each visible pane's worker renders it into an image (a lost
  // context rejects, and reports through the engine's `error` event).
  const visible = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>(".cv-dock-slot [data-harness-pane]")].map(
      (el) => el.dataset["harnessPane"] ?? "",
    ),
  );
  expect(visible.length).toBeGreaterThan(0);
  for (const pane of visible) {
    const bytes = await page.evaluate((p) => window.__dockHarness?.screenshot(p), pane);
    expect(bytes, pane).toBeGreaterThan(0);
  }
  expect({ step: "after screenshots", ...(await counters(page)) }).toEqual({
    step: "after screenshots",
    ...mounted,
  });
  // No engine error but the frame-budget warning a software renderer may raise: a context loss,
  // a restore, a worker loss or a missing WebGL2 all arrive here.
  const errors = Object.values(await page.evaluate(() => window.__dockHarness?.errors() ?? {}));
  expect(errors.flat().filter((code) => !TOLERATED_ERRORS.has(code))).toEqual([]);
  expect(await page.evaluate(() => window.__dockHarness?.panes().sort())).toEqual([...PANE_IDS]);
});

test("negative control: re-keying one pane's chart is seen as a new transfer and a new canvas", async ({
  page,
}) => {
  const mounted = await mountHarness(page);
  await page.evaluate(() => window.__dockHarness?.remount("b"));
  await settle(page);
  const after = await counters(page);
  test.info().annotations.push({ type: "after remount", description: JSON.stringify(after) });
  expect(after.offscreenTransfers).toBe(mounted.offscreenTransfers + 1);
  expect(await replacedCanvases(page)).toEqual(["b"]);
});
