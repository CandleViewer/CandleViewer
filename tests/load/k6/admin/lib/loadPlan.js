// E42-Q03 (#1216) part 4: the numbers and plans of the admin load profiles (plan section 4, TM 7)
// [BQ-8]. Pure: no k6 import, so node runs it in the harness tests, which pin every value to its
// source (settings, the rbac matrix, the AUDIT-10M timeline) and to tests/load/admin/load_results.py.
import { COMBOS, SPAN_DAYS, SPAN_START, queryString } from "./combos.js";

export const READ_P95_MS = 400; // SCR-135 filter round trip: the Owner's reads under load
export const READ_AB_RATIO = 1.05; // export: within 5 % of the same reads with no export
export const PROBE_P90_MS = 300; // 06 row 4 (demo), E29's refusal probe, nearest-rank p90
export const PROBE_RATIO = 1.2; // within 20 % of the probe's own no-load figure [BQ-8]
export const PROBE_N = 20; // E29: N=20 reps a second apart
export const PACE_S = 1.05; // the reader and the probe: one call a second, under 60 a minute
export const LOAD_AT_S = 30; // the load starts after PROBE_N idle probes and reads
export const FLOOD_RPS = 200; // TM 7: a Manager refusal flood at 200 a second for 60 s
export const FLOOD_S = 60;
export const WAL_CAP_BYTES = 64 * 1024 * 1024; // audit/wal.py AuditWal max_bytes
export const WAL_LIMIT = 0.8; // the run fails above 80 % of the cap
export const VERIFY_MAX_SPAN = 1000000; // audit_verify_max_span
export const VERIFY_DEADLINE_S = 60; // audit_verify_deadline_s
export const VERIFY_RATE_PER_HOUR = 30; // audit_verify_rate_per_hour: the 31st is 429
export const EXPORT_RATE_PER_HOUR = 5; // audit_export_rate_per_hour: the 6th is 429
export const DOWNLOAD_RATE_PER_HOUR = 20; // audit_download_rate_per_hour: the 21st is 429
export const EXPORT_MAX_DAYS = 31; // audit_export_max_range_days: 32 days is 422
// A 31-day window in the past of the dataset's year, so no record this run writes falls in it.
export const EXPORT_WINDOW = { from: "2026-02-01T00:00:00Z", to: "2026-03-04T00:00:00Z" };
export const EXPORT_TOO_LONG = { from: "2026-02-01T00:00:00Z", to: "2026-03-05T00:00:00Z" };
export const EXPORT_SMALL = { from: "2026-01-10T00:00:00Z", to: "2026-01-10T00:01:00Z" };

// How long the reader and the probe run in each profile, from the start of the test.
export const PROFILES = {
  export: {
    readS: 300,
    bounds: [
      "export_single_flight",
      "export_succeeded",
      "export_rows",
      "export_max_range",
      "export_hourly",
      "download_hourly",
    ],
  },
  verify: {
    readS: 150,
    bounds: [
      "verify_max_span",
      "verify_single_flight",
      "verify_verified",
      "verify_span",
      "verify_deadline",
      "verify_hourly",
    ],
  },
  flood: { readS: 150, bounds: [] },
};

// [BQ-8] The reader's queries: the common combinations at page 1, less `severity_actor`, which
// fails its budget by design until #1710 lands and would be read as the load's cost.
export function readerQueries(limit = 200) {
  return COMBOS.filter((c) => c.cls === "common" && c.name !== "severity_actor").map((c) => ({
    combo: c.name,
    query: queryString({ ...c.params, limit: String(limit) }),
  }));
}

// The entries AUDIT-10M puts in [from, to): row g of `rows` is at SPAN_START + g / rows x 365 days.
export function expectedRows(window, rows) {
  const start = Date.parse(SPAN_START);
  const span = SPAN_DAYS * 864e5;
  const first = (t) => Math.min(rows, Math.max(0, Math.ceil(((t - start) / span) * rows)));
  return first(Date.parse(window.to)) - first(Date.parse(window.from));
}

// A v4-shaped id from a counter: the Idempotency-Key of a call, never reused within a run.
export function callId(run, n) {
  const hex = (run * 1e9 + n).toString(16).padStart(12, "0").slice(-12);
  return `00000000-0000-4000-8000-${hex}`;
}

