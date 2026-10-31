import console from "node:console";
import process from "node:process";
import { performance } from "node:perf_hooks";

// Runner calibration for the wall-clock budgets in `*.perf.test.ts` (the engine-bench job).
//
// A budget is an absolute number from the spec (06 §2 / the ticket). A slower shared runner moves
// every timing, so an absolute bound fails by construction (a 120.459 ms median against a 120 ms
// budget). One fixed, in-process CPU probe measures how slow this runner is against the reference;
// `budget(ms)` widens the spec number by that ratio, never tightens it below the spec number, and
// refuses to judge at all above MAX_SCALE. This normalises runner class (capacity), not momentary
// contention (C-9.3), except on the resampled branch: there the factor uses the median of ten (by
// ruling), which can widen the bound on a contended run, still capped at MAX_SCALE.
//
// A random-access memory probe was tried and dropped: on the first ubuntu-latest engine-bench run
// (12 processes) the CPU probe was stable (20.59-21.15 ms, sample spread 1.00-1.21) but the 64 MiB
// memory walk varied 7.4-19.6 ms with sample spread up to 2.66, so its trust check failed 10 of 18
// perf tests with no real budget miss. Its variance made the gate flakier, not safer.
//
// Runner normalisation is not loosening a budget: the spec numbers stay at every call site. The
// reference figure changes only through the `bench:baseline` path (CODEOWNER-approved PR with a
// written justification, 06 section 7.4). Never bump a budget number.

/**
 * The CPU probe reference: the least CPU calibration over five ubuntu-latest engine-bench runs on
 * PR #5142 (2026-10-31; per-run least 20.587 / 17.984 / 20.527 / 17.986 / 20.527 ms, the table in
 * the PR). Re-take it when engine-bench moves to the self-hosted runner (E03-T14). Raising it
 * loosens the gate: baseline-class (06 section 7.4).
 */
export const REFERENCE_CPU_MS = 17.984;

/** Above this factor the test fails with "runner too slow" instead of passing widened. */
export const MAX_SCALE = 3;

const CPU_ITERATIONS = 6_000_000;
const SAMPLES = 5;

/**
 * Calibration is untrustworthy above this: max/min of a set of five CPU samples, and only when a
 * second set of five also exceeds it. A trust check that can fail on its own is the flake the
 * calibration removes: the observed per-run maxima were 1.21 / 1.33 / 1.43 / 1.30 / 1.47.
 */
export const MAX_SPREAD = 2.0;

/** Above this (but accepted) the run emits one `::warning` annotation naming process and spread. */
export const WARN_SPREAD = 1.5;

/** Written by the probes so the loops stay observable and cannot be eliminated. */
export const probeSink = { value: 0 };

/** One timed pass of a seeded integer hash (xorshift/imul mix): no allocation, no memory traffic. */
function cpuPass() {
  let h = 0x9e3779b9 | 0;
  const start = performance.now();
  for (let i = 0; i < CPU_ITERATIONS; i += 1) {
    h = Math.imul(h ^ (h >>> 15), 0x85ebca6b) ^ i;
    h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35);
  }
  const elapsed = performance.now() - start;
  probeSink.value = h;
  return elapsed;
}

/** `SAMPLES` timed passes (no warm-up). */
function samples(pass) {
  const out = [];
  for (let i = 0; i < SAMPLES; i += 1) out.push(pass());
  return out;
}

const spreadOf = (values) => {
  const best = Math.min(...values);
  return best > 0 ? Math.max(...values) / best : Number.POSITIVE_INFINITY;
};

const medianOf = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
};

/**
 * The pure trust decision. `first` is the first set of five samples (after the warm-up); `second`
 * is the optional resample, taken only when the first set's spread (max/min) exceeds MAX_SPREAD.
 * Refuses only when BOTH sets exceed MAX_SPREAD. Without a resample the CPU figure is the least of
 * the five: REFERENCE_CPU_MS was derived like-for-like from least-of-five. Only the noisy branch
 * (a resample was taken) uses the median of all ten, as the ruling requires. `spread` is the one
 * used: the first set's, or all ten's when resampled. `warn` is set when it exceeds WARN_SPREAD
 * and the calibration is accepted.
 */
export function judgeSamples(first, second) {
  const firstSpread = spreadOf(first);
  const resampled = firstSpread > MAX_SPREAD && second !== undefined;
  if (!resampled) {
    return {
      cpu: Math.min(...first),
      spread: firstSpread,
      resampled: false,
      warn: firstSpread > WARN_SPREAD && firstSpread <= MAX_SPREAD,
      refuse: firstSpread > MAX_SPREAD,
    };
  }
  const all = [...first, ...second];
  const spread = spreadOf(all);
  const refuse = spreadOf(second) > MAX_SPREAD;
  return {
    cpu: medianOf(all),
    spread,
    resampled: true,
    warn: !refuse && spread > WARN_SPREAD,
    refuse,
  };
}

/** Does the first set need a second one? (the sole trigger for the resample) */
export const needsResample = (first) => !(spreadOf(first) <= MAX_SPREAD);

let memo;
let warned = false;

/** The warning annotation (stdout, once per test file: each perf file is its own module graph). */
export function spreadWarning(pid, spread, cpu, resampled) {
  return (
    `::warning title=perf calibration::process ${pid} cpu spread ${spread.toFixed(3)} > ` +
    `${WARN_SPREAD} (cpu ${cpu.toFixed(3)} ms, resampled ${resampled ? "yes" : "no"})`
  );
}

/**
 * The CPU probe, measured once per test file (per module graph): `{ cpu, cpuSpread, resampled, refuse }` (ms; spread is
 * max/min of the samples used). Warms up once, takes five samples, and takes five more only when
 * the first five spread above MAX_SPREAD.
 */
