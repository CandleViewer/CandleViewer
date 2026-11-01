// BQ-nn markers here: RULED (orchestrator, 2026-11-01, #892 ruling of record 6555033109).
// E27-Q03 (#892) target guard, shared by the three account scripts.
// An allow-list, not a block-list: the base URL must be loopback or the compose service name `api`
// (BQ-11). Anything that names an exchange host is refused first, so the message says why.
// The fixture stack is the only target (ADR-0036: demo + synthetic feed); the operator attests it
// with CV_E27_FIXTURE_STACK=1, since the API has no route that says "the fixture is armed".
/* global __ENV */

// Case-insensitive, as the Python guard (a URL's scheme and host compare without case).
const ALLOWED = /^http:\/\/(127\.0\.0\.1|localhost|\[::1\]|api)(:\d{1,5})?$/i; // BQ-11
const EXCHANGE = /(^|\.)(bybit|bytick)\.com(:\d+)?(\/|$)/i; // C-13.5 deny list

export function guardedBase() {
  const base = (__ENV.BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
  if (EXCHANGE.test(base.replace(/^https?:\/\//, ""))) {
    throw new Error("refusing an exchange host as the load target (C-13.5)");
  }
  if (!ALLOWED.test(base)) {
    throw new Error("refusing a target that is not loopback or the compose service `api`");
  }
  if (__ENV.CV_E27_FIXTURE_STACK !== "1") {
    throw new Error(
      "set CV_E27_FIXTURE_STACK=1: these scripts run on the account fixture stack only",
    );
  }
  return base;
}
