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
