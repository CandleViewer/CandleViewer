import { mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { _electron as electron, chromium, expect, test, type Page } from "@playwright/test";
import { calibration } from "@candleviewer/config/perf-calibration";
import { ELECTRON_EGRESS_GUARD, ELECTRON_EGRESS_HITS } from "@candleviewer/fixtures/e2e";
import { MAIN_PERF_MARKS } from "../../src/main/perfMarks.js";
import {
  buildReport,
  toMarkdown,
  writeReport,
  type HostClass,
  type RunSample,
  type Target,
} from "./support/report";
import { NON_LOOPBACK, RESOLVER, REST, VERSION, WEB_ROOT } from "./support/shell";
import { startStubBackend, type StubBackend } from "./support/stubBackend";

// E10-Q04 PR-2 cold-start harness (budget #10; AC1, AC2, AC6; BQ-Q04-02/03/04/07/08). Per target:
// one discarded priming launch, then RUNS cold launches, each a new process with a fresh profile
// ("app-cold, OS-warm": the OS page cache is not dropped). Every stage is read back by exact name
// from the main timeline (`electronApp.evaluate`) and the renderer timeline (`page.evaluate`). The
// shell boots against a loopback stub (C-13.5); every other host is aborted or unresolvable.
// Recording only: the harness writes the report and never fails on the budget (`30` §4.4).

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MAIN_ENTRY = path.join(__dirname, "../../dist/main/index.js");
const REPORT_DIR =
  process.env["CV_PERF_REPORT_DIR"] ?? path.join(__dirname, "../../test-results/perf");
const RUNS = 10;
const STAGE_TIMEOUT_MS = 30_000;
const HOST: HostClass = process.env["CI"]
  ? "ci"
  : process.env["CV_PERF_HOST_CLASS"] === "reference"
    ? "reference"
    : "below-class";
/** apps/web's `SHELL_PERF_MARKS` (src/shell/perfMarks.ts), verbatim: this app may not import it. */
const RENDERER_STAGES = ["shell_bootstrap_ms", "ws_live", "route_mounted", "shell_cold_start_ms"];
const MAIN_STAGES: readonly string[] = Object.values(MAIN_PERF_MARKS);

interface Timeline {
  readonly origin: number;
  readonly marks: Readonly<Record<string, number>>;
}

/** The named stages of the renderer's timeline, once shell interactive is marked. */
async function rendererTimeline(page: Page): Promise<Timeline> {
  await page.waitForFunction(
    (name) => performance.getEntriesByName(name, "mark").length > 0,
    "shell_cold_start_ms",
    { timeout: STAGE_TIMEOUT_MS },
  );
  return page.evaluate((names) => {
    const marks: Record<string, number> = {};
    for (const name of names) {
      const entry = performance.getEntriesByName(name, "mark")[0];
      if (entry !== undefined) marks[name] = entry.startTime;
    }
    return { origin: performance.timeOrigin, marks };
  }, RENDERER_STAGES);
}

/** Every expected stage, by exact name; a missing one fails the run rather than skewing it. */
function stagesOf(expected: readonly string[], marks: Readonly<Record<string, number>>): RunSample {
  expect(Object.keys(marks).sort(), "a stage mark is missing").toEqual([...expected].sort());
  return marks;
}

function profileDir(): string {
  return mkdtempSync(path.join(os.tmpdir(), "cv-shell-perf-"));
}

async function electronRun(
  stub: StubBackend,
  versions: Record<string, string>,
): Promise<RunSample> {
  const profile = profileDir();
  const env: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) if (v !== undefined) env[k] = v;
  const app = await electron.launch({
    args: [MAIN_ENTRY, `--user-data-dir=${profile}`, "--lang=en-US", RESOLVER],
    env: {
      ...env,
      CV_DEV_SERVER_URL: stub.origin,
      CV_BACKEND_ORIGIN: stub.origin,
      XDG_CONFIG_HOME: profile,
    },
    chromiumSandbox: true,
  });
  try {
    await app.evaluate(({ app: a }) => a.whenReady());
    await app.evaluate(ELECTRON_EGRESS_GUARD);
    const renderer = await rendererTimeline(await app.firstWindow());
    const main = await app.evaluate((_electron, names) => {
      const marks: Record<string, number> = {};
      for (const name of names) {
        const entry = performance.getEntriesByName(name, "mark")[0];
        if (entry !== undefined) marks[name] = entry.startTime;
      }
      const v = process.versions;
      return {
        origin: performance.timeOrigin,
        marks,
        versions: { electron: v.electron ?? "", chrome: v.chrome ?? "", node: v.node },
      };
    }, MAIN_STAGES);
    Object.assign(versions, main.versions);
    expect(await app.evaluate(ELECTRON_EGRESS_HITS), "a request left the loopback").toEqual([]);
    // Renderer stages move onto the main timeline: t0 is the main process's start.
    const shift = renderer.origin - main.origin;
    const rendererOnMain = Object.fromEntries(
      Object.entries(renderer.marks).map(([k, v]) => [k, v + shift]),
    );
    return stagesOf([...MAIN_STAGES, ...RENDERER_STAGES], { ...main.marks, ...rendererOnMain });
  } finally {
    await app.close();
    rmSync(profile, { recursive: true, force: true });
  }
}

async function browserRun(stub: StubBackend, versions: Record<string, string>): Promise<RunSample> {
  const browser = await chromium.launch({ args: [RESOLVER, "--lang=en-US"] });
  try {
    versions["chromium"] = browser.version();
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const hits: string[] = [];
    await context.route(NON_LOOPBACK, (r) => {
      hits.push(new URL(r.request().url()).origin);
      return r.abort("blockedbyclient");
    });
    const page = await context.newPage();
    await page.goto(`${stub.origin}/`);
    const renderer = await rendererTimeline(page);
    expect(hits, "a request left the loopback").toEqual([]);
    return stagesOf(RENDERER_STAGES, renderer.marks);
  } finally {
    await browser.close();
  }
}

async function measure(target: Target, run: typeof electronRun): Promise<void> {
  const stub = await startStubBackend({ webRoot: WEB_ROOT, rest: REST, version: VERSION });
  try {
    const versions: Record<string, string> = { node: process.versions.node };
    await run(stub, versions); // priming launch, discarded
    const runs: RunSample[] = [];
    for (let i = 0; i < RUNS; i += 1) runs.push(await run(stub, versions));
    const report = buildReport({
      target,
      host: HOST,
      calibration: calibration(),
      versions,
      runs,
      unanswered: stub.unanswered(),
    });
    const [json] = writeReport(REPORT_DIR, report);
    console.log(
      `shell-perf ${JSON.stringify({ target, host: HOST, budget: report.budget, report: json })}`,
    );
    console.log(toMarkdown(report));
    await test
      .info()
      .attach(`${target}-cold-start.json`, { path: json, contentType: "application/json" });
  } finally {
    await stub.close();
  }
}

test.describe.configure({ mode: "serial" });

test("electron cold start: whenReady → shell interactive, 10 cold launches", async () => {
  test.setTimeout(15 * 60_000);
  await measure("electron", electronRun);
});

test("browser cold start: navigation → shell interactive, 10 cold launches", async () => {
  test.setTimeout(15 * 60_000);
  await measure("browser", browserRun);
});
