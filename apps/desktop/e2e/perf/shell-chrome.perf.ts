import { execFileSync } from "node:child_process";
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, expect, test, type Browser, type BrowserContextOptions } from "@playwright/test";
import { calibration } from "@candleviewer/config/perf-calibration";
import { IN_PAGE } from "./support/inPage";
import { nearestRank, type HostClass } from "./support/report";
import { NON_LOOPBACK, RESOLVER, REST, VERSION, WEB_ROOT } from "./support/shell";
import { startStubBackend, type StubBackend } from "./support/stubBackend";

// E10-Q04 PR-3 (#303; AC3, AC4; BQ-Q04-05/06 ruled as proposed with the critic corrections): the
// route-change bench over the seven rail routes, the rail transition traced over CDP, and the
// browser twin of status-bar-isolation.test.tsx, in Chromium against PR-2's loopback stub
// (C-13.5). Timings are recorded (`30` §4.4); only a reference-class host is held to 120 ms.

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPORT_DIR =
  process.env["CV_PERF_REPORT_DIR"] ?? path.join(__dirname, "../../test-results/perf");
const PROBE_ROOT = path.join(WEB_ROOT, "../node_modules/.cache/cv-perf-probe-dist");
const PROBE_MARKER = "__cvPerfProbe"; // perfProbe.tsx's window key
/** The Profiler `onRender` read: in react-dom's profiling build only, never its production one. */
const PROFILING_MARKER = ".onRender";
const HOST: HostClass = process.env["CI"]
  ? "ci"
  : process.env["CV_PERF_HOST_CLASS"] === "reference"
    ? "reference"
    : "below-class";
/** R-100, R-160, R-180, R-170, R-190, R-200, R-300 in rail order (`navItems.ts`, owner). */
const ROUTES = ["/terminal", "/rules", "/journal", "/replay", "/alerts", "/settings", "/admin"];
const REPEATS = 20;
const RAIL_LIMIT_MS = 120; // `14` SCR-011
// The measured span runs from the click to `finished`, so it carries up to one frame of start
// latency the declared duration does not: a reference host gets that one frame (60 Hz) on top.
const FRAME_MS = 17;
const INSTANT_MS = 0.01; // reduced motion: `theme.css` clamps every transition to 0.01 ms (D04)

let browser: Browser;
test.describe.configure({ mode: "serial" });
test.beforeAll(async () => {
  const args = [RESOLVER, "--lang=en-US", "--enable-unsafe-swiftshader"]; // software WebGL2
  browser = await chromium.launch({ args });
});
test.afterAll(async () => browser.close());

/** A signed-in, interactive shell with `cvBench` installed; every non-loopback request aborted. */
async function shell(stub: StubBackend, at: string, options: BrowserContextOptions = {}) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, ...options });
  const hits: string[] = [];
  await context.route(NON_LOOPBACK, (r) => {
    hits.push(new URL(r.request().url()).origin);
    return r.abort("blockedbyclient");
  });
  await context.addInitScript(IN_PAGE);
  const page = await context.newPage();
  await page.goto(`${stub.origin}${at}`);
  await page.waitForFunction(`performance.getEntriesByName("shell_cold_start_ms").length > 0`);
  const run = <T>(expr: string): Promise<T> => page.evaluate(expr) as Promise<T>;
  const close = async (): Promise<void> => {
    expect(hits, "a request left the loopback").toEqual([]);
    await context.close();
  };
  return { page, run, close };
}

function save(name: string, data: Record<string, unknown>): void {
  mkdirSync(REPORT_DIR, { recursive: true });
  const body = {
    schema: "cv-shell-chrome-report/1",
    host: HOST,
    calibration: calibration(),
    ...data,
  };
  writeFileSync(path.join(REPORT_DIR, `${name}.json`), `${JSON.stringify(body, null, 2)}\n`);
  console.log(`shell-perf ${name} ${JSON.stringify(data)}`);
}

const pct = (v: readonly number[]) => ({
  n: v.length,
  p50: nearestRank(v, 50),
  p95: nearestRank(v, 95),
});
type Nav = { ms: number; jsBytes: number };
const go = (route: string) => `cvBench.navigate(${JSON.stringify(route)})`;

