// E40-Q02 (#1203) AC "Latency budgets hold", REST half: GET /notifications at 500 rows a page,
// p95 < 200 ms, over the >= 1M rows seed_alerts.py writes across the four sources.
//
// The route serves the four-source UNION ALL (E40-T04); seed_alerts.py seeds all four sources
// (alert_deliveries, rule_events, order_events, system_events). Each VU follows its own cursor.
/* global __ENV */
import http from "k6/http";
import exec from "k6/execution";
import { check } from "k6";
import { guardedBase } from "./lib/guard.js";
import { auth, loadUsers, signIn } from "./lib/session.js";

const BASE = guardedBase();
const USERS = loadUsers();
const PAGE = 500; // the ticket's page size (22 Limit maximum)
const BUDGET_MS = 200; // the ticket's p95

export const options = {
  setupTimeout: "300s",
  summaryTrendStats: ["avg", "p(50)", "p(95)", "p(99)", "max", "count"],
  scenarios: {
    pages: {
      executor: "constant-arrival-rate",
      rate: 10,
      timeUnit: "1s",
      duration: `${Number(__ENV.CV_E40_NOTIFICATIONS_S || 120)}s`,
      preAllocatedVUs: USERS.length,
      maxVUs: USERS.length,
    },
  },
  thresholds: {
    checks: ["rate>0.99"],
    "http_req_duration{endpoint:notifications}": [`p(95)<${BUDGET_MS}`],
  },
};

export function setup() {
  return { sessions: USERS.map((u) => signIn(BASE, u)) };
}

// Each request walks one page deeper on its own cursor, so deep pages are measured too.
const cursors = {};
export default function (data) {
  const i = (exec.vu.idInTest - 1) % data.sessions.length;
  const c = cursors[i] ? `&cursor=${encodeURIComponent(cursors[i])}` : "";
  const r = http.get(
    `${BASE}/notifications?limit=${PAGE}${c}`,
    auth(data.sessions[i], { tags: { endpoint: "notifications" } }),
  );
  check(r, { "page 200": (x) => x.status === 200 });
  cursors[i] = r.status === 200 ? r.json("meta.next_cursor") : null;
}

export function handleSummary(data) {
  delete data.setup_data; // session tokens: never written to a file (C-12.2)
  return { [__ENV.CV_E40_SUMMARY || "k6-summary-alerts-notifications.json"]: JSON.stringify(data) };
}
