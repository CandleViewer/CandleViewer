#!/usr/bin/env node
// E06-T01 — one-command matrix driver for ONE runtime.
//
//   node bench/matrix/run-matrix.mjs --runtime chromium|electron|tauri [options]
//
// Runs B1,B2,B3,B4,B5,B7,B9,B10 x N repetitions (B10 soak once) against the SAME page,
// seed and fixture on every runtime and writes reports/matrix/<runtime>-<timestamp>.json
// with seed + fixture sha256 + the full version manifest. Medians of p95 per 06-... §7.4.
//
// Options:
//   --runtime <r>        chromium | electron | tauri (required)
//   --reps <n>           repetitions per scenario (default 3)
//   --scenarios <list>   default B1,B2,B3,B4,B5,B7,B9,B10
//   --seed <s>           default 20260928 (K01 default)
//   --bars <n>           fixture bars (default 100000 = the M0 fixture; smaller = smoke only)
//   --duration-ms <n>    per-repetition logical duration (default 20000)
//   --soak-ms <n>        B10 duration (default 1800000 = 30 min)
//   --flagset <name>     electron only: default | tuned (see electron/flagsets.cjs)
//   --cotenancy          label the run as the co-tenancy variant (dev stack running)
//   --out-dir <dir>      default <repo>/reports/matrix
//   --dry-run            no browser: validate B5 composition + B7 logic, emit the manifest
//   --headed             chromium only: show the window
import { createServer } from "node:http";
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { spawn, execFileSync } from "node:child_process";
import { dirname, join, normalize, resolve, extname, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import {
  captureVersionManifest,
  assertDescriptorComplete,
  missingManifestFields,
} from "../machine.mjs";
import { PINNED_CHROMIUM_FLAGS } from "../report.mjs";
import { generateM0Fixture, hashFixture } from "../fixtures/index.mjs";
import { SceneB5, B5_GATES } from "./scenes/b5-combined.mjs";
import { encodeMessage, StormStores, evaluateStorm, STORM } from "./scenes/b7-storm.mjs";
import { mulberry32 } from "../fixtures/rng.mjs";
import { percentile } from "../stats.mjs";
import { buildDriverScript } from "../driver.mjs";
import {
  MATRIX_SCENARIOS,
  RUNTIMES,
  REPORT_SCHEMA,
  DONE_GRACE_MS,
  cellsComplete,
  summariseCell,
} from "./matrix-lib.mjs";
import { ELECTRON_FLAGSETS } from "./electron/flagsets.cjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const BENCH = resolve(HERE, "..");
const REPO = resolve(BENCH, "../../..");

export function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (!a.startsWith("--")) continue;
    const eq = a.indexOf("=");
    if (eq !== -1) out[a.slice(2, eq)] = a.slice(eq + 1);
    else if (argv[i + 1] && !argv[i + 1].startsWith("--")) out[a.slice(2)] = argv[(i += 1)];
    else out[a.slice(2)] = "true";
  }
  return out;
}

const MIME = {
  ".mjs": "text/javascript",
  ".js": "text/javascript",
  ".html": "text/html",
  ".json": "application/json",
};

/** Loopback harness server: static bench files, token JSON, result sink. */
function startServer(state) {
  const server = createServer((req, res) => {
    const url = new URL(req.url ?? "/", "http://127.0.0.1");
    if (req.method === "POST") {
      const chunks = [];
      req.on("data", (c) => chunks.push(c));
      req.on("end", () => {
        let body = {};
        try {
          body = JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
        } catch {
          /* ignore */
        }
        if (url.pathname === "/result") state.onResult(body);
        else if (url.pathname === "/done") state.onDone(body);
        else if (url.pathname === "/shell-metrics") state.onShellMetrics(body);
        res.writeHead(204).end();
      });
      return;
    }
    let file;
    if (url.pathname === "/matrix/page/matrix.html") state.onPageRequest(url.searchParams);
    if (url.pathname.startsWith("/tokens/")) {
      file = join(REPO, "packages/ui/tokens", url.pathname.slice("/tokens/".length));
    } else {
      file = join(BENCH, url.pathname);
    }
    file = normalize(file);
    const allowed = [BENCH + sep, join(REPO, "packages/ui/tokens") + sep];
    if (!allowed.some((r) => file.startsWith(r)) || !existsSync(file)) {
      res.writeHead(404).end("not found");
      return;
    }
    let data = readFileSync(file);
    const ext = extname(file);
    if (ext === ".mjs") {
      // Browser shims for the three node: modules heatmap-lut.mjs imports for token loading.
      data = Buffer.from(
        data
          .toString("utf8")
          .replace(/from "node:(fs|url|path)"/g, 'from "/matrix/page/shims/node-$1.mjs"'),
      );
    }
    res.writeHead(200, {
      "content-type": MIME[ext] ?? "application/octet-stream",
      "cache-control": "no-store",
    });
    res.end(data);
  });
  return new Promise((ok) => server.listen(0, "127.0.0.1", () => ok(server)));
}

