// BQ-nn markers here: RULED (orchestrator, 2026-11-01, #892 ruling of record 6555033109).
// E27-Q03 (#892): sign-in helpers for the account scripts, the auth.js flow (password, then TOTP;
// tests/load/k6/auth.js) against the fixture stack's seeded roster (cvdev.account_fixture.seed:
// pw-<user>, totp-<user>). No credential is committed or logged; the files are read at run time.
/* global __ENV, open */
import http from "k6/http";
import { sleep } from "k6";
import { base32Bytes, codeForStep, stepAt, STEP_S } from "../../lib/totp.js";

const CSRF_COOKIE = "__Host-cv_csrf";

// CV_E27_USERS_FILE (mode 0600): [{"identifier": "<owner username>", "totp_seed": "<base32>"}].
// CV_E27_PASSWORD: the roster password. Both come from the seed run directory; BQ-04 (the seeded
// roster has three Owners, `seed.ROSTER`; the file lists as many as the run uses).
export function loadUsers() {
  if (!__ENV.CV_E27_PASSWORD || !__ENV.CV_E27_USERS_FILE) {
    throw new Error(
      "CV_E27_PASSWORD and CV_E27_USERS_FILE are required (qa/plans/e27/chaos.md, section 3)",
    );
  }
  return JSON.parse(open(__ENV.CV_E27_USERS_FILE)).map((u) => ({
    identifier: u.identifier,
    seed: base32Bytes(u.totp_seed),
  }));
}

const json = (extra) => ({ headers: { "Content-Type": "application/json" }, ...extra });

function csrfOf(r) {
  const jar = r.cookies[CSRF_COOKIE];
  if (jar && jar.length) return jar[0].value;
  const m = new RegExp(`${CSRF_COOKIE}=([^;,\\s]+)`).exec(r.headers["Set-Cookie"] || "");
  return m ? m[1] : r.headers["X-Csrf-Token"];
}

// The API refuses a TOTP step already spent (SR-021): wait for a fresh one when needed.
export function signIn(base, user, lastStep) {
  const l = http.post(
    `${base}/auth/login`,
    JSON.stringify({ identifier: user.identifier, password: __ENV.CV_E27_PASSWORD }),
    json(),
  );
  if (l.status !== 200 || l.json("status") !== "mfa_required") throw new Error(`login ${l.status}`);
  let now = Date.now() / 1000;
  if (stepAt(now) <= lastStep) {
    sleep((lastStep + 1) * STEP_S - now + 0.5);
    now = Date.now() / 1000;
  }
  const step = stepAt(now);
  const v = http.post(
    `${base}/auth/mfa/verify`,
    JSON.stringify({
      mfa_token: l.json("mfa_token"),
      method: "totp",
      code: codeForStep(user.seed, step),
    }),
    json(),
  );
  if (v.status !== 200) throw new Error(`mfa/verify ${v.status}`);
  return { token: v.json("tokens.access_token"), csrf: csrfOf(v), step };
}

export function auth(session, params = {}) {
  return {
    ...params,
    headers: {
      Authorization: `Bearer ${session.token}`,
      "X-CSRF-Token": session.csrf,
      "Content-Type": "application/json",
      ...(params.headers || {}),
    },
    cookies: { [CSRF_COOKIE]: { value: session.csrf, replace: true } },
  };
}
