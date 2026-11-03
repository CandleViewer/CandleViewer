// E12-Q05 slice 4 (#528): bars backfill REST load, budget #13 (reads p95 < 150 ms).
// Target is ONLY the fixture backend on loopback or the compose service `api` (never an exchange host, C-13.5):
//   k6 run -e BASE_URL=http://127.0.0.1:<port> -e PLAN=plan.json -e SUMMARY=out.json \
//     tests/load/k6/bars/backfill.js
// `PLAN` comes from `python -m bench.bars.backfill_plan <end_us> plan.json`: `pages` is a 30-day
// window in order (one chart open walks them all), `other` is the request sent beside the opens to
// show their paging does not stall other readers. VUS and DURATION by -e only (see ingestion_rest.js).
// The simulated upstream 10018 leg is pending: the fixture backend has no such hook yet.
/* global __ENV, open -- k6 init-context globals */
import http from "k6/http";
import { check, fail } from "k6";
import { Counter, Trend } from "k6/metrics";

// The E27-Q03 allow-list (accounts/lib/guard.js, bench.bars.guard): loopback or the compose `api`.
const ALLOWED = /^http:\/\/(127\.0\.0\.1|localhost|\[::1\]|api)(:\d{1,5})?$/i;
const EXCHANGE = /(^|\.)(bybit|bytick)\.com\.?(:\d+)?(\/|$)/i; // C-13.5
const BASE = __ENV.BASE_URL || "http://127.0.0.1:8000";
if (EXCHANGE.test(BASE.replace(/^https?:\/\//, ""))) fail("refusing an exchange host (C-13.5)");
if (!ALLOWED.test(BASE))
  fail("refusing a target that is not loopback or the compose service `api`");
const PLAN = JSON.parse(open(__ENV.PLAN));
const DURATION = __ENV.DURATION || "60s";

const pageMs = new Trend("backfill_page_ms", true);
const otherMs = new Trend("other_route_ms", true);
const pages = new Counter("backfill_pages");

export const options = {
  scenarios: {
    opens: {
      executor: "constant-vus",
      exec: "open_chart",
      vus: Number(__ENV.VUS || 5),
      duration: DURATION,
    },
    others: {
      executor: "constant-arrival-rate",
      exec: "other",
      rate: 5,
      timeUnit: "1s",
      duration: DURATION,
      preAllocatedVUs: 2,
    },
  },
  thresholds: {
    checks: ["rate>0.99"],
    backfill_page_ms: ["p(95)<150"], // budget #13 (reads)
    other_route_ms: ["p(95)<150"], // not stalled by the backfill paging
  },
  summaryTrendStats: ["p(50)", "p(95)", "max", "count"],
};

function qs(params) {
  return Object.keys(params)
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`)
    .join("&");
}

function get(spec, trend) {
  const res = http.get(`${BASE}${spec.path}?${qs(spec.params)}`);
  trend.add(res.timings.duration);
  check(res, { "klines 200": (r) => r.status === 200 });
}

export function open_chart() {
  for (const p of PLAN.pages) {
    get(p, pageMs);
    pages.add(1);
  }
}

export function other() {
  get(PLAN.other, otherMs);
}

export function handleSummary(data) {
  return { [__ENV.SUMMARY || "summary.json"]: JSON.stringify(data) };
}
