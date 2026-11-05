// E42-Q03 (#1216) part 4: a verify walking the full span under interactive load (plan 4.2, TM 7
// AD-D04) [BQ-8]. Run by bench/admin/run.py `verify` on the chained dataset, beside the WAL
// sampler. From the start of the test (t0):
// - the actor (run N's first Owner): a span past the cap is 422 first (it counts nothing); at
//   LOAD_AT_S `POST /admin/audit/verify` with no bound walks the newest `audit_verify_max_span`
//   ids (about half as many entries), sent with a second run in one batch: one is 409 (single
//   flight, however short the walk: C-1216P4-04; a 409 starts no run, so counts nothing), the
//   other is the walk and the load window. It must answer 200 `verified: true` over the whole cap
//   inside the 60 s deadline. Then the hourly limit: 29 more one-entry runs, the 31st is 429;
// - the reader and the probe as in export_under_load.js. TM 7 says the walk hashes on the event
//   loop between reads: the probe and the reads are what show it.
/* global __ENV */
import http from "k6/http";
import { guardedBase, guardedDatabase, DATASETS } from "./lib/guard.js";
import { auth, loadUsers, signIn } from "./lib/adminSession.js";
import {
  bound,
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
  LOAD_AT_S,
  PROFILES,
  VERIFY_DEADLINE_S,
  VERIFY_MAX_SPAN,
  VERIFY_RATE_PER_HOUR,
} from "./lib/loadPlan.js";

const BASE = guardedBase(__ENV.BASE_URL);
if (guardedDatabase(__ENV.CV_ADMIN_PERF_DB) !== DATASETS.chained) {
  throw new Error("the verify profile runs on the chained dataset only");
}
const RUN = Number(__ENV.CV_ADMIN_RUN || 1);
const ROWS = Number(__ENV.CV_ADMIN_ROWS || 1000000);
const U = runUsers(loadUsers(), loadManagers(), RUN);
const READ_S = PROFILES.verify.readS;

export const options = {
  setupTimeout: "180s",
  summaryTrendStats: ["p(50)", "p(90)", "p(95)", "p(99)", "max", "count"],
  scenarios: {
    actor: oneVu("actor", "20m"),
    reads: oneVu("reads", "10m"),
    probes: oneVu("probes", "10m"),
  },
  thresholds: loadThresholds,
};

export function setup() {
  checkHealth(BASE);
  const actor = signIn(BASE, U.actor);
  const readerSession = signIn(BASE, U.reader);
  const probeSession = signIn(BASE, U.probe);
  checkProbe(BASE, probeSession, RUN);
  const t0 = Date.now();
  return { t0, actor, reader: { session: readerSession, signedAt: t0 }, probe: probeSession };
}

function verifyReq(session, body, timeout = "20s") {
  const params = auth(session, { timeout, tags: { name: "verify" } });
  return ["POST", `${BASE}/admin/audit/verify`, JSON.stringify(body), params];
}

function verify(session, body) {
  const r = http.request(...verifyReq(session, body));
  note(r);
  return r;
}

export function actor(data) {
  const s = data.actor;
  const wide = verify(s, { from_id: 1, to_id: 1 + VERIFY_MAX_SPAN });
  const rule = wide.status === 422 ? wide.json("errors.0.rule") : "";
  bound("verify_max_span", rule === "max_verify_span", wide);
  waitUntil(data.t0, LOAD_AT_S);
  edge("start");
  const both = http.batch([0, 1].map(() => verifyReq(s, {}, `${VERIFY_DEADLINE_S + 30}s`)));
  edge("end");
  both.forEach(note);
  const lost = both.findIndex((r) => r.status === 409 && r.json("code") === "conflict");
  bound("verify_single_flight", lost !== -1, both[lost === -1 ? 0 : lost]);
  const full = both[lost === 0 ? 1 : 0];
  const ok = full.status === 200;
  bound("verify_verified", ok && full.json("verified") === true, full);
  const span = ok ? full.json("to_id") - full.json("from_id") + 1 : 0;
  bound("verify_span", span >= Math.min(VERIFY_MAX_SPAN, ROWS), full);
  bound("verify_deadline", ok && full.timings.duration <= VERIFY_DEADLINE_S * 1000, full);
  if (!ok) return bound("verify_hourly", false, full);
  const head = full.json("to_id");
  for (let n = 2; n <= VERIFY_RATE_PER_HOUR; n += 1) {
    const r = verify(s, { from_id: head - 1, to_id: head });
    if (r.status !== 200) return bound("verify_hourly", false, r);
  }
  const over = verify(s, { from_id: head - 1, to_id: head });
  bound("verify_hourly", over.status === 429, over);
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
