// E11-T06 real-engine bench page: runs the built engine (`dist/bench-engine.js`, `createChart` in
// bench mode) in Chromium and posts each scenario's raw repetitions to the runner's loopback
// server (`run-matrix.mjs --page engine`). Single-chart scenarios run inline so 06 §4.3's stage
// marks land on this page's timeline; B6 runs its four charts on the shared render worker. The
// scripted input goes through the public `timeScale`, frame by frame. No network beyond loopback.
import { generateM0Fixture } from "../../fixtures/index.mjs";
import { toSeed32 } from "../../fixtures/rng.mjs";
import { fixtureDigests } from "../../matrix/fixture-digest.mjs";
import { probeCapabilities } from "../../matrix/page/gl-load.mjs";
import {
  frameStatsSample,
  framesFromMarks,
  heapReadingMb,
  memoryDeltaMb,
  panWindow,
  zoomSpacing,
} from "../engine-lib.mjs";

// The built engine, served by the runner from the package's dist/ (`pnpm build` first). A runtime
// URL, not a static import: the page is not part of the source module graph.
const ENGINE_URL = "/dist/bench-engine.js";
let createBenchChart = null;

const q = new URLSearchParams(location.search);
const cfg = {
  scenarios: (q.get("scenarios") ?? "B1,B2,B5,B6,B9").split(","),
  reps: Number(q.get("reps") ?? 5),
  seed: q.get("seed") ?? "20260928",
  barCount: Number(q.get("barCount") ?? 100_000),
  durationMs: Number(q.get("durationMs") ?? 20_000),
  soakMs: Number(q.get("soakMs") ?? 30 * 60_000),
  // Set by the runner only when it launched Chromium with `--enable-precise-memory-info`.
  preciseMemory: q.get("preciseMemory") === "1",
};
const W = 1600;
const H = 900;
const BAR_US = 60_000_000;
const theme = {
  palette: "default",
  convention: "standard",
  colors: { "color.chart.background": "#0b0e11", "color.candle.up": "#26a69a" },
};
const say = (s) => (document.getElementById("status").textContent = s);
const post = (path, body) =>
  fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
const nextFrame = () => new Promise((r) => requestAnimationFrame(() => r(0)));
const heapMb = () => heapReadingMb(performance.memory, cfg.preciseMemory);

/** Fresh columns per chart: `setData` transfers (detaches) them. */
function candles(bars, n) {
  const d = {
    time: new Float64Array(n),
    open: new Int32Array(n),
    high: new Int32Array(n),
    low: new Int32Array(n),
    close: new Int32Array(n),
    volume: new Float32Array(n),
    priceOrigin: 0,
    tickSize: 0.01,
  };
  for (let i = 0; i < n; i += 1) {
    const b = bars[i];
    d.time[i] = b.tOpenMs * 1000;
    d.open[i] = b.o;
    d.high[i] = b.h;
    d.low[i] = b.l;
    d.close[i] = b.c;
    d.volume[i] = b.v;
  }
  return d;
}

/** Mounts one chart with the scenario's content; returns it and its candle series. */
function mount(scenario, bars, n, runMode) {
  const container = document.createElement("div");
  const [w, h] = scenario === "B6" ? [W / 2, H / 2] : [W, H];
  container.style.cssText = `width:${w}px;height:${h}px;position:relative`;
  document.getElementById("stage").appendChild(container);
  const chart = createBenchChart({
    container,
    theme,
    runMode,
    ...(scenario === "B6" && { syncGroup: "b6" }),
  });
  const pane = chart.addPane({});
  const series = pane.addSeries("candles", {});
  series.setData(candles(bars, n));
  if (scenario === "B5" || scenario === "B6") {
    pane.addSeries("footprint", {});
    pane.addSeries("heatmap", {});
    for (let i = 0; i < 3; i += 1) pane.addIndicator({}, {});
    pane.addOverlay({}, { lines: 50 });
  }
  return { chart, container, series, w };
}

