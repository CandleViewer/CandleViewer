import type { Page } from "@playwright/test";
import type { generated } from "@candleviewer/protocol";
import { json } from "./api";

type Schemas = generated.rest.components["schemas"];

// SCR-120's reads (E42-S01), answered at the network layer: no backend, no live exchange (C-13.5).
// The overview is E42-Q01's HEALTH-RECORDER-HANG world (`services/api/tests/fixtures/admin/payloads/
// overview_recorder_hang.json`): the recorder's slice timed out after 300 ms, everything else read.

const AT = "2026-10-22T12:00:00Z";

export const ADMIN_OVERVIEW: Schemas["AdminOverview"] = {
  generated_at: AT,
  users: { status: "ok", generated_at: AT, total: 9, active: 6, without_mfa: 0 },
  accounts: {
    status: "ok",
    generated_at: AT,
    total: 5,
    enabled: 5,
    keys_expiring_30d: 0,
    keys_invalid: 0,
  },
  recorder: { status: "error", detail: "timed out after 300 ms", generated_at: AT },
  storage: {
    status: "ok",
    generated_at: AT,
    used_bytes: 1073741824,
    free_bytes: 107374182400,
    days_until_full: null,
  },
  trading: {
    status: "ok",
    generated_at: AT,
    live_enabled: false,
    kill_switch_engaged: false,
    open_positions: 0,
  },
  incidents_open: 0,
  incidents: { status: "ok", generated_at: AT, open: 0 },
};

const CAPACITY: Schemas["CapacityReport"] = {
  generated_at: AT,
  subaccounts: {
    status: "ok",
    generated_at: AT,
    tier: null,
    cap: null,
    used: 3,
    tier_source: "unrecorded",
  },
};

const HEALTH: Schemas["HealthReport"] = {
  overall: "healthy",
  server_time: AT,
  components: [
    { name: "postgres", state: "healthy", latency_ms: 3, latency_unit: "ms", detail: "" },
    { name: "bars_writer", state: "not_deployed", detail: "" },
  ],
};

type FlagList =
  generated.rest.operations["listFeatureFlags"]["responses"][200]["content"]["application/json"];
const FLAGS: FlagList = {
  resolution: "stored",
  items: [
    { key: "maintenance.mode", kind: "boolean", value: false, updated_at: AT },
    { key: "trading.live_enabled", kind: "boolean", value: false, updated_at: AT },
  ],
};

const AUDIT_ENTRY: Schemas["AuditEntry"] = {
  id: 1204118,
  ts: "2026-10-22T11:59:58.123456Z",
  action: "admin.area_entered",
  actor_user_id: "11111111-2222-3333-4444-555555555555",
  actor_username: "owner.one",
  detail: { before: null, after: null },
  entry_hash: null,
  prev_hash: null,
  outcome: "success",
  severity: "info",
  subject_id: null,
  subject_type: null,
};

/** Each read's path (with its query) and its answer: `/admin/backups` is 501 until catalogued. */
export const ADMIN_READS: Readonly<Record<string, { status: number; body: unknown }>> = {
  "/api/v1/admin/overview": { status: 200, body: ADMIN_OVERVIEW },
  "/api/v1/admin/capacity": { status: 200, body: CAPACITY },
  "/api/v1/admin/health": { status: 200, body: HEALTH },
  "/api/v1/admin/feature-flags": { status: 200, body: FLAGS },
  "/api/v1/admin/audit?limit=3": {
    status: 200,
    body: { chain_verified: true, items: [AUDIT_ENTRY], meta: { count: 1, has_more: true } },
  },
  "/api/v1/admin/backups?limit=1": {
    status: 501,
    body: { type: "about:blank", title: "Not implemented", status: 501, code: "not_implemented" },
  },
  "/api/v1/users/invites": { status: 200, body: { items: [] } },
};

/**
 * Answers SCR-120's `GET`s from `ADMIN_READS`, a path in `replies` with its own answer instead; any
 * other admin `GET` is a `404`. Returns the setter a test uses to change an answer mid-visit.
 */
export async function stubAdminReads(
  page: Page,
  replies: Readonly<Record<string, { status: number; body: unknown }>> = {},
): Promise<(path: string, status: number, body: unknown) => void> {
  const answers = new Map(Object.entries({ ...ADMIN_READS, ...replies }));
  await page.route(
    (url) => url.pathname.startsWith("/api/v1/admin/") || url.pathname === "/api/v1/users/invites",
    (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const url = new URL(route.request().url());
      const answer = answers.get(`${url.pathname}${url.search}`) ?? { status: 404, body: {} };
      return route.fulfill(json(answer.body, answer.status));
    },
  );
  return (path, status, body) => answers.set(path, { status, body });
}

