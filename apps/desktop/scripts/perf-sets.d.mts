// Types for perf-sets.mjs (E10-Q04 PR-4): the three-set fold of the cold-start reports.
import type { ShellPerfReport } from "../e2e/perf/support/report";

export interface SetLine {
  readonly p50: number;
  readonly p95: number;
  readonly n: number;
  readonly spread: number;
  readonly calibrationCpu: number;
}
export interface SetsLine {
  readonly schema: "cv-shell-perf-sets/1";
  readonly target: string;
  readonly sets: readonly SetLine[];
  readonly medianP95Ms: number;
  readonly trendP50Ms: number;
  readonly baselineP50Ms: number | null;
  readonly flagged: boolean;
}
export const TREND_BAND: number;
export function median(values: readonly number[]): number;
export function setLine(report: ShellPerfReport): SetLine;
export function foldSets(
  target: string,
  reports: readonly ShellPerfReport[],
  baseline: { readonly trendP50Ms: number } | null,
): SetsLine;
export function toMarkdown(r: SetsLine): string;
