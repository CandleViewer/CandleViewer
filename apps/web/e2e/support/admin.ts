import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
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

// The statechart inspector's reads (E42-S08, R-357): the SC-CHAIN-TRIPS world of
// `services/api/tests/fixtures/admin/latched_machine.py` (E42-Q01) beside `22`'s `degradedOrder`
// example (E42-D05:201-202): the demo kill switch, clear; the latched order, triggered with two
// chain trips and two deferred events; and one latched B8 `position_protection`, which has no
// public id, so no row. The metrics source timed out, so no dropped receipts count is known. The
// hashes are the committed `machine_hashes.lock` entries, read at spec time, and the chart is the
// unit tests' frozen B01 (`test/features/admin/statecharts/frozen/`), so no chart bump moves it.

type Ok<K extends keyof generated.rest.operations> = generated.rest.operations[K] extends {
  responses: { 200: { content: { "application/json": infer B } } };
}
  ? B
  : never;

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../../..");
const isRecord = (raw: unknown): raw is Readonly<Record<string, unknown>> =>
  typeof raw === "object" && raw !== null && !Array.isArray(raw);

/** `kind`'s hash in the committed `machine_hashes.lock`, as it is when the spec runs. */
function lockHash(kind: string): string {
  const file = join(ROOT, "services/api/candleviewer/statechart/machines/machine_hashes.lock");
  const lock: unknown = JSON.parse(readFileSync(file, "utf8"));
  const machines = isRecord(lock) ? lock["machines"] : undefined;
  const entry = isRecord(machines) ? machines[kind] : undefined;
  const hash = isRecord(entry) ? entry["hash"] : undefined;
  // A sha256, the pattern `22` gives every `machine_hash`, as the unit fixtures' `lockHash` checks.
  if (typeof hash !== "string" || !/^[0-9a-f]{64}$/.test(hash)) {
    throw new Error(`machine_hashes.lock: no hash for ${kind}`);
  }
  return hash;
}

export const LATCHED_KEY = "order:0a000000-0000-4000-8000-0000000000c7";
export const ORDER_HASH = lockHash("order");
export const KILL_SWITCH_HASH = lockHash("kill_switch");
const SNAPSHOT_AT = "2026-10-15T18:00:05Z";

const KILL_SWITCH_ROW: Schemas["StatechartMachine"] = {
  machine_key: "kill_switch",
  machine_kind: "kill_switch",
  environment: "demo",
  state: "clear",
  machine_hash: KILL_SWITCH_HASH,
  lock_matches: true,
  chain_trips: 0,
  degraded: false,
  deferred_depth: 0,
  updated_at: "2026-10-15T18:00:00Z",
};

export const LATCHED_ROW: Schemas["StatechartMachine"] = {
  machine_key: LATCHED_KEY,
  machine_kind: "order",
  environment: "demo",
  state: "triggered",
  machine_hash: ORDER_HASH,
  lock_matches: true,
  chain_trips: 2,
  degraded: true,
  deferred_depth: 2,
  updated_at: "2026-10-15T18:00:02Z",
};

export const STATECHART_LIST: Ok<"listStatecharts"> = {
  items: [KILL_SWITCH_ROW, LATCHED_ROW],
  kinds: [
    {
      machine_kind: "kill_switch",
      environment: "demo",
      machines: 1,
      by_state: { clear: 1 },
      chain_trips: 0,
      degraded_machines: 0,
      dropped_receipts: null,
    },
    {
      machine_kind: "order",
      environment: "demo",
      machines: 1,
      by_state: { triggered: 1 },
      chain_trips: 2,
      degraded_machines: 1,
      dropped_receipts: null,
    },
    {
      machine_kind: "position_protection",
      environment: "demo",
      machines: 1,
      by_state: { naked: 1 },
      chain_trips: 1,
      degraded_machines: 1,
      dropped_receipts: null,
    },
  ],
  meta: { next_cursor: null, has_more: false, count: 2 },
  snapshots: { status: "ok", generated_at: SNAPSHOT_AT },
  metrics: { status: "error", detail: "metrics timed out after 300 ms", generated_at: SNAPSHOT_AT },
};

/** The latched order's detail: its snapshot's configuration and three events, newest first. */
export const LATCHED_DETAIL: Ok<"getStatechart"> = {
  snapshots: { status: "ok", generated_at: SNAPSHOT_AT },
  events: { status: "ok", generated_at: SNAPSHOT_AT },
  machine: LATCHED_ROW,
  configuration: [
    "order",
    "order.lifecycle",
    "order.lifecycle.triggered",
    "order.protection",
    "order.protection.sl_present",
  ],
  recent_events: [
    {
      event_type: "PRICE_TRIGGERED",
      phase: "commit",
      from_states: ["order.lifecycle.submitted", "order.protection.sl_present"],
      to_states: ["order.lifecycle.triggered", "order.protection.sl_present"],
      faulted: false,
      occurred_at: "2026-10-15T18:00:01Z",
    },
    {
      event_type: "FILL",
      phase: "fault",
      from_states: ["order.lifecycle.submitted"],
      to_states: ["order.lifecycle.submitted"],
      faulted: true,
      occurred_at: "2026-10-15T17:59:58Z",
    },
    {
      event_type: "SUBMITTED",
      phase: "ahead",
      from_states: ["order.lifecycle.submitting"],
      to_states: [],
      occurred_at: "2026-10-15T17:59:57Z",
    },
  ],
};

/** The frozen B01 as `exportStatechart` serves it (23 states, 76 pairs), with the lock's hash. */
export function orderExport(): Schemas["StatechartExport"] {
  const file = join(ROOT, "apps/web/test/features/admin/statecharts/frozen/B01.order.json");
  const chart: unknown = JSON.parse(readFileSync(file, "utf8"));
  if (!isRecord(chart)) throw new Error("the frozen B01 is not a chart");
  return { machine_kind: "order", machine_hash: ORDER_HASH, stately: chart };
}

/** The inspector's paths, as the page asks for them: every segment and parameter encoded. */
export const STATECHART_PATHS = {
  list: "/api/v1/admin/statecharts?limit=200",
  latchedOnly: "/api/v1/admin/statecharts?limit=200&degraded=true",
  detail: `/api/v1/admin/statecharts/${encodeURIComponent(LATCHED_KEY)}?environment=demo`,
  export: "/api/v1/admin/statecharts/order/export",
} as const;

/** The inspector's world for `stubAdminReads`: "Latched only" answers the order alone. */
export function inspectorReads(): Readonly<Record<string, { status: number; body: unknown }>> {
  const latched = {
    ...STATECHART_LIST,
    items: [LATCHED_ROW],
    meta: { next_cursor: null, has_more: false, count: 1 },
  };
  return {
    [STATECHART_PATHS.list]: { status: 200, body: STATECHART_LIST },
    [STATECHART_PATHS.latchedOnly]: { status: 200, body: latched },
    [STATECHART_PATHS.detail]: { status: 200, body: LATCHED_DETAIL },
    [STATECHART_PATHS.export]: { status: 200, body: orderExport() },
  };
}
