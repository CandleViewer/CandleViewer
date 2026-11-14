// E42-Q03 (#1216): sign-in for the admin scripts. The E27 helpers' flow (password, then TOTP,
// tests/load/k6/accounts/lib/session.js) with the admin harness's own inputs: `auth` is imported
// from there; `signIn` is not, since it reads the E27 roster's password variable.
// CV_ADMIN_USERS_FILE (mode 0600): [{"identifier": "<owner username>", "totp_file": "<path>"}],
// each TOTP file the base32 text seed_fixture_user.py --totp-secret-out wrote (mode 0600).
// CV_ADMIN_PASSWORD: the run's generated password. Nothing here is logged or written.
/* global __ENV, open */
import http from "k6/http";
import { sleep } from "k6";
import { base32Bytes, codeForStep, stepAt, STEP_S } from "../../lib/totp.js";

export { auth } from "../../accounts/lib/session.js";

const CSRF_COOKIE = "__Host-cv_csrf";

export function loadUsers() {
  if (!__ENV.CV_ADMIN_PASSWORD || !__ENV.CV_ADMIN_USERS_FILE) {
    throw new Error(
      "CV_ADMIN_PASSWORD and CV_ADMIN_USERS_FILE are required (qa/plans/e42-perf-chaos.md)",
    );
  }
  return JSON.parse(open(__ENV.CV_ADMIN_USERS_FILE)).map((u) => ({
    identifier: u.identifier,
    seed: base32Bytes(open(u.totp_file).trim()),
  }));
}

const json = { headers: { "Content-Type": "application/json" } };

function csrfOf(r) {
  const jar = r.cookies[CSRF_COOKIE];
  if (jar && jar.length) return jar[0].value;
  const m = new RegExp(`${CSRF_COOKIE}=([^;,\\s]+)`).exec(r.headers["Set-Cookie"] || "");
  return m ? m[1] : r.headers["X-Csrf-Token"];
}

// One Owner session. The API refuses a TOTP step already spent: wait for a fresh one when needed.
export function signIn(base, user, lastStep = -1) {
  const body = { identifier: user.identifier, password: __ENV.CV_ADMIN_PASSWORD };
  const l = http.post(`${base}/auth/login`, JSON.stringify(body), json);
  if (l.status !== 200 || l.json("status") !== "mfa_required") throw new Error(`login ${l.status}`);
  let now = Date.now() / 1000;
  if (stepAt(now) <= lastStep) {
    sleep((lastStep + 1) * STEP_S - now + 0.5);
    now = Date.now() / 1000;
  }
  const step = stepAt(now);
  const code = codeForStep(user.seed, step);
  const v = http.post(
    `${base}/auth/mfa/verify`,
    JSON.stringify({ mfa_token: l.json("mfa_token"), method: "totp", code }),
    json,
  );
  if (v.status !== 200) throw new Error(`mfa/verify ${v.status}`);
  return { token: v.json("tokens.access_token"), csrf: csrfOf(v), step };
}
