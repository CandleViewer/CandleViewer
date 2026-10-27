// E09-Q05 auth perf profile (#296; made runnable by #2848). Four scenarios, one after another so
// no budget is measured under another scenario's Argon2 load: login_burst (password + TOTP sign-in,
// the Argon2id step reported apart from the rest of the request), session_bootstrap
// (GET /auth/session, budget #13), stepup_burst (POST /auth/step-up answering a real challenge,
// SCR-006) and mfa_verify (POST /auth/mfa/verify, SCR-002). About 10 minutes.
//
// Target: a throwaway TESTNET stack only (C-2.11, C-13.5): before sending any credential,
// setup() refuses to run unless GET /auth/_perf/argon2-params exists (401 unauthenticated, not
// 404), which the API mounts only with CV_AUTH_PERF_ENABLED on a testnet with no exchange key
// (#2097). The CI lane is perf-ingestion-nightly.yml, dispatched with
// profile=auth (job auth-k6). By hand, against such a stack:
//   1. seed N Owners (N >= 10, one per VU), each with a fresh TOTP method:
//        CV_ENVIRONMENT=testnet CV_SEED_USERNAME=perf-1 CV_SEED_PASSWORD=... \
//          uv run python scripts/seed_fixture_user.py --totp-secret-out /tmp/perf/perf-1.totp
//   2. write CV_PERF_USERS_FILE (mode 0600): [{"identifier": "perf-1", "totp_seed": "<base32>"}]
//   3. CV_PERF_PASSWORD=... k6 run -e BASE_URL=http://127.0.0.1:8000 \
//        -e CV_PERF_USERS_FILE=/tmp/perf/users.json tests/load/k6/auth.js
// The seeds are made per run by seed_fixture_user.py; none is committed and none is logged.
//
// TOTP: the API refuses a time step a user already spent (SR-021), so each VU signs in as its own
// user and waits for a fresh 30 s step before each code. stepup_burst provokes its challenge on
// POST /admin/recorder/purge, the owner-only no-grace `recorder_purge` class: every request needs
// a fresh code, so every iteration gets a new challenge. Its body purges nothing even if it were
// ever let through (`before` is the epoch), and the VU never re-sends it while its one-shot grant
// lives (60 s), so the grant is never spent. There is no session cache in candleviewer/auth
// (ADR-0010 addendum, "Session cache"): no cache-off control, no separate first-request figure.
/* global __ENV, open -- k6 init-context globals */
import http from "k6/http";
import exec from "k6/execution";
import { check, fail, sleep } from "k6";
import { Counter, Trend } from "k6/metrics";
import { base32Bytes, codeForStep, stepAt, STEP_S } from "./lib/totp.js";

