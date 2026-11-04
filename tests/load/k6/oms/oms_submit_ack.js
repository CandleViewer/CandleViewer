// E29-Q03 (#977), budget #4 on the account fixture stack's order lane in pack mode (BQ-02). One
// VU per account opens `orders` for it, then places a limit entry, native stop-loss included
// (C-2.6), every RATE_MS. The timer runs from the POST to the first `orders` ack or reject for
// that `order_link_id` (BQ-01, lib/frames.js); the backend-added portion is `order_submit_seconds`
// over the run less one pack draw (lib/thresholds.js). CV_E29_PROFILE=calibrate is the BQ-09
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
import { backendAddedMs, packDelayMs, profileOf, thresholdsFor } from "./lib/thresholds.js";

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
const DECIMAL = /^\d{1,12}(\.\d{1,8})?$/;
const SYMBOL = __ENV.CV_E29_SYMBOL || "BTCUSDT";
const PRICE = __ENV.CV_E29_PRICE || "";
const QTY = __ENV.CV_E29_QTY || "0.001";
const SL_PCT = __ENV.CV_E29_SL_PERCENT || "1";
if (!/^[A-Z0-9]{2,16}USDT$/.test(SYMBOL) || ![PRICE, QTY, SL_PCT].every((x) => DECIMAL.test(x))) {
  throw new Error("CV_E29_SYMBOL, CV_E29_PRICE, CV_E29_QTY and CV_E29_SL_PERCENT must be valid");
}
const px = (k) => (Number(PRICE) * k).toFixed(8).replace(/\.?0+$/, "");
const BUY_PRICE = px(0.99); // 1 % either side of CV_E29_PRICE, which should sit near the mark
const SELL_PRICE = px(1.01);
const MAX_ORDERS = Number(__ENV.CV_E29_MAX_ORDERS || 200); // open orders per account (none cancelled)
const RUN_S = Number(__ENV.CV_E29_RUN_S || 120);
const RATE_MS = Number(__ENV.CV_E29_RATE_MS || 500);
const ACK_TIMEOUT_MS = 5000; // an ack later than this is a miss, not a slow sample
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

// One limit entry, its native SL a percent off the entry (22 PlaceOrderRequest, Offset).
function order(account, i) {
  return JSON.stringify({
    exchange_account_id: account,
    symbol: SYMBOL,
    side: i % 2 === 0 ? "buy" : "sell",
    order_type: "limit",
    intent: "entry",
    price: i % 2 === 0 ? BUY_PRICE : SELL_PRICE, // buy below, sell above: they never cross
    time_in_force: "GTC",
    sizing: { mode: "fixed_qty", qty: QTY },
    stop_loss: { unit: "percent", value: SL_PCT },
  });
}

export default function (data) {
  const account = ACCOUNTS[(__VU - 1) % ACCOUNTS.length];
  const ws = new WebSocket(WS_URL, ["cv.v1.json"], { headers: { Origin: ORIGIN } });
  const mt = fr.newMatcher();
  let seq = 0;
  let ready = false;
  let n = 0;
  let inFlight = 0;
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

  const end = Date.now() + RUN_S * 1000;
  const fire = () => {
    const i = n++;
    const t0 = Date.now();
    inFlight += 1;
    http
      .asyncRequest(
        "POST",
        `${BASE}/orders`,
        order(account, i),
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
    if (ready && now < end && n < MAX_ORDERS) fire();
    else if (
      now >= end &&
      ((inFlight === 0 && mt.sent.size === 0) || now > end + ACK_TIMEOUT_MS * 2)
    ) {
      clearInterval(tick);
      missing.add(mt.sent.size + inFlight);
      ws.close();
      check(n, { "the account was ready and submitted": (c) => c > 0 });
    }
  }, RATE_MS);
}

export function teardown(data) {
  const p95 = fr.quantile(0.95, fr.delta(data.before, submitted()));
  const added = backendAddedMs(p95, DELAY_MS);
  if (added === null) backendMissing.add(1);
  else backendAdded.add(added);
}

export function handleSummary(data) {
  delete data.setup_data; // the session token: never written to a file (C-12.2)
  data.cv_profile = PROFILE; // compare_baseline.py refuses a calibration summary
  data.cv_pack_delay_ms = DELAY_MS;
  return { [__ENV.CV_E29_SUMMARY || "k6-summary-oms-submit-ack.json"]: JSON.stringify(data) };
}