test("route change: first and repeat visits over the seven rail routes", async () => {
  test.setTimeout(10 * 60_000);
  const stub = await startStubBackend({ webRoot: WEB_ROOT, rest: REST, version: VERSION });
  try {
    // First visit: a fresh page per route, so a lazy chunk (none yet, BQ-05 A) would show in jsBytes.
    const first: Record<string, Nav> = {};
    for (const [i, route] of ROUTES.entries()) {
      const s = await shell(stub, ROUTES[(i + 1) % ROUTES.length] ?? "/");
      first[route] = await s.run<Nav>(go(route));
      await s.close();
    }
    const s = await shell(stub, "/settings");
    for (const route of ROUTES) await s.run(go(route)); // every route visited once
    const repeat = new Map(ROUTES.map((r) => [r, [] as number[]]));
    for (let lap = 0; lap < REPEATS; lap += 1)
      for (const route of ROUTES) repeat.get(route)?.push((await s.run<Nav>(go(route))).ms);
    await s.close();
    save("route-change", {
      metric: "shell_route_change_ms",
      routes: ROUTES.map((r) => ({ route: r, first: first[r], repeat: pct(repeat.get(r) ?? []) })),
      first: pct(Object.values(first).map((f) => f.ms)),
      repeat: pct([...repeat.values()].flat()),
      unanswered: stub.unanswered(),
    });
  } finally {
    await stub.close();
  }
});

type TraceEvent = { name: string; cat: string; ts: number; dur?: number; pid: number };

/**
 * Per toggle, E10-D04 R-2 (PROPOSED; ruled as the reading of AC4): layouts during the frames, and
 * at the boundary frames (from the click to the second frame, and from the first frame at or after
 * the animations finished to the end). `scriptMsPerFrame` sums every FunctionCall in the window,
 * the bench's own rAF loop and promise continuations included: an upper bound, recorded only.
 */
function perToggle(events: readonly TraceEvent[]) {
  const marks = events.filter((e) => e.cat.includes("user_timing") && e.name.startsWith("cv-rail"));
  const pid = marks[0]?.pid;
  const of = (name: string) => events.filter((e) => e.name === name && e.pid === pid);
  const counts = [];
  for (const [i, start] of marks.entries()) {
    if (start.name !== "cv-rail-start") continue;
    const end = marks.slice(i).find((m) => m.name === "cv-rail-end")?.ts ?? Infinity;
    const frames = marks.filter((m) => m.name === "cv-rail-frame" && m.ts > start.ts && m.ts < end);
    const finished = marks.slice(i).find((m) => m.name === "cv-rail-finished")?.ts ?? end;
    const [from, to] = [frames[1]?.ts ?? end, frames.find((f) => f.ts >= finished)?.ts ?? end];
    const during = (e: TraceEvent) => e.ts >= from && e.ts < to;
    const layouts = of("Layout").filter((e) => e.ts >= start.ts && e.ts <= end);
    const scriptUs = of("FunctionCall")
      .filter(during)
      .reduce((n, e) => n + (e.dur ?? 0), 0);
    counts.push({
      traceFrames: frames.length,
      during: layouts.filter(during).length,
      boundary: layouts.filter((e) => !during(e)).length,
      scriptMsPerFrame: scriptUs / 1000 / Math.max(1, frames.length), // D04: ≤ 1 ms; an upper bound
    });
  }
  return counts;
}

const MODES: readonly { name: string; options: BrowserContextOptions; reduce: boolean }[] = [
  { name: "column", options: { reducedMotion: "no-preference" }, reduce: false },
  {
    name: "overlay",
    options: { viewport: { width: 600, height: 800 }, reducedMotion: "no-preference" },
    reduce: false,
  },
  { name: "reduce-os", options: { reducedMotion: "reduce" }, reduce: true },
  { name: "reduce-in-app", options: { reducedMotion: "no-preference" }, reduce: true },
];
type Toggle = {
  measuredMs: number;
  declaredMs: number;
  animations: number;
  frames: number;
  durationsMs: number[];
};

