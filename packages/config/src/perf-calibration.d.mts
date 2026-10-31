// Types for perf-calibration.mjs: the runner calibration behind every wall-clock perf budget.
export interface Calibration {
  readonly cpu: number;
  readonly cpuSpread?: number;
  readonly resampled?: boolean;
  readonly refuse?: boolean;
}
export interface Judgement {
  cpu: number;
  spread: number;
  resampled: boolean;
  warn: boolean;
  refuse: boolean;
}
export const REFERENCE_CPU_MS: number;
export const MAX_SCALE: number;
export const MAX_SPREAD: number;
export const WARN_SPREAD: number;
export function judgeSamples(first: readonly number[], second?: readonly number[]): Judgement;
export function needsResample(first: readonly number[]): boolean;
export function spreadWarning(pid: number, spread: number, cpu: number, resampled: boolean): string;
export function summary(): string;
export const probeSink: { value: number };
export function calibration(): Calibration;
export function scaleFor(measured: number, reference: number): number;
export function scaleFromCalibration(
  measured: Calibration,
  reference?: number,
  max?: number,
): number;
export function runnerScale(): number;
export function budget(specMs: number): number;
export function why(measured: number, specMs: number, cal?: Calibration): string;
export interface LastAssertion {
  measured: number;
  bound: number;
  calibration: number;
}
export function takeLastAssertion(): LastAssertion | undefined;
export function attemptLine(
  name: string,
  attempt: number,
  state: string,
  seen: Partial<LastAssertion> | undefined,
): string;
export function retryWarning(
  name: string,
  attempt: number,
  measured: number | undefined,
  calibration: number | undefined,
  bound: number | undefined,
): string;
