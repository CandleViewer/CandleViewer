// E42-Q03 (#1216) part 4: an audit export under interactive load (plan 4.1, TM 7) [BQ-8].
// Run by bench/admin/run.py `export` on the chained dataset (admin_perf1m_test), which checks the
// database and the environment first and samples the audit WAL beside it (tests/load/admin/
// wal_check.py). Three VUs from the start of the test (t0):
// - the actor (run N's first Owner) steps up for `audit`, then at LOAD_AT_S exports a 31-day window
//   (the load window's edges are the 202 and the job's end), downloads the file and counts its
//   entries against the window's; then the bounds: a second export while one runs is 409, a
//   32-day window 422, the sixth export in an hour 429, the 21st download in an hour 429;
// - the reader (run N's second Owner) reads the common combinations at one a second throughout:
//   before the window it is the A of the A/B, inside it the B;
// - the probe (run N's first Manager): E29's `POST /orders` refusal, one a second throughout.
// load_results.py judges the points; k6's own thresholds are a second signal.
/* global __ENV */
import http from "k6/http";
import { sleep } from "k6";
import { guardedBase, guardedDatabase, DATASETS } from "./lib/guard.js";
import { auth, loadUsers, signIn } from "./lib/adminSession.js";
import { RESIGN_AFTER_S } from "./lib/thresholds.js";
import {
  bound,
  checkHealth,
  checkProbe,
  edge,
  elevated,
  loadManagers,
  loadThresholds,
  oneVu,
  probe,
  reader,
  runUsers,
  stepUp,
  waitUntil,
} from "./lib/loadCalls.js";
import {
  DOWNLOAD_RATE_PER_HOUR,
  EXPORT_RATE_PER_HOUR,
  EXPORT_SMALL,
  EXPORT_TOO_LONG,
  EXPORT_WINDOW,
  LOAD_AT_S,
  PROFILES,
  callId,
  expectedRows,
  exportEntries,
} from "./lib/loadPlan.js";

const BASE = guardedBase(__ENV.BASE_URL);
if (guardedDatabase(__ENV.CV_ADMIN_PERF_DB) !== DATASETS.chained) {
  throw new Error("the export profile runs on the chained dataset only");
}
const RUN = Number(__ENV.CV_ADMIN_RUN || 1);
const ROWS = Number(__ENV.CV_ADMIN_ROWS || 1000000);
const U = runUsers(loadUsers(), loadManagers(), RUN);
const READ_S = PROFILES.export.readS;
// C-1216P4-08: the actor's token is never re-signed, so its wait for the job ends before the
// token is RESIGN_AFTER_S old; a slower export fails `export_succeeded`.
const JOB_WAIT_S = RESIGN_AFTER_S - LOAD_AT_S - 30;

export const options = {
  setupTimeout: "180s",
  summaryTrendStats: ["p(50)", "p(90)", "p(95)", "p(99)", "max", "count"],
  scenarios: {
    actor: oneVu("actor", "45m"),
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

function job(session, id) {
  const end = Date.now() + JOB_WAIT_S * 1000;
  let r = null;
  while (Date.now() < end) {
    r = http.get(`${BASE}/admin/jobs/${id}`, auth(session, { tags: { name: "job" } }));
    if (r.status !== 200) return r;
    if (["succeeded", "failed", "cancelled"].includes(r.json("status"))) return r;
    sleep(1);
  }
  return r;
}

function exportOf(session, window, n) {
  const body = JSON.stringify({ ...window, compress: false });
  const params = { headers: { "Idempotency-Key": callId(RUN, n) }, tags: { name: "export" } };
  return elevated(BASE, U.actor, session, "POST", "/admin/audit/export", body, params);
}

function download(session, id) {
  const params = { responseType: "text", tags: { name: "download" } };
  return elevated(BASE, U.actor, session, "GET", `/admin/audit/exports/${id}`, null, params);
}

export function actor(data) {
  const session = stepUp(BASE, U.actor, data.actor, null); // the grace, before the window
  waitUntil(data.t0, LOAD_AT_S);
  const started = exportOf(session, EXPORT_WINDOW, 0);
  edge("start");
  if (!bound("export_succeeded", started.status === 202, started)) return edge("end");
  const id = started.json("job_id");
  const second = exportOf(session, EXPORT_SMALL, 1);
  bound(
    "export_single_flight",
    second.status === 409 && second.json("code") === "conflict",
    second,
  );
  const done = job(session, id);
  edge("end");
  if (
    !bound("export_succeeded", done.status === 200 && done.json("status") === "succeeded", done)
  ) {
    return;
  }
  const file = download(session, id);
  const entries = file.status === 200 ? exportEntries(file.body) : -1;
  const want = expectedRows(EXPORT_WINDOW, ROWS);
  bound("export_rows", entries === want && done.json("result.row_count") === want, file);
  const long = exportOf(session, EXPORT_TOO_LONG, 2);
  const rule = long.status === 422 ? long.json("errors.0.rule") : "";
  bound("export_max_range", rule === "max_export_range", long);
  let last = id;
  for (let n = 1; n < EXPORT_RATE_PER_HOUR; n += 1) {
    const r = exportOf(session, EXPORT_SMALL, 2 + n);
    if (r.status !== 202) return bound("export_hourly", false, r);
    last = r.json("job_id");
    job(session, last);
  }
  const over = exportOf(session, EXPORT_SMALL, 99);
  bound("export_hourly", over.status === 429, over);
  for (let n = 1; n < DOWNLOAD_RATE_PER_HOUR; n += 1) {
    const r = download(session, last);
    if (r.status !== 200) return bound("download_hourly", false, r);
  }
  const extra = download(session, last);
  bound("download_hourly", extra.status === 429, extra);
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