// SCR-135 and SCR-136's calls (E42-S04, #1135), answered at the network layer (C-13.5), after E42-D04
// §1's worked example: the owner `basiltt`, the manager `alex`, LIVE, 2026-10-22 "as of 14:02:11",
// the break at entry 1,204,118. No value is secret-shaped: hashes and keys repeat one character.

const OWNER_ID = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001";
const ALEX_ID = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002";
export const AUDIT_JOB_ID = "19000000-0000-4000-8000-000000000001";
const STEP_UP_CHALLENGE = "6f1d2c3b-4a5e-4f60-8a7b-9c0d1e2f3a4b";

/** Entry `id` of the worked example, one second apart up to 14:02:11, one field changed. */
export function auditEntry(
  id: number,
  over: Partial<Schemas["AuditEntry"]> = {},
): Schemas["AuditEntry"] {
  const at = Date.UTC(2026, 9, 22, 14, 2, 11) - (1_204_300 - id) * 1_000;
  return {
    id,
    ts: new Date(at).toISOString(),
    actor_user_id: OWNER_ID,
    actor_username: "basiltt",
    action: "orders.submit",
    subject_type: "order",
    subject_id: "0a000000-0000-4000-8000-000000000001",
    subject_label: "BTCUSDT",
    outcome: "success",
    severity: "info",
    reason: null,
    environment: "live",
    session_id: "5e000000-0000-4000-8000-000000000001",
    ip: "100.84.12.9",
    user_agent: null,
    request_id: "0193f2bb-9c11-7a3d-88f1-0d2e3f4a5b6c",
    detail: { before: { qty: "0.010" }, after: { qty: "0.020" } },
    entry_hash: "3".repeat(64),
    prev_hash: "7".repeat(64),
    ...over,
  };
}

const auditPage = (
  items: readonly Schemas["AuditEntry"][],
  next: string | null,
): { items: Schemas["AuditEntry"][]; chain_verified: boolean; meta: Schemas["PageMeta"] } => ({
  items: [...items],
  chain_verified: true,
  meta: { next_cursor: next, has_more: next !== null, count: items.length },
});

/** Page 1 (three rows, an Older cursor), page 2 (the end), and a filtered page of one row. */
export const AUDIT_PAGES = {
  first: auditPage([auditEntry(1_204_300), auditEntry(1_204_299), auditEntry(1_204_298)], "c1"),
  second: auditPage([auditEntry(1_204_297), auditEntry(1_204_296)], null),
  filtered: auditPage([auditEntry(1_204_299, { severity: "error", outcome: "failure" })], null),
  own: auditPage(
    [
      auditEntry(1_204_295, {
        actor_user_id: ALEX_ID,
        actor_username: "alex",
        environment: null,
        ip: null,
        session_id: null,
        subject_label: null,
        entry_hash: null,
        prev_hash: null,
        detail: {},
      }),
    ],
    null,
  ),
};

const CHAIN_BREAK: Schemas["Incident"] = {
  id: "1a000000-0000-4000-8000-000000000007",
  component: "db",
  severity: "critical",
  status: "open",
  title: "audit chain break at id <n>",
  detail: "audit chain break at id 1204118",
  occurrences: 1,
  first_seen_at: "2026-10-22T14:05:07Z",
  last_seen_at: "2026-10-22T14:05:07Z",
  acknowledged_by: null,
  acknowledged_at: null,
  resolved_at: null,
  runbook_ref: null,
  signature: "5f0c2d9e4b7a1c3e",
};

const EXPORT_RESULT: Schemas["AuditExportResult"] = {
  download_url: `/api/v1/admin/audit/exports/${AUDIT_JOB_ID}`,
  sha256: "d".repeat(64),
  signature: `${"A".repeat(86)}==`,
  signature_alg: "ed25519",
  key_id: `cv-audit-export-v1:${"2".repeat(16)}`,
  public_key: `${"B".repeat(43)}=`,
  compressed: true,
  size_bytes: 44_120_000,
  row_count: 851_204,
  from: "2026-10-21T14:02:00Z",
  to: "2026-10-22T14:02:00Z",
  first_id: 87_268_001,
  last_id: 88_119_204,
  expires_at: "2026-10-23T14:03:00Z",
};

