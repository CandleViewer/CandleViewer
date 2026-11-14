// E42-Q03 (#1216): the numbers the admin audit profile runs and gates on, and where each comes
// from. Pure: no k6 import, so the harness guard tests run it under node and pin every value.
// Each pinned to its source in services/api/tests/chaos/admin/test_e42_harness_guards.py.

export const COMMON_P95_MS = 400; // SCR-135 filter round trip, US-ADMIN-009 (K01, ADR-0025)
export const Q_P95_MS = 2000; // SCR-135 first page, the `q` worst case (K01, ADR-0025)
export const PAGE_LIMIT = 200; // SCR-135's page (D04) [BQ-2]
// [BQ-2] One call at a time, one call per 1.05 s: under the shipped 60 a minute per user
// (`audit_query_rate_per_minute`), which is part of the build and never raised. A 429 is a
// harness bug: the script stops on it rather than retry.
export const PACE_S = 1.05;
export const WARMUP = 1; // per combination and position, dropped from every statistic
export const SAMPLES = 20; // N per combination and position per run (06 section 7.4)
// The access token lives 12 min (`ACCESS_TOKEN_TTL`) and is never refreshed here; a row of the
// profile takes at most (WARMUP + SAMPLES) calls at the server's own stop (`audit_query_timeout_ms`)
// plus a TOTP step's wait on sign-in. So the session is signed in again at a row boundary once it
// is RESIGN_AFTER_S old: no call is ever made on an expired token.
export const SESSION_TTL_S = 720;
export const STOP_S = 4;
export const RESIGN_AFTER_S = 480;

export function needsSignIn(ageS) {
  return ageS >= RESIGN_AFTER_S;
}

// The loop's decision, pure so a test can drive it with a fake clock: at a row boundary, a session
// `RESIGN_AFTER_S` old is replaced by `signInFn(lastStep)`, and its age restarts at `nowMs`.
export function maybeResign(state, nowMs, signInFn) {
  if (needsSignIn((nowMs - state.signedAt) / 1000)) {
    return { session: signInFn(state.session.step), signedAt: nowMs };
  }
  return state;
}

// A sample is a duration (tag `ok` "1") only when the call answered 200 with a page of at
// most `limit` items that is not vacuous (an empty page passes any budget), unless its combination
// is sparse by construction. `page` is the parsed `items` array, or null when it did not parse.
export function pageOk(status, page, limit, sparse) {
  if (status !== 200 || !Array.isArray(page) || page.length > limit) return false;
  return sparse === true || page.length > 0;
}

export function budgetFor(cls) {
  if (cls === "common") return COMMON_P95_MS;
  if (cls === "q") return Q_P95_MS;
  throw new Error(`no budget for class ${cls}`);
}

// k6's own thresholds, interpolated, at most the budget: a second signal. The figure of record is results.py's
// nearest-rank median of 3 (06 section 7.4). Every call must answer 200: a 503 is a miss.
export function thresholds() {
  return {
    "cv_admin_audit_ms{cls:common,warm:0}": [`p(95)<=${COMMON_P95_MS}`],
    "cv_admin_audit_ms{cls:q,warm:0}": [`p(95)<=${Q_P95_MS}`],
    http_req_failed: ["rate==0"],
    checks: ["rate==1"],
  };
}
