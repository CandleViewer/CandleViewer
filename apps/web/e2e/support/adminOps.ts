import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { stubAdminReads } from "./admin";

// SCR-143's reads (E42-S06), answered at the network layer beside S01's: no backend and no live
// exchange (C-13.5). The health bodies are the server's own pinned payloads.

type Json = Record<string, unknown>;
const PAYLOADS = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../../../services/api/tests/fixtures/admin/payloads",
);
const payload = (name: string): Json =>
  JSON.parse(readFileSync(join(PAYLOADS, `${name}.json`), "utf8")) as Json;

const DEGRADED = payload("health_degraded");
/** The degraded payload with its one fault cleared. */
export const HEALTH_OK: Json = {
  ...DEGRADED,
  overall: "healthy",
  components: (DEGRADED["components"] as Json[]).map((c) => ({
    ...c,
    state: "healthy",
    detail: "",
  })),
};
export const HEALTH_OUTAGE = payload("health_outage");

const AT = "2026-10-22T12:00:00Z";
const page = (items: Json[]): Json => ({
  items,
  meta: { has_more: false, count: items.length, next_cursor: null },
});
const GAP: Json = {
  ...{ id: "5f3c2d1e-0a9b-4c8d-9e7f-6a5b4c3d2e1f", component: "recorder", severity: "error" },
  ...{ status: "open", title: "recorder gap on BTCUSDT", first_seen_at: AT, last_seen_at: AT },
};
/** Today's statecharts read (no key provider): `snapshots` unavailable, so D9 withholds. */
const PROTECTION_TODAY = { ...page([]), kinds: [], snapshots: { status: "unavailable" } };
/** The world where every D9 leg holds: a live position_protection machine, none latched. */
const PROTECTED = { machine_kind: "position_protection", environment: "demo", machines: 1 };
export const PROTECTION_OK: Json = {
  ...PROTECTION_TODAY,
  kinds: [
    { ...PROTECTED, by_state: {}, chain_trips: 0, degraded_machines: 0, dropped_receipts: 0 },
  ],
  snapshots: { status: "ok" },
};

const OPS_READS: Readonly<Record<string, { status: number; body: unknown }>> = {
  "/api/v1/admin/health": { status: 200, body: HEALTH_OK },
  "/api/v1/admin/incidents?status=open&limit=100": { status: 200, body: page([GAP]) },
  "/api/v1/admin/incidents?status=acknowledged&limit=100": { status: 200, body: page([]) },
  "/api/v1/admin/statecharts?kind=position_protection": { status: 200, body: PROTECTION_TODAY },
};

/** SCR-143's reads beside S01's, through S01's stub; `replies` override an answer. */
export const stubOpsReads = (
  page: Page,
  replies: Readonly<Record<string, { status: number; body: unknown }>> = {},
): ReturnType<typeof stubAdminReads> => stubAdminReads(page, { ...OPS_READS, ...replies });
