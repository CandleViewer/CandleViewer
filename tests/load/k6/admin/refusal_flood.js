// E42-Q03 (#1216) part 4: a Manager refusal flood (plan 4.3, TM 7 AD-D06) [BQ-8]. Run by
// bench/admin/run.py `flood` on the chained dataset, beside the WAL sampler. A Manager with no
// grant and no step-up (run N's second Manager) sends every `/admin/*` operation the rbac matrix
// refuses it (`services/api/tests/contract/rbac/matrix.yaml`, written to CV_ADMIN_FLOOD_OPS by
// bench/admin/load.py) at FLOOD_RPS a second for FLOOD_S from LOAD_AT_S; each refusal is a durable
// `admin.area_entered` (denied) record through the one writer. The reader and the probe run as in
// export_under_load.js. Asserted by load_results.py: the WAL stays under 80 % of its cap, no
// `audit_unavailable`, the probe and the Owner's reads inside their budgets.
// Expected to FAIL until #2836 caps the admin guard's refusal records per user (only the audit
// router's are capped on main): a full WAL refuses every audited action (C-2.9), which is the
// finding. Judged, never skipped or widened; the results name #2836.
/* global __ENV, open */
import http from "k6/http";
import exec from "k6/execution";
import { Counter } from "k6/metrics";
import { guardedBase, guardedDatabase, DATASETS } from "./lib/guard.js";
import { auth, loadUsers, signIn } from "./lib/adminSession.js";
import {
  checkHealth,
  checkProbe,
  edge,
  loadManagers,
  loadThresholds,
  note,
  oneVu,
  probe,
  reader,
  runUsers,
  waitUntil,
} from "./lib/loadCalls.js";
import {
  FLOOD_RPS,
  FLOOD_S,
  LOAD_AT_S,
  PROFILES,
  floodRequests,
  rbacEscape,
} from "./lib/loadPlan.js";

const BASE = guardedBase(__ENV.BASE_URL);
if (guardedDatabase(__ENV.CV_ADMIN_PERF_DB) !== DATASETS.chained) {
  throw new Error("the flood profile runs on the chained dataset only");
}
const RUN = Number(__ENV.CV_ADMIN_RUN || 1);
const U = runUsers(loadUsers(), loadManagers(), RUN);
if (!__ENV.CV_ADMIN_FLOOD_OPS) throw new Error("CV_ADMIN_FLOOD_OPS is required");
const REQUESTS = floodRequests(JSON.parse(open(__ENV.CV_ADMIN_FLOOD_OPS)));
if (!REQUESTS.length) throw new Error("the flood has no operation");
const READ_S = PROFILES.flood.readS;
const flood = new Counter("cv_admin_flood");

export const options = {
  setupTimeout: "180s",
  summaryTrendStats: ["p(50)", "p(90)", "p(95)", "p(99)", "max", "count"],
  scenarios: {
    flood: {
      executor: "constant-arrival-rate",
      rate: FLOOD_RPS,
      timeUnit: "1s",
      duration: `${FLOOD_S}s`,
      preAllocatedVUs: 50,
      maxVUs: 200,
      startTime: `${LOAD_AT_S}s`,
      exec: "refused",
    },
    edges: oneVu("edges", "5m", LOAD_AT_S),
    reads: oneVu("reads", "10m"),
    probes: oneVu("probes", "10m"),
  },
  thresholds: loadThresholds,
};

export function setup() {
  checkHealth(BASE);
  const readerSession = signIn(BASE, U.reader);
  const probeSession = signIn(BASE, U.probe);
  checkProbe(BASE, probeSession, RUN);
  const floodSession = signIn(BASE, U.flood);
  const t0 = Date.now();
  return {
    t0,
    reader: { session: readerSession, signedAt: t0 },
    probe: probeSession,
    flood: floodSession,
  };
}

export function refused(data) {
  const req = REQUESTS[exec.scenario.iterationInTest % REQUESTS.length];
  const params = auth(data.flood, { timeout: "10s", tags: { name: req.name } });
  const r = http.request(req.method, `${BASE}${req.url}`, req.body, params);
  const code = note(r);
  flood.add(1, { status: String(r.status), code });
  if (rbacEscape(r.status)) {
    exec.test.abort("an admin operation answered a Manager with no grant: RBAC escape");
  }
}

export function edges(data) {
  edge("start");
  waitUntil(data.t0, LOAD_AT_S + FLOOD_S);
  edge("end");
}

export function reads(data) {
  reader(BASE, U.reader, { ...data.reader, t0: data.t0 }, READ_S);
}

export function probes(data) {
  probe(BASE, data.probe, data, READ_S, RUN);
}

export function handleSummary(data) {
  delete data.setup_data; // setup() returns sessions: never written to a file (C-12.2)
  return { [`${__ENV.CV_ADMIN_OUT || "."}/summary.json`]: JSON.stringify(data) };
}
