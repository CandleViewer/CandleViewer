#!/usr/bin/env node
// E10-Q04 PR-4 (#303; BQ-Q04-03, the critic's correction): folds the three cold-start sets of a CI
// run into one recorded line. Per set: p50 and p95 of `shell_cold_start_ms` (with n = 10 the p95
// is the maximum), the spread (max / min of the run totals) and the calibration. Across sets: the
// median of the three p95s (06 §7.4's gate value, recorded only) and the median of the three
// p50s, the trend value. The trend is flagged at >= 15 % above a baseline sets file (PR-5 commits
// it); a flag never fails the run (`30` §4.4, R0 records). A missing or unreadable set report
// exits 1: no report is a harness failure, never a pass.
//
//   node scripts/perf-sets.mjs --target electron --out <dir> [--baseline <file>] [--summary <file>]
//        <set dir> <set dir> <set dir>
import { appendFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

export const TREND_BAND = 0.15;
const TOTAL = "shell_cold_start_ms";

/** The median of three or more values (the lower middle for an even count). */
export function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor((sorted.length - 1) / 2)];
}

/** One set's line from its `cv-shell-perf-report/1`; throws when the report lacks the total. */
export function setLine(report) {
  const total = report.stages.find((s) => s.stage === TOTAL);
  const runs = report.runs.map((r) => r[TOTAL]).filter((v) => typeof v === "number");
  if (total === undefined || runs.length === 0) throw new Error(`no ${TOTAL} in the report`);
  return {
    p50: total.p50,
    p95: total.p95,
    n: total.n,
    spread: Math.max(...runs) / Math.min(...runs),
    calibrationCpu: report.calibration.cpu,
  };
}

/** The run's line over its sets, with the trend judged against a baseline line (or null). */
export function foldSets(target, reports, baseline) {
  if (reports.length < 3) throw new Error(`${reports.length} set(s); 06 §7.4 asks for 3`);
  const sets = reports.map(setLine);
  const trendP50Ms = median(sets.map((s) => s.p50));
  const baseMs = baseline?.trendP50Ms ?? null;
  const ratio = baseMs === null ? null : trendP50Ms / baseMs;
  return {
    schema: "cv-shell-perf-sets/1",
    target,
    sets,
    medianP95Ms: median(sets.map((s) => s.p95)),
    trendP50Ms,
    baselineP50Ms: baseMs,
    flagged: ratio !== null && ratio >= 1 + TREND_BAND,
  };
}

export function toMarkdown(r) {
  const f = (v) => (v === null ? "n/a" : v.toFixed(1));
  const trend =
    r.baselineP50Ms === null
      ? "no baseline yet (E10-Q04 PR-5)"
      : `baseline ${f(r.baselineP50Ms)} ms: ${r.flagged ? "**FLAG** (>= 15 %)" : "within 15 %"}`;
  return [
    `### Shell cold start, ${r.target}: 3 sets of 10 (recording, not gating)`,
    "",
    "| Set | n | p50 ms | p95 ms | spread (max/min) | calibration cpu ms |",
    "| --- | --- | --- | --- | --- | --- |",
    ...r.sets.map(
      (s, i) =>
        `| ${i + 1} | ${s.n} | ${f(s.p50)} | ${f(s.p95)} | ${s.spread.toFixed(2)} | ` +
        `${f(s.calibrationCpu)} |`,
    ),
    "",
    `Median of the p95s: ${f(r.medianP95Ms)} ms. Trend (median of the p50s): ` +
      `${f(r.trendP50Ms)} ms; ${trend}. CI numbers are never compared with the budget.`,
    "",
  ].join("\n");
}

function main(argv) {
  const opts = {};
  const dirs = [];
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i].startsWith("--")) opts[argv[i].slice(2)] = argv[(i += 1)];
    else dirs.push(argv[i]);
  }
  const target = opts.target;
  const reports = dirs.map((d) => {
    const file = path.join(d, `${target}-cold-start.json`);
    if (!existsSync(file)) throw new Error(`missing set report ${file}`);
    return JSON.parse(readFileSync(file, "utf8"));
  });
  const base = opts.baseline;
  const baseline = base && existsSync(base) ? JSON.parse(readFileSync(base, "utf8")) : null;
  const line = foldSets(target, reports, baseline);
  writeFileSync(path.join(opts.out, `${target}-sets.json`), `${JSON.stringify(line, null, 2)}\n`);
  if (opts.summary) appendFileSync(opts.summary, toMarkdown(line));
  console.log(`shell-perf-sets ${JSON.stringify(line)}`);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    console.error(`perf-sets: ${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  }
}