const BASE = (__ENV.BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const PASSWORD = __ENV.CV_PERF_PASSWORD;
if (!PASSWORD || !__ENV.CV_PERF_USERS_FILE) {
  throw new Error("CV_PERF_PASSWORD and CV_PERF_USERS_FILE are required (see the header)");
}
const USERS = JSON.parse(open(__ENV.CV_PERF_USERS_FILE)).map((u) => ({
  identifier: u.identifier,
  seed: base32Bytes(u.totp_seed),
}));
const N = USERS.length;
if (N < 1) throw new Error("CV_PERF_USERS_FILE lists no user");

const CSRF_COOKIE = "__Host-cv_csrf";
// A UTC instant no recorded data precedes: the purge window [earliest, before) is empty.
const PURGE_PROBE = {
  symbol: "BTCUSDT",
  confirm_symbol: "BTCUSDT",
  reason: "k6 auth profile step-up probe; purges nothing",
  before: "1970-01-01T00:00:00Z",
};
// The one-shot grant lives 60 s (auth/step_up.py SINGLE_USE_WINDOW); the VU waits it out.
const GRANT_WAIT_MS = 62000;

const argon2Ms = new Trend("auth_argon2_step_ms", true);
const restMs = new Trend("auth_login_rest_ms", true);
// #4663: sign-in verification is bounded (CV_AUTH_LOGIN_VERIFY_CONCURRENCY, default 4); an attempt
// past it is refused 429 rate_limited with Retry-After, as a client is told to, and retried.
const loginBusy = new Counter("auth_login_busy_refusals");
const LOGIN_TRIES = 5;

// The host class: "reference" (the default; #2105's host) or "hosted" (a CI runner).
const HOST_CLASS = __ENV.K6_HOST_CLASS || "reference";
if (!["reference", "hosted"].includes(HOST_CLASS)) {
  throw new Error(`K6_HOST_CLASS must be reference or hosted, not ${HOST_CLASS}`);
}
const HOSTED = HOST_CLASS === "hosted";
const STEP_UP = "http_req_duration{scenario:stepup_burst,endpoint:step_up}";

export const options = {
  setupTimeout: "180s",
  summaryTrendStats: ["avg", "p(50)", "p(95)", "p(99)", "max", "count"],
  // Back to back, never overlapping (each start is after the last one's duration + gracefulStop),
  // so the run needs N VUs at most and VU k is always user k.
  scenarios: {
    login_burst: {
      executor: "constant-vus",
      vus: Math.min(5, N),
      duration: "90s",
      gracefulStop: "35s",
      exec: "loginBurst",
    },
    session_bootstrap: {
      executor: "constant-arrival-rate",
      rate: 50,
      timeUnit: "1s",
      duration: "60s",
      preAllocatedVUs: N,
      maxVUs: N,
      gracefulStop: "5s",
      exec: "sessionBootstrap",
      startTime: "130s",
    },
    stepup_burst: {
      executor: "constant-vus",
      vus: N,
      duration: "180s",
      gracefulStop: "70s",
      exec: "stepUp",
      startTime: "200s",
    },
    mfa_verify: {
      executor: "constant-vus",
      vus: N,
      duration: "90s",
      gracefulStop: "35s",
      exec: "mfaVerify",
      startTime: "455s",
    },
  },
  thresholds: {
    checks: ["rate>0.99"],
    "http_req_duration{scenario:session_bootstrap}": ["p(95)<=100"], // budget #13
    // SCR-006's 400 ms is judged on #2105's reference host. On a hosted runner (K6_HOST_CLASS=
    // hosted) the step-up p95 is reported beside it, never gating: the always-true threshold
    // prints the measured p95 in the summary (576 ms on the first hosted run).
    [STEP_UP]: [HOSTED ? "p(95)>=0" : "p(95)<=400"],
    "http_req_duration{scenario:mfa_verify,endpoint:mfa_verify}": ["p(95)<=400"], // SCR-002
    auth_argon2_step_ms: ["p(50)>=100"], // SR-011; login_burst checks the header is there
  },
};

function json(params = {}) {
  return { ...params, headers: { "Content-Type": "application/json", ...(params.headers || {}) } };
}

function bearer(session, params = {}) {
  return {
    ...params,
    headers: {
      Authorization: `Bearer ${session.token}`,
      "X-CSRF-Token": session.csrf,
      ...(params.headers || {}),
    },
    cookies: { [CSRF_COOKIE]: { value: session.csrf, replace: true } },
  };
}

function csrfOf(r) {
  const jar = r.cookies[CSRF_COOKIE];
  if (jar && jar.length) return jar[0].value;
  const m = new RegExp(`${CSRF_COOKIE}=([^;,\\s]+)`).exec(r.headers["Set-Cookie"] || "");
  return m ? m[1] : r.headers["X-Csrf-Token"];
}

// Wait, if need be, for a 30 s step after `last`, then return it and its code.
function freshCode(user, last) {
  let now = Date.now() / 1000;
  if (stepAt(now) <= last) {
    sleep((last + 1) * STEP_S - now + 0.5);
    now = Date.now() / 1000;
  }
  const step = stepAt(now);
  return { step, code: codeForStep(user.seed, step) };
}

function login(user) {
  const body = JSON.stringify({ identifier: user.identifier, password: PASSWORD });
  const params = json({ tags: { endpoint: "login" } });
  let r = http.post(`${BASE}/auth/login`, body, params);
  for (let i = 1; i < LOGIN_TRIES && r.status === 429; i += 1) {
    loginBusy.add(1);
    sleep(Math.min(Number(r.headers["Retry-After"]) || 1, 10));
    r = http.post(`${BASE}/auth/login`, body, params);
  }
  return r;
}

function verify(mfaToken, code) {
  const body = JSON.stringify({ mfa_token: mfaToken, method: "totp", code });
  return http.post(`${BASE}/auth/mfa/verify`, body, json({ tags: { endpoint: "mfa_verify" } }));
}

// Password, then TOTP; the session ({token, csrf}) or null, and the step it spent.
function signIn(user, last) {
  const l = login(user);
  if (l.status !== 200 || l.json("status") !== "mfa_required")
    return { l, session: null, step: last };
  const { step, code } = freshCode(user, last);
  const v = verify(l.json("mfa_token"), code);
  const token = v.status === 200 ? v.json("tokens.access_token") : null;
  return { l, v, step, session: token ? { token, csrf: csrfOf(v) } : null };
}

export function setup() {
  // Before any credential leaves: the perf route answers 401 unauthenticated only where it is
  // mounted (a keyless testnet with CV_AUTH_PERF_ENABLED); anywhere else it is a 404. Only that
  // exact Problem passes, never a redirect or another server's 401.
  const probe = http.get(`${BASE}/auth/_perf/argon2-params`, { redirects: 0 });
  const problem = String(probe.headers["Content-Type"] || "").startsWith(
    "application/problem+json",
  );
  if (probe.status !== 401 || !problem || probe.json("code") !== "unauthenticated") {
    throw new Error(
      `GET /auth/_perf/argon2-params answered HTTP ${probe.status} unauthenticated: not a perf ` +
        "stack, so no credential is sent",
    );
  }
  const sessions = [];
  const steps = [];
  for (const user of USERS) {
    let got = signIn(user, -1);
    // A step an earlier run on this stack spent is refused: one retry on the next step.
    if (!got.session && got.v && got.v.status === 401) got = signIn(user, got.step);
    if (!got.session) {
      const status = got.v ? `mfa/verify HTTP ${got.v.status}` : `login HTTP ${got.l.status}`;
      throw new Error(`setup sign-in failed for user ${sessions.length + 1}: ${status}`);
    }
    sessions.push(got.session);
    steps.push(got.step);
  }
  const pr = http.get(`${BASE}/auth/_perf/argon2-params`, bearer(sessions[0]));
  if (pr.status !== 200) {
    throw new Error(
      `GET /auth/_perf/argon2-params answered HTTP ${pr.status}: start the API with ` +
        "CV_AUTH_PERF_ENABLED=true on a keyless testnet, and seed Owners",
    );
  }
  const a = pr.json(); // SR-011 floor: m=64 MiB, t=3, p=4
  if (!(a.m >= 65536 && a.t >= 3 && a.p >= 4)) {
    throw new Error(`Argon2id params below floor: ${JSON.stringify(a)}`);
  }
  return { sessions, steps };
}

// VU-local: VU k signs in as user k, and remembers the last step it spent and its grant's end.
const mine = { last: null, grantUntil: 0 };
function me(data) {
  const idx = exec.vu.idInTest - 1;
  if (idx >= N) fail(`VU ${idx + 1} has no user: CV_PERF_USERS_FILE lists ${N}`);
  if (mine.last === null) mine.last = data.steps[idx];
  return { idx, user: USERS[idx] };
}

export function loginBurst(data) {
  const { user } = me(data);
  const got = signIn(user, mine.last);
  mine.last = got.step;
  const timing = /argon2;dur=([\d.]+)/.exec(got.l.headers["Server-Timing"] || "");
  if (timing) {
    argon2Ms.add(parseFloat(timing[1]));
    restMs.add(got.l.timings.duration - parseFloat(timing[1]));
  }
  check(got.l, {
    "login 200 mfa_required": (r) => r.status === 200,
    "login carries Server-Timing argon2": () => timing !== null,
  });
  if (!check(got, { "mfa/verify 200 with tokens": (g) => g.session !== null })) sleep(STEP_S);
}

export function sessionBootstrap(data) {
  const s = data.sessions[(exec.vu.idInTest - 1) % data.sessions.length];
  const r = http.get(`${BASE}/auth/session`, bearer(s));
  check(r, { "session 200": (x) => x.status === 200 });
}

export function stepUp(data) {
  const { idx, user } = me(data);
  const session = data.sessions[idx];
  const wait = mine.grantUntil - Date.now();
  if (wait > 0) sleep(wait / 1000);
  const probe = http.post(
    `${BASE}/admin/recorder/purge`,
    JSON.stringify(PURGE_PROBE),
    json(
      bearer(session, {
        headers: {
          "Idempotency-Key": `00000000-0000-4000-8000-${String(idx + 1).padStart(12, "0")}`,
        },
        tags: { endpoint: "purge_probe" },
        responseCallback: http.expectedStatuses(403),
      }),
    ),
  );
  const challengeId = probe.status === 403 ? probe.json("challenge_id") : null;
  const challenged = check(probe, {
    "purge probe refused with a step-up challenge": (r) =>
      r.status === 403 && r.json("code") === "step_up_required" && Boolean(challengeId),
  });
  if (!challenged) {
    sleep(STEP_S); // a refused or broken probe is never retried in a hot loop
    return;
  }
  const { step, code } = freshCode(user, mine.last);
  mine.last = step;
  const r = http.post(
    `${BASE}/auth/step-up`,
    JSON.stringify({ code, password: PASSWORD, challenge_id: challengeId }),
    json(bearer(session, { tags: { endpoint: "step_up" } })),
  );
  mine.grantUntil = Date.now() + GRANT_WAIT_MS;
  check(r, {
    "step-up 200 answers the challenge": (x) =>
      x.status === 200 && x.json("challenge_id") === challengeId && x.json("single_use") === true,
  });
}

export function mfaVerify(data) {
  const { user } = me(data);
  const got = signIn(user, mine.last);
  mine.last = got.step;
  if (!check(got, { "mfa/verify 200 with tokens": (g) => g.session !== null })) sleep(STEP_S);
}
