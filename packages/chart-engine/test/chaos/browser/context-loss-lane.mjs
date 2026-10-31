#!/usr/bin/env node
// E11-Q04 browser lane (BQ-09): real `WEBGL_lose_context` in headless Chromium on SwiftShader,
// against the built engine. EVIDENCE ONLY: its timings are not deterministic, it gates nothing,
// it is not a pass for any Gherkin row, and software GL is not GPU evidence (E11-Q07 #519).
//
//   pnpm --filter @candleviewer/chart-engine build
//   node packages/chart-engine/test/chaos/browser/context-loss-lane.mjs > lane.json
//
// No new dependency: Playwright is resolved from apps/desktop, as bench/matrix/run-matrix.mjs
// does, and launched with the bench's pinned software-GL flags. The page is served from a local
// static server bound to the loopback interface; nothing is fetched from anywhere else.
// Each loss waits 250 ms before `restoreContext()`, so restoredMs (loss to first complete frame)
// includes that wait. Cases: loss and restore at idle and mid-pan, three losses inside 10 s, F-14's inline fallback
// (worker creation blocked; canvas transfer blocked) and, where the page is cross-origin
// isolated, the JS heap before and after 100 create / dispose cycles. Output: one JSON document.
import console from "node:console";
import { existsSync, readFileSync } from "node:fs";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { dirname, extname, join, normalize, resolve, sep } from "node:path";
import process from "node:process";
import { fileURLToPath, URL } from "node:url";
import { PINNED_CHROMIUM_FLAGS } from "../../../bench/report.mjs";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const REPO = resolve(PKG, "../..");
const DIST = join(PKG, "dist");
const MIME = { ".js": "text/javascript", ".map": "application/json", ".html": "text/html" };

// The page: mounts a chart, records every ChartEvents.error, and exposes the lane's levers.
const PAGE = `<!doctype html><meta charset="utf-8"><title>E11-Q04 lane</title>
<div id="box" style="width:600px;height:300px"></div>
<script type="module">
import { createChart } from "/dist/index.js";
const theme = { palette: "default", convention: "standard", colors: { "color.chart.background": "#0b0e11" } };
const box = document.getElementById("box");
const lane = { errors: [], chart: null, ext: null };
lane.mount = (runMode) => {
  lane.chart = createChart({ container: box, theme, ...(runMode && { runMode }) });
  lane.chart.subscribe("error", (e) => lane.errors.push({ at: performance.now(), code: e.code, message: e.message }));
  return lane.chart.runMode ?? null;
};
lane.lose = () => {
  const gl = box.querySelector("canvas").getContext("webgl2");
  lane.ext = gl.getExtension("WEBGL_lose_context");
  lane.ext.loseContext();
};
lane.restore = () => lane.ext.restoreContext();
lane.pan = (ms) => new Promise((done) => {
  const t0 = performance.now();
  const step = (t) => {
    const from = 1.7e15 + (t - t0) * 1e9;
    lane.chart.timeScale.setVisibleRange({ from, to: from + 3.6e12 });
    if (t - t0 < ms) requestAnimationFrame(step); else done();
  };
  requestAnimationFrame(step);
});
lane.cycles = async (n) => {
  for (let i = 0; i < n; i += 1) {
    const c = createChart({ container: box, theme, runMode: "inline" });
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    c.dispose();
  }
};
lane.heap = async () => {
  if (!globalThis.crossOriginIsolated || !performance.measureUserAgentSpecificMemory) {
    return { bytes: null, why: "not cross-origin isolated, or the API is absent" };
  }
  try {
    return { bytes: (await performance.measureUserAgentSpecificMemory()).bytes };
  } catch (e) {
    return { bytes: null, why: e.name + ": " + e.message };
  }
};
window.lane = lane;
window.laneReady = true;
</script>`;

function serve() {
  const server = createServer((req, res) => {
    const path = new URL(req.url ?? "/", "http://127.0.0.1").pathname;
    // Cross-origin isolation, so the heap can be measured without app changes (BQ-11).
    const headers = {
      "cache-control": "no-store",
      "cross-origin-opener-policy": "same-origin",
      "cross-origin-embedder-policy": "require-corp",
    };
    if (path === "/") {
      res.writeHead(200, { ...headers, "content-type": MIME[".html"] });
      res.end(PAGE);
      return;
    }
    const file = normalize(join(PKG, path));
    if (!file.startsWith(DIST + sep) || !existsSync(file)) {
      res.writeHead(404, headers);
      res.end();
      return;
    }
    res.writeHead(200, {
      ...headers,
      "content-type": MIME[extname(file)] ?? "application/octet-stream",
    });
    res.end(readFileSync(file));
  });
  return new Promise((ok) => server.listen(0, "127.0.0.1", () => ok(server)));
}

