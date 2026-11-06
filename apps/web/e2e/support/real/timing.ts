import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, type TestInfo } from "@playwright/test";

// E42-Q02 (#1215) part 1: the admin lane's budgeted timings (BQ-4). A timing never sleeps: it polls
// to a deadline (`expect.poll`) and reports what it observed, so a pass still says how close it came.
// Where the server stamps both ends, the budget is judged on those stamps (an audit row's `event_ts`,
// `server-record`; a frame's `ts`, `server-frame-ts`) and the runner's own figure is recorded beside
// it; only where it does not is the runner's figure judged (`runner`). Each measurement is written
// to `test-results/timings/<case>.json`, which the nightly keeps as its `e2e-admin-timings` artefact
// pass or fail, so a series of runs is the trend. A record holds a case id, numbers, the build and
// the run: never a username or anything of a session.

export type Basis = "server-record" | "server-frame-ts" | "runner";

/** What a poll saw: its last value, how long it took on the runner's clock, and how many reads. */
export interface Observed<T> {
  readonly value: T;
  readonly observedMs: number;
  readonly polls: number;
}

/** The default failure summary: the last read's kind only, never its body (fixture names, ids). */
function kindOf(value: unknown): string {
  if (Array.isArray(value)) return `${value.length} items, not shown`;
  if (value === null) return "null";
  return `${typeof value === "object" ? "an object" : `a ${typeof value}`}, not shown`;
}

/** How `untilWithin` polls, and how its failure shows the last read. */
export interface UntilOptions<T> {
  readonly intervalMs?: number;
  readonly now?: () => number;
  /** A summary of the last read for the failure message; by default its kind only. */
  readonly show?: (value: T) => string;
}

/**
 * A label reaches the artefact, the annotation and a failure message, so it is a short slug a case
 * names (`manager-next-request`), never free text: no username, address, token or anything of a
 * session fits it.
 */
const LABEL = /^[a-z0-9][a-z0-9_.:-]{0,63}$/u;

function assertLabel(label: string): void {
  if (!LABEL.test(label)) {
    throw new Error("a timing's label is a short slug (a-z, 0-9, _ . : -), never free text");
  }
}

/**
 * Reads `probe` until `done` holds, at most `deadlineMs`; fails naming `label`, the deadline and
 * the last value read as `show` summarises it (by default its kind, not its body).
 */
export async function untilWithin<T>(
  label: string,
  deadlineMs: number,
  probe: () => T | Promise<T>,
  done: (value: T) => boolean,
  { intervalMs = 100, now = Date.now, show = kindOf }: UntilOptions<T> = {},
): Promise<Observed<T>> {
  assertLabel(label);
  const started = now();
  let polls = 0;
  let last: { value: T } | undefined;
  try {
    await expect
      .poll(
        async () => {
          polls += 1;
          last = { value: await probe() };
          return done(last.value);
        },
        { timeout: deadlineMs, intervals: [intervalMs] },
      )
      .toBe(true);
  } catch {
    const seen = last === undefined ? "nothing" : show(last.value).slice(0, 300);
    throw new Error(`${label}: not within ${deadlineMs} ms, after ${polls} reads (last: ${seen})`);
  }
  if (last === undefined) throw new Error(`${label}: the probe was never read`);
  return { value: last.value, observedMs: now() - started, polls };
}

/** Milliseconds from one audit row's `event_ts` to another's: the server's own clock. */
export function serverDeltaMs(
  from: Readonly<Record<string, unknown>>,
  to: Readonly<Record<string, unknown>>,
): number {
  const at = (row: Readonly<Record<string, unknown>>): number =>
    Date.parse(String(row["event_ts"]));
  const [a, b] = [at(from), at(to)] as const;
  if (!Number.isFinite(a) || !Number.isFinite(b)) {
    throw new Error("an audit row without a readable event_ts");
  }
  return b - a;
}

/** One measurement, as the artefact keeps it. */
export interface TimingRecord {
  readonly case: string;
  readonly label: string;
  readonly budget_ms: number;
  readonly observed_ms: number;
  readonly runner_ms: number;
  readonly basis: Basis;
  readonly build_sha: string;
  readonly run_id: string;
}

/** `apps/web/test-results/timings`, beside the lane's output folder (the workflow uploads it). */
export const TIMINGS_DIR = fileURLToPath(new URL("../../../test-results/timings", import.meta.url));
const CASE = /^[A-Z0-9][A-Z0-9-]{0,40}$/u;

/** A record for `fields`, stamped with the build and the run (`local` off CI). */
export function timingRecord(
  fields: Omit<TimingRecord, "build_sha" | "run_id">,
  env: Readonly<Record<string, string | undefined>> = process.env,
): TimingRecord {
  if (!CASE.test(fields.case)) throw new Error("a timing's case is a case id, such as AD-X-01");
  assertLabel(fields.label);
  return {
    ...fields,
    build_sha: env["GITHUB_SHA"] ?? "local",
    run_id: env["GITHUB_RUN_ID"] ?? "local",
  };
}

/**
 * Keeps `record` (its file, then a `measured` annotation, as e17/realtime.nightly.ts does), then
 * judges it: the observed figure within the budget. A miss is kept before it fails.
 */
export function judgeTiming(
  info: Pick<TestInfo, "annotations">,
  record: TimingRecord,
  dir: string = TIMINGS_DIR,
): void {
  assertLabel(record.label);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, `${record.case}.json`), `${JSON.stringify(record, null, 2)}\n`);
  info.annotations.push({
    type: "measured",
    description:
      `${record.case} ${record.label}: ${record.observed_ms} ms of ${record.budget_ms} ms ` +
      `(${record.basis}); runner ${record.runner_ms} ms`,
  });
  expect(
    record.observed_ms,
    `${record.case} ${record.label} (${record.basis})`,
  ).toBeLessThanOrEqual(record.budget_ms);
}