// E29's probe: `POST /orders` an account the Manager is not granted (refused at step 2, before
// any OMS work), or CV_ADMIN_PROBE_ACCOUNT, a granted account under maintenance [BQ-8].
export const PROBE_ACCOUNT = "00000000-0000-4000-8000-0000000000aa";
export function probeBody(account) {
  return {
    exchange_account_id: account || PROBE_ACCOUNT,
    symbol: "BTCUSDT",
    side: "buy",
    order_type: "limit",
    price: "60000",
    sizing: { mode: "fixed_qty", qty: "0.010" },
    stop_loss: { unit: "price", value: "58000" }, // C-2.6: every entry names its native stop
  };
}
export const PROBE_CODES = ["account_scope_denied", "trading_disabled"];
// S-1216P4-01: the only answer the probe accepts, else the test aborts: a 403 with a probe code,
// and with CV_ADMIN_PROBE_ACCOUNT set (a granted account) only `trading_disabled`.
export function isProbeRefusal(status, code, account) {
  if (status !== 403) return false;
  return account ? code === "trading_disabled" : PROBE_CODES.includes(code);
}
// S-1216P4-01, -03: the part 4 profiles run only on an API whose /healthz reports testnet.
export function part4Environment(raw) {
  if (raw !== "testnet") throw new Error("refusing a part 4 profile on an API not in testnet");
  return raw;
}
// S-1216P4-02: a flood answer from 1 to 399 is an admin operation a Manager ran: an RBAC escape.
// Status 0 is a transport failure (timeout, reset), not an answer: the flood counts it under
// `status=0` and `flood_refused` fails it, rather than aborting the run as an escape.
export function rbacEscape(status) {
  return status > 0 && status < 400;
}

// The flood's requests from the matrix's operations (bench/admin/load.py writes them): each path
// parameter from the row's `request`, else a placeholder id that names nothing.
const PLACEHOLDER = "00000000-0000-4000-8000-000000000001";
export function floodRequests(ops) {
  return ops.map((op) => {
    const path = op.path.replace(/\{([^}]+)\}/g, (_m, k) =>
      encodeURIComponent((op.request.path || {})[k] || PLACEHOLDER),
    );
    const params = op.request.params ? `?${queryString(op.request.params)}` : "";
    const body = op.method === "GET" ? null : JSON.stringify(op.request.json || {});
    return { method: op.method, url: `${path}${params}`, body, name: `${op.method} ${op.path}` };
  });
}

// The line count of a downloaded NDJSON export: the header line, then one line an entry.
export function exportEntries(text) {
  let lines = 0;
  for (let i = text.indexOf("\n"); i !== -1; i = text.indexOf("\n", i + 1)) lines += 1;
  if (text.length && !text.endsWith("\n")) lines += 1;
  return lines - 1;
}

// SCR-143's added load (plan 5.2) [BQ-8]: A/A windows first (the noise floor), then three
// alternating A/B pairs, each window ADDED_WINDOW_S long; in a B window ADDED_SESSIONS Owner
// sessions mount SCR-143 (its four reads, D05) with a `system` socket and re-read every REREAD_S.
export const ADDED_WINDOW_S = 600;
export const ADDED_WINDOWS = ["aa_1", "aa_2", "a_1", "b_1", "a_2", "b_2", "a_3", "b_3"];
export const ADDED_SESSIONS = 5;
export const REREAD_S = 10; // worse than a human
export const SCRAPE_S = 5;
export const ADDED_LIMIT = 0.01; // SCR-143: at most 1 % added load
export const NOISE_LIMIT = 0.003; // above it the delta cannot judge 1 %
export const MOUNT_READS = [
  "/admin/health",
  "/admin/incidents?status=open",
  "/admin/incidents?status=acknowledged",
  "/admin/statecharts?kind=position_protection",
];

export function windowAt(elapsedS, windowS = ADDED_WINDOW_S) {
  const i = Math.floor(elapsedS / windowS);
  return i >= 0 && i < ADDED_WINDOWS.length ? ADDED_WINDOWS[i] : null;
}

// The `process_cpu_seconds_total` of a Prometheus text body (every sample summed), or null.
export function cpuSeconds(body) {
  const re = /^process_cpu_seconds_total(?:\{[^}]*\})? ([0-9.e+-]+)$/gm;
  let sum = null;
  for (let m = re.exec(body); m !== null; m = re.exec(body)) sum = (sum || 0) + Number(m[1]);
  return sum;
}
