// E42-Q03 (#1216) part 4: the calls the admin load profiles share [BQ-8]: the Owner's reader, E29's
// order-path probe, the `audit` step-up, the bounds and the load window's edges. The numbers are
// lib/loadPlan.js's. Every sample is tagged `ok` (the answer it should get): load_results.py never
// counts a failed call as a duration (part 1's rule). Nothing here logs or writes a credential.
/* global __ENV, open */
import http from "k6/http";
import exec from "k6/execution";
import { sleep } from "k6";
import { Counter, Trend } from "k6/metrics";
import { codeForStep, stepAt, STEP_S, base32Bytes } from "../../lib/totp.js";
import { auth, signIn } from "./adminSession.js";
import { guardedEnvironment } from "./guard.js";
import { maybeResign } from "./thresholds.js";
import {
  PACE_S,
  callId,
  isProbeRefusal,
  part4Environment,
  probeBody,
  readerQueries,
} from "./loadPlan.js";

const readMs = new Trend("cv_admin_read_ms", true);
const probeMs = new Trend("cv_admin_probe_ms", true);
const edgeAt = new Trend("cv_admin_edge_at"); // the value is the edge's epoch ms
const bounds = new Counter("cv_admin_bound");
const unavailable = new Counter("cv_admin_audit_unavailable");

// CV_ADMIN_MANAGERS_FILE (mode 0600): the Managers, as CV_ADMIN_USERS_FILE lists the Owners.
export function loadManagers() {
  if (!__ENV.CV_ADMIN_MANAGERS_FILE) throw new Error("CV_ADMIN_MANAGERS_FILE is required");
  return JSON.parse(open(__ENV.CV_ADMIN_MANAGERS_FILE)).map((u) => ({
    identifier: u.identifier,
    seed: base32Bytes(open(u.totp_file).trim()),
  }));
}

// Run N's users: two Owners (the actor, the reader) and two Managers (the probe, the flood), so
// no run carries another's hourly limits or record budget.
export function runUsers(owners, managers, run) {
  const at = 2 * (run - 1);
  if (owners.length < at + 2 || managers.length < at + 2) {
    throw new Error("the users files need two Owners and two Managers a run");
  }
  return {
    actor: owners[at],
    reader: owners[at + 1],
    probe: managers[at],
    flood: managers[at + 1],
  };
}

export function checkHealth(base) {
  const health = http.get(`${base}/healthz`);
  if (health.status !== 200) throw new Error(`healthz ${health.status}`);
  part4Environment(guardedEnvironment(health.json("environment")));
}

function problemCode(r) {
  try {
    return String(r.json("code") || "");
  } catch {
    return "";
  }
}

// A refused audited action is the finding of TM 7: any 503 `audit_unavailable` is counted.
export function note(r) {
  const code = problemCode(r);
  if (r.status === 503 && code === "audit_unavailable") unavailable.add(1);
  return code;
}

export function bound(name, ok, r) {
  bounds.add(1, { bound: name, ok: ok ? "1" : "0", status: String(r ? r.status : 0) });
  return ok;
}

export function edge(name) {
  edgeAt.add(Date.now(), { edge: name });
}

export function waitUntil(t0, s) {
  const left = t0 / 1000 + s - Date.now() / 1000;
  if (left > 0) sleep(left);
}

function freshStep(lastStep) {
  let now = Date.now() / 1000;
  if (stepAt(now) <= lastStep) {
    sleep((lastStep + 1) * STEP_S - now + 0.5);
    now = Date.now() / 1000;
  }
  return stepAt(now);
}

// `POST /auth/step-up` for `audit` (a grace class): the live challenge's id when there is one,
// else `action_class`. The session is rotated: the VU carries on with the new one.
export function stepUp(base, user, session, challengeId) {
  const step = freshStep(session.step);
  const body = { code: codeForStep(user.seed, step), password: __ENV.CV_ADMIN_PASSWORD };
  if (challengeId) body.challenge_id = challengeId;
  else body.action_class = "audit";
  const r = http.post(`${base}/auth/step-up`, JSON.stringify(body), auth(session));
  note(r);
  if (r.status !== 200) throw new Error(`step-up ${r.status}`);
  const jar = r.cookies["__Host-cv_csrf"];
  session.token = r.json("tokens.access_token");
  session.csrf = jar && jar.length ? jar[0].value : session.csrf;
  session.step = step;
  return session;
}

// A call behind the `audit` step-up: a challenge is answered once and the same request re-sent.
export function elevated(base, user, session, method, url, body, params = {}) {
  const send = () => http.request(method, `${base}${url}`, body, auth(session, params));
  let r = send();
  if (r.status === 403 && problemCode(r) === "step_up_required") {
    stepUp(base, user, session, r.json("challenge_id"));
    r = send();
  }
  note(r);
  return r;
}

// The Owner's reads at one a second until `untilS` after `t0`, signed in again before expiry.
export function reader(base, user, data, untilS) {
  let { session, signedAt } = data;
  const queries = readerQueries();
  for (let i = 0; Date.now() < data.t0 + untilS * 1000; i += 1) {
    ({ session, signedAt } = maybeResign({ session, signedAt }, Date.now(), (step) =>
      signIn(base, user, step),
    ));
    const q = queries[i % queries.length];
    const t = Date.now();
    const r = http.get(`${base}/admin/audit?${q.query}`, auth(session, { tags: { name: "read" } }));
    note(r);
    readMs.add(r.timings.duration, { combo: q.combo, ok: r.status === 200 ? "1" : "0" });
    const left = PACE_S - (Date.now() - t) / 1000;
    if (left > 0) sleep(left);
  }
}

// One probe call; anything but the refusal aborts the whole test (S-1216P4-01): no probe may
// reach the OMS, so never an order on any account.
function probeOnce(base, session, run, n) {
  const account = __ENV.CV_ADMIN_PROBE_ACCOUNT;
  const headers = { "Idempotency-Key": callId(run, n) };
  const params = auth(session, { headers, tags: { name: "probe" } });
  const r = http.post(`${base}/orders`, JSON.stringify(probeBody(account)), params);
  const code = note(r);
  const ok = isProbeRefusal(r.status, code, account);
  if (!ok) exec.test.abort(`the order probe was not refused (${r.status} ${code}): S-1216P4-01`);
  return { r, code };
}

// setup()'s check, before any load: one probe, refused, or the test aborts.
export function checkProbe(base, session, run) {
  probeOnce(base, session, run, 1e9 - 1); // its own Idempotency-Key, never the loop's
}

// E29's refusal probe, one a second until `untilS` after `t0`: only the refusal is ever sampled.
export function probe(base, session, data, untilS, run) {
  for (let n = 0; Date.now() < data.t0 + untilS * 1000; n += 1) {
    const t = Date.now();
    const { r, code } = probeOnce(base, session, run, n);
    probeMs.add(r.timings.duration, { ok: "1", code });
    const left = PACE_S - (Date.now() - t) / 1000;
    if (left > 0) sleep(left);
  }
}

// One VU, one iteration of `exec`, from `startS` into the test.
export function oneVu(exec, maxDuration, startS = 0) {
  const at = { startTime: `${startS}s` };
  return { executor: "per-vu-iterations", vus: 1, iterations: 1, maxDuration, exec, ...at };
}

// Every k6 threshold of the load profiles: a second signal; load_results.py is the judge.
export const loadThresholds = {
  cv_admin_audit_unavailable: ["count==0"],
  "cv_admin_bound{ok:0}": ["count==0"],
};
