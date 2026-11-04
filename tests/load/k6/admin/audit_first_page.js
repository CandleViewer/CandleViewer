// E42-Q03 (#1216): the SCR-135 audit first-page profile [BQ-1, BQ-2]. Run by bench/admin/run.py,
// which checks the database and the environment first and sets every variable below:
//
//   k6 run --out json=<run dir>/points.json -e BASE_URL=<the API under test, no default> \
//     -e CV_ADMIN_PERF_DB=admin_perf_test -e CV_ADMIN_RUN=1 -e CV_ADMIN_OUT=<run dir> \
//     -e CV_ADMIN_USERS_FILE=<0600 file> -e CV_ADMIN_PASSWORD=<generated> \
//     tests/load/k6/admin/audit_first_page.js
//
// One VU, one Owner, one call at a time: `GET /admin/audit?limit=200` for each of the 14
// combinations (lib/combos.js) at page 1 and at a cursor 90 % deep, one warm-up and 20 samples
// each, paced at 1.05 s so the shipped limiter (60 a minute per user) is never what is measured.
// Each call checks: 200, at most `limit` items, and items present unless the combination is
// selective by construction (a vacuous page would pass any budget). A 429 stops the run: it is a
// harness bug, never retried. Every run signs a different Owner in (`CV_ADMIN_RUN`), so no run
// carries another's audit-record budget, and signs it in again at a row boundary before its
// token can expire (lib/thresholds.js `maybeResign`). Each sample is tagged `ok` by the same three
// checks (lib/thresholds.js `pageOk`): results.py never counts a failed call as a duration.
// [BQ-1] Expected today: `severity_actor` over 400 ms (FAIL, #1710) and `q_selective` at the 4 s
// stop (503, so ERRORS, or FAIL if it ever answers over budget; #1711). Never skipped.
/* global __ENV */
import http from "k6/http";
import exec from "k6/execution";
import { check, sleep } from "k6";
import { Trend } from "k6/metrics";
import { guardedBase, guardedDatabase, guardedEnvironment } from "./lib/guard.js";
import { auth, loadUsers, signIn } from "./lib/adminSession.js";
import { plan } from "./lib/combos.js";
import {
  PACE_S,
  PAGE_LIMIT,
  SAMPLES,
  WARMUP,
  maybeResign,
  pageOk,
  thresholds,
} from "./lib/thresholds.js";

const BASE = guardedBase(__ENV.BASE_URL);
guardedDatabase(__ENV.CV_ADMIN_PERF_DB);
const USERS = loadUsers();
const RUN = Number(__ENV.CV_ADMIN_RUN || 1);
if (!Number.isInteger(RUN) || RUN < 1 || RUN > USERS.length) {
  throw new Error("CV_ADMIN_RUN must name one of the users file's Owners (1-based)");
}
const PLAN = plan(PAGE_LIMIT);
const auditMs = new Trend("cv_admin_audit_ms", true);

export const options = {
  setupTimeout: "120s",
  summaryTrendStats: ["p(50)", "p(95)", "p(99)", "max", "count"],
  scenarios: {
    profile: {
      executor: "per-vu-iterations",
      vus: 1,
      iterations: 1,
      maxDuration: "45m", // 28 x 21 calls at >= 1.05 s each is about 11 min; 4 s calls add more
      exec: "profile",
    },
  },
  thresholds: thresholds(),
};

export function setup() {
  const health = http.get(`${BASE}/healthz`);
  if (health.status !== 200) throw new Error(`healthz ${health.status}`);
  guardedEnvironment(health.json("environment"));
  const signedAt = Date.now(); // before the call: the token's age is never under-counted
  return { session: signIn(BASE, USERS[RUN - 1]), signedAt };
}

function items(r) {
  try {
    const page = r.json();
    return Array.isArray(page.items) ? page.items : null;
  } catch {
    return null;
  }
}

export function profile(data) {
  let { session, signedAt } = data;
  for (const row of PLAN) {
    ({ session, signedAt } = maybeResign({ session, signedAt }, Date.now(), (step) =>
      signIn(BASE, USERS[RUN - 1], step),
    ));
    const tags = { combo: row.combo, pos: row.pos, cls: row.cls };
    for (let i = 0; i < WARMUP + SAMPLES; i += 1) {
      const t0 = Date.now();
      const r = http.get(
        `${BASE}/admin/audit?${row.query}`,
        auth(session, { tags: { name: "GET /admin/audit", ...tags } }),
      );
      if (r.status === 429) exec.test.abort("429 from the audit limiter: the pacing is wrong");
      const page = items(r);
      const ok = pageOk(r.status, page, PAGE_LIMIT, row.sparse) ? "1" : "0";
      auditMs.add(r.timings.duration, { ...tags, warm: i < WARMUP ? "1" : "0", ok });
      check(r, {
        "status 200": (x) => x.status === 200,
        "at most limit items": () => page !== null && page.length <= PAGE_LIMIT,
        "not vacuous": () => row.sparse || (page !== null && page.length > 0),
      });
      const left = PACE_S - (Date.now() - t0) / 1000;
      if (left > 0) sleep(left);
    }
  }
}

export function handleSummary(data) {
  delete data.setup_data; // setup() returns a session: never written to a file (C-12.2)
  return { [`${__ENV.CV_ADMIN_OUT || "."}/summary.json`]: JSON.stringify(data) };
}
