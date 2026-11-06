// E29-Q03 (#977), budget #4 on the account fixture stack's order lane in pack mode (BQ-02). One
// VU per account opens `orders` for it, then places a limit entry, native stop-loss included
// (C-2.6), every RATE_MS. The timer runs from the POST to the first `orders` ack or reject for
// that `order_link_id` (BQ-01, lib/frames.js); the backend-added portion is `order_submit_seconds`
// over the run less the one pack draw the create waits on (lib/thresholds.js). CV_E29_PROFILE=calibrate is the BQ-09
// self-test. How to run: docs/qa/perf/e29-oms-k6.md.
/* global __ENV */
import http from "k6/http";
import { WebSocket } from "k6/websockets";
import { randomBytes } from "k6/crypto";
import { check } from "k6";
import { Counter, Gauge, Trend } from "k6/metrics";
import { guardedBase, guardedWsUrl } from "./lib/guard.js";
import { loadUser, signIn, submitParams } from "./lib/session.js";
import * as fr from "./lib/frames.js";
import { backendReading, mayFire, orderBody, orderEnv, summaryOf } from "./lib/order.js";
import { packDelayMs, profileOf, thresholdsFor } from "./lib/thresholds.js";

const BASE = guardedBase();
const WS_URL = guardedWsUrl(BASE);
const USER = loadUser();
const PROFILE = profileOf(__ENV.CV_E29_PROFILE);
const DELAY_MS = packDelayMs(__ENV.CV_E29_PACK_DELAY_MS);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ACCOUNTS = String(__ENV.CV_E29_ACCOUNT_IDS || "")
  .split(",")
  .map((x) => x.trim())
  .filter((x) => x !== "");
if (ACCOUNTS.length < 1 || !ACCOUNTS.every((x) => UUID.test(x))) {
  throw new Error("CV_E29_ACCOUNT_IDS must list the demo account ids (uuid, comma separated)");
}
const CFG = orderEnv(__ENV);
const MAX_ORDERS = CFG.maxOrders; // open orders per account (none cancelled)
const RUN_S = CFG.runS;
const RATE_MS = CFG.rateMs;
const ACK_TIMEOUT_MS = 5000; // SUBMIT_TIMEOUT_S, oms/commands.py:289: an ack later is a miss
const ORIGIN = "http://127.0.0.1:5173"; // tests/load/ws/profiles.json origin

const ackMs = new Trend("oms_submit_ack_ms", true);
const httpMs = new Trend("oms_submit_http_ms", true); // the 202, reported, not gated
const acks = new Counter("oms_submit_acks");
const rejects = new Counter("oms_submit_rejects");
const missing = new Counter("oms_ack_missing");
const refused = new Counter("oms_submit_refused");
const wsErrors = new Counter("oms_ws_errors");
const backendAdded = new Gauge("oms_backend_added_p95_ms");
const backendMissing = new Counter("oms_backend_added_missing");

export const options = {
  setupTimeout: "120s",
  summaryTrendStats: ["min", "p(50)", "p(95)", "p(99)", "max", "count"],
  scenarios: {
    submit: {
      executor: "per-vu-iterations",
      vus: ACCOUNTS.length,
      iterations: 1,
      maxDuration: `${RUN_S + 60}s`,
    },
  },
  thresholds: thresholdsFor(PROFILE, DELAY_MS, __ENV.CV_E29_BACKEND_GATE === "1"),
};

function submitted() {
  const body = http.get(`${BASE}/metrics`).body || "";
  return fr.histogram(body, "order_submit_seconds");
}

export function setup() {
  return { session: signIn(BASE, USER), before: submitted() };
}

export default function (data) {
  const account = ACCOUNTS[(__VU - 1) % ACCOUNTS.length];
  const ws = new WebSocket(WS_URL, ["cv.v1.json"], { headers: { Origin: ORIGIN } });
  const mt = fr.newMatcher();
  let seq = 0;
  let ready = false;
  let n = 0;
  let inFlight = 0;
  let closing = false;
  const record = (s) => {
    if (s === null) return;
    ackMs.add(s.ms);
    acks.add(1);
    if (s.kind === "reject") rejects.add(1);
  };
  const send = (t, p, extra) => ws.send(JSON.stringify({ t, id: `c-${++seq}`, ...extra, p }));
  ws.addEventListener("open", () =>
    send("hello", {
      client: "candleviewer-k6",
      client_version: "e29-q03/1",
      shell: "other",
      protocol: "cv.v1",
      encodings: ["structured"],
      capabilities: ["coalescing"],
      locale: "en-GB",
      clock_ms: Date.now(),
    }),
  );
  ws.addEventListener("message", (e) => {
    const at = Date.now();
    const m = JSON.parse(e.data);
    if (m.t === "welcome") send("auth", { access_token: data.session.token });
    else if (m.t === "auth_ok") {
      send("sub", { topics: [{ ch: "orders", opts: { exchange_account_ids: [account] } }] });
    } else if (m.t === "ping") send("pong", { client_ms: Date.now() }, { id: m.id });
    else if (m.t === "err") wsErrors.add(1);
    else if (m.t === "snap" && m.ch === "orders")
      ready = true; // submits start after it
    else for (const a of fr.acksOf(m, at)) record(fr.addAck(mt, a));
  });
  ws.addEventListener("error", () => wsErrors.add(1));
  ws.addEventListener("close", () => {
    if (!closing) wsErrors.add(1); // dropped before the run ended
  });

  const end = Date.now() + RUN_S * 1000;
  const fire = () => {
    const i = n++;
    const t0 = Date.now();
    inFlight += 1;
    http
      .asyncRequest(
        "POST",
        `${BASE}/orders`,
        JSON.stringify(orderBody(CFG, account, i)),
        submitParams(data.session, fr.uuidV4(new Uint8Array(randomBytes(16)))),
      )
      .then((r) => {
        inFlight -= 1;
        httpMs.add(r.timings.duration);
        const link = r.status === 202 ? fr.linkOf(r.json()) : null;
        if (!check(link, { "202 names the order_link_id": (x) => x !== null })) {
          refused.add(1);
          return;
        }
        record(fr.addSent(mt, link, t0));
      });
  };
  const tick = setInterval(() => {
    const now = Date.now();
    missing.add(fr.expire(mt, now, ACK_TIMEOUT_MS));
    if (mayFire(ready, now, end, n, MAX_ORDERS)) fire();
    else if (
      now >= end &&
      ((inFlight === 0 && mt.sent.size === 0) || now > end + ACK_TIMEOUT_MS * 2)
    ) {
      clearInterval(tick);
      missing.add(mt.sent.size + inFlight);
      closing = true;
      ws.close();
      check(n, { "the account was ready and submitted": (c) => c > 0 });
    }
  }, RATE_MS);
}

export function teardown(data) {
  const p95 = fr.quantile(0.95, fr.delta(data.before, submitted()));
  const r = backendReading(p95, DELAY_MS);
  backendMissing.add(r.missing);
  if (r.added !== null) backendAdded.add(r.added);
}

export function handleSummary(data) {
  const out = summaryOf(data, PROFILE); // no session token; compare_baseline.py refuses calibrate
  return { [__ENV.CV_E29_SUMMARY || "k6-summary-oms-submit-ack.json"]: JSON.stringify(out) };
}
