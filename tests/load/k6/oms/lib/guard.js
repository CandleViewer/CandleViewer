// E29-Q03 (#977): the load target guard, the shape of E27-Q03's and the alert kit's pattern
// (copied, not imported, BQ-07): loopback or the compose service `api` only, never an exchange
// host (C-13.5), a plain WS path, and the operator's word that the target is the account fixture
// stack with the order lane in pack mode (the API has no route that says so).
/* global __ENV */
const ALLOWED = /^http:\/\/(127\.0\.0\.1|localhost|\[::1\]|api)(:\d{1,5})?$/i;
const EXCHANGE = /(^|\.)(bybit|bytick)\.com(:\d+)?(\/|$)/i;
const PATH = /^\/[\w/-]*$/;

export function guardedBase() {
  const base = (__ENV.BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
  if (EXCHANGE.test(base.replace(/^https?:\/\//, ""))) {
    throw new Error("refusing an exchange host as the load target (C-13.5)");
  }
  if (!ALLOWED.test(base)) throw new Error("refusing a target that is not loopback or `api`");
  if (__ENV.CV_E29_FIXTURE_STACK !== "1") {
    throw new Error("set CV_E29_FIXTURE_STACK=1: this script runs on the fixture order lane only");
  }
  return base;
}

export function guardedWsUrl(base) {
  const path = __ENV.WS_PATH ? String(__ENV.WS_PATH) : "/ws";
  if (!PATH.test(path)) throw new Error("refusing a WS path that is not a plain absolute path");
  return base.replace(/^http/i, "ws") + path;
}
