import { execFile } from "node:child_process";
import { appendFileSync, readFileSync, writeFileSync } from "node:fs";
import { promisify } from "node:util";
import {
  test as base,
  expect,
  type BrowserContext,
  type Request,
  type Response,
  type TestInfo,
} from "@playwright/test";
import { REFRESH_COOKIE } from "./cookies";
import { realStack, type FixtureUser, type RealStack } from "./stack";

// E09-Q02 (#293) PR 2 (#2490): the real lane's test fixture. Every test gets `lane`: the stack, a
// fresh fixture user per `lane.user()`, and a record of the `X-Correlation-Id` of every API answer
// its pages saw (`observability/correlation.py`). When a test fails, the record and a read-only
// slice of `audit_log` are attached: the rows of the test's users and of those correlation ids
// since it began. The audit lane is journal-first (ADR-0037), so a row may land after the answer:
// the slice is read until two reads agree, within a bound (`expect.poll`), and attached either way;
// a slice that cannot be read at all fails the test's teardown, so it is never missing silently.
// Nothing here holds a secret: paths without their query, statuses, ids and audit columns that
// the redaction rules keep secret-free (`before_state` and `after_state` are not read).
// PR 3 (#2086): the per-address refresh budget (`api/sessions.py`, REFRESH_MAX_PER_WINDOW in
// REFRESH_WINDOW_S) counts every `POST /auth/refresh` that presents a refresh cookie, and every
// request reaches the API from the preview's proxy on 127.0.0.1, so all tests share one budget.
// Each test declares how often it presents the cookie (`lane.refreshes`); the fixture waits until
// the run's ledger leaves room for that under REFRESH_BUDGET, and fails a test that presents it
// any other number of times, so the count is pinned in each spec and a change has to recount it.
// The pace is per worker: a test's refreshes enter the ledger as they settle, so two workers that
// check at once both see room for their own. `real-clock` runs one worker, so its pace is exact.
// `real` runs two, so its declared total must stay within REFRESH_LIMIT, and so must their worst
// case in one window, REFRESH_BUDGET plus the largest count one `real` test declares: no `real`
// test may declare more than REFRESH_LIMIT - REFRESH_BUDGET (`test/e2e-real-lane.test.ts` checks).

/** One API answer a page saw. */
export interface Seen {
  readonly at: string;
  readonly method: string;
  readonly path: string;
  readonly status: number;
  readonly correlationId: string;
}

/** An audit row as the slice reads it (`SLICE_COLUMNS`). */
export type AuditRow = Readonly<Record<string, unknown>>;