/** Resolve a dependency from apps/desktop (which already pins playwright + electron). */
function desktopRequire(id) {
  return createRequire(join(REPO, "apps/desktop/package.json"))(id);
}

function sampleWorkingSetMb(names) {
  if (process.platform !== "win32" || names.length === 0) return null;
  try {
    const out = execFileSync(
      "powershell.exe",
      [
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        `(Get-Process -Name ${names.join(",")} -ErrorAction SilentlyContinue | Measure-Object WorkingSet64 -Sum).Sum`,
      ],
      { encoding: "utf8", timeout: 10_000 },
    );
    const v = Number(out.trim());
    return Number.isFinite(v) && v > 0 ? Math.round(v / 1048576) : null;
  } catch {
    return null;
  }
}

/** Offline validation of everything that does not need a GPU/browser. */
export async function dryRunChecks({ seed, bars }) {
  const fixture = generateM0Fixture({ seed, barCount: bars });
  const scene = new SceneB5({ seed: typeof seed === "number" ? seed : 20260928 });
  scene.init(fixture);
  const script = buildDriverScript({ scenario: "B5", durationMs: 1000, sampleHz: 60 });
  let maxDraw = 0;
  let maxFrame = 0;
  for (const ev of script) {
    scene.step(ev.tMs, ev);
    const s = scene.stats();
    maxDraw = Math.max(maxDraw, s.drawCalls);
    maxFrame = Math.max(maxFrame, s.frameTimeMs);
  }
  const composition = scene.describe();
  scene.dispose();
  // B7 logic: encode -> decode -> zero drops, on a fake clock-free pass.
  const rng = mulberry32(1);
  const stores = new StormStores();
  const seqs = new Int32Array(STORM.storeCount);
  const decodeMs = [];
  let sent = 0;
  for (let n = 0; n < 200; n += 1) {
    for (let s = 0; s < STORM.storeCount; s += 1) {
      const buf = encodeMessage(rng, s, seqs[s]++);
      sent += 1;
      const t = performance.now();
      stores.decodeAndApply(buf);
      decodeMs.push(performance.now() - t);
    }
  }
  const storm = evaluateStorm(
    { sent, applied: stores.applied, gaps: stores.gaps, duplicates: stores.duplicates, decodeMs },
    percentile,
  );
  const problems = [];
  if (maxDraw > B5_GATES.maxDrawCalls)
    problems.push(`B5 draw calls ${maxDraw} > ${B5_GATES.maxDrawCalls}`);
  if (composition.indicatorSeries !== 3 || composition.orderLines !== 50)
    problems.push("B5 composition drift");
  if (!storm.pass) problems.push(`B7 logic failed: ${JSON.stringify(storm)}`);
  return {
    composition,
    maxDrawCalls: maxDraw,
    modelledMaxFrameMs: maxFrame,
    storm,
    fixtureFnv1a: hashFixture(fixture),
    problems,
  };
}

async function launchChromium(url, args) {
  const { chromium } = desktopRequire("playwright");
  const browser = await chromium.launch({
    headless: args.headed !== "true",
    args: [...PINNED_CHROMIUM_FLAGS],
  });
  const page = await browser.newPage({ viewport: { width: 1700, height: 1000 } });
  page.on("pageerror", (e) => console.error("[page]", e.message));
  await page.goto(url);
  return {
    versions: {
      chromium: browser.version(),
      playwright: desktopRequire("playwright/package.json").version,
    },
    flagSet: {
      name: "pinned-K01 (software GL; override with a real-GPU set on the reference machine, see README)",
      flags: [...PINNED_CHROMIUM_FLAGS],
    },
    memNames: ["chrome", "headless_shell", "chrome-headless-shell"],
    close: () => browser.close(),
  };
}

