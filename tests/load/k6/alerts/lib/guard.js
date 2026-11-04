// E40-Q02 (#1203): the load target guard, as E27-Q03's (../../accounts/lib/guard.js): loopback or
// the compose service `api` only, never an exchange host (C-13.5), and a plain WS path.
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
  return base;
}

export function guardedWsUrl(base) {
  const path = __ENV.WS_PATH ? String(__ENV.WS_PATH) : "/ws";
  if (!PATH.test(path)) throw new Error("refusing a WS path that is not a plain absolute path");
  return base.replace(/^http/, "ws") + path;
}
