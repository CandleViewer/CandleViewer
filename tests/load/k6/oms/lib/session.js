// E29-Q03 (#977): sign-in for the OMS scripts, the auth.js flow (password, then TOTP) for one
// seeded Owner of the account fixture stack (cvdev.account_fixture.seed: pw-<user>, totp-<user>).
// CV_E29_USER_FILE (mode 0600): {"identifier": "<owner>", "totp_seed": "<base32>"};
// CV_E29_PASSWORD: its password. Neither is committed or logged; setup() returns the token, so
// handleSummary drops setup_data (C-12.2).
/* global __ENV, open */
import http from "k6/http";
import { base32Bytes, codeForStep, stepAt } from "../../lib/totp.js";

const CSRF_COOKIE = "__Host-cv_csrf";
const json = { headers: { "Content-Type": "application/json" } };

export function loadUser() {
  if (!__ENV.CV_E29_PASSWORD || !__ENV.CV_E29_USER_FILE) {
    throw new Error("CV_E29_PASSWORD and CV_E29_USER_FILE are required");
  }
  const u = JSON.parse(open(__ENV.CV_E29_USER_FILE));
  return { identifier: u.identifier, seed: base32Bytes(u.totp_seed) };
}

function csrfOf(r) {
  const jar = r.cookies[CSRF_COOKIE];
  if (jar && jar.length) return jar[0].value;
  const m = new RegExp(`${CSRF_COOKIE}=([^;,\\s]+)`).exec(r.headers["Set-Cookie"] || "");
  return m ? m[1] : r.headers["X-Csrf-Token"];
}

export function signIn(base, user) {
  const body = { identifier: user.identifier, password: __ENV.CV_E29_PASSWORD };
  const l = http.post(`${base}/auth/login`, JSON.stringify(body), json);
  if (l.status !== 200 || l.json("status") !== "mfa_required") throw new Error(`login ${l.status}`);
  const code = codeForStep(user.seed, stepAt(Date.now() / 1000));
  const v = http.post(
    `${base}/auth/mfa/verify`,
    JSON.stringify({ mfa_token: l.json("mfa_token"), method: "totp", code }),
    json,
  );
  if (v.status !== 200) throw new Error(`mfa/verify ${v.status}`);
  return { token: v.json("tokens.access_token"), csrf: csrfOf(v) };
}

// One submit's headers: the bearer, the double-submit CSRF pair and a fresh Idempotency-Key
// (a UUIDv4, 22 IdempotencyKeyRequired). A demo account needs no X-Arm-Token (22 ArmToken).
export function submitParams(s, key) {
  return {
    headers: {
      Authorization: `Bearer ${s.token}`,
      "X-CSRF-Token": s.csrf,
      "Idempotency-Key": key,
      "Content-Type": "application/json",
    },
    cookies: { [CSRF_COOKIE]: { value: s.csrf, replace: true } },
    tags: { endpoint: "orders" },
  };
}
