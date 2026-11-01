// THROWAWAY SPIKE HARNESS (E15-K01 #371). Node driver: serves this folder on 127.0.0.1, drives headless
// Chromium through Playwright, runs the cut layout-scaling matrix in a seeded shuffled order, the long trigger
// runs, the sync fan-out and the context-count probe, applies the rule fixed below (written before the run),
// and writes ../E15-K01-results.json. Imports nothing from the engine package or the app (BQ-02 ruling): the
// statistics, fixture generator and probe/trigger rules are mirrored in lib.mjs.
// Run from apps/web (for @playwright/test):  node ../../docs/plan/spikes/E15-K01-harness/run.mjs [--smoke]
import { execFileSync } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { cpus, loadavg, release, totalmem } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import {
  classify,
  isAdmissible,
  medianOfP95,
  mulberry32,
  percentile,
  reducedTrigger,
  summariseFrames,
  SWIFTSHADER_FLAGS,
} from "./lib.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../../../..");
const { values: a } = parseArgs({
  options: {
    seed: { type: "string", default: "371" },
    reps: { type: "string", default: "3" },
    "warm-s": { type: "string", default: "2" },
    "window-s": { type: "string", default: "10" },
    "long-s": { type: "string", default: "70" },
    out: { type: "string", default: resolve(here, "..") },
    fixture: {
      type: "string",
      default: join(repo, "apps/web/test/lib/capability/fixtures/e15-k01-windows.json"),
    },
    raw: { type: "string", default: join(process.env.TMPDIR || "/tmp", "E15-K01-raw.jsonl") },
    resume: { type: "boolean", default: false },
    chromium: { type: "string", default: "" },
    smoke: { type: "boolean", default: false },
    devices: { type: "string", default: "dgpu,igpu,swiftshader" },
    only: { type: "string", default: "" }, // a regex over "leg/density/N": run a subset, print, write nothing
  },
});
const SEED = Number(a.seed);
const REPS = a.smoke ? 1 : Number(a.reps);
const WARM_MS = (a.smoke ? 1 : Number(a["warm-s"])) * 1000;
const WINDOW_MS = (a.smoke ? 3 : Number(a["window-s"])) * 1000;
const LONG_MS = (a.smoke ? 6 : Number(a["long-s"])) * 1000;
const SYNC_FRAMES = a.smoke ? 90 : 420; // the first 60 are dropped: 360 measured frames per rep
const JOB_TIMEOUT_MS = 180_000; // a job that hangs over 3 min is killed and recorded

// ---- The rule, PROPOSED and fixed before the run (E15-K01 §5) ---------------------------------------------
const RULE = {
  BUDGET_MS: 16.6, // budget #1 (06 §2); C-14.2 reads "< 16 ms p95": both are reported
  C14_2_MS: 16,
  FLOOR_MS: 33.3, // roadmap §5.3 criterion 2 (30 fps)
  ORDERFLOW4_MS: 18.2, // US-LAY-001 NFR: >= 55 fps with four order-flow panes
  HEADROOM: 1.2, // the p95 with 20 % to spare must fit the budget (ceiling = p95 <= 13.83 ms)
  HARD_CAP: 16, // SCR-020
  FULL_MIN: 4, // below four panes the profile is reduced (US-LAY-001's four)
  REPRO_PCT: 10, // AC1
  SYNC_MAIN_MAX_MS: 0.5, // BQ-12: main thread if p95 per frame at 16 panes <= 0.5 ms (3 % of 16.6)
  // the E15-D12 BQ-10 runtime trigger, as ruled; calibrated below (T1..T5 in E15-K01 §5)
  TRIGGER: { thresholdMs: 18.2, windowMs: 60_000, warmupMs: 10_000, outlierMs: 200 },
  SETTLE_FACTOR: 1.25, // a 1 s bucket is "unsettled" while its p95 is over 1.25 x the cell's window p95
  OUTLIER_RATE_MAX: 0.01, // T3: the 200 ms rule stays if > 200 ms frames are under 1 % of healthy frames
  PROBE_WARMUP_MIN_FRAMES: 30, // the probe's warm-up: max(30, the measured settle in frames at 60 Hz)
};

const req = createRequire(join(process.cwd(), "package.json"));
const { chromium } = req("@playwright/test");
const pwVersion = req("@playwright/test/package.json").version;

