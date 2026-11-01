// BQ-nn markers here: RULED (orchestrator, 2026-11-01, #892 ruling of record 6555033109).
// E27-Q03 (#892) wallet-fanout: the private `wallet` topic to 5 concurrent browser-like connections
// on the account fixture stack; what each connection receives is judged against 23 section 6.2
// (wallet throttle 500 ms), section 8.2 (whole-object last-write-wins) and section 3.3 (one `s` per
// frame, coalesced or not; no gap).
//
// BQ-02: the ticket names "the existing WS load harness". tests/load/ws/ws_load.js is tied to the
// loopback bench fixture app and to public topics (profiles.json); UNVERIFIED that it can drive a
// private topic on the compose stack. This script therefore speaks the same cv.v1.json envelope as
// tests/load/ws/lib/client.js (hello, auth, sub, ping answered), on a deliberately small client
// that keeps no stream state beyond `s`. If a ruling prefers the shared harness, only the Connection
// below is replaced by an import; the checks stay.
//
// INPUT (plan section 6 item 2, finding F9): the pack's `compliant` scenario sends a wallet snapshot
// after auth and then a wallet frame every 5 s (`every_ms` 5000, packages/fixtures/accounts/
// compliant/manifest.json lines 76-83); no pack scenario sends one at or below the 500 ms throttle.
// So this run gates what the stream does send: the median gap between two frames carrying one
// account's balance must sit within one throttle of the manifest's period, and every connection
// must see MIN_FRAMES frames, so a silent, too-slow or too-fast stream fails. The p5 floor
// (no frame closer than the throttle less the tolerance) holds trivially on a 5 s stream: it is
// not a throttle test until a sub-500 ms scenario exists, which touches the shared E27-Q01 pack
// and is recorded as F9, not built here. The run prints that the throttle was not exercised.
/* global __ENV */
import http from "k6/http";
import { WebSocket } from "k6/websockets";
import { check, fail } from "k6";
import { Counter, Trend } from "k6/metrics";
import { guardedBase, guardedPath } from "./lib/guard.js";
import { auth, loadUsers, signIn } from "./lib/session.js";
import {
  COMPLIANT_WALLET_PERIOD_MS,
  throttleExercised,
  walletFloor,
  walletPacing,
} from "./lib/thresholds.js";

const BASE = guardedBase(); // BQ-11
const USERS = loadUsers();
const CONNS = 5; // 06 section 10: 5 concurrent users
// The per-account period of the scenario the keys run as: `compliant`'s `every_ms` unless the run
// switches them to another scenario, whose manifest `every_ms` it then passes here.
const PERIOD_MS = Number(__ENV.CV_E27_WALLET_PERIOD_MS || COMPLIANT_WALLET_PERIOD_MS);
const RUN_S = Number(__ENV.CV_E27_WS_RUN_S || 600);
const MIN_FRAMES = 20;
const WS_URL = BASE.replace(/^http/, "ws") + guardedPath(__ENV.WS_PATH); // profiles.json ws_path
const ORIGIN = "http://127.0.0.1:5173"; // profiles.json origin
const SUBPROTOCOL = "cv.v1.json"; // profiles.json subprotocol

const gapMs = new Trend("e27_wallet_gap_ms", true); // topic gap: any two wallet frames
const accountGapMs = new Trend("e27_wallet_account_gap_ms", true); // one account's two frames
const seqGaps = new Counter("e27_wallet_seq_gaps");
const frames = new Counter("e27_wallet_frames");
const errors = new Counter("e27_wallet_errors");

export const options = {
  setupTimeout: "120s",
  summaryTrendStats: ["min", "p(5)", "p(50)", "p(95)", "max", "count"],
  scenarios: {
    clients: {
      executor: "per-vu-iterations",
      vus: CONNS,
      iterations: 1,
      maxDuration: `${RUN_S + 60}s`,
    },
  },
  thresholds: {
    checks: ["rate==1"], // every connection's own frame and gap counts (one silent one fails)
    e27_wallet_seq_gaps: ["count==0"], // a coalesced delta still takes one sequence number (23 section 4)
    e27_wallet_errors: ["count==0"],
    // the floor: no frame closer than the throttle less the tolerance (the p5 topic gap)
    e27_wallet_gap_ms: walletFloor(),
    // the pacing: one account's median gap within one throttle of the manifest's period
    e27_wallet_account_gap_ms: walletPacing(PERIOD_MS),
    e27_wallet_frames: [`count>=${MIN_FRAMES * CONNS}`], // fails on a silent stream
  },
};