const desktopRequire = (id) => createRequire(join(REPO, "apps/desktop/package.json"))(id);
const wait = (page, ms) => page.waitForTimeout(ms);
const errors = (page) => page.evaluate("window.lane.errors");

/** Waits (up to `ms`) for `code` to appear `n` times; returns the errors seen. */
async function until(page, code, n, ms = 9000) {
  const end = Date.now() + ms;
  for (;;) {
    const seen = await errors(page);
    if (seen.filter((e) => e.code === code).length >= n || Date.now() > end) return seen;
    await wait(page, 50);
  }
}

/** The engine's own restore time from each RESTORED message ("Chart restored in N ms"). */
const restoredMs = (seen) =>
  seen.flatMap((e) => {
    const m = e.code === "ENGINE_CONTEXT_RESTORED" ? /([\d.]+) ms$/.exec(e.message) : null;
    return m ? [Math.round(Number(m[1]))] : [];
  });

async function fresh(browser, base, before) {
  const page = await browser.newPage({ viewport: { width: 800, height: 400 } });
  page.on("pageerror", (e) => console.error("[page]", e.message));
  if (before) await page.addInitScript(before);
  await page.goto(base);
  await page.waitForFunction("window.laneReady === true");
  return page;
}

/** `losses` loss / restore cycles; `block` (F-14) runs before the page, else inline is asked. */
async function lossCase(browser, base, { pan = false, losses = 1, block } = {}) {
  const page = await fresh(browser, base, block);
  // Inline (asked, or forced by the block): the page owns the context it loses.
  const runMode = await page.evaluate(
    block ? "window.lane.mount()" : "window.lane.mount('inline')",
  );
  await wait(page, 300);
  for (let k = 0; k < losses; k += 1) {
    const panning = pan ? page.evaluate("window.lane.pan(1200)") : Promise.resolve();
    await wait(page, pan ? 400 : 100);
    await page.evaluate("window.lane.lose()");
    await wait(page, 250);
    await page.evaluate("window.lane.restore()");
    await until(page, "ENGINE_CONTEXT_RESTORED", k + 1);
    await panning;
    if (losses > 1) await wait(page, 1500);
  }
  const seen = await errors(page);
  await page.close();
  const spanMs = seen.length > 0 ? Math.round(seen.at(-1).at - seen[0].at) : null;
  return { runMode, codes: seen.map((e) => e.code), restoredMs: restoredMs(seen), spanMs };
}

async function heapCase(browser, base) {
  const page = await fresh(browser, base);
  const start = await page.evaluate("window.lane.heap()");
  if (start.bytes === null) {
    await page.close();
    return { status: "pending", reason: start.why }; // no approximation from performance.memory
  }
  await page.evaluate("window.lane.cycles(100)");
  const end = await page.evaluate("window.lane.heap()");
  await page.close();
  const deltaPct = end.bytes === null ? null : ((end.bytes - start.bytes) / start.bytes) * 100;
  return { status: "measured", startBytes: start.bytes, endBytes: end.bytes, deltaPct };
}

async function main() {
  if (!existsSync(join(DIST, "index.js"))) {
    console.error(
      "dist/index.js missing: run `pnpm --filter @candleviewer/chart-engine build` first",
    );
    process.exit(2);
  }
  const { chromium } = desktopRequire("playwright");
  // The eager-memory flag only shortens measureUserAgentSpecificMemory's wait; GL stays pinned.
  const flags = [...PINNED_CHROMIUM_FLAGS, "--enable-blink-features=ForceEagerMeasureMemory"];
  const server = await serve();
  const base = `http://127.0.0.1:${server.address().port}/`;
  const browser = await chromium.launch({ headless: true, args: flags });
  const blockWorker = "window.Worker = function () { throw new Error('blocked by policy'); };";
  const blockTransfer =
    "HTMLCanvasElement.prototype.transferControlToOffscreen = function () { throw new Error('blocked'); };";
  try {
    const report = {
      lane: "E11-Q04 browser lane (evidence only)",
      versions: {
        chromium: browser.version(),
        playwright: desktopRequire("playwright/package.json").version,
        node: process.version,
      },
      flags,
      command: "node packages/chart-engine/test/chaos/browser/context-loss-lane.mjs",
      cases: {
        idle: await lossCase(browser, base),
        midPan: await lossCase(browser, base, { pan: true }),
        threeIn10s: await lossCase(browser, base, { losses: 3 }),
        f14WorkerBlocked: await lossCase(browser, base, { block: blockWorker }),
        f14TransferBlocked: await lossCase(browser, base, { block: blockTransfer }),
        heap100Cycles: await heapCase(browser, base),
      },
    };
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await browser.close();
    server.close();
  }
}

await main();
