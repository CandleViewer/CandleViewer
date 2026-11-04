// E40-Q02 (#1203) AC "Latency budgets hold", WS half: 50 subscribers on the `alerts` topic while a
// driver acknowledges deliveries, judged against 23 section 6.2.1: the 250 ms cadence holds, and
// no delta is truncated, out of order or missing (lib/frames.js says how each is read).
//
//   k6 run -e BASE_URL=http://127.0.0.1:8000 -e CV_E40_PASSWORD=... \
//     -e CV_E40_USERS_FILE=<0600 file> tests/load/k6/alerts/ws_subscribers.js
//
// Target: the CI stack perf-alerts-nightly.yml starts (loopback). Users: the seeded Owners, 5
// connections each (10 Owners -> 50 subscribers). Input: seed_alerts.py leaves each Owner
// `sent` deliveries; one driver VU per Owner acknowledges them, one per DRIVE_MS, so every window
// of every connection has a change to close on. The topic is scoped to its user, so each ack
// reaches that Owner's 5 connections. Nothing else changes the set (the soak runs afterwards).
// This speaks the cv.v1.json envelope as tests/load/ws/lib/client.js and E27-Q03's wallet_fanout.js.
/* global __ENV */
import http from "k6/http";
import { WebSocket } from "k6/websockets";
import { check, sleep } from "k6";
import { Counter, Trend } from "k6/metrics";
import { guardedBase, guardedWsUrl } from "./lib/guard.js";
import { auth, loadUsers, signIn } from "./lib/session.js";
import { newState, onFrame, PACING_MAX_MS, WINDOW_MS, WINDOW_TOL_MS } from "./lib/frames.js";

const BASE = guardedBase();
const WS_URL = guardedWsUrl(BASE);
const USERS = loadUsers();
const SUBSCRIBERS = 50; // the ticket's 50 WS subscribers
const RUN_S = Number(__ENV.CV_E40_WS_RUN_S || 120);
const SETTLE_S = 10; // the subscribers' snapshots land before the driver starts
const DRIVE_MS = 125; // two acks a window per Owner
const MIN_DELTAS = Math.floor((RUN_S * 1000) / (WINDOW_MS * 4)); // a quarter of the windows
const ORIGIN = "http://127.0.0.1:5173"; // tests/load/ws/profiles.json origin

const windowGap = new Trend("alerts_window_gap_ms", true);
const deltas = new Counter("alerts_deltas");
const issues = {};
for (const k of ["out_of_order", "gap", "truncated", "unacked_rose", "delta_before_snap"]) {
  issues[k] = new Counter(`alerts_${k}`);
}
const wsErrors = new Counter("alerts_ws_errors");
const ackMs = new Trend("alerts_ack_ms", true);

const thresholds = {
  checks: ["rate==1"],
  alerts_ws_errors: ["count==0"],
  alerts_window_gap_ms: [`p(5)>=${WINDOW_MS - WINDOW_TOL_MS}`, `p(50)<=${PACING_MAX_MS}`],
  alerts_deltas: [`count>=${MIN_DELTAS * SUBSCRIBERS}`], // a silent stream fails
};
for (const k of Object.keys(issues)) thresholds[`alerts_${k}`] = ["count==0"];

export const options = {
  setupTimeout: "300s",
  summaryTrendStats: ["min", "p(5)", "p(50)", "p(95)", "p(99)", "max", "count"],
  scenarios: {
    subscribers: {
      executor: "per-vu-iterations",
      vus: SUBSCRIBERS,
      iterations: 1,
      maxDuration: `${RUN_S + SETTLE_S + 60}s`,
    },
    driver: {
      executor: "constant-vus",
      vus: USERS.length,
      duration: `${RUN_S}s`,
      startTime: `${SETTLE_S}s`,
      gracefulStop: "5s",
      exec: "drive",
    },
  },
  thresholds,
};

export function setup() {
  return { sessions: USERS.map((u) => signIn(BASE, u)) }; // distinct users: no step is reused
}

export default function (data) {
  const s = data.sessions[(__VU - 1) % data.sessions.length];
  const ws = new WebSocket(WS_URL, ["cv.v1.json"], { headers: { Origin: ORIGIN } });
  const st = newState();
  let n = 0;
  let seq = 0;
  const send = (t, p, extra) => ws.send(JSON.stringify({ t, id: `c-${++seq}`, ...extra, p }));
  ws.addEventListener("open", () =>
    send("hello", {
      client: "candleviewer-k6",
      client_version: "e40-q02/1",
      shell: "other",
      protocol: "cv.v1",
      encodings: ["structured"],
      capabilities: ["coalescing"],
      locale: "en-GB",
      clock_ms: Date.now(),
    }),
  );
  ws.addEventListener("message", (e) => {
    const m = JSON.parse(e.data);
    if (m.t === "welcome") send("auth", { access_token: s.token });
    else if (m.t === "auth_ok") send("sub", { topics: [{ ch: "alerts" }] });
    else if (m.t === "ping") send("pong", { client_ms: Date.now() }, { id: m.id });
    else if (m.t === "err") wsErrors.add(1);
    else {
      const r = onFrame(st, m, Date.now());
      if (r.kind !== "delta") return;
      n += 1;
      deltas.add(1);
      for (const k of r.issues) issues[k].add(1);
      if (r.windowGapMs !== null) windowGap.add(r.windowGapMs);
    }
  });
  ws.addEventListener("error", () => wsErrors.add(1));
  const end = Date.now() + (RUN_S + SETTLE_S) * 1000;
  const tick = setInterval(() => {
    if (Date.now() < end) return;
    clearInterval(tick);
    ws.close();
    check(n, { "every subscriber saw its deltas": (c) => c >= MIN_DELTAS });
  }, 500);
}

// One driver VU per Owner: a page of its unacked deliveries, then one ack per DRIVE_MS.
export function drive(data) {
  const s = data.sessions[(__VU - 1) % data.sessions.length];
  const page = http.get(`${BASE}/alerts/deliveries?unacked_only=true&limit=50`, auth(s));
  const ids = page.status === 200 ? page.json("items").map((d) => d.id) : [];
  check(ids, { "the Owner has deliveries to ack": (x) => x.length > 0 });
  if (ids.length === 0) return sleep(1); // nothing to ack: never spin GETs for the rest of the run
  for (const id of ids) {
    const t0 = Date.now();
    const r = http.post(`${BASE}/alerts/deliveries/${id}/ack`, null, auth(s));
    ackMs.add(r.timings.duration);
    check(r, { "ack 200 acked": (x) => x.status === 200 && x.json("status") === "acked" });
    const left = DRIVE_MS - (Date.now() - t0);
    if (left > 0) sleep(left / 1000);
  }
}

export function handleSummary(data) {
  delete data.setup_data; // session tokens: never written to a file (C-12.2)
  return { [__ENV.CV_E40_SUMMARY || "k6-summary-alerts-ws.json"]: JSON.stringify(data) };
}
