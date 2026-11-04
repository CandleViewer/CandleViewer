// E42-Q03 (#1216): the target guards of the admin k6 scripts [BQ-9], the rules of
// tests/load/admin/guard.py; the harness guard tests pin the two to one table.
// - The API: loopback or the compose service `api`, an exchange host refused first (the E27 rule,
//   tests/load/k6/accounts/lib/guard.js, whose ALLOWED the tests pin equal to this one).
// - The database the driver says the API serves: one of the datasets' own `_test` databases. k6
//   cannot see the DSN; the driver (bench/admin/run.py) checks it and passes the name.
// - The environment `/healthz` reports: testnet or demo, never live.
// Pure functions of their argument: no k6 import, so node runs them in the tests. No message echoes
// the value it refuses.

const ALLOWED = /^http:\/\/(127\.0\.0\.1|localhost|\[::1\]|api)(:\d{1,5})?$/i;
const EXCHANGE = /(^|\.)(bybit|bytick)\.com(:\d+)?(\/|$)/i; // C-13.5 deny list
export const DATASETS = { bulk: "admin_perf_test", chained: "admin_perf1m_test" }; // [BQ-3]
export const ENVIRONMENTS = ["testnet", "demo"];

export function guardedBase(raw) {
  if (!raw) throw new Error("BASE_URL is required: the API under test is always named");
  const base = String(raw).replace(/\/$/, "");
  if (EXCHANGE.test(base.replace(/^https?:\/\//i, ""))) {
    throw new Error("refusing an exchange host as the load target (C-13.5)");
  }
  if (!ALLOWED.test(base)) {
    throw new Error("refusing a target that is not loopback or the compose service `api`");
  }
  return base;
}

export function guardedDatabase(raw) {
  const name = String(raw || "");
  if (!Object.values(DATASETS).includes(name) || !name.endsWith("_test")) {
    throw new Error("refusing a database that is not one of the admin perf datasets' own");
  }
  return name;
}

export function guardedEnvironment(raw) {
  if (!ENVIRONMENTS.includes(raw)) {
    throw new Error("refusing an API that does not run in testnet or demo");
  }
  return raw;
}
