#!/usr/bin/env node
// E06-T02 — the CI matrix job's comparison against the committed baseline. Recording only
// (R0, `30-release-roadmap.md` §4.4 "not yet gating"): a regression is printed, never an
// exit code. A failure to RUN is an exit code: no report, an invalid report (`validateReport`),
// or a run error from the harness (watchdog, early shell exit) all exit 1 so the job goes red.
//
//   node bench/matrix/ci-compare.mjs --runtime chromium --report-dir <dir> \
//        --baseline bench/matrix/baselines/chromium-ubuntu-latest.json [--summary <out.md>]
//        [--threshold-pct 5] [--min-delta-ms 0.2]
//
// The threshold is 06 §7.4's 5 %. The `--min-delta-ms` floor is this job's own (not 06's): frame
// times are quantised to the page's 0.1 ms timer, so a delta under two ticks is reported but never
// flagged. Hosted runners vary in CPU model, so the hardware class compared is core count, arch and
// GPU (SwiftShader on hosted runners), not the CPU model string.
import { appendFileSync, existsSync, readFileSync, readdirSync } from "node:fs";
import { basename, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { validateReport } from "./matrix-lib.mjs";

export const DEFAULTS = Object.freeze({ thresholdPct: 5, minDeltaMs: 0.2 });

/** The comparable figures of one report, keyed by metric name. */
export function metrics(report) {
  const out = {};
  for (const c of report.cells ?? []) {
    if (c.status !== "ok") continue;
    if (c.scenario === "B7") {
      for (const [mode, m] of Object.entries(c.modes ?? {}))
        out[`B7 ${mode} decode p95`] = m.decodeP95Ms;
    } else if (c.scenario === "B9") out["B9 cold init"] = c.coldInitToFirstFrameMs;
    else out[`${c.scenario} frame p95`] = c.p95;
  }
  return out;
}

/** Reasons two reports are not like-for-like (empty when comparable). */
export function comparability(a, b) {
  const why = [];
  if (a.fixture?.sha256 !== b.fixture?.sha256) why.push("fixture differs");
  if (String(a.seed) !== String(b.seed)) why.push("seed differs");
  if (a.driverScriptSha256 !== b.driverScriptSha256) why.push("driver script differs");
  for (const k of ["reps", "durationMs", "soakMs", "bars"])
    if (a.config?.[k] !== b.config?.[k]) why.push(`config.${k} differs`);
  if (a.manifest?.flagSet?.name !== b.manifest?.flagSet?.name) why.push("flag set differs");
  const cls = (r) => {
    const m = r.manifest?.machine ?? {};
    return `${m.cpuCount}|${m.arch}|${m.gpu}`;
  };
  if (cls(a) !== cls(b)) why.push("runner hardware class differs");
  return why;
}

/** Rows of { metric, baseline, current, deltaMs, deltaPct, status }. */
export function compareToBaseline(report, baseline, opts = DEFAULTS) {
  const cur = metrics(report);
  const base = baseline ? metrics(baseline) : {};
  return Object.keys({ ...base, ...cur }).map((metric) => {
    const b = base[metric];
    const c = cur[metric];
    if (c == null) return { metric, baseline: b, current: null, status: "missing in this run" };
    if (b == null)
      return { metric, baseline: null, current: c, status: baseline ? "new" : "no baseline yet" };
    const deltaMs = c - b;
    const deltaPct = b > 0 ? (deltaMs / b) * 100 : null;
    const big = Math.abs(deltaMs) >= opts.minDeltaMs - 1e-9;
    let status = "within threshold";
    if (big && deltaPct != null && deltaPct > opts.thresholdPct) status = "REGRESSION (recorded)";
    else if (big && deltaPct != null && deltaPct < -opts.thresholdPct) status = "improved";
    return { metric, baseline: b, current: c, deltaMs, deltaPct, status };
  });
}

const f = (v, d = 2) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(d) : "-");

export function renderSummary({ runtime, file, rows, notComparable, baselineName, thresholds }) {
  const L = [
    `## Engine matrix (${runtime}) — recording only, not gating`,
    "",
    `Report \`${file}\`; baseline ${baselineName ? `\`${baselineName}\`` : "none committed yet"}; flag at > ${thresholds.thresholdPct} % (06 §7.4) and ≥ ${thresholds.minDeltaMs} ms (two timer ticks). A regression here never fails the build in R0. Hosted software-GL numbers are regression tracking only, not reference-hardware evidence (the committed matrix on \`main\` is).`,
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

/** Picks the single report for `runtime` in `dir`; null when there is none. */
export function findReport(dir, runtime) {
  if (!existsSync(dir)) return null;
  const files = readdirSync(dir)
    .filter((n) => n.startsWith(`${runtime}-`) && n.endsWith(".json"))
    .sort();
  return files.length ? join(dir, files[files.length - 1]) : null;
}

/** CLI body; returns the exit code (1 only when the run itself failed). */
export function run(argv, io = { log: console.log, error: console.error, append: appendFileSync }) {
  const get = (flag) => {
    const i = argv.indexOf(flag);
    return i >= 0 ? argv[i + 1] : undefined;
  };
  const runtime = get("--runtime");
  const dir = get("--report-dir");
  if (!runtime || !dir) {
    io.error(
      "usage: ci-compare.mjs --runtime <r> --report-dir <dir> [--baseline <f>] [--summary <f>]",
    );
    return 2;
  }
  const thresholds = {
    thresholdPct: Number(get("--threshold-pct") ?? DEFAULTS.thresholdPct),
    minDeltaMs: Number(get("--min-delta-ms") ?? DEFAULTS.minDeltaMs),
  };
  const fail = (msg) => {
    io.error(`::error title=engine-matrix ${runtime}::${msg}`);
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
  const rows = compareToBaseline(report, baseline, thresholds);
  const md = renderSummary({
    runtime,
    file: basename(path),
    rows,
    notComparable: baseline ? comparability(report, baseline) : [],
    baselineName: baseline ? basename(String(bPath)) : null,
    thresholds,
  });
  io.log(md);
  const out = get("--summary");
  if (out) io.append(out, md);
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(run(process.argv.slice(2)));
}
