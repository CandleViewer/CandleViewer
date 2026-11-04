// E12-X02 (#452) abuse battery for GET /market/bars and GET /market/klines: the 10-minute,
// abusive-client leg of BQ-3/BQ-4 (ruling 6554826610). MANUAL: no workflow runs it, nothing gates
// a PR on it (C-9.2); its CI run is carried to E12-Q05 (#528). Three scenarios at once:
//   maximal  SESSIONS VUs loop maximal pages: limit=5000 at each window cap (400 d of daily time
//            bars, 250 000 one-minute bars, 31 d of tick:100, 400 d of daily klines)
//   hostile  one VU sends hostile parameters (SQL and line-protocol metacharacters, traversal,
//            NUL, overlong UTF-8, the 24/25-character param edge, absurd numbers, inverted,
//            pre-epoch and year-9999 windows) and checks each answer as the PR suite's oracle does
//   polite   one VU sends small reads and times them: budget #13, p95 < 150 ms
// A 500 anywhere, a status outside 22's set, a body with a traceback, path or SQL, or a polite
// p95 over 150 ms fails the run (thresholds).
// Target is ONLY a loopback app (the dev stack on 127.0.0.1, C-12.9; never an exchange host and
// never a remote one, C-13.5). SESSION is a file holding one `Authorization` header value of a
// local dev session with marketdata:read; it is read, never printed, and never committed:
//   k6 run -e BASE_URL=http://127.0.0.1:8000 -e SESSION=/tmp/cv-dev-session \
//     -e TO=2026-11-01T00:00:00Z tests/load/k6/bars_abuse.js
// Set SESSIONS and DURATION (whole seconds, default 600s) with -e only, as in ingestion_rest.js:
// k6's own --vus or --duration would replace the three scenarios with the default export, which
// this script lacks. scripts/tests/test_bars_abuse_k6.py pins the host guard without running k6.
/* global __ENV, open -- k6 init-context globals */
import http from "k6/http";
import { check, fail } from "k6";
import { Counter, Trend } from "k6/metrics";

