// E40-Q02 (#1203): sign-in for the alert scripts, the auth.js flow (password, then TOTP) over the
// Owners the workflow seeds per run (seed_fixture_user.py). CV_E40_USERS_FILE (mode 0600):
// [{"identifier": "...", "totp_seed": "<base32>"}]; CV_E40_PASSWORD: their password. Neither is
// committed or logged; setup() returns tokens, so every handleSummary drops setup_data (C-12.2).
/* global __ENV, open */
import http from "k6/http";
import { sleep } from "k6";
import { base32Bytes, codeForStep, stepAt, STEP_S } from "../../lib/totp.js";

const CSRF_COOKIE = "__Host-cv_csrf";

export function loadUsers() {
  if (!__ENV.CV_E40_PASSWORD || !__ENV.CV_E40_USERS_FILE) {
    throw new Error("CV_E40_PASSWORD and CV_E40_USERS_FILE are required");
  }
  const users = JSON.parse(open(__ENV.CV_E40_USERS_FILE));
  if (users.length < 1) throw new Error("CV_E40_USERS_FILE lists no user");
  return users.map((u) => ({ identifier: u.identifier, seed: base32Bytes(u.totp_seed) }));
}

const json = { headers: { "Content-Type": "application/json" } };

function csrfOf(r) {
  const jar = r.cookies[CSRF_COOKIE];
  if (jar && jar.length) return jar[0].value;
  const m = new RegExp(`${CSRF_COOKIE}=([^;,\\s]+)`).exec(r.headers["Set-Cookie"] || "");
  return m ? m[1] : r.headers["X-Csrf-Token"];
}

// The API refuses a TOTP step this user already spent (SR-021): `lastStep` is theirs, or -1.
export function signIn(base, user, lastStep = -1) {
  const body = { identifier: user.identifier, password: __ENV.CV_E40_PASSWORD };
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

export function auth(s, params = {}) {
  return {
    ...params,
    headers: {
      Authorization: `Bearer ${s.token}`,
      "X-CSRF-Token": s.csrf,
      "Content-Type": "application/json",
      ...(params.headers || {}),
    },
    cookies: { [CSRF_COOKIE]: { value: s.csrf, replace: true } },
  };
}

// A /metrics family summed over its samples; null when absent (never read as 0).
export function scrape(base, name) {
  const body = http.get(`${base}/metrics`).body || "";
  const re = new RegExp(`^${name}(?:\\{[^}]*\\})? ([0-9.e+-]+)$`, "gm");
  let sum = null;
  for (let m = re.exec(body); m !== null; m = re.exec(body)) sum = (sum || 0) + Number(m[1]);
  return sum;
}
