// Types for perf-budget-guard.mjs: the guard that every perf wall-clock bound uses budget().
export const EXEMPT_REASONS: readonly string[];
export const GOOD_UPPER: RegExp;
export function bareBounds(source: string): string[];
export function perfTestFiles(dir: string): string[];
export function scanPerfTests(dir: string): { files: string[]; offenders: string[] };
