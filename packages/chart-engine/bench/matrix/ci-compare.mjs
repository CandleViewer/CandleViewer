#!/usr/bin/env node
// E06-T02 — the CI matrix job's comparison against the committed baseline. Recording only by
// default (R0, `30-release-roadmap.md` §4.4 "not yet gating"): a regression is printed, never an
// exit code. A failure to RUN is an exit code: no report, an invalid report (`validateReport`),
// or a run error from the harness (watchdog, early shell exit) all exit 1 so the job goes red.
//
// E03-T14: `--enforce` (the GPU-runner mode of `_job-engine-bench.yml`, never the hosted
// fallback) makes a like-for-like regression above the threshold exit 1 with CI-BEN-001. A run that
// is not like-for-like with the baseline (other reps, fixture, hardware class) is never enforced:
// it is reported (CI-BEN-002 warning), because a gate must compare the same thing to the same thing.
//
//   node bench/matrix/ci-compare.mjs --runtime chromium --report-dir <dir> \
//        --baseline bench/matrix/baselines/chromium-ubuntu-latest.json [--summary <out.md>]
//        [--threshold-pct 5] [--min-delta-ms 0.2] [--enforce] [--json <numbers.json>]
//
// The threshold is 06 §7.4's 5 %. The `--min-delta-ms` floor is this job's own (not 06's): frame
// times are quantised to the page's 0.1 ms timer, so a delta under two ticks is reported but never
// flagged. Hosted runners vary in CPU model, so the hardware class compared is core count, arch and
// GPU (SwiftShader on hosted runners), not the CPU model string.
//
// E11-T06 (rulings on BQ-04 / BQ-08): frame time, draw calls and memory each fail above 5 % (C-9.1
// #16), on the median of the repetitions' p95s. The 0.2 ms floor is PROPOSED (no owner doc) and
// binds only on a baseline under 4 ms (where 5 % is under two ticks); counters and memory have no
// floor. A real-engine report (`config.page: "engine"`) also gets 26 §13's absolute gates, and
// its per-rep p95 spread is published, never failed on; stub scenarios are listed by owner Epic.
import { appendFileSync, existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { basename, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { validateReport } from "./matrix-lib.mjs";
import {
  ENGINE_REPS,
  ENGINE_SCENARIO_IDS,
  ENGINE_STAGES,
  gateRows,
} from "../engine/engine-lib.mjs";
import { medianOfP95 } from "../stats.mjs";

export const DEFAULTS = Object.freeze({ thresholdPct: 5, minDeltaMs: 0.2, floorBelowMs: 4 });

/** A metric's unit, from its name: counters and memory are never floored. */
export const unitOf = (metric) =>
  metric.endsWith("draw calls") ? "count" : metric.endsWith(" MB") ? "MB" : "ms";

/**
 * A cell's p95: the median of its per-rep p95s when the report carries them (C-9.1 #16); NaN
 * when any rep's p95 is not finite, so a broken rep is never sorted into a passing median.
 */
const p95Of = (c) =>
  Array.isArray(c.p95PerRep) && c.p95PerRep.length
    ? c.p95PerRep.every((x) => typeof x === "number" && Number.isFinite(x))
      ? medianOfP95(c.p95PerRep)
      : NaN
    : c.p95;
const isEngine = (r) => r?.config?.page === "engine";

/** Memory metrics recorded as imprecise (quantised heap): never compared, never failing (M3). */
export function impreciseMetrics(report) {
  const out = new Set();
  for (const c of report?.cells ?? [])
    if (c.status === "ok" && c.memoryPrecision === "imprecise")
      out.add(`${c.scenario} memory MB`).add(`${c.scenario} peak memory MB`);
  return out;
}

/** The comparable figures of one report, keyed by metric name. */
export function metrics(report) {
  const out = {};
  for (const c of report.cells ?? []) {
    if (c.status !== "ok") continue;
    if (c.scenario === "B7") {
      for (const [mode, m] of Object.entries(c.modes ?? {}))
        out[`B7 ${mode} decode p95`] = m.decodeP95Ms;
    } else if (c.scenario === "B9") out["B9 cold init"] = c.coldInitToFirstFrameMs;
    else {
      out[`${c.scenario} frame p95`] = p95Of(c);
      // C-9.1 #16 also gates draw calls and memory; the same percentage applies, with no floor.
      if (typeof c.drawCalls === "number") out[`${c.scenario} draw calls`] = c.drawCalls;
      if (typeof c.memoryMb === "number") out[`${c.scenario} memory MB`] = c.memoryMb;
      if (typeof c.peakMemoryMb === "number") out[`${c.scenario} peak memory MB`] = c.peakMemoryMb;
    }
  }
  return out;
}

/** Reasons two reports are not like-for-like (empty when comparable). */
export function comparability(a, b) {
  const why = [];
  if (a.fixture?.sha256 !== b.fixture?.sha256) why.push("fixture differs");
  if (String(a.seed) !== String(b.seed)) why.push("seed differs");
  if (a.driverScriptSha256 !== b.driverScriptSha256) why.push("driver script differs");
  for (const k of ["reps", "durationMs", "soakMs", "bars", "page"])
    if (a.config?.[k] !== b.config?.[k]) why.push(`config.${k} differs`);
  if (a.manifest?.flagSet?.name !== b.manifest?.flagSet?.name) why.push("flag set differs");
  const cls = (r) => {
    const m = r.manifest?.machine ?? {};
    return `${m.cpuCount}|${m.arch}|${m.gpu}`;
  };
  if (cls(a) !== cls(b)) why.push("runner hardware class differs");
  return why;
}

/**
 * Rows of { metric, baseline, current, deltaMs, deltaPct, status }. `opts.enforce` renames the
 * regression status "REGRESSION (enforced)", and a metric the baseline has but this run lacks or
 * reads as non-finite (a not-runnable cell, a NaN, an imprecise memory reading against a precise
 * baseline) "MISSING (enforced)": a gate never passes on an absent figure. Otherwise an imprecise
 * memory figure is recorded, never failing. A frame time of 0 reads as missing; a zero baseline is
 * never compared ("ZERO BASELINE (enforced)" for a frame time under `enforce`).
 * @param {{ thresholdPct: number, minDeltaMs: number, floorBelowMs?: number, enforce?: boolean }} [opts]
 */
export function compareToBaseline(report, baseline, opts = DEFAULTS) {
  const cur = metrics(report);
  const base = baseline ? metrics(baseline) : {};
  return Object.keys({ ...base, ...cur }).map((metric) => {
    const b = Number.isFinite(base[metric]) ? base[metric] : null;
    const ms = unitOf(metric) === "ms";
    // A frame time of 0 ms is no measurement (nothing rendered or marked): read as missing.
    const c = ms && !(cur[metric] > 0) ? null : cur[metric];
    if (c == null || !Number.isFinite(c)) {
      // A baseline figure an enforced run cannot match fails, an imprecise reading included
      // (E11-T06 PR-2): a precise baseline never passes on an imprecise current run.
      const status =
        b != null && opts.enforce
          ? "MISSING (enforced)"
          : impreciseMetrics(report).has(metric)
            ? "imprecise memory (not compared)"
            : "missing in this run";
      return { metric, baseline: b, current: null, status };
    }
    if (b == null)
      return { metric, baseline: null, current: c, status: baseline ? "new" : "no baseline yet" };
    // A non-positive baseline has no percentage: never "within threshold". A zero frame time is a
    // broken baseline and fails under --enforce; a zero counter or memory figure is only reported.
    if (!(b > 0)) {
      const status =
        ms && opts.enforce ? "ZERO BASELINE (enforced)" : "zero baseline (not compared)";
      return { metric, baseline: b, current: c, status };
    }
    const deltaMs = c - b;
    const deltaPct = (deltaMs / b) * 100;
    // The floor binds frame times under `floorBelowMs` only (PROPOSED, ruling BQ-04).
    const floored = unitOf(metric) === "ms" && b < (opts.floorBelowMs ?? DEFAULTS.floorBelowMs);
    const big = !floored || Math.abs(deltaMs) >= opts.minDeltaMs - 1e-9;
    let status = "within threshold";
    if (big && deltaPct > opts.thresholdPct)
      status = opts.enforce ? "REGRESSION (enforced)" : "REGRESSION (recorded)";
    else if (big && deltaPct < -opts.thresholdPct) status = "improved";
    return { metric, baseline: b, current: c, deltaMs, deltaPct, status };
  });
}

const f = (v, d = 2) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(d) : "-");

/** 26 §13's absolute gates over a real-engine report; `enforce` names a breach as failing. */
export function absoluteGates(report, enforce = false) {
  if (!isEngine(report)) return [];
  const over = enforce ? "OVER GATE (enforced)" : "OVER GATE (recorded)";
  return (report.cells ?? [])
    .flatMap((c) => gateRows(c.status === "ok" ? { ...c, p95: p95Of(c) } : c))
    .map((g) => (g.status === "over gate" ? { ...g, status: over } : g));
}

/** Scenarios this engine report could not run (status `not-runnable`). */
export function notRunScenarios(report) {
  return (report.cells ?? []).filter((c) => c.status === "not-runnable").map((c) => c.scenario);
}

/** The per-rep p95 spread of each frame cell (AC2): published, never a failure (ruling BQ-08). */
export function spreads(report) {
  return (report.cells ?? [])
    .filter((c) => c.status === "ok" && Array.isArray(c.p95PerRep) && c.p95PerRep.length > 1)
    .map((c) => ({ scenario: c.scenario, reps: c.p95PerRep.length, spreadPct: c.spreadPct }));
}

/** Engine-section markdown: gates, spreads, stubs, the worst stage. Empty for a matrix report. */
export function renderEngineSection(report, gates, enforce = false) {
  if (!isEngine(report)) return "";
  const L = [
    "",
    "### 26 §13 absolute gates",
    "",
    "| Gate | This run | Status |",
    "| --- | --- | --- |",
  ];
  for (const g of gates) L.push(`| ${g.metric} | ${f(g.value)} | ${g.status} |`);
  L.push("", "### Spread of the per-rep p95s (published, never failing)", "");
  L.push("| Scenario | Reps | Spread % | Worst stage (06 §4.3) |", "| --- | --- | --- | --- |");
  const cells = Object.fromEntries((report.cells ?? []).map((c) => [c.scenario, c]));
  for (const s of spreads(report))
    L.push(
      `| ${s.scenario} | ${s.reps} | ${f(s.spreadPct, 1)} | ${cells[s.scenario]?.worstStage ?? "-"} |`,
    );
  for (const c of report.cells ?? []) {
    if (c.status !== "ok") continue;
    if (c.partial) L.push("", `**${c.scenario} ${c.partial}.**`);
    if (c.memoryPrecision === "imprecise")
      L.push("", `${c.scenario} memory: imprecise (quantised heap), recorded and not compared.`);
    if (c.memoryScope) L.push("", `${c.scenario} memory: ${c.memoryScope}.`);
  }
  const stubs = (report.cells ?? []).filter((c) => c.status === "stub");
  if (stubs.length)
    L.push(
      "",
      `**Not implemented (stubs):** ${stubs.map((c) => `${c.scenario} (${c.owner})`).join(", ")}.`,
    );
  const broken = (report.cells ?? []).filter((c) => c.status === "not-runnable");
  if (broken.length)
    L.push(
      "",
      `**Not runnable${enforce ? " — NOT RUN (enforced)" : " — NOT RUN, recorded only"}:** ${broken.map((c) => c.scenario).join(", ")} (see the report).`,
    );
  return L.join("\n") + "\n";
}

export function renderSummary({
  runtime,
  file,
  rows,
  notComparable,
  baselineName,
  thresholds,
  enforce = false,
}) {
  const L = enforce
    ? [
        `## Engine matrix (${runtime}) — GPU mode, enforced`,
        "",
        `Report \`${file}\`; baseline ${baselineName ? `\`${baselineName}\`` : "none committed yet"}; a like-for-like regression > ${thresholds.thresholdPct} % (C-9.1 #16) in frame time, draw calls or memory fails the job; a frame time under ${thresholds.floorBelowMs ?? DEFAULTS.floorBelowMs} ms also needs ≥ ${thresholds.minDeltaMs} ms (PROPOSED floor) (CI-BEN-001). A run that is not like-for-like is reported, never enforced.`,
        "",
      ]
    : [
        `## Engine matrix (${runtime}) — recording only, not gating`,
        "",
        `Report \`${file}\`; baseline ${baselineName ? `\`${baselineName}\`` : "none committed yet"}; flag at > ${thresholds.thresholdPct} % (06 §7.4); a frame time under ${thresholds.floorBelowMs ?? DEFAULTS.floorBelowMs} ms also needs ≥ ${thresholds.minDeltaMs} ms (two timer ticks, PROPOSED floor). A regression here never fails the build in R0. Hosted software-GL numbers are regression tracking only, not reference-hardware evidence (the committed matrix on \`main\` is).`,
        "",
      ];
  if (notComparable.length)
    L.push(`**Not like-for-like with the baseline:** ${notComparable.join("; ")}.`, "");
  L.push("| Metric | Baseline ms | This run ms | Delta ms | Delta % | Status |");
  L.push("| --- | --- | --- | --- | --- | --- |");
  for (const r of rows)
    L.push(
      `| ${r.metric} | ${f(r.baseline)} | ${f(r.current)} | ${f(r.deltaMs)} | ${f(r.deltaPct, 1)} | ${r.status} |`,
    );
  return L.join("\n") + "\n";
}

/**
 * The closed set of metric and gate names this script can emit for the real engine. It is the
 * comment job's allow-list: engine-bench-comment.yml carries it verbatim (ci-compare.test.ts checks
 * both that every emitted name is in it and that the workflow's copy is identical), so no text from
 * a pull request's run ever reaches the comment.
 */
export const COMMENT_NAMES = Object.freeze(
  ENGINE_SCENARIO_IDS.flatMap((id) => [
    ...(id === "B7"
      ? ["inline", "worker"].map((mode) => `B7 ${mode} decode p95`)
      : id === "B9"
        ? ["B9 cold init"]
        : ["frame p95", "draw calls", "memory MB", "peak memory MB"].map((m) => `${id} ${m}`)),
    ...gateRows({ scenario: id, status: "ok" }).map((g) => g.metric),
  ]),
);

/** Every row or gate status this script can emit: the comment job's fixed status set. */
export const COMMENT_STATUSES = Object.freeze([
  "within threshold",
  "improved",
  "new",
  "no baseline yet",
  "missing in this run",
  "imprecise memory (not compared)",
  "zero baseline (not compared)",
  "ZERO BASELINE (enforced)",
  "REGRESSION (recorded)",
  "REGRESSION (enforced)",
  "MISSING (enforced)",
  "within gate",
  "not measured",
  "OVER GATE (recorded)",
  "OVER GATE (enforced)",
]);

/** The comment job's input: names, numbers and statuses only, never free text from the run. */
export function numbersOf(rows, gates, report, enforce) {
  const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  return {
    schema: "cv-engine-bench-numbers/1",
    enforce,
    rows: rows.map((r) => ({
      metric: r.metric,
      baseline: num(r.baseline),
      current: num(r.current),
      deltaPct: num(r.deltaPct),
      status: r.status,
    })),
    gates: gates.map((g) => ({ metric: g.metric, value: num(g.value), status: g.status })),
    // AC1: the worst 06 §4.3 stage per scenario, only ever one of the nine stage names.
    spreads: spreads(report).map((x) => {
      const w = report.cells.find((c) => c.scenario === x.scenario)?.worstStage;
      return {
        scenario: x.scenario,
        spreadPct: num(x.spreadPct),
        worstStage: ENGINE_STAGES.includes(w) ? w : null,
      };
    }),
  };
}

/** Picks the single report for `runtime` in `dir`; null when there is none. */
export function findReport(dir, runtime) {
  if (!existsSync(dir)) return null;
  const files = readdirSync(dir)
    .filter((n) => n.startsWith(`${runtime}-`) && n.endsWith(".json"))
    .sort();
  return files.length ? join(dir, files[files.length - 1]) : null;
}

/** CLI body; returns the exit code (1 only when the run itself failed). */
export function run(
  argv,
  io = { log: console.log, error: console.error, append: appendFileSync, write: writeFileSync },
) {
  const get = (flag) => {
    const i = argv.indexOf(flag);
    return i >= 0 ? argv[i + 1] : undefined;
  };
  const runtime = get("--runtime");
  const dir = get("--report-dir");
  if (!runtime || !dir) {
    io.error(
      "usage: ci-compare.mjs --runtime <r> --report-dir <dir> [--baseline <f>] [--summary <f>] [--enforce]",
    );
    return 2;
  }
  const thresholds = {
    thresholdPct: Number(get("--threshold-pct") ?? DEFAULTS.thresholdPct),
    minDeltaMs: Number(get("--min-delta-ms") ?? DEFAULTS.minDeltaMs),
    floorBelowMs: DEFAULTS.floorBelowMs,
  };
  const enforce = argv.includes("--enforce");
  const fail = (msg) => {
    io.error(`::error title=engine-matrix ${runtime}::CI-BEN-002: ${msg}`);
    const out = get("--summary");
    if (out) io.append(out, `## Engine matrix (${runtime}) — FAILED TO RUN\n\n${msg}\n`);
    return 1;
  };
  const path = findReport(resolve(dir), runtime);
  if (!path) return fail(`no ${runtime} report was produced: the harness did not finish`);
  let report;
  try {
    report = JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return fail(`${basename(path)} is not valid JSON`);
  }
  const problems = validateReport(report);
  if (report.runError) problems.push(`harness run error: ${report.runError}`);
  if (problems.length) return fail(`${basename(path)} is not usable: ${problems.join("; ")}`);

  const bPath = get("--baseline");
  let baseline = null;
  if (bPath && existsSync(bPath)) {
    try {
      baseline = JSON.parse(readFileSync(bPath, "utf8"));
    } catch {
      return fail(`baseline ${basename(bPath)} is not valid JSON`);
    }
    const bad = validateReport(baseline);
    if (bad.length) return fail(`baseline ${basename(bPath)} is invalid: ${bad.join("; ")}`);
  }
  // An enforced engine gate is taken on C-9.1's five reps, never on a `--reps 1` pair.
  if (enforce && isEngine(report) && !(Number(report.config?.reps) >= ENGINE_REPS))
    return fail(
      `${basename(path)} has ${report.config?.reps} reps; an enforced engine run needs ${ENGINE_REPS}`,
    );
  const notComparable = baseline ? comparability(report, baseline) : [];
  // Enforcement needs a like-for-like baseline: with none, or a different one, it only reports.
  const enforcing = enforce && baseline != null && notComparable.length === 0;
  const rows = compareToBaseline(report, baseline, { ...thresholds, enforce: enforcing });
  const gates = absoluteGates(report, enforce);
  const md0 = renderSummary({
    runtime,
    file: basename(path),
    rows,
    notComparable,
    baselineName: baseline ? basename(String(bPath)) : null,
    thresholds,
    enforce,
  });
  const md = md0 + renderEngineSection(report, gates, enforce);
  io.log(md);
  const out = get("--summary");
  if (out) io.append(out, md);
  // E11-T06 PR-2: the numbers alone, for engine-bench-comment.yml (it re-validates every field).
  const json = get("--json");
  if (json) io.write(json, JSON.stringify(numbersOf(rows, gates, report, enforce)));
  if (enforce && notComparable.length > 0)
    io.log(
      `::warning title=engine-matrix ${runtime}::CI-BEN-002: not like-for-like with the baseline (${notComparable.join("; ")}): regressions reported, not enforced`,
    );
  const missing = rows.filter((r) => r.status === "MISSING (enforced)");
  if (missing.length > 0)
    io.error(
      `::error title=engine-matrix ${runtime}::CI-BEN-001: missing or non-finite in this run: ${missing.map((r) => r.metric).join(", ")}`,
    );
  const zero = rows.filter((r) => r.status === "ZERO BASELINE (enforced)");
  if (zero.length > 0)
    io.error(
      `::error title=engine-matrix ${runtime}::CI-BEN-001: zero baseline: ${zero.map((r) => r.metric).join(", ")}`,
    );
  // Under --enforce a not-runnable scenario fails with or without a like-for-like baseline: a gate
  // that was never measured never passes.
  const notRun = enforce && isEngine(report) ? notRunScenarios(report) : [];
  if (notRun.length > 0)
    io.error(`::error title=engine-matrix ${runtime}::CI-BEN-001: not run: ${notRun.join(", ")}`);
  const regressed = rows.filter((r) => r.status === "REGRESSION (enforced)");
  const breached = gates.filter((g) => g.status === "OVER GATE (enforced)");
  if (breached.length > 0)
    io.error(
      `::error title=engine-matrix ${runtime}::CI-BEN-001: over the 26 §13 gate: ${breached.map((g) => g.metric).join(", ")}`,
    );
  if (regressed.length > 0) {
    io.error(
      `::error title=engine-matrix ${runtime}::CI-BEN-001: regression above ${thresholds.thresholdPct} %: ${regressed.map((r) => r.metric).join(", ")}`,
    );
    return 1;
  }
  return breached.length + missing.length + zero.length + notRun.length > 0 ? 1 : 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(run(process.argv.slice(2)));
}