export function calibration() {
  if (memo === undefined) {
    cpuPass();
    const first = samples(cpuPass);
    const second = needsResample(first) ? samples(cpuPass) : undefined;
    const j = judgeSamples(first, second);
    memo = { cpu: j.cpu, cpuSpread: j.spread, resampled: j.resampled, refuse: j.refuse };
    if (j.warn && !warned) {
      warned = true;
      console.info(spreadWarning(process.pid, j.spread, j.cpu, j.resampled));
    }
  }
  return memo;
}

/** One probe's widening factor: `>= 1` always; a non-finite or non-positive input falls back to 1. */
export function scaleFor(measured, reference) {
  if (!Number.isFinite(measured) || !Number.isFinite(reference)) return 1;
  if (measured <= 0 || reference <= 0) return 1;
  return Math.max(1, measured / reference);
}

/** One summary line per process (printed by the perf setup file, before any timed region). */
export function summary() {
  const c = calibration();
  const factor = scaleFor(c.cpu, REFERENCE_CPU_MS);
  return (
    `calibration cpu=${c.cpu.toFixed(3)} cpu spread=${c.cpuSpread.toFixed(3)} ` +
    `resampled=${c.resampled ? "yes" : "no"} reference=${REFERENCE_CPU_MS} factor=${factor.toFixed(3)}`
  );
}

/**
 * The factor for a measured CPU probe: `max(1, cpu / reference)`. Throws when the calibration was
 * refused (`refuse`: both sets of five spread above `MAX_SPREAD`; a bare `cpuSpread` above it counts
 * too; untrustworthy, fail closed, measured value appended), and above
 * `max` (too slow to judge; a widened pass would hide a regression). A non-finite cpu falls back
 * to 1; a missing spread skips the trust check.
 */
export function scaleFromCalibration(measured, reference = REFERENCE_CPU_MS, max = MAX_SCALE) {
  const factor = scaleFor(measured.cpu, reference);
  const spread = measured.cpuSpread;
  const bad =
    measured.refuse === true ||
    (measured.refuse === undefined && spread !== undefined && !(spread <= MAX_SPREAD));
  if (bad && Number.isFinite(measured.cpu)) {
    throw new RangeError(
      `calibration untrustworthy (cpu ${measured.cpu.toFixed(2)} ms, sample spread ${spread} > ` +
        `limit ${MAX_SPREAD}): not judging the perf budgets on this runner`,
    );
  }
  if (factor > max) {
    throw new RangeError(
      `runner too slow (calibration cpu ${measured.cpu.toFixed(2)} ms vs reference ${reference} ms, ` +
        `factor ${factor.toFixed(2)} > ${max}): not judging the perf budgets on this runner`,
    );
  }
  return factor;
}

/** The factor for this process on this runner. */
export function runnerScale() {
  return scaleFromCalibration(calibration());
}

/** Scale a spec budget (ms) for this runner. Keep the spec number visible at the call site. */
export function budget(specMs) {
  return specMs * runnerScale();
}

/**
 * An assertion message: measured vs the scaled bound and calibration (shown on a failure). Every
 * call logs just the margin; the calibration itself is logged once per test file by the setup file.
 * On the refusal paths (runner too slow, calibration untrustworthy) it rethrows the RangeError with
 * the measured value appended, so no failure hides the number under test.
 */
export function why(measured, specMs, cal = calibration()) {
  let scale;
  try {
    scale = scaleFromCalibration(cal);
  } catch (error) {
    // Fail closed, but say what was measured: the refusal alone hides the number under test.
    if (!(error instanceof RangeError)) throw error;
    throw new RangeError(`${error.message} [measured ${measured} ms vs spec ${specMs} ms]`, {
      cause: error,
    });
  }
  const bound = specMs * scale;
  last = { measured, bound, calibration: cal.cpu };
  const text =
    `measured ${measured} ms vs bound ${bound.toFixed(3)} ms (spec ${specMs} ms x scale ${scale.toFixed(3)}; ` +
    `calibration cpu=${cal.cpu.toFixed(3)} reference=${REFERENCE_CPU_MS})`;
  console.info(
    `perf margin=${(measured / bound).toFixed(3)} (measured ${measured} ms, bound ${bound.toFixed(3)} ms, ` +
      `calibration cpu=${cal.cpu.toFixed(3)} ms)`,
  );
  return text;
}

let last;

/** The last assertion's `{ measured, bound, calibration }` since the previous call, then cleared. */
export function takeLastAssertion() {
  const taken = last;
  last = undefined;
  return taken;
}

const ms = (value) => (Number.isFinite(value) ? `${Number(value.toFixed(3))}` : "n/a");

/** The per-attempt line (printed for every attempt, failing ones included). */
export function attemptLine(name, attempt, state, seen) {
  return (
    `perf attempt=${attempt} state=${state} test=${name} measured=${ms(seen?.measured)} ms ` +
    `calibration=${ms(seen?.calibration)} ms bound=${ms(seen?.bound)} ms`
  );
}

/**
 * The GitHub annotation for a test that passed only on a retry (attempt is 1-based: 2 = first retry).
 * Stdout, so it shows in the run's Annotations panel and on the PR checks (GitHub caps warning
 * annotations per step; the per-attempt log lines always remain). The budget never moves by retry.
 */
export function retryWarning(name, attempt, measured, calibration, bound) {
  return (
    `::warning title=perf retry::${name} passed on attempt ${attempt} \u2014 measured ${ms(measured)} ms, ` +
    `calibration ${ms(calibration)} ms, bound ${ms(bound)} ms`
  );
}
