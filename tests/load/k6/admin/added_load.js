// E42-Q03 (#1216) part 4: SCR-143's added load, at most 1 % (plan 5.2) [BQ-8]. Run by
// bench/admin/run.py `added`, one run (the method has its own three pairs). Same backend load in
// every window (the API's synthetic feed, nominal). The windows, ADDED_WINDOW_S each, from the
// start of the test: aa_1 and aa_2 (no admin session: the noise floor), then a_1, b_1, a_2, b_2,
// a_3, b_3. In each b window ADDED_SESSIONS Owners (users 1 to 5 of the users file) sign in, mount
// SCR-143 (its four reads, `D05:354-356`), open a `system` socket and re-read every REREAD_S;
// in an a window nobody does. A scraper reads the API's `process_cpu_seconds_total` every SCRAPE_S
// from its own loopback `/metrics` (never another port on the host), tagged with its window.
// load_results.py `added`: the CPU rate per window, the A/A noise, the median of the three
// B-minus-A deltas as a share of A, and the CPU per mount. The strip's own reads (S01's) are not
// made here: they are reported apart.
/* global __ENV, setInterval, clearInterval */
import http from "k6/http";
import exec from "k6/execution";
import { sleep } from "k6";
import { WebSocket } from "k6/websockets";
import { Counter, Trend } from "k6/metrics";
import { guardedBase, guardedDatabase } from "./lib/guard.js";
import { auth, loadUsers, signIn } from "./lib/adminSession.js";
import { checkHealth } from "./lib/loadCalls.js";
import {
  ADDED_SESSIONS,
  ADDED_WINDOWS,
  ADDED_WINDOW_S,
  MOUNT_READS,
  REREAD_S,
  SCRAPE_S,
  cpuSeconds,
  windowAt,
} from "./lib/loadPlan.js";

const BASE = guardedBase(__ENV.BASE_URL);
guardedDatabase(__ENV.CV_ADMIN_PERF_DB);
const USERS = loadUsers();
if (USERS.length < ADDED_SESSIONS) throw new Error(`the users file needs ${ADDED_SESSIONS} Owners`);
const WS_URL = `${BASE.replace(/^http/, "ws")}/ws`;
const cpu = new Trend("cv_admin_cpu_s");
const mounts = new Counter("cv_admin_mounts");
const failed = new Counter("cv_admin_read_failed");
const TOTAL_S = ADDED_WINDOWS.length * ADDED_WINDOW_S;

function bWindow(name) {
  const at = ADDED_WINDOWS.indexOf(name) * ADDED_WINDOW_S;
  return {
    executor: "per-vu-iterations",
    vus: ADDED_SESSIONS,
    iterations: 1,
    startTime: `${at}s`,
    maxDuration: `${ADDED_WINDOW_S + 60}s`,
    exec: "admin",
  };
}

export const options = {
  setupTimeout: "60s",
  scenarios: {
    scrape: {
      executor: "per-vu-iterations",
      vus: 1,
      iterations: 1,
      maxDuration: `${TOTAL_S + 60}s`,
      exec: "scrape",
    },
    b_1: bWindow("b_1"),
    b_2: bWindow("b_2"),
    b_3: bWindow("b_3"),
  },
  thresholds: { cv_admin_read_failed: ["count==0"] },
};

export function setup() {
  checkHealth(BASE);
  return { t0: Date.now() };
}

export function scrape(data) {
  while (Date.now() < data.t0 + TOTAL_S * 1000) {
    const name = windowAt((Date.now() - data.t0) / 1000);
    const r = http.get(`${BASE}/metrics`, { tags: { name: "metrics" } });
    const value = r.status === 200 ? cpuSeconds(r.body) : null;
    if (value === null) failed.add(1, { read: "metrics" });
    else if (name) cpu.add(value, { window: name });
    sleep(SCRAPE_S);
  }
}

function mount(session, name) {
  for (const path of MOUNT_READS) {
    const r = http.get(`${BASE}${path}`, auth(session, { tags: { name: path.split("?")[0] } }));
    if (r.status !== 200) failed.add(1, { read: path.split("?")[0], window: name });
  }
  mounts.add(1, { window: name });
}

export function admin(data) {
  const name = exec.scenario.name;
  const end = data.t0 + (ADDED_WINDOWS.indexOf(name) + 1) * ADDED_WINDOW_S * 1000;
  const session = signIn(BASE, USERS[exec.scenario.iterationInTest % ADDED_SESSIONS]);
  mount(session, name);
  const ws = new WebSocket(WS_URL, ["cv.v1.json"], {
    headers: { Origin: "http://127.0.0.1:5173" },
  });
  let seq = 0;
  const send = (t, p, extra) => ws.send(JSON.stringify({ t, id: `c-${++seq}`, ...extra, p }));
  ws.addEventListener("open", () =>
    send("hello", {
      client: "candleviewer-k6",
      client_version: "e42-q03/4",
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
    else if (m.t === "auth_ok") send("sub", { topics: [{ ch: "system" }] });
    else if (m.t === "ping") send("pong", { client_ms: Date.now() }, { id: m.id });
    else if (m.t === "err") failed.add(1, { read: "ws", window: name });
  });
  const tick = setInterval(() => {
    if (Date.now() >= end) {
      clearInterval(tick);
      ws.close();
    } else mount(session, name);
  }, REREAD_S * 1000);
}

export function handleSummary(data) {
  delete data.setup_data;
  return { [`${__ENV.CV_ADMIN_OUT || "."}/summary.json`]: JSON.stringify(data) };
}