const job = (over: Partial<Schemas["Job"]>): Schemas["Job"] => ({
  id: AUDIT_JOB_ID,
  kind: "audit_export",
  status: "running",
  started_at: "2026-10-22T14:02:30Z",
  finished_at: null,
  result: null,
  error: null,
  ...over,
});

export interface AuditWire {
  /** Each `GET /admin/audit` (but the strip's `?limit=3`) as its query string. */
  readonly reads: string[];
  readonly stepUps: string[];
  readonly exports: string[];
  readonly downloads: number;
}

/**
 * SCR-135's server: the list reads by cursor and filter (`rows`: page 1's size, 3 by default;
 * `own`: a Manager's projected page 1), the incidents (`broken`: one open chain break), the export
 * (`stepUp`: its first answer `403 step_up_required`; `outcome`: the job's end) and its download
 * (the file's bytes, `403 step_up_required` first under `stepUp`). Registered after
 * `stubAdminReads`, so it answers first.
 */
export async function stubAuditLog(
  page: Page,
  options: {
    readonly broken?: boolean;
    readonly stepUp?: boolean;
    readonly outcome?: "succeeded" | "failed";
    readonly rows?: number;
    readonly own?: boolean;
  } = {},
): Promise<AuditWire> {
  const first =
    options.own === true
      ? AUDIT_PAGES.own
      : options.rows === undefined
        ? AUDIT_PAGES.first
        : auditPage(
            Array.from({ length: options.rows }, (_, i) => auditEntry(1_204_300 - i)),
            "c1",
          );
  const wire = {
    reads: [] as string[],
    stepUps: [] as string[],
    exports: [] as string[],
    downloads: 0,
  };
  const challenge = (cls: string, summary: string) =>
    json(
      {
        type: "https://candleviewer.local/errors/step_up_required",
        title: "A dangerous action needs a live step-up elevation for its action class",
        status: 403,
        code: "step_up_required",
        action_class: cls,
        challenge_id: STEP_UP_CHALLENGE,
        challenge_expires_at: new Date(Date.now() + 5 * 60_000).toISOString(),
        action_summary: summary,
        target: null,
      },
      403,
    );
  await page.route(
    (url) => url.pathname === "/api/v1/admin/audit" && url.search !== "?limit=3",
    (route) => {
      const url = new URL(route.request().url());
      wire.reads.push(url.search);
      const params = url.searchParams;
      const filtered = [...params.keys()].some((name) => !["limit", "cursor"].includes(name));
      const body = filtered
        ? AUDIT_PAGES.filtered
        : params.get("cursor") === "c1"
          ? AUDIT_PAGES.second
          : first;
      return route.fulfill(json(body));
    },
  );
  await page.route("**/api/v1/admin/incidents?*", (route) =>
    route.fulfill(
      json({
        items: options.broken === true ? [CHAIN_BREAK] : [],
        meta: { next_cursor: null, has_more: false, count: options.broken === true ? 1 : 0 },
      }),
    ),
  );
  let polls = 0;
  await page.route("**/api/v1/admin/audit/export", (route) => {
    wire.exports.push(route.request().headers()["idempotency-key"] ?? "");
    return route.fulfill(
      options.stepUp === true && wire.exports.length === 1
        ? challenge("audit", "Export the audit log (UTC)")
        : json({ job_id: AUDIT_JOB_ID, download_url: null }, 202),
    );
  });
  await page.route(`**/api/v1/admin/jobs/${AUDIT_JOB_ID}`, (route) => {
    polls += 1;
    if (polls === 1) return route.fulfill(json(job({ progress_pct: 50 })));
    return route.fulfill(
      json(
        options.outcome === "failed"
          ? job({ status: "failed", error: "export_too_large" })
          : job({ status: "succeeded", progress_pct: 100, result: EXPORT_RESULT }),
      ),
    );
  });
  await page.route(`**/api/v1/admin/audit/exports/${AUDIT_JOB_ID}`, (route) => {
    wire.downloads += 1;
    if (options.stepUp === true && wire.downloads === 1) {
      return route.fulfill(challenge("audit", "Download the audit export"));
    }
    return route.fulfill({
      status: 200,
      contentType: "application/gzip",
      headers: { "Content-Disposition": 'attachment; filename="audit-2026-10-22.ndjson.gz"' },
      body: "{}\n",
    });
  });
  await page.route("**/api/v1/auth/step-up", (route) => {
    wire.stepUps.push(route.request().postData() ?? "");
    return route.fulfill(json({ elevated_until: new Date().toISOString(), action_class: "audit" }));
  });
  return wire;
}
