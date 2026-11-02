// E10-Q04 cold-start report (budget #10, `06` §2 row 10; BQ-Q04-03/04/10): nearest-rank p50/p95
// per stage, the budget line and its verdict, written as `cv-shell-perf-report/1` JSON plus a
// markdown table. Pure maths and formatting; the only I/O is `writeReport`. A budget here is a
// fixed spec number: the calibration is recorded beside it and never widens it.
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import type { Calibration } from "@candleviewer/config/perf-calibration";

export type Target = "electron" | "browser";
/** `ci`: compared with a CI baseline, never with the budget (ticket Test plan; `30` §4.4). */
export type HostClass = "reference" | "below-class" | "ci";
export type Verdict = "PASS" | "FAIL" | "INCONCLUSIVE" | "RECORDED";

/** One measured launch: each stage's time in ms from the run's t0. */
export type RunSample = Readonly<Record<string, number>>;

export interface StageStats {
  readonly stage: string;
  readonly n: number;
  readonly p50: number;
  readonly p95: number;
}

/** The shell-interactive stage the budget is read on (BQ-Q04-02). */
export const TOTAL_STAGE = "shell_cold_start_ms";
/** 06 row 10's literal measure, reported beside the total from t0 (BQ-Q04-02 B as a stage). */
export const SINCE_READY = "whenReady→shell_cold_start_ms";
/** Electron ≤ 3 s (`06` §2 row 10, C-14.2); browser ≤ 4 s (`20` §14). Never scaled. */
export const BUDGET_MS: Readonly<Record<Target, number>> = { electron: 3_000, browser: 4_000 };

/** Nearest-rank percentile: the value at rank ⌈p/100 × n⌉ (so with n = 10, p95 is the maximum). */
export function nearestRank(values: readonly number[], p: number): number {
  if (values.length === 0) throw new Error("nearestRank: no samples");
  const sorted = [...values].sort((a, b) => a - b);
  const rank = Math.max(1, Math.ceil((p / 100) * sorted.length));
  return sorted[rank - 1] as number;
}

/** p50/p95 per stage, in the order stages are first seen; a stage missing from a run counts n−1. */
export function summarize(runs: readonly RunSample[]): StageStats[] {
  const order: string[] = [];
  for (const run of runs) for (const s of Object.keys(run)) if (!order.includes(s)) order.push(s);
  return order.map((stage) => {
    return stats(
      stage,
      runs.map((r) => r[stage]).filter((v): v is number => v !== undefined),
    );
  });
}

const stats = (stage: string, values: readonly number[]): StageStats => ({
  stage,
  n: values.length,
  p50: nearestRank(values, 50),
  p95: nearestRank(values, 95),
});

/**
 * The stage that took longest: per run, stages sorted by time, each one's segment is its time minus
 * the previous stage's (the first from t0); the stage with the largest median segment wins (AC6).
 */
export function slowestStage(runs: readonly RunSample[]): string {
  const segments = new Map<string, number[]>();
  for (const run of runs) {
    let previous = 0;
    for (const [stage, at] of Object.entries(run).sort((a, b) => a[1] - b[1])) {
      segments.set(stage, [...(segments.get(stage) ?? []), at - previous]);
      previous = at;
    }
  }
  let best = { stage: "", ms: Number.NEGATIVE_INFINITY };
  for (const [stage, values] of segments) {
    const ms = nearestRank(values, 50);
    if (ms > best.ms) best = { stage, ms };
  }
  return best.stage;
}

export interface BudgetLine {
  readonly stage: string;
  readonly limitMs: number;
  readonly p95Ms: number | null;
  readonly verdict: Verdict;
  readonly slowestStage: string;
}

/**
 * The verdict rule (BQ-Q04-04, the #220 evidence rule): only a reference-class run can FAIL; a
 * below-class host that meets the budget is conservative evidence and one that misses it is
 * inconclusive; a CI run is RECORDED, informational only. A missing total is never a pass.
 */