const files = Object.fromEntries(
  ["page.html", "page.mjs", "worker.mjs", "scene.mjs", "sync.mjs", "lib.mjs", "load.mjs"].map(
    (f) => [`/${f}`, [join(here, f), f.endsWith(".html") ? "text/html" : "text/javascript"]],
  ),
);
const server = createServer((q, res) => {
  const f = files[(q.url || "/").split("?")[0]];
  if (!f) return void res.writeHead(404).end();
  res
    .writeHead(200, {
      "content-type": f[1],
      "cross-origin-opener-policy": "same-origin",
      "cross-origin-embedder-policy": "require-corp",
    })
    .end(readFileSync(f[0]));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const origin = `http://127.0.0.1:${server.address().port}`;

// The devices (BQ-04). The host's own GPUs through WSL2's Mesa d3d12 driver (GL on D3D12) and ANGLE's GL
// backend, one per adapter; SwiftShader = the bench's pinned CI flag set (software GL).
const HW = [
  "--use-gl=angle",
  "--use-angle=gl",
  "--ignore-gpu-blocklist",
  "--enable-gpu",
  "--disable-gpu-vsync",
  "--enable-webgl2",
];
const wsl = (adapter) => ({
  GALLIUM_DRIVER: "d3d12",
  LD_LIBRARY_PATH: "/usr/lib/wsl/lib",
  MESA_D3D12_DEFAULT_ADAPTER_NAME: adapter,
});
const DEVICES = {
  dgpu: { args: HW, env: wsl("NVIDIA") },
  igpu: { args: HW, env: wsl("Intel") },
  swiftshader: { args: [...SWIFTSHADER_FLAGS], env: {} },
};
const browsers = {};
const launch = async (id) => {
  browsers[id] = await chromium.launch({
    args: DEVICES[id].args,
    env: { ...process.env, ...DEVICES[id].env },
    ...(a.chromium ? { executablePath: a.chromium } : {}),
  });
};
for (const id of a.devices.split(",")) await launch(id);

async function open(device, throttle) {
  if (!browsers[device].isConnected()) await launch(device);
  // a fresh browser context per job: closed pages' contexts count against the live-context limit otherwise
  const ctx = await browsers[device].newContext({ viewport: { width: 1600, height: 900 } });
  const page = await ctx.newPage();
  page.close = () => ctx.close().catch(() => undefined);
  page.errors = [];
  page.on("pageerror", (e) => page.errors.push(e.message));
  if (throttle > 1)
    await (
      await ctx.newCDPSession(page)
    ).send("Emulation.setCPUThrottlingRate", { rate: throttle });
  await page.goto(`${origin}/page.html`);
  await page.waitForFunction(() => window.ready === true);
  return page;
}
const withTimeout = (p, ms) =>
  Promise.race([
    p,
    new Promise((_, rej) => setTimeout(() => rej(new Error(`timeout ${ms} ms`)), ms)),
  ]);

// ---- The cut matrix (E15-K01 §2.3; sized from the smoke run to fit 45 min) -----------------------------------
// Topologies (BQ-05): "worker-shared" = one render worker, one context, a viewport + scissor per pane;
// "worker" = one render worker, one context per pane; "inline" = main thread, one context per pane.
const P = a.smoke ? [1, 4, 16] : [1, 2, 4, 6, 8, 12, 16];
const P3 = a.smoke ? [1, 16] : [1, 6, 16];
const LEGS = [
  {
    id: "dgpu-shared-A",
    device: "dgpu",
    mode: "worker-shared",
    throttle: 1,
    densities: ["bare", "indicators", "drawings"],
    panes: P,
  },
  {
    id: "dgpu-shared-B",
    device: "dgpu",
    mode: "worker-shared",
    throttle: 1,
    densities: ["drawings"],
    panes: P,
  }, // AC1
  {
    id: "dgpu-worker-ctx",
    device: "dgpu",
    mode: "worker",
    throttle: 1,
    densities: ["indicators"],
    panes: P3,
  },
  {
    id: "dgpu-inline",
    device: "dgpu",
    mode: "inline",
    throttle: 1,
    densities: ["indicators"],
    panes: P3,
  },
  {
    id: "dgpu-proxy",
    device: "dgpu",
    mode: "worker",
    throttle: 1,
    densities: ["orderflow-proxy"],
    panes: a.smoke ? [4] : [1, 2, 4],
  },
  {
    id: "igpu-shared",
    device: "igpu",
    mode: "worker-shared",
    throttle: 1,
    densities: ["indicators"],
    panes: P3.map((n) => (n === 6 ? 4 : n)),
  },
  // CDP's CPU throttle does not reach a dedicated worker (smoke run): this leg shows it; the weak leg is inline
  {
    id: "igpu-shared-cpu4x",
    device: "igpu",
    mode: "worker-shared",
    throttle: 4,
    densities: ["indicators"],
    panes: P3.map((n) => (n === 6 ? 4 : n)),
  },
  {
    id: "igpu-inline-cpu4x",
    device: "igpu",
    mode: "inline",
    throttle: 4,
    densities: ["indicators"],
    panes: P,
  },
  {
    id: "igpu-inline-cpu4x-dr",
    device: "igpu",
    mode: "inline",
    throttle: 4,
    densities: ["drawings"],
    panes: a.smoke ? [4] : [1, 4, 6],
  },
  {
    id: "swiftshader-shared",
    device: "swiftshader",
    mode: "worker-shared",
    throttle: 1,
    densities: ["indicators"],
    panes: [1, 4],
  },
  // the probe's 120-frame windows on the software-GL device: a 10 s window holds too few frames there, so one
  // rep with a 45 s window (a supplementary --resume pass after the main run; E15-K01 §2.3)
  {
    id: "swiftshader-probe",
    device: "swiftshader",
    mode: "worker-shared",
    throttle: 1,
    densities: ["indicators"],
    panes: [1, 4],
    reps: 1,
    windowMs: 45_000,
  },
].filter((l) => browsers[l.device]);
// The long trigger runs (BQ-10 ruling): the ruled 60 s window needs > 60 s of frames after the 10 s warm-up.
const LONG = [
  {
    id: "long-dgpu-shared",
    device: "dgpu",
    mode: "worker-shared",
    throttle: 1,
    density: "indicators",
    n: 16,
  },
  {
    id: "long-igpu-inline-cpu4x-4",
    device: "igpu",
    mode: "inline",
    throttle: 4,
    density: "indicators",
    n: 4,
  },
  {
    id: "long-igpu-inline-cpu4x-16",
    device: "igpu",
    mode: "inline",
    throttle: 4,
    density: "indicators",
    n: 16,
  },
].filter((l) => browsers[l.device]);

const jobs = [];
for (const leg of LEGS)
  for (const density of leg.densities)
    for (const n of leg.panes)
      for (let rep = 0; rep < (leg.reps ?? REPS); rep += 1)
        jobs.push({ leg, density, n, rep, key: `${leg.id}/${density}/${n}/${rep}` });
if (a.only)
  jobs.splice(
    0,
    jobs.length,
    ...jobs.filter((j) => new RegExp(a.only).test(`${j.leg.id}/${j.density}/${j.n}`)),
  );
const rand = mulberry32(SEED);
for (let i = jobs.length - 1; i > 0; i -= 1) {
  const j = Math.floor(rand() * (i + 1));
  [jobs[i], jobs[j]] = [jobs[j], jobs[i]];
}

const host = {
  cpu: cpus()[0]?.model,
  logicalCpus: cpus().length,
  memGb: Math.round(totalmem() / 2 ** 30),
  kernel: release(),
  node: process.version,
  chromium: Object.values(browsers)[0].version(),
  playwright: pwVersion,
  buildSha: execFileSync("git", ["rev-parse", "HEAD"], { cwd: repo }).toString().trim(),
  loadavgStart: loadavg().map((x) => +x.toFixed(2)),
  devices: {},
};
const prevOut = join(a.out, "E15-K01-results.json");
const prev = a.resume && existsSync(prevOut) ? JSON.parse(readFileSync(prevOut, "utf8")) : null;
if (prev)
  Object.assign(host, {
    devices: prev.host.devices,
    loadavgStart: prev.host.loadavgStart,
    resumedFrom: prev.startedAt,
  });
for (const id of prev ? [] : Object.keys(browsers)) {
  const p = await open(id, 1);
  host.devices[id] = {
    flags: DEVICES[id].args,
    env: Object.keys(DEVICES[id].env).map((k) => `${k}=${DEVICES[id].env[k]}`),
    gl: await p.evaluate(() => window.__h.glInfo()), // harness record only, never a probe input
    contexts: await p.evaluate(() => window.__h.contexts(20)), // BQ-05: the live-context limit
    workerContexts: await p.evaluate(() => window.__h.workerContexts(20)),
  };
  await p.close();
}

// ---- run the jobs (raw lines appended as they finish, so a crash keeps them; --resume skips them) -----------
const r3 = (x) => (x === null || x === undefined ? null : +x.toFixed(3));
const done = new Map();
if (a.resume && existsSync(a.raw))
  for (const l of readFileSync(a.raw, "utf8").split("\n").filter(Boolean)) {
    const r = JSON.parse(l);
    done.set(r.job, r);
  }
else if (!a.only) {
  mkdirSync(dirname(a.raw), { recursive: true });
  writeFileSync(a.raw, "");
}
const startedAt = prev?.startedAt ?? new Date().toISOString();
const t0 = Date.now();
const progress = (s) => process.stdout.write(`[${((Date.now() - t0) / 1000).toFixed(0)}s] ${s}\n`);

/** Settle (s): the end of the last 1 s bucket, starting before warm-up + 5 s, whose p95 exceeds SETTLE_FACTOR x steady. */
function settleS(r, steadyP95) {
  const at = [...r.warmAt, ...r.workAt],
    ms = [...r.warm, ...r.work];
  let last = 0;
  for (let b = 0; b * 1000 < WARM_MS + 5000; b += 1) {
    const v = ms.filter((_, i) => at[i] >= b * 1000 && at[i] < (b + 1) * 1000);
    if (v.length && percentile(v, 95) > RULE.SETTLE_FACTOR * steadyP95) last = b + 1;
  }
  return last;
}

async function runJob(device, throttle, o) {
  const page = await open(device, throttle);
  try {
    const r = await withTimeout(
      page.evaluate((x) => window.__h.run(x), o),
      JOB_TIMEOUT_MS,
    );
    return { r, errors: page.errors };
  } finally {
    await page.close();
  }
}

for (const [k, job] of jobs.entries()) {
  if (done.has(job.key)) continue;
  const la = loadavg()[0];
  let line;
  try {
    const { r, errors } = await runJob(job.leg.device, job.leg.throttle, {
      mode: job.leg.mode,
      density: job.density,
      n: job.n,
      warmMs: WARM_MS,
      windowMs: job.leg.windowMs ?? WINDOW_MS,
      seed: SEED,
    });
    const work = summariseFrames(r.work);
    line = {
      job: job.key,
      order: k,
      leg: job.leg.id,
      density: job.density,
      n: job.n,
      rep: job.rep,
      ok: true,
      frames: r.work.length,
      work,
      firstFrameMs: r.warm[0] ?? null,
      settleS: settleS(r, work.p95),
      interval: { p50: percentile(r.interval, 50), p95: percentile(r.interval, 95) },
      submit: { p50: percentile(r.submit, 50), p95: percentile(r.submit, 95) },
      drawsPerFrame: r.drawsPerFrame,
      bytesPerFrame: r.bytesPerFrame,
      lostContexts: r.lost,
      setupMsPerPaneP50: percentile(r.setupMs, 50),
      dataMs: r.dataMs,
      workerRaf: r.hasRaf,
      // the cell-window trigger: the ruled rule with the window set to this cell's (the warm-up already dropped)
      trigger: reducedTrigger(
        r.work.map((ms, i) => ({ t: r.workAt[i], ms })),
        { ...RULE.TRIGGER, windowMs: (job.leg.windowMs ?? WINDOW_MS) * 0.9, warmupMs: 0 },
      ),
      probeWindow: job.n === 1 || job.n === 4 ? r.work.slice(0, 120).map(r3) : undefined,
      loadavgBefore: la,
      errors,
    };
    progress(
      `${k + 1}/${jobs.length} ${job.leg.id} ${job.density} N=${job.n} rep=${job.rep} p95=${work.p95.toFixed(2)} frames=${r.work.length} lost=${r.lost}`,
    );
  } catch (e) {
    line = {
      job: job.key,
      order: k,
      leg: job.leg.id,
      density: job.density,
      n: job.n,
      rep: job.rep,
      ok: false,
      reason: String(e.message).slice(0, 200),
      loadavgBefore: la,
    };
    progress(
      `${k + 1}/${jobs.length} ${job.leg.id} ${job.density} N=${job.n} rep=${job.rep} FAILED ${line.reason}`,
    );
  }
  done.set(job.key, line);
  if (!a.only) appendFileSync(a.raw, `${JSON.stringify(line)}\n`);
}
if (a.only) {
  console.log(JSON.stringify(host.devices));
  process.exit(0);
}
const raw = jobs.map((j) => done.get(j.key));

// ---- long trigger runs (BQ-10): warm-up 0 in the page; the ruled trigger applies its own 10 s -----------------
const longRuns = [];
for (const L of LONG) {
  const key = `long/${L.id}`;
  if (done.has(key)) {
    longRuns.push(done.get(key));
    continue;
  }
  let line;
  try {
    const { r } = await runJob(L.device, L.throttle, {
      mode: L.mode,
      density: L.density,
      n: L.n,
      warmMs: 0,
      windowMs: LONG_MS,
      seed: SEED,
    });
    const samples = r.work.map((ms, i) => ({ t: r.workAt[i], ms }));
    const trig = reducedTrigger(
      samples,
      a.smoke ? { ...RULE.TRIGGER, windowMs: 3000, warmupMs: 1000 } : RULE.TRIGGER,
    );
    const per10 = [];
    for (let s = 10_000; s + 10_000 <= LONG_MS; s += 10_000)
      per10.push(
        r3(
          percentile(
            samples.filter((x) => x.t >= s && x.t < s + 10_000).map((x) => x.ms),
            95,
          ),
        ),
      );
    const firstS = samples.filter((x) => x.t < 10_000).map((x) => x.ms);
    line = {
      job: key,
      id: L.id,
      leg: L,
      ok: true,
      frames: r.work.length,
      trigger: { ...trig, p95: r3(trig.p95) },
      p95Per10s: per10,
      p95First10s: r3(percentile(firstS, 95)),
      over200: r.work.filter((x) => x > 200).length,
      maxMs: r3(Math.max(...r.work)),
    };
    progress(`long ${L.id} frames=${r.work.length} p95(60s)=${r3(trig.p95)} fired=${trig.fired}`);
  } catch (e) {
    line = { job: key, id: L.id, leg: L, ok: false, reason: String(e.message).slice(0, 200) };
    progress(`long ${L.id} FAILED ${line.reason}`);
  }
  appendFileSync(a.raw, `${JSON.stringify(line)}\n`);
  longRuns.push(line);
}

// ---- sync fan-out (BQ-12): main thread against worker, at 6 and 16 panes, plain and under 4x -----------------
const SYNC_DEVICE = browsers.igpu ? "igpu" : Object.keys(browsers)[0];
const sync = [];
for (const throttle of [1, 4])
  for (const n of [6, 16])
    for (const where of ["main", "worker"])
      for (let rep = 0; rep < REPS; rep += 1) {
        const key = `sync/${throttle}/${n}/${where}/${rep}`;
        if (done.has(key)) {
          sync.push(done.get(key));
          continue;
        }
        let line;
        try {
          const page = await open(SYNC_DEVICE, throttle);
          const r = await withTimeout(
            page.evaluate((o) => window.__h.sync(o.n, o.f, o.w), { n, f: SYNC_FRAMES, w: where }),
            JOB_TIMEOUT_MS,
          );
          await page.close();
          const m = r.main.slice(60),
            w = r.worker.slice(60);
          line = {
            job: key,
            ok: true,
            throttle,
            n,
            where,
            rep,
            frames: m.length,
            mainP50: r3(percentile(m, 50)),
            mainP95: r3(percentile(m, 95)),
            workerP95: r3(percentile(w, 95)),
          };
        } catch (e) {
          line = {
            job: key,
            ok: false,
            throttle,
            n,
            where,
            rep,
            reason: String(e.message).slice(0, 200),
          };
        }
        progress(
          `sync x${throttle} N=${n} ${where} rep=${rep} main p95=${line.mainP95 ?? "FAILED"}`,
        );
        appendFileSync(a.raw, `${JSON.stringify(line)}\n`);
        sync.push(line);
      }

// ---- aggregate and apply the rule -------------------------------------------------------------------------
const cells = [];
for (const leg of LEGS)
  for (const density of leg.densities)
    for (const n of leg.panes) {
      const all = raw.filter((x) => x && x.leg === leg.id && x.density === density && x.n === n);
      const reps = all.filter((x) => x.ok);
      const lost = reps.length ? Math.max(...reps.map((x) => x.lostContexts)) : null;
      const framesMin = reps.length ? Math.min(...reps.map((x) => x.frames)) : 0;
      cells.push({
        leg: leg.id,
        device: leg.device,
        mode: leg.mode,
        throttle: leg.throttle,
        density,
        n,
        reps: reps.length,
        failedReps: all.length - reps.length,
        admissible: isAdmissible(reps.length),
        p95: reps.length ? r3(medianOfP95(reps.map((x) => x.work.p95))) : null,
        p95Label: framesMin < 100 ? "max" : "p95", // BQ-14 ruling: below n = 100 the nearest-rank p95 is labelled max
        p95PerRep: reps.map((x) => r3(x.work.p95)),
        p50: reps.length ? r3(medianOfP95(reps.map((x) => x.work.p50))) : null,
        submitP95: reps.length ? r3(medianOfP95(reps.map((x) => x.submit.p95))) : null,
        intervalP50: reps.length ? r3(medianOfP95(reps.map((x) => x.interval.p50))) : null,
        framesMin,
        framesOk600: framesMin >= 600,
        over200: reps.reduce((s, x) => s + x.work.over200, 0),
        settleSMax: reps.length ? Math.max(...reps.map((x) => x.settleS)) : null,
        firstFrameMsMax: reps.length ? r3(Math.max(...reps.map((x) => x.firstFrameMs ?? 0))) : null,
        triggerFiredReps: reps.filter((x) => x.trigger.fired).length,
        drawsPerFrame: reps[0]?.drawsPerFrame ?? null,
        kbPerFrame: r3((reps[0]?.bytesPerFrame ?? 0) / 1024),
        lostContexts: lost,
        valid: reps.length > 0 && lost === 0, // a lost context draws nothing: excluded
      });
    }
const at = (leg, density, n) =>
  cells.find((c) => c.leg === leg && c.density === density && c.n === n);
const cross = (rows, ms) => {
  const i = rows.findIndex((c) => c.p95 > ms);
  if (i === -1) return { firstN: null, interpolatedN: null };
  if (i === 0) return { firstN: rows[0].n, interpolatedN: null };
  const [p, q] = [rows[i - 1], rows[i]];
  return { firstN: q.n, interpolatedN: r3(p.n + ((ms - p.p95) * (q.n - p.n)) / (q.p95 - p.p95)) };
};
const curves = [];
for (const leg of LEGS)
  for (const density of leg.densities) {
    const rows = leg.panes.map((n) => at(leg.id, density, n)).filter((c) => c.valid);
    if (rows.length === 0) continue;
    const xs = rows.map((c) => c.n),
      ys = rows.map((c) => c.p95);
    const mx = xs.reduce((s, x) => s + x, 0) / xs.length,
      my = ys.reduce((s, y) => s + y, 0) / ys.length;
    const sxx = xs.reduce((s, x) => s + (x - mx) ** 2, 0);
    const slope = sxx > 0 ? xs.reduce((s, x, i) => s + (x - mx) * (ys[i] - my), 0) / sxx : null;
    let ceiling = 0;
    for (const c of rows)
      if (c.p95 * RULE.HEADROOM <= RULE.BUDGET_MS) ceiling = c.n;
      else break;
    const max = Math.min(RULE.HARD_CAP, ceiling);
    curves.push({
      leg: leg.id,
      density,
      measuredN: xs,
      cross16: cross(rows, RULE.BUDGET_MS),
      cross16C142: cross(rows, RULE.C14_2_MS),
      cross18: cross(rows, RULE.ORDERFLOW4_MS),
      cross33: cross(rows, RULE.FLOOR_MS),
      marginalMsPerPane: rows.slice(1).map((c, i) => ({
        from: rows[i].n,
        to: c.n,
        ms: r3((c.p95 - rows[i].p95) / (c.n - rows[i].n)),
      })),
      fit: { interceptMs: slope === null ? null : r3(my - slope * mx), slopeMsPerPane: r3(slope) },
      recommendedMaxPanes: max,
      profile: max >= RULE.FULL_MIN ? "full" : "reduced",
      // a ceiling at the largest measured N is "at least" that N: nothing above it was measured
      ceilingIsLowerBound: max === Math.max(...xs) && max < RULE.HARD_CAP,
    });
  }
// the probe (mirror of the app's classify) on the measured windows: one at one pane and one at four, per rep
const probeRuns = [];
for (const leg of LEGS)
  for (const density of leg.densities)
    for (let rep = 0; rep < (leg.reps ?? REPS); rep += 1) {
      const w1 = done.get(`${leg.id}/${density}/1/${rep}`)?.probeWindow,
        w4 = done.get(`${leg.id}/${density}/4/${rep}`)?.probeWindow;
      if (!w1 || !w4 || Math.min(w1.length, w4.length) < 60) continue;
      const windows = [
        { paneCount: 1, frameMs: w1 },
        { paneCount: 4, frameMs: w4 },
      ];
      probeRuns.push({
        leg: leg.id,
        density,
        rep,
        windows,
        ...classify(windows, {
          budgetMs: RULE.BUDGET_MS,
          headroom: RULE.HEADROOM,
          hardCap: RULE.HARD_CAP,
          fullMin: RULE.FULL_MIN,
        }),
      });
    }
const repro = cells
  .filter((c) => c.leg === "dgpu-shared-A" && at("dgpu-shared-B", c.density, c.n))
  .map((c) => {
    const b = at("dgpu-shared-B", c.density, c.n);
    const pct =
      c.p95 && b.p95 ? r3((100 * Math.abs(c.p95 - b.p95)) / Math.min(c.p95, b.p95)) : null;
    return {
      density: c.density,
      n: c.n,
      a: c.p95,
      b: b.p95,
      diffPct: pct,
      within: pct !== null && pct <= RULE.REPRO_PCT,
    };
  });
const syncAgg = [];
for (const throttle of [1, 4])
  for (const n of [6, 16])
    for (const where of ["main", "worker"]) {
      const rs = sync.filter(
        (s) => s.ok && s.throttle === throttle && s.n === n && s.where === where,
      );
      syncAgg.push({
        throttle,
        n,
        where,
        reps: rs.length,
        frames: rs[0]?.frames ?? 0,
        mainP95: r3(medianOfP95(rs.map((s) => s.mainP95))),
        workerP95: r3(medianOfP95(rs.map((s) => s.workerP95))),
      });
    }
const syncMain16 =
  syncAgg.find((s) => s.throttle === 1 && s.n === 16 && s.where === "main")?.mainP95 ?? null;

// trigger calibration (T1..T5, E15-K01 §5)
const curve = (leg, d) => curves.find((c) => c.leg === leg && c.density === d);
const healthy = cells.filter(
  (c) =>
    c.valid &&
    c.throttle === 1 &&
    c.device !== "swiftshader" &&
    c.p95 * RULE.HEADROOM <= RULE.BUDGET_MS,
);
const healthyFrames = raw
  .filter(
    (x) => x?.ok && healthy.some((c) => c.leg === x.leg && c.density === x.density && c.n === x.n),
  )
  .reduce((s, x) => s + x.frames, 0);
const healthyOver200 = healthy.reduce((s, c) => s + c.over200, 0);
const settleMax = Math.max(
  0,
  ...cells.filter((c) => c.valid && c.device !== "swiftshader").map((c) => c.settleSMax ?? 0),
);
const trig = {
  T1_falseProposalOnHealthy: healthy
    .filter((c) => c.triggerFiredReps > 0)
    .map((c) => `${c.leg}/${c.density}/${c.n}`),
  T2_firstNOver18_2: curves.map((c) => ({
    leg: c.leg,
    density: c.density,
    firstN: c.cross18.firstN,
    interpolatedN: c.cross18.interpolatedN,
    ceiling: c.recommendedMaxPanes,
  })),
  T3_outliers: {
    healthyFrames,
    healthyOver200,
    rate: healthyFrames ? r3(healthyOver200 / healthyFrames) : null,
    keep200: healthyFrames > 0 && healthyOver200 / healthyFrames < RULE.OUTLIER_RATE_MAX,
  },
  T4_warmup: {
    settleSMax: settleMax,
    keep10s: settleMax <= 10,
    proposedWarmupS: Math.max(10, Math.ceil(settleMax)),
  },
  T5_long: longRuns.map((l) =>
    l.ok
      ? {
          id: l.id,
          p95_60s: l.trigger.p95,
          fired: l.trigger.fired,
          framesInWindow: l.trigger.frames,
          p95Per10s: l.p95Per10s,
          p95First10s: l.p95First10s,
          over200: l.over200,
        }
      : { id: l.id, failed: l.reason },
  ),
  probeWarmupFrames: Math.max(RULE.PROBE_WARMUP_MIN_FRAMES, Math.ceil(settleMax * 60)),
};
const ac4 = cells
  .filter((c) => c.density === "drawings" && c.n === 6)
  .map((c) => ({
    leg: c.leg,
    p95: c.p95,
    valid: c.valid,
    over33: c.valid ? c.p95 > RULE.FLOOR_MS : null,
  }));
const decision = {
  ceilingPerLeg: curves.map((c) => ({
    leg: c.leg,
    density: c.density,
    recommendedMaxPanes: c.recommendedMaxPanes,
    profile: c.profile,
    lowerBound: c.ceilingIsLowerBound,
  })),
  probeIndicators: probeRuns
    .filter((p) => p.density === "indicators")
    .map((p) => ({
      leg: p.leg,
      rep: p.rep,
      maxPanes: p.recommendedMaxPanes,
      profile: p.recommendedProfile,
      p95: r3(p.p95FrameMs),
    })),
  ac1AllWithin: repro.length > 0 && repro.every((r) => r.within),
  ac1Worst: repro.reduce((w, r) => ((r.diffPct ?? -1) > (w?.diffPct ?? -1) ? r : w), null),
  ac4,
  orderflow4: cells
    .filter((c) => c.density === "orderflow-proxy" && c.n === 4)
    .map((c) => ({
      leg: c.leg,
      p95: c.p95,
      valid: c.valid,
      meets18_2: c.valid ? c.p95 <= RULE.ORDERFLOW4_MS : null,
    })),
  sync: {
    main16P95: syncMain16,
    rule: `main if <= ${RULE.SYNC_MAIN_MAX_MS} ms`,
    recommendation:
      syncMain16 === null ? null : syncMain16 <= RULE.SYNC_MAIN_MAX_MS ? "main" : "worker",
  },
  ac2: {
    weakIgpu4x: curve("igpu-inline-cpu4x", "indicators")?.recommendedMaxPanes ?? null,
    best: curve("dgpu-shared-A", "indicators")?.recommendedMaxPanes ?? null,
  },
  reducedMaxPanes: curve("igpu-inline-cpu4x", "indicators")?.recommendedMaxPanes ?? null,
  trigger: trig,
};

const out = {
  harness: "E15-K01 layout-scaling (throwaway)",
  scenarioId: "layout-scaling",
  startedAt,
  finishedAt: new Date().toISOString(),
  wallS: Math.round((Date.now() - t0) / 1000) + (prev?.wallS ?? 0), // main run + the --resume pass
  passes: prev
    ? [
        { wallS: prev.wallS, finishedAt: prev.finishedAt },
        { wallS: Math.round((Date.now() - t0) / 1000) },
      ]
    : undefined,
  smoke: a.smoke,
  params: {
    seed: SEED,
    fixtureSeed: 20260928,
    reps: REPS,
    warmMs: WARM_MS,
    windowMs: WINDOW_MS,
    longMs: LONG_MS,
    syncFrames: SYNC_FRAMES,
    measuredSyncFrames: SYNC_FRAMES - 60,
    jobTimeoutMs: JOB_TIMEOUT_MS,
    plotArea: "1600x900 css px, dpr 1",
  },
  rule: RULE,
  host: { ...host, loadavgEnd: loadavg().map((x) => +x.toFixed(2)) },
  evidenceClass:
    "below reference class: host GPUs reached through WSL2 (Mesa d3d12 + ANGLE GL), not the reference ANGLE D3D11 path; SwiftShader software GL. A met budget is conservative evidence, a missed one is inconclusive",
  legs: LEGS.map((l) => ({ ...l })),
  order: jobs.map((j) => j.key),
  cells,
  curves,
  repro,
  probeRuns: probeRuns.map(({ windows, ...p }) => ({ ...p, p95FrameMs: r3(p.p95FrameMs) })),
  longRuns,
  sync: syncAgg,
  syncRuns: sync,
  decision,
  failedJobs: raw.filter((x) => x && !x.ok),
  rawRuns: raw.map((x) => (x && x.ok ? { ...x, probeWindow: undefined } : x)),
};
const file = a.smoke
  ? join(process.env.TMPDIR || "/tmp", "E15-K01-results.smoke.json")
  : join(a.out, "E15-K01-results.json");
writeFileSync(file, `${JSON.stringify(out, null, 1)}\n`);
// The app's unit test re-runs the app's classify on these windows and must reach the mirror's answers.
const fixLegs = ["dgpu-shared-A", "igpu-inline-cpu4x", "swiftshader-probe"];
const fixture = {
  source: "docs/plan/spikes/E15-K01-harness/run.mjs (generated; measured frame times, ms)",
  startedAt,
  runs: probeRuns
    .filter((p) => p.density === "indicators" && p.rep === 0 && fixLegs.includes(p.leg))
    .map((p) => ({
      leg: p.leg,
      windows: p.windows,
      expected: {
        recommendedMaxPanes: p.recommendedMaxPanes,
        recommendedProfile: p.recommendedProfile,
        p95FrameMs: p.p95FrameMs,
      },
    })),
};
if (!a.smoke) writeFileSync(a.fixture, `${JSON.stringify(fixture)}\n`);
progress(`wrote ${file}`);
for (const b of Object.values(browsers)) await b.close();
server.close();