test("rail transition: no layout during its frames, one at most at the boundary, GL kept", async () => {
  test.setTimeout(5 * 60_000);
  const stub = await startStubBackend({ webRoot: WEB_ROOT, rest: REST, version: VERSION });
  const results: Record<string, unknown>[] = [];
  try {
    for (const mode of MODES) {
      const s = await shell(stub, "/settings", mode.options);
      if (mode.name === "reduce-in-app") await s.page.keyboard.press("Control+Shift+M");
      const motion = expect(s.page.locator("html"));
      await (mode.reduce ? motion : motion.not).toHaveAttribute("data-motion", "reduce");
      expect(await s.run("cvBench.glProbe()"), "a WebGL2 context for the probe canvas").toBe(true);
      await browser.startTracing(s.page, {
        categories: ["devtools.timeline", "blink.user_timing"],
      });
      const toggles = [await s.run<Toggle>("cvBench.toggleRail()")];
      toggles.push(await s.run<Toggle>("cvBench.toggleRail()"));
      const trace = JSON.parse((await browser.stopTracing()).toString("utf8")) as {
        traceEvents: TraceEvent[];
      };
      const counts = perToggle(trace.traceEvents);
      expect(counts).toHaveLength(2);
      for (const [i, t] of toggles.entries()) {
        const c = counts[i];
        results.push({ mode: mode.name, ...t, ...c });
        expect(c?.during, `${mode.name}: layouts during the transition`).toBe(0);
        expect(c?.boundary, `${mode.name}: layouts at the boundary`).toBeLessThanOrEqual(1);
        if (mode.reduce) {
          expect(t.durationsMs.length, `${mode.name}: rail label transitions read`).toBeGreaterThan(
            0,
          );
          expect(Math.max(...t.durationsMs)).toBeLessThanOrEqual(INSTANT_MS);
          continue;
        }
        // Each guard below keeps the duration and layout asserts from passing on nothing measured.
        expect(t.animations, `${mode.name}: rail animations found`).toBeGreaterThan(0);
        expect(t.declaredMs, `${mode.name}: declared duration`).toBeGreaterThan(0);
        expect(t.declaredMs).toBeLessThanOrEqual(RAIL_LIMIT_MS);
        expect(t.frames, `${mode.name}: frames looped`).toBeGreaterThanOrEqual(2);
        expect(c?.traceFrames, `${mode.name}: frames traced`).toBeGreaterThanOrEqual(2);
        if (HOST === "reference")
          expect(t.measuredMs).toBeLessThanOrEqual(RAIL_LIMIT_MS + FRAME_MS);
      }
      const gl = await s.run("cvBench.glState()");
      expect(gl, "the canvas kept and its context alive").toEqual({
        attached: true,
        lost: 0,
        contextLost: false,
      });
      await s.close();
    }
  } finally {
    await stub.close();
    save("rail-transition", { limitMs: RAIL_LIMIT_MS, toggles: results });
  }
});

/** The JS files under `dir` that hold `text` (source maps carry the sources, so they are skipped). */
const holding = (dir: string, text: string): string[] =>
  readdirSync(dir, { recursive: true, withFileTypes: true })
    .filter((e) => e.isFile() && /\.m?js$/.test(e.name))
    .filter((e) => readFileSync(path.join(e.parentPath, e.name), "utf8").includes(text))
    .map((e) => e.name);

test("status chips at 1 Hz for 60 s re-render neither the shell nor the outlet", async () => {
  test.setTimeout(10 * 60_000);
  expect(holding(WEB_ROOT, PROBE_MARKER), "the counter in the production build").toEqual([]);
  execFileSync("pnpm", ["exec", "vite", "build", "--outDir", PROBE_ROOT, "--emptyOutDir"], {
    cwd: path.dirname(WEB_ROOT),
    env: { ...process.env, CV_PERF_PROBE: "1" },
    stdio: "inherit",
  });
  expect(holding(PROBE_ROOT, PROBE_MARKER), "the probe build's counter").not.toEqual([]);
  expect(holding(PROBE_ROOT, PROFILING_MARKER), "profiling react-dom: commits counted").not.toEqual(
    [],
  );
  const stub = await startStubBackend({ webRoot: PROBE_ROOT, rest: REST, version: VERSION });
  let report: Record<string, unknown> = { error: "no counts read" };
  try {
    const s = await shell(stub, "/settings");
    const counts = () => s.run<Record<string, number>>(`({ ...window.${PROBE_MARKER} })`);
    await s.run("cvBench.watchChrome()");
    const base = await counts();
    await s.page.waitForFunction("window.cvChrome.ticks >= 60", undefined, { timeout: 120_000 });
    const end = await counts();
    const delta = (k: string): number => (end[k] ?? 0) - (base[k] ?? 0);
    const { ticks, said } = await s.run<{ ticks: number; said: number }>("window.cvChrome");
    const [shellRenders, outlet, status] = [delta("shell"), delta("outlet"), delta("status")];
    report = { ticks, shell: shellRenders, outlet, status, announcements: said };
    expect(outlet, "outlet commits").toBe(0);
    expect(shellRenders, "shell renders").toBe(0);
    // The baseline read may race one tick, so one commit of slack against the ticks seen.
    expect(status, "status-bar commits: the chips did tick").toBeGreaterThanOrEqual(ticks - 1);
    await s.close();
  } finally {
    await stub.close();
    save("chip-isolation", report);
  }
});