export interface Lane {
  readonly stack: RealStack;
  /** Claims a fixture user for this test; its audit rows join the failure artefacts. */
  user(): FixtureUser;
  /**
   * Another browser for this test (its own cookie jar and shared worker), recorded as the test's
   * own `context` is, and closed by the fixture once its refreshes are counted.
   */
  newContext(): Promise<BrowserContext>;
  /**
   * Declares that this test presents `cv_refresh` to `POST /auth/refresh` exactly `count` times
   * (the page loads that carry one included), and waits until the run's last minute has room.
   */
  refreshes(count: number): Promise<void>;
  /** The test's audit slice as it stands: its users' and correlation ids' rows since it began. */
  auditRows(): Promise<AuditRow[]>;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
const NAME = /^[a-z0-9][a-z0-9-]{0,62}$/u;
/** Rows stamped by the API just before the test's own clock read still count. */
const SKEW_MS = 5_000;
const MAX_ROWS = 500;
/** The slice's columns: a row with any other set means the query and the table drifted apart. */
export const SLICE_COLUMNS = [
  "id",
  "event_ts",
  "action",
  "outcome",
  "severity",
  "reason",
  "request_id",
  "session_id",
  "actor",
] as const;

/** `api/sessions.py` REFRESH_MAX_PER_WINDOW refreshes per source address in REFRESH_WINDOW_S. */
export const REFRESH_LIMIT = 10;
export const REFRESH_WINDOW_MS = 60_000;
/** What the run lets one window hold: two under the limit, for a refresh no test foresaw. */
export const REFRESH_BUDGET = REFRESH_LIMIT - 2;
/** A ledger entry counts this much longer than the server's window: the two clocks are not one. */
const LEDGER_SLACK_MS = 1_000;
/** The longest a test waits for room: one window and a margin, added to its own timeout. */
const PACE_MS = 75_000;

/** The slice's query. Every interpolated value is checked against a closed grammar first. */
export function auditSliceSql(
  since: Date,
  users: readonly string[],
  ids: readonly string[],
): string {
  if (Number.isNaN(since.getTime())) throw new Error("the slice needs a start time");
  for (const user of users) if (!NAME.test(user)) throw new Error("not a fixture username");
  for (const id of ids) if (!UUID.test(id)) throw new Error("not a correlation id");
  const quoted = (values: readonly string[]) => values.map((v) => `'${v}'`).join(",");
  const names = `ARRAY[${quoted(users)}]::text[]`;
  return [
    "SELECT coalesce(json_agg(row_to_json(t) ORDER BY t.event_ts, t.id), '[]'::json) FROM (",
    "SELECT a.id, a.event_ts, a.action, a.outcome, a.severity, a.reason, a.request_id,",
    "a.session_id, coalesce(u.username, a.actor_label) AS actor",
    "FROM audit_log a LEFT JOIN users u ON u.id = a.actor_user_id",
    `WHERE a.event_ts >= '${since.toISOString()}'::timestamptz`,
    `AND (u.username = ANY(${names}) OR a.actor_label = ANY(${names})`,
    `OR a.request_id = ANY(ARRAY[${quoted(ids)}]::uuid[]))`,
    `ORDER BY a.event_ts, a.id LIMIT ${MAX_ROWS}) t`,
  ].join(" ");
}

/** `rows` as audit rows; one whose columns are not exactly `SLICE_COLUMNS` fails, naming them. */
export function sliceRows(rows: readonly unknown[]): AuditRow[] {
  const expected = [...SLICE_COLUMNS].sort().join(", ");
  return rows.map((row, index) => {
    const columns = typeof row === "object" && row !== null ? Object.keys(row).sort() : [];
    if (columns.join(", ") !== expected) {
      throw new Error(`audit slice row ${index} has the columns [${columns.join(", ")}]`);
    }
    return row as AuditRow;
  });
}

const run = promisify(execFile);

/**
 * Reads the slice in a read-only transaction through the compose `postgres` service, as the
 * DAST nightlies read theirs. The project, files and the stores' variables come from the lane's
 * environment (`COMPOSE_PROJECT_NAME`, `COMPOSE_FILE`, `COMPOSE_PROFILES`).
 */
export async function readAuditSlice(sql: string): Promise<unknown[]> {
  const { stdout } = await run(
    "docker",
    [
      ...["compose", "exec", "-T", "postgres", "psql", "-U", "cv", "-d", "candleviewer"],
      ...["-v", "ON_ERROR_STOP=1", "-qAt", "-c", "SET default_transaction_read_only = on"],
      ...["-c", sql],
    ],
    { timeout: 20_000, maxBuffer: 8 * 1024 * 1024 },
  );
  const rows: unknown = JSON.parse(stdout.trim() || "[]");
  return Array.isArray(rows) ? rows : [];
}

/** Why a read failed, in one line: psql's own `ERROR:` line when there is one, not the command. */
function why(error: unknown): string {
  const stderr = (error as { stderr?: unknown } | null)?.stderr;
  const lines = [
    ...(typeof stderr === "string" ? stderr.split("\n") : []),
    ...(error instanceof Error ? error.message.split("\n") : []),
  ].map((line) => line.trim());
  return lines.find((line) => line.startsWith("ERROR:")) ?? lines.find(Boolean) ?? "unknown";
}

/** What a failed test leaves for triage. */
export interface FailureRecord {
  readonly since: Date;
  readonly users: readonly string[];
  readonly seen: readonly Seen[];
}

/** How long, and how often, the slice is read before it is attached as it stands. */
export const SLICE_SETTLE = { timeout: 15_000, intervals: [500, 1_000, 2_000] };

/**
 * A failed test's artefacts: its correlation ids, then its audit slice, as files in its output
 * directory (the lane uploads that; a `body` attachment reaches only the reporters). A slice that
 * never settles is attached with a note; one that cannot be read (a query the table no longer
 * answers, a row of other columns) is attached with a note and then throws, so the run says so.
 */
export async function keepFailureArtefacts(
  info: Pick<TestInfo, "outputPath" | "attach">,
  record: FailureRecord,
  read: (sql: string) => Promise<unknown[]> = readAuditSlice,
  settle: { timeout: number; intervals: number[] } = SLICE_SETTLE,
): Promise<void> {
  const keep = async (name: string, value: unknown): Promise<void> => {
    const path = info.outputPath(name);
    writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`);
    await info.attach(name, { path, contentType: "application/json" });
  };
  await keep("correlation-ids.json", record.seen);
  const ids = [...new Set(record.seen.map((s) => s.correlationId).filter((id) => UUID.test(id)))];
  let rows: AuditRow[] = [];
  let note = "settled";
  let broken: string | undefined;
  try {
    const sql = auditSliceSql(record.since, record.users, ids);
    let last = -1;
    await expect
      .poll(async () => {
        try {
          rows = sliceRows(await read(sql));
        } catch (error) {
          broken = why(error); // no later read answers a query that failed: stop reading
          return true;
        }
        const settled = rows.length > 0 && rows.length === last;
        last = rows.length;
        return settled;
      }, settle)
      .toBe(true);
  } catch (error) {
    note = `not settled: ${why(error)}`;
  }
  if (broken !== undefined) note = `read failed: ${broken}`;
  await keep("audit-log-slice.json", {
    since: record.since.toISOString(),
    users: record.users,
    note,
    rows,
  });
  if (broken !== undefined) throw new Error(`the audit slice could not be read: ${broken}`);
}

/** Records a cookie-presenting refresh, sent at `atMs`, in the run's ledger. */
export function recordRefresh(ledger: string, atMs: number): void {
  appendFileSync(ledger, `${atMs}\n`);
}

/** How many of the ledger's refreshes the server may still count at `nowMs`. */
export function refreshesInWindow(ledger: string, nowMs: number): number {
  let text = "";
  try {
    text = readFileSync(ledger, "ascii");
  } catch (error) {
    if ((error as { code?: string }).code !== "ENOENT") throw error;
  }
  const since = nowMs - REFRESH_WINDOW_MS - LEDGER_SLACK_MS;
  return text.split("\n").filter((line) => line !== "" && Number(line) >= since).length;
}

/** Whether a `Cookie` header carries the refresh cookie (names only: no value is kept). */
export function presentsRefresh(cookie: string | null | undefined): boolean {
  return (cookie ?? "").split(";").some((pair) => pair.split("=")[0]?.trim() === REFRESH_COOKIE);
}

/** Waits, at most PACE_MS on top of the test's own timeout, until the window has room. */
export async function paceRefreshes(
  ledger: string,
  count: number,
  info: Pick<TestInfo, "timeout" | "setTimeout">,
  { now = Date.now, intervalMs = 1_000 }: { now?: () => number; intervalMs?: number } = {},
): Promise<void> {
  if (!Number.isInteger(count) || count < 0 || count > REFRESH_BUDGET) {
    throw new RangeError(`a test may present the refresh cookie 0 to ${REFRESH_BUDGET} times`);
  }
  if (count === 0) return;
  info.setTimeout(info.timeout + PACE_MS);
  await expect
    .poll(() => refreshesInWindow(ledger, now()) + count, {
      message: `room for ${count} refreshes under ${REFRESH_BUDGET} a minute`,
      timeout: PACE_MS,
      intervals: [intervalMs],
    })
    .toBeLessThanOrEqual(REFRESH_BUDGET);
}

const REFRESH_PATH = "/api/v1/auth/refresh";

/** How long a test's end waits for the refreshes it sent to settle, and how often it looks. */
export const REFRESH_SETTLE = { timeout: 3_000, intervals: [100, 250, 500] };

/** A test's refreshes at its end: those that presented the cookie, and those still in flight. */
export interface RefreshTally {
  readonly presented: number;
  readonly unsettled: number;
}

/**
 * Counts the cookie-presenting refreshes of the contexts it watches, writing each to `ledger` as
 * it settles. `count` first waits, within `settle`, for those still in flight, and returns at once
 * when none is.
 */
export function refreshCounter(
  ledger: string,
  settle: { timeout: number; intervals: number[] } = REFRESH_SETTLE,
) {
  const sent = new Map<Request, number>();
  const checks: Promise<boolean>[] = [];
  const settled = (request: Request): void => {
    const at = sent.get(request);
    if (at === undefined) return;
    sent.delete(request);
    checks.push(
      request.headerValue("cookie").then((cookie) => {
        if (presentsRefresh(cookie)) recordRefresh(ledger, at);
        return presentsRefresh(cookie);
      }),
    );
  };
  return {
    watch(context: BrowserContext): void {
      context.on("request", (request) => {
        const isRefresh = new URL(request.url()).pathname === REFRESH_PATH;
        if (isRefresh && request.method() === "POST") sent.set(request, Date.now());
      });
      context.on("requestfinished", settled);
      context.on("requestfailed", settled);
    },
    /** The tally once every refresh sent has settled, or the wait for them has run out. */
    async count(): Promise<RefreshTally> {
      if (sent.size > 0) {
        try {
          await expect.poll(() => sent.size, settle).toBe(0);
        } catch {
          // one is still in flight: the tally says so, and checkRefreshTally reports it as that
        }
      }
      const presented = (await Promise.all(checks)).filter(Boolean).length;
      return { presented, unsettled: sent.size };
    },
  };
}

/**
 * Fails a passing test whose refreshes are not what it declares. One still in flight at its end
 * fails it too, as a refresh that never settled: its count cannot be checked, and the declaration
 * is not what to change.
 */
export function checkRefreshTally(tally: RefreshTally, declared: number | undefined): void {
  if (tally.unsettled > 0) {
    const n = tally.unsettled;
    const were = n === 1 ? "was" : "were";
    throw new Error(
      `a refresh never settled: ${n} POST /auth/refresh this test sent ${were} still in flight ` +
        `when the wait after it ended ran out, so its count could not be checked ` +
        `(look at why it hung, not at lane.refreshes)`,
    );
  }
  if (tally.presented !== (declared ?? 0)) {
    const told = `${declared ?? "none"} (lane.refreshes)`;
    throw new Error(
      `this test presented ${REFRESH_COOKIE} to POST /auth/refresh ${tally.presented} times and ` +
        `declares ${told}: recount it against the ${REFRESH_LIMIT}-a-minute budget`,
    );
  }
}

function recorder(seen: Seen[]): (res: Response) => void {
  return (res) => {
    const id = res.headers()["x-correlation-id"];
    if (id === undefined) return; // not the API's: the preview's own files
    const request = res.request();
    seen.push({
      at: new Date().toISOString(),
      method: request.method(),
      path: new URL(res.url()).pathname,
      status: res.status(),
      correlationId: id,
    });
  };
}

export const test = base.extend<{ lane: Lane }>({
  lane: [
    async ({ browser, context }, use, testInfo) => {
      const since = new Date(Date.now() - SKEW_MS);
      const seen: Seen[] = [];
      const users: string[] = [];
      const stack = realStack();
      const refreshes = refreshCounter(stack.refreshLedger);
      const others: BrowserContext[] = [];
      let declared: number | undefined;
      const watch = (ctx: BrowserContext): void => {
        ctx.on("response", recorder(seen));
        refreshes.watch(ctx);
      };
      watch(context);
      await use({
        stack,
        user: () => {
          const user = stack.claimUser();
          users.push(user.username);
          return user;
        },
        newContext: async () => {
          const ctx = await browser.newContext();
          others.push(ctx);
          watch(ctx);
          return ctx;
        },
        refreshes: async (count) => {
          declared = count;
          await paceRefreshes(stack.refreshLedger, count, testInfo);
        },
        auditRows: async () => {
          const ids = [...new Set(seen.map((s) => s.correlationId).filter((id) => UUID.test(id)))];
          return sliceRows(await readAuditSlice(auditSliceSql(since, users, ids)));
        },
      });
      const tally = await refreshes.count();
      for (const ctx of others) await ctx.close();
      if (testInfo.status !== testInfo.expectedStatus) {
        await keepFailureArtefacts(testInfo, { since, users, seen });
        return;
      }
      checkRefreshTally(tally, declared);
    },
    { auto: true },
  ],
});

export { expect };
