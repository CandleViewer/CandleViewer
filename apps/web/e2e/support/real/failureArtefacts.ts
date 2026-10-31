import { execFile } from "node:child_process";
import { writeFileSync } from "node:fs";
import { promisify } from "node:util";
import { test as base, expect, type BrowserContext, type Response } from "@playwright/test";
import { realStack, type FixtureUser, type RealStack } from "./stack";

// E09-Q02 (#293) PR 2 (#2490): the real lane's test fixture. Every test gets `lane`: the stack, a
// fresh fixture user per `lane.user()`, and a record of the `X-Correlation-Id` of every API answer
// its pages saw (`observability/correlation.py`). When a test fails, the record and a read-only
// slice of `audit_log` are attached: the rows of the test's users and of those correlation ids
// since it began. The audit lane is journal-first (ADR-0037), so a row may land after the answer:
// the slice is read until two reads agree, within a bound (`expect.poll`), and attached either way.
// Nothing here holds a secret: paths without their query, statuses, ids and audit columns that
// the redaction rules keep secret-free (`before_state` and `after_state` are not read).

/** One API answer a page saw. */
export interface Seen {
  readonly at: string;
  readonly method: string;
  readonly path: string;
  readonly status: number;
  readonly correlationId: string;
}

export interface Lane {
  readonly stack: RealStack;
  /** Claims a fixture user for this test; its audit rows join the failure artefacts. */
  user(): FixtureUser;
  /** Records another context's answers too (the test's own `context` is recorded already). */
  watch(context: BrowserContext): void;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
const NAME = /^[a-z0-9][a-z0-9-]{0,62}$/u;
/** Rows stamped by the API just before the test's own clock read still count. */
const SKEW_MS = 5_000;
const MAX_ROWS = 500;

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
    async ({ context }, use, testInfo) => {
      const since = new Date(Date.now() - SKEW_MS);
      const seen: Seen[] = [];
      const users: string[] = [];
      const stack = realStack();
      const watch = (ctx: BrowserContext): void => {
        ctx.on("response", recorder(seen));
      };
      watch(context);
      await use({
        stack,
        user: () => {
          const user = stack.claimUser();
          users.push(user.username);
          return user;
        },
        watch,
      });
      if (testInfo.status === testInfo.expectedStatus) return;
      // Files in the test's output directory, which the lane uploads: a `body` attachment reaches only
      // the reporters, and the lane's reporters keep none.
      const keep = async (name: string, value: unknown): Promise<void> => {
        const path = testInfo.outputPath(name);
        writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`);
        await testInfo.attach(name, { path, contentType: "application/json" });
      };
      await keep("correlation-ids.json", seen);
      const ids = [...new Set(seen.map((s) => s.correlationId).filter((id) => UUID.test(id)))];
      let rows: unknown[] = [];
      let note = "settled";
      try {
        const sql = auditSliceSql(since, users, ids);
        let last = -1;
        await expect
          .poll(
            async () => {
              rows = await readAuditSlice(sql);
              const settled = rows.length > 0 && rows.length === last;
              last = rows.length;
              return settled;
            },
            { timeout: 15_000, intervals: [500, 1_000, 2_000] },
          )
          .toBe(true);
      } catch (error) {
        note = `not settled: ${error instanceof Error ? error.message.split("\n")[0] : "unknown"}`;
      }
      await keep("audit-log-slice.json", { since: since.toISOString(), users, note, rows });
    },
    { auto: true },
  ],
});

export { expect };