function scrape(name) {
  // /metrics is a public operational route (deny_by_default.PUBLIC_OPERATIONAL_ROUTES). Every sample
  // of the family is summed, so a label set does not matter.
  const body = http.get(`${BASE}/metrics`).body;
  const re = new RegExp(`^${name}(?:\\{[^}]*\\})? ([0-9.e+-]+)$`, "gm");
  let sum = null;
  for (let m = re.exec(body); m !== null; m = re.exec(body)) sum = (sum || 0) + Number(m[1]);
  return sum;
}

export function setup() {
  if (!throttleExercised(PERIOD_MS)) {
    console.warn(
      `wallet period ${PERIOD_MS} ms is not below the 500 ms throttle: the throttle is not ` +
        "exercised by this run (plan finding F9); the floor and pacing gates still apply",
    );
  }
  const owner = signIn(BASE, USERS[0], -1);
  const items = http
    .get(`${BASE}/exchange-accounts?include_balance=false`, auth(owner))
    .json("items");
  const sessions = [owner];
  let last = owner.step;
  for (let i = 1; i < CONNS; i += 1) {
    // one session per connection when the roster has the users; else the Owner's is reused (BQ-04)
    if (i < USERS.length) {
      const s = signIn(BASE, USERS[i], last);
      last = s.step;
      sessions.push(s);
    } else sessions.push(owner);
  }
  return {
    sessions,
    accountIds: items.map((a) => a.id),
    overflowBefore: scrape("cv_ws_overflow_total"),
  };
}

export default function (data) {
  const session = data.sessions[(__VU - 1) % data.sessions.length];
  const ws = new WebSocket(WS_URL, [SUBPROTOCOL], { headers: { Origin: ORIGIN } });
  let lastTs = null;
  let lastS = null;
  let n = 0;
  let accountGaps = 0;
  const lastByAccount = {};
  let seq = 0;
  const send = (t, p, extra) => ws.send(JSON.stringify({ t, id: `c-${++seq}`, ...extra, p }));
  ws.addEventListener("open", () =>
    send("hello", {
      client: "candleviewer-k6",
      client_version: "e27-q03/1",
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
    if (m.t === "welcome") send("auth", { access_token: session.token });
    else if (m.t === "auth_ok") {
      // 23 section 6.2 table: `wallet` takes `exchange_account_ids`; sub frame as in 23 section 12.1.
      send("sub", { topics: [{ ch: "wallet", opts: { exchange_account_ids: data.accountIds } }] });
    } else if (m.t === "ping")
      send("pong", { client_ms: Date.now() }, { id: m.id }); // as client.js pong()
    else if ((m.t === "snap" || m.t === "d") && m.ch === "wallet") {
      const now = Date.now();
      if (m.t === "d" && lastS !== null && m.s !== lastS + 1) seqGaps.add(1);
      if (lastTs !== null) gapMs.add(now - lastTs);
      lastTs = now;
      // 23 section 15.4: `balances[].exchange_account_id`; one gap per account the frame carries
      const ids = new Set(((m.p && m.p.balances) || []).map((b) => b.exchange_account_id));
      for (const id of ids) {
        if (lastByAccount[id] !== undefined) {
          accountGapMs.add(now - lastByAccount[id]);
          accountGaps += 1;
        }
        lastByAccount[id] = now;
      }
      lastS = m.s;
      n += 1;
      frames.add(1);
    } else if (m.t === "err") errors.add(1);
  });
  ws.addEventListener("error", () => errors.add(1));
  ws.addEventListener("close", () => {});
  // end the iteration at RUN_S; the check names the shortfall
  const end = Date.now() + RUN_S * 1000;
  const tick = setInterval(() => {
    if (Date.now() >= end) {
      clearInterval(tick);
      ws.close();
      check(n, { enough_frames: (c) => c >= MIN_FRAMES });
      check(accountGaps, { enough_account_gaps: (c) => c >= MIN_FRAMES - 1 });
    }
  }, 500);
}

export function teardown(data) {
  const after = scrape("cv_ws_overflow_total");
  // cv_ws_overflow_total is declared in metrics_catalogue.py (:3258); its label set is read at the
  // first run. null on either side is a failure, never a pass.
  if (data.overflowBefore === null || after === null)
    fail("cv_ws_overflow_total not found: queue check blind");
  if (after > data.overflowBefore)
    fail(`cv_ws_overflow_total rose ${data.overflowBefore} -> ${after}`);
}

export function handleSummary(data) {
  delete data.setup_data; // setup() returns session tokens: never written to a file (C-12.2)
  return { [__ENV.CV_E27_SUMMARY || "k6-summary-wallet-fanout.json"]: JSON.stringify(data) };
}