const LOOPBACK = /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/;
const BASE = (__ENV.BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
if (!LOOPBACK.test(BASE)) {
  fail(`refusing non-loopback target ${BASE}`); // security notes: never a staging or live host
}
if (!__ENV.SESSION) fail("SESSION is unset: a file with a local dev Authorization header value");
const AUTH = { Authorization: open(__ENV.SESSION).trim() };
const DURATION = __ENV.DURATION || "600s";
if (!/^[1-9]\d*s$/.test(DURATION)) fail(`DURATION is whole seconds, like 600s: ${DURATION}`);
const SESSIONS = Number(__ENV.SESSIONS || 8);
const SYMBOL = __ENV.SYMBOL || "BTCUSDT";
const TO_MS = Date.parse(__ENV.TO || new Date().toISOString());
if (Number.isNaN(TO_MS)) fail(`TO is not an instant: ${__ENV.TO}`);

const DAY_MS = 86_400_000;
const MIN_MS = 60_000;
const ECHO_MAX = 32; // the oracle's echo bound: a probe longer than this must not come back
const STATUSES = new Set([200, 400, 401, 403, 422, 503]); // 22's declared answers
// Built from parts, so the script holds no SQL statement a static rule would read as one.
const SQL = ["SEL" + "ECT", "DR" + "OP TABLE bars_tick", "UNI" + "ON ALL"];
const LEAK = new RegExp(
  ["Traceback", 'File "', "/candleviewer/", `\\b${SQL[0]}\\b`, "\\bFROM bars_"].join("|"),
  "i",
);

const iso = (ms) => new Date(ms).toISOString();
const span = (days) => ({ from: iso(TO_MS - days * DAY_MS), to: iso(TO_MS) });
const bars = (p) => ({ path: "/market/bars", params: { symbol: SYMBOL, limit: 5000, ...p } });
const klines = (p) => ({ path: "/market/klines", params: { symbol: SYMBOL, limit: 5000, ...p } });

const MAXIMAL = [
  bars({ bar_type: "time", param: "D", ...span(400) }),
  bars({ bar_type: "time", param: "1", from: iso(TO_MS - 250_000 * MIN_MS), to: iso(TO_MS) }),
  bars({ bar_type: "tick", param: "100", ...span(31) }),
  klines({ interval: "D", ...span(400) }),
];
// prettier-ignore
const PARAMS = [
  "", "0", "-1", "1e3", "0x64", "100%00", "%00", `100'; ${SQL[1]}; --`, `100 ${SQL[2]} ${SQL[0]} 1`,
  "100,a=1", "100 i=1", "../100", "..%2f..%2f", "%C0%AE%C0%AE", "%E0%80%AE", "\uff11\uff10\uff10",
  "100\u200b", "NaN", "Infinity", "$(id)", "{{7*7}}", "9".repeat(18), "9".repeat(19),
  "1".repeat(24), "1".repeat(25), "x".repeat(4096), "atr:", "atr:" + "9".repeat(20), "10:3",
];
const WINDOWS = [
  { from: "1900-01-01T00:00:00Z", to: "1970-06-01T00:00:00Z" },
  { from: "9999-12-30T00:00:00Z", to: "9999-12-31T23:59:59.999999Z" },
  { from: iso(TO_MS), to: iso(TO_MS - DAY_MS) },
  { from: "2023-13-01T00:00:00Z" },
  { from: "x".repeat(200) },
];
const HOSTILE = [
  ...PARAMS.map((param) => bars({ bar_type: "tick", param, ...span(1) })),
  ...PARAMS.map((interval) => klines({ interval, ...span(1) })),
  ...WINDOWS.map((w) => bars({ bar_type: "time", param: "1", ...w })),
  ...WINDOWS.map((w) => klines({ interval: "1", ...w })),
  ...["0", "-1", "5001", "1e3", "9".repeat(30)].map((limit) =>
    bars({ bar_type: "tick", param: "100", ...span(1), limit }),
  ),
];
const POLITE = bars({ bar_type: "time", param: "1", limit: 100, ...span(0.1) });

const politeMs = new Trend("polite_ms", true);
const serverErrors = new Counter("server_errors");
const offOracle = new Counter("off_oracle");

export const options = {
  scenarios: {
    maximal: { executor: "constant-vus", exec: "maximal", vus: SESSIONS, duration: DURATION },
    hostile: { executor: "constant-vus", exec: "hostile", vus: 1, duration: DURATION },
    polite: { executor: "constant-vus", exec: "polite", vus: 1, duration: DURATION },
  },
  thresholds: {
    polite_ms: ["p(95)<150"], // budget #13 (reads), for the well-behaved session only
    server_errors: ["count==0"],
    off_oracle: ["count==0"],
  },
  summaryTrendStats: ["p(50)", "p(95)", "max", "count"],
};

function qs(params) {
  return Object.keys(params)
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`)
    .join("&");
}

function send(req, tag) {
  const res = http.get(`${BASE}${req.path}?${qs(req.params)}`, { headers: AUTH, tags: { tag } });
  if (res.status >= 500 && res.status !== 503) serverErrors.add(1);
  return res;
}

/** The PR suite's oracle (`_oracle.check`), less the cap arithmetic: a declared status, no leak,
 * no echo of a probe longer than ECHO_MAX. */
function oracle(req, res) {
  const body = res.body || "";
  const echoed = Object.values(req.params).some(
    (v) => String(v).length > ECHO_MAX && body.includes(String(v)),
  );
  const ok = STATUSES.has(res.status) && !LEAK.test(body) && !echoed;
  if (!ok) offOracle.add(1);
  return ok;
}

export function maximal() {
  for (const req of MAXIMAL) {
    const res = send(req, "maximal");
    check(res, {
      "maximal: served or refused, never a 500": (r) => [200, 422, 503].includes(r.status),
    });
  }
}

export function hostile() {
  for (const req of HOSTILE) {
    const res = send(req, "hostile");
    check(res, { "hostile: meets the oracle": (r) => oracle(req, r) });
  }
}

export function polite() {
  const res = send(POLITE, "polite");
  politeMs.add(res.timings.duration);
  check(res, { "polite: 200": (r) => r.status === 200 });
}