function launchElectron(url, args) {
  const electronBin = desktopRequire("electron");
  const flagset = args.flagset ?? "default";
  const def = ELECTRON_FLAGSETS[flagset];
  if (!def)
    throw new Error(
      `unknown --flagset ${flagset}; known: ${Object.keys(ELECTRON_FLAGSETS).join(", ")}`,
    );
  const child = spawn(electronBin, [join(HERE, "electron/main.cjs")], {
    stdio: "inherit",
    env: {
      ...process.env,
      CV_MATRIX_URL: url,
      CV_MATRIX_FLAGSET: flagset,
      ELECTRON_ENABLE_LOGGING: "1",
    },
  });
  return {
    flagSet: { name: `electron-${flagset}`, flags: def.flags },
    memNames: ["electron"],
    close: () => child.kill(),
    exited: new Promise((r) => child.on("exit", r)),
  };
}

function launchTauri(url) {
  const manifest = join(HERE, "tauri/src-tauri/Cargo.toml");
  const child = spawn("cargo", ["run", "--release", "--manifest-path", manifest], {
    stdio: "inherit",
    env: { ...process.env, CV_MATRIX_URL: url },
    shell: process.platform === "win32",
  });
  return {
    flagSet: { name: "webview2-default (no GPU flags; WebView2 owns them)", flags: [] },
    memNames: ["candleviewer-matrix", "msedgewebview2"],
    close: () => child.kill(),
    exited: new Promise((r) => child.on("exit", r)),
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const runtime = args.runtime;
  if (!RUNTIMES.includes(runtime)) {
    console.error(`--runtime must be one of ${RUNTIMES.join("|")}`);
    process.exit(2);
  }
  const scenarios = (args.scenarios ?? MATRIX_SCENARIOS.join(",")).split(",");
  const bad = scenarios.filter((s) => !MATRIX_SCENARIOS.includes(s));
  if (bad.length) {
    console.error(`unknown scenario(s): ${bad.join(",")}`);
    process.exit(2);
  }
  const cfg = {
    reps: Number(args.reps ?? 3),
    seed: args.seed ?? "20260928",
    bars: Number(args.bars ?? 100_000),
    durationMs: Number(args["duration-ms"] ?? 20_000),
    soakMs: Number(args["soak-ms"] ?? 30 * 60_000),
  };
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const outDir = resolve(args["out-dir"] ?? join(REPO, "reports/matrix"));
  mkdirSync(outDir, { recursive: true });
  const outPath = join(outDir, `${runtime}-${stamp}.json`);

  if (args["dry-run"] === "true") {
    const checks = await dryRunChecks({ seed: cfg.seed, bars: Math.min(cfg.bars, 5000) });
    const manifest = captureVersionManifest({
      runtime,
      versions: {},
      flagSet: { name: "dry-run", flags: [] },
    });
    const report = { schema: REPORT_SCHEMA, dryRun: true, runtime, manifest, config: cfg, checks };
    writeFileSync(outPath, JSON.stringify(report, null, 2) + "\n");
    console.log(`[matrix] dry-run ${checks.problems.length ? "FAILED" : "ok"} -> ${outPath}`);
    for (const p of checks.problems) console.error("  -", p);
    process.exit(checks.problems.length ? 1 : 0);
  }

  const state = {
    results: [],
    preamble: null,
    shellQuery: null,
    shellMetrics: [],
    done: null,
    onResult(b) {
      if (b.kind === "preamble") this.preamble = b;
      else if (b.kind === "cell") {
        this.results.push(b);
        console.log(`[matrix] ${runtime} ${b.scenario} ${b.notRunnable ? "NOT RUNNABLE" : "done"}`);
        if (cellsComplete(this.results, scenarios)) this.onCellsComplete();
      } else this.results.push(b);
    },
    onCellsComplete: () => {},
    onPageRequest(q) {
      this.shellQuery ??= Object.fromEntries(q.entries());
    },
    onShellMetrics(b) {
      this.shellMetrics.push(b);
    },
    onDone: () => {},
  };
  const donePromise = new Promise((ok) => {
    state.onDone = ok;
  });
  // Every requested cell is in: a page that never sends `/done` cannot hold the run to its budget.
  const cellsDone = new Promise((ok) => {
    let armed = false;
    state.onCellsComplete = () => {
      if (armed) return;
      armed = true;
      setTimeout(() => {
        console.warn(`[matrix] every requested cell arrived; no /done within ${DONE_GRACE_MS} ms`);
        ok({});
      }, DONE_GRACE_MS).unref();
    };
  });
  const server = await startServer(state);
  const port = server.address().port;
  const params = new URLSearchParams({
    scenarios: scenarios.join(","),
    reps: String(cfg.reps),
    seed: cfg.seed,
    barCount: String(cfg.bars),
    durationMs: String(cfg.durationMs),
    soakMs: String(cfg.soakMs),
  });
  const url = `http://127.0.0.1:${port}/matrix/page/matrix.html?${params}`;
  console.log(
    `[matrix] runtime=${runtime} reps=${cfg.reps} scenarios=${scenarios} bars=${cfg.bars}`,
  );

  const handle =
    runtime === "chromium"
      ? await launchChromium(url, args)
      : runtime === "electron"
        ? launchElectron(url, args)
        : launchTauri(url);
  const memSamples = [];
  const memTimer = setInterval(() => {
    const mb = sampleWorkingSetMb(handle.memNames ?? []);
    if (mb) memSamples.push(mb);
  }, 15_000);
  const budgetMs =
    (scenarios.includes("B10") ? cfg.soakMs : 0) +
    scenarios.length * (cfg.reps * cfg.durationMs + 5000) +
    10 * 60_000;
  const timeout = new Promise((ok) =>
    setTimeout(() => ok({ error: `timeout after ${budgetMs} ms` }), budgetMs),
  );
  const done = await Promise.race([
    donePromise,
    cellsDone,
    timeout,
    handle.exited?.then(() => ({ error: "shell exited early" })) ?? new Promise(() => {}),
  ]);
  clearInterval(memTimer);
  await handle.close();
  server.close();

  const q = state.shellQuery ?? {};
  const versions = {
    ...(handle.versions ?? {}),
    ...(q.sv_electron ? { electron: q.sv_electron } : {}),
    ...(q.sv_chromium ? { chromium: q.sv_chromium } : {}),
    ...(q.sv_tauri ? { tauri: q.sv_tauri } : {}),
    ...(q.sv_webview2 ? { webview2: q.sv_webview2 } : {}),
  };
  const ua = state.preamble?.userAgent ?? "";
  if (!versions.chromium) versions.chromium = /Chrome\/([\d.]+)/.exec(ua)?.[1] ?? null;
  const manifest = captureVersionManifest({
    runtime,
    versions,
    flagSet: handle.flagSet,
    machine:
      state.preamble?.caps?.renderer && state.preamble.caps.renderer !== "unknown"
        ? undefined
        : undefined,
  });
  // GPU from the OS probe wins; fall back to the WebGL renderer string the page saw.
  if (manifest.machine.gpu.startsWith("unknown") && state.preamble?.caps?.renderer) {
    manifest.machine.gpu = state.preamble.caps.renderer;
  }
  if (manifest.machine.driver.startsWith("unknown") && state.preamble?.caps?.vendor) {
    manifest.machine.driver = `webgl-vendor:${state.preamble.caps.vendor}`;
  }
  const incomplete = [];
  try {
    assertDescriptorComplete(manifest.machine);
  } catch (e) {
    incomplete.push(String(e.message));
  }
  incomplete.push(...missingManifestFields(manifest).map((f) => `missing version: ${f}`));

  const cells = state.results.filter((r) => r.kind === "cell").map(summariseCell);
  const fixture = state.preamble?.fixture ?? null;
  const report = {
    schema: REPORT_SCHEMA,
    dryRun: false,
    runtime,
    timestamp: new Date().toISOString(),
    cotenancy: args.cotenancy === "true",
    manifest,
    manifestIncomplete: incomplete,
    seed: fixture?.seed ?? cfg.seed,
    seed32: fixture?.seed32 ?? null,
    fixture,
    driverScriptSha256: createHash("sha256")
      .update(readFileSync(join(BENCH, "driver.mjs")))
      .update(readFileSync(join(HERE, "page/page-main.mjs")))
      .update(readFileSync(join(HERE, "scenes/b5-combined.mjs")))
      .update(readFileSync(join(HERE, "scenes/b7-storm.mjs")))
      .digest("hex"),
    config: cfg,
    capabilities: state.preamble?.caps ?? null,
    cells,
    residentMemoryMb: {
      source:
        runtime === "electron"
          ? "app.getAppMetrics() workingSetSize sum"
          : "PowerShell WorkingSet64 sum by process name",
      shellMetrics: state.shellMetrics,
      sampledMb: memSamples,
      peakMb:
        Math.max(0, ...memSamples, ...state.shellMetrics.map((m) => m.workingSetMb ?? 0)) || null,
    },
    runError: done?.error ?? null,
  };
  writeFileSync(outPath, JSON.stringify(report, null, 2) + "\n");
  console.log(`[matrix] wrote ${outPath}`);
  if (incomplete.length)
    console.error("[matrix] MANIFEST INCOMPLETE:\n  - " + incomplete.join("\n  - "));
  process.exit(done?.error || incomplete.length ? 1 : 0);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}