/** One repetition: the scripted frames for `durationMs`, then the raw series. */
async function runRep(scenario, bars) {
  const multi = scenario === "B6";
  const soak = scenario === "B10";
  const duration = soak ? cfg.soakMs : cfg.durationMs;
  // B6 is half density; B10 holds back one bar per 100 ms of soak for its live feed.
  const n = multi
    ? Math.floor(cfg.barCount / 2)
    : soak
      ? Math.max(1, cfg.barCount - Math.ceil(duration / 100))
      : cfg.barCount;
  performance.clearMarks();
  // Read before mounting: the fixture is already allocated, so the memory delta excludes it.
  const baseMb = heapMb();
  const t0 = performance.now();
  const charts = [];
  for (let i = 0; i < (multi ? 4 : 1); i += 1)
    charts.push(mount(scenario, bars, n, multi ? "worker" : "inline"));
  const rep = {
    frameMs: [],
    stageMs: {},
    drawCalls: [],
    lod: [],
    memoryMb: null,
    memoryPrecision: cfg.preciseMemory ? "precise" : "imprecise",
    // B6 renders on the shared worker: its heap is not visible to this page's performance.memory.
    ...(multi && { memoryScope: "main thread only; the render worker's heap is not counted" }),
  };
  let first = null;
  let busyMs = 0;
  let tickMs = 0;
  let tickFrames = 0;
  let badStats = null;
  const unsub = charts.map(({ chart }) =>
    chart.subscribe("frameStats", (s) => {
      first ??= performance.now();
      let x;
      try {
        x = frameStatsSample(s);
      } catch (e) {
        badStats ??= String(e);
        return;
      }
      rep.drawCalls.push(x.drawCalls);
      rep.lod.push(x.lod);
      busyMs += x.frameMs;
      tickMs += x.frameMs;
      tickFrames += 1;
    }),
  );
  const drain = () => {
    const f = framesFromMarks(performance.getEntriesByType("mark"));
    performance.clearMarks();
    rep.frameMs.push(...f.frameMs);
    for (const [s, xs] of Object.entries(f.stageMs)) (rep.stageMs[s] ??= []).push(...xs);
  };
  while (first === null && performance.now() - t0 < 10_000) await nextFrame();
  // No frame at all is a failed run, never a p95 of 0 ms (the cell becomes not-runnable).
  if (first === null) badStats ??= `${scenario}: no frame arrived within 10 s of mount`;
  if (scenario === "B9") rep.coldInitMs = first === null ? null : first - t0;
  rep.atlasFromCacheMs = null; // E11-S11's atlas counters are not on the bench page yet
  const start = performance.now();
  const series = [];
  let lastSample = start;
  let appended = n;
  for (let t = 0; t < duration && scenario !== "B9" && !badStats; t = performance.now() - start) {
    const lead = charts[0];
    const spacing = scenario === "B2" ? zoomSpacing(t, duration) : 6;
    const win = panWindow(scenario === "B2" ? 0 : t, {
      bars: appended,
      widthPx: lead.w,
      spacingPx: spacing,
    });
    const from = bars[0].tOpenMs * 1000;
    lead.chart.timeScale.setVisibleRange({
      from: from + win.from * BAR_US,
      to: from + win.to * BAR_US,
    });
    if (soak && appended < bars.length && Math.floor(t / 100) > appended - n) {
      lead.series.append(candles(bars.slice(appended, appended + 1), 1));
      appended += 1;
    }
    await nextFrame();
    // Only a rAF in which a frame arrived: idle zeros would dilute the p95.
    if (multi && tickFrames > 0) rep.frameMs.push(tickMs);
    tickMs = 0;
    tickFrames = 0;
    if (!multi) drain();
    if (performance.now() - lastSample >= (soak ? 10_000 : 1000)) {
      lastSample = performance.now();
      series.push(heapMb());
    }
  }
  if (!multi) drain();
  const wall = performance.now() - start;
  if (multi) rep.workerCpuPct = wall > 0 ? (busyMs / wall) * 100 : null;
  rep.memoryMb = memoryDeltaMb(baseMb, [...series, heapMb()]);
  if (soak) rep.memorySeriesMb = series.filter((v) => v !== null);
  for (const u of unsub) u();
  for (const c of charts) {
    c.chart.dispose();
    c.container.remove();
  }
  if (badStats) throw new Error(badStats);
  return rep;
}

async function main() {
  ({ createBenchChart } = await import(ENGINE_URL));
  say("capability probe");
  const caps = probeCapabilities();
  say(`generating fixture (${cfg.barCount} bars)`);
  const fixture = generateM0Fixture({ seed: cfg.seed, barCount: cfg.barCount });
  const digests = await fixtureDigests(fixture);
  await post("/result", {
    kind: "preamble",
    userAgent: navigator.userAgent,
    caps,
    fixture: { seed: cfg.seed, seed32: toSeed32(cfg.seed), barCount: cfg.barCount, ...digests },
    cfg,
  });
  for (const scenario of cfg.scenarios) {
    const cell = { kind: "cell", scenario, reps: [] };
    try {
      const reps = scenario === "B10" ? 1 : cfg.reps;
      for (let r = 0; r < reps; r += 1) {
        say(`running ${scenario} rep ${r + 1}/${reps}`);
        cell.reps.push(await runRep(scenario, fixture.bars));
      }
    } catch (e) {
      cell.notRunnable = String(e && e.stack ? e.stack : e);
    }
    await post("/result", cell);
  }
  say("done");
  await post("/done", {});
}

main().catch(async (e) => {
  say(`FAILED ${e}`);
  await post("/done", { error: String(e && e.stack ? e.stack : e) });
});