export function budgetLine(
  target: Target,
  runs: readonly RunSample[],
  host: HostClass,
): BudgetLine {
  const limitMs = BUDGET_MS[target];
  const total = summarize(runs).find((s) => s.stage === TOTAL_STAGE);
  const p95Ms = total === undefined || total.n < runs.length ? null : total.p95;
  const met = p95Ms !== null && p95Ms <= limitMs;
  const verdict: Verdict =
    host === "ci" ? "RECORDED" : met ? "PASS" : host === "reference" ? "FAIL" : "INCONCLUSIVE";
  return { stage: TOTAL_STAGE, limitMs, p95Ms, verdict, slowestStage: slowestStage(runs) };
}

export interface ShellPerfReport {
  readonly schema: "cv-shell-perf-report/1";
  readonly target: Target;
  readonly host: HostClass;
  readonly protocol: string;
  readonly priming: number;
  readonly calibration: Calibration;
  readonly versions: Readonly<Record<string, string>>;
  readonly stages: readonly StageStats[];
  readonly budget: BudgetLine;
  readonly runs: readonly RunSample[];
  /** Stub requests nothing answered: a shell call the stub lacks shows here, not as a guess. */
  readonly unanswered: readonly string[];
}

export type ReportInput = Omit<
  ShellPerfReport,
  "schema" | "protocol" | "priming" | "stages" | "budget"
>;

export function buildReport(input: ReportInput): ShellPerfReport {
  return {
    schema: "cv-shell-perf-report/1",
    protocol: "app-cold, OS-warm: fresh profile per run, 1 discarded priming launch",
    priming: 1,
    ...input,
    stages: [...summarize(input.runs), ...sinceReady(input.runs)],
    budget: budgetLine(input.target, input.runs, input.host),
  };
}

/** whenReady → interactive per run (Electron only: a browser run has no whenReady). */
function sinceReady(runs: readonly RunSample[]): StageStats[] {
  const spans = runs.flatMap((r) => {
    const ready = r["whenReady"];
    const total = r[TOTAL_STAGE];
    return ready === undefined || total === undefined ? [] : [total - ready];
  });
  return spans.length === 0 ? [] : [stats(SINCE_READY, spans)];
}

const ms = (v: number | null): string => (v === null ? "—" : v.toFixed(1));

export function toMarkdown(r: ShellPerfReport): string {
  const b = r.budget;
  const spread =
    r.calibration.cpuSpread === undefined ? "" : `, spread ${ms(r.calibration.cpuSpread)}`;
  return [
    `## Shell cold start (${r.target}), n = ${r.runs.length}, host ${r.host}`,
    "",
    `Protocol: ${r.protocol}. Nearest rank: with n = 10, p95 is the maximum.`,
    `Calibration (recorded, never applied to the budget): cpu ${ms(r.calibration.cpu)} ms${spread}.`,
    "",
    "| Stage | n | p50 ms | p95 ms |",
    "|---|---|---|---|",
    ...r.stages.map((s) => `| ${s.stage} | ${s.n} | ${ms(s.p50)} | ${ms(s.p95)} |`),
    "",
    `Budget: ${b.stage} p95 ${ms(b.p95Ms)} ms ≤ ${b.limitMs} ms: **${b.verdict}**` +
      `${r.host === "ci" ? " (informational on CI)" : ""}; slowest stage ${b.slowestStage}.`,
    ...(r.unanswered.length > 0
      ? ["", `Unanswered stub requests: ${r.unanswered.join(", ")}`]
      : []),
    "",
  ].join("\n");
}

/** Writes `<target>-cold-start.json` and `.md` under `dir`; returns the two paths. */
export function writeReport(dir: string, r: ShellPerfReport): [string, string] {
  mkdirSync(dir, { recursive: true });
  const base = path.join(dir, `${r.target}-cold-start`);
  writeFileSync(`${base}.json`, `${JSON.stringify(r, null, 2)}\n`);
  writeFileSync(`${base}.md`, toMarkdown(r));
  return [`${base}.json`, `${base}.md`];
}
