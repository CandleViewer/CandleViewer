// BQ-nn markers here: RULED (orchestrator, 2026-11-01, #892 ruling of record 6555033109).
// E27-Q03 (#892) health-poll: steady-state account-list reads on the account fixture stack.
//
//   k6 run -e BASE_URL=http://127.0.0.1:8000 -e CV_E27_FIXTURE_STACK=1 \
//     -e CV_E27_PASSWORD=<from the seed run dir> -e CV_E27_USERS_FILE=<0600 file> \
//     tests/load/k6/accounts/health_poll.js
//
// Two scenarios, back to back (README: scenario table, row E27-L1):
//   cadence  5 VUs, one GET /exchange-accounts per 60 s each (SCR-125 refresh), 30 min (the AC).
//   peak     5 VUs, one GET per second each, 5 min: a 60x overshoot so a p95 means something
//            (06 section 2 row 13: 5-user realistic peak).
// What k6 cannot see is the exchange side: "no more than the 60 s cache policy permits" is judged
// from the stub's request log by request_log_check.py after the run (README), never here.
// SCR-079 (<=100 ms drawer) is a UI timing: only its REST part is read here (stated in the README).
/* global __ENV */
import http from "k6/http";
import exec from "k6/execution";
import { check } from "k6";
import { Trend } from "k6/metrics";
import { guardedBase } from "./lib/guard.js";
import { auth, loadUsers, signIn } from "./lib/session.js";

const BASE = guardedBase(); // BQ-11
const USERS = loadUsers();
const BUDGET_MS = 150; // 06 section 2 row 13: read endpoints p95 < 150 ms
const STAGE_S = Number(__ENV.CV_E27_CADENCE_S || 1800); // BQ-07: 30 min per the AC; a dry run shortens it
const VUS = Math.min(5, USERS.length); // BQ-04: 5 concurrent users, fewer if the roster has fewer

const listMs = new Trend("e27_list_accounts_ms", true);

export const options = {
  setupTimeout: "120s",
  summaryTrendStats: ["avg", "p(50)", "p(95)", "p(99)", "max", "count"],
  scenarios: {
    cadence: {
      executor: "constant-arrival-rate",
      rate: VUS, // VUS requests per 60 s
      timeUnit: "60s",
      duration: `${STAGE_S}s`,
      preAllocatedVUs: VUS,
      maxVUs: VUS,
      exec: "poll",
    },
    peak: {
      executor: "constant-arrival-rate",
      rate: VUS,
      timeUnit: "1s",
      duration: "300s",
      preAllocatedVUs: VUS,
      maxVUs: VUS,
      startTime: `${STAGE_S + 5}s`,
      exec: "poll",
    },
  },
  thresholds: {
    checks: ["rate>0.99"],
    // 06 row 13 verbatim; k6 prints the measured p95 for the results file (BQ-07).
    "http_req_duration{scenario:cadence}": [`p(95)<${BUDGET_MS}`],
    "http_req_duration{scenario:peak}": [`p(95)<${BUDGET_MS}`],
    http_req_failed: ["rate<0.001"],
  },
};

export function setup() {
  const sessions = [];
  let last = -1;
  for (let i = 0; i < VUS; i += 1) {
    const s = signIn(BASE, USERS[i], i === 0 ? -1 : last);
    last = s.step;
    sessions.push(s);
  }
  return { sessions };
}

export function poll(data) {
  const s = data.sessions[(exec.vu.idInTest - 1) % data.sessions.length];
  const r = http.get(
    `${BASE}/exchange-accounts?include_balance=true`,
    auth(s, { tags: { endpoint: "list" } }),
  );
  listMs.add(r.timings.duration);
  check(r, {
    "list 200": (x) => x.status === 200,
    // `items` and `connection_state` are in 22 listExchangeAccounts; no other field is read.
    "every item has a connection_state": (x) =>
      x.status === 200 && x.json("items").every((a) => typeof a.connection_state === "string"),
  });
}

// One JSON summary for the results file (README: where results go).
export function handleSummary(data) {
  return { [__ENV.CV_E27_SUMMARY || "k6-summary-health-poll.json"]: JSON.stringify(data) };
}
