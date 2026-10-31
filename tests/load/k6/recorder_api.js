// E16-Q04 recorder API/WS load (#481): 5 `recorder` WS subscribers, 1 Hz GET /recording/status
// polling and data-coverage queries, for 20 symbols. Budgets (bench/recorder/budgets.py): API p95
// < 150 ms, a `recorder` frame < 8 KiB for 20 symbols. Every frame received counts; a run that got
// none fails (`recorder_frames`), so the frame budget is never met by an empty run.
// Target is ONLY the loopback fixture app (`bench/recorder/api_app.py`: production routers, the
// real `/ws` gateway and `recorder` topic over a stand-in runtime; no exchange client, no
// credential: its bench sessions are minted in process into a 0600 tokens.json):
//   uv run --project services/api python -m bench.recorder.api_app --out /tmp/cvr   # its port
//   k6 run -e BASE_URL=http://127.0.0.1:<port> -e TOKENS=/tmp/cvr/tokens.json \
//     tests/load/k6/recorder_api.js
// DURATION (whole seconds, default 120s) with -e only, as in ingestion_rest.js: k6's own
// --duration would replace the scenarios. The perf-recorder-nightly workflow runs it; nothing
// gates a PR on it (C-9.2).
/* global __ENV, __VU, open, console, setTimeout, setInterval, clearInterval -- k6 globals */
import http from "k6/http";
import { WebSocket } from "k6/websockets";
import { check, fail } from "k6";
import { Counter, Trend } from "k6/metrics";

const LOOPBACK = /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/;
const BASE = (__ENV.BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
if (!LOOPBACK.test(BASE)) {
  fail(`refusing non-loopback target ${BASE}`); // security notes: the bench is pinned to the stub
}
const WS_URL = `${BASE.replace(/^http/, "ws")}/ws`;
const FIXTURE = JSON.parse(open(__ENV.TOKENS));
const SYMBOLS = FIXTURE.symbols;
const SESSIONS = FIXTURE.sessions;
const SUBSCRIBERS = 5;
if (SYMBOLS.length !== 20) fail(`the frame budget is defined at 20 symbols, got ${SYMBOLS.length}`);
if (SESSIONS.length < SUBSCRIBERS) fail(`need ${SUBSCRIBERS} sessions, got ${SESSIONS.length}`);

const DURATION = __ENV.DURATION || "120s";
if (!/^[1-9]\d*s$/.test(DURATION)) fail(`DURATION is whole seconds, like 120s: ${DURATION}`);
const DURATION_MS = parseInt(DURATION, 10) * 1000;
const FRAME_MAX_BYTES = 8192;
const API_P95_MS = 150;

const frameBytes = new Trend("recorder_frame_bytes");
const frames = new Counter("recorder_frames");
const wsErrors = new Counter("recorder_ws_errors");

export const options = {
  scenarios: {
    subscribers: {
      executor: "per-vu-iterations",
      exec: "subscriber",
      vus: SUBSCRIBERS,
      iterations: 1,
      maxDuration: `${Math.ceil(DURATION_MS / 1000) + 30}s`,
    },
    status_poll: {
      executor: "constant-arrival-rate",
      exec: "status",
      rate: 1, // 1 Hz, the cadence the status cache computes at
      timeUnit: "1s",
      duration: DURATION,
      preAllocatedVUs: 2,
    },
    coverage: {
      executor: "constant-arrival-rate",
      exec: "coverage",
      rate: 2,
      timeUnit: "1s",
      duration: DURATION,
      preAllocatedVUs: 2,
    },
  },
  thresholds: {
    checks: ["rate>0.99"],
    "http_req_duration{endpoint:status}": [`p(95)<${API_P95_MS}`],
    "http_req_duration{endpoint:coverage}": [`p(95)<${API_P95_MS}`],
    recorder_frame_bytes: [`max<${FRAME_MAX_BYTES}`],
    recorder_frames: ["count>0"],
    recorder_ws_errors: ["count==0"],
  },
  summaryTrendStats: ["p(50)", "p(95)", "max", "count"],
};

function bearer(i) {
  return { Authorization: `Bearer ${SESSIONS[i % SESSIONS.length].access}` };
}

export function status() {
  const res = http.get(`${BASE}/recording/status`, {
    headers: bearer(0),
    tags: { endpoint: "status" },
  });
  check(res, { "status 200": (r) => r.status === 200 });
}

export function coverage() {
  const symbol = SYMBOLS[Math.floor(Math.random() * SYMBOLS.length)];
  const res = http.get(`${BASE}/market/data-coverage?symbol=${symbol}`, {
    headers: bearer(1),
    tags: { endpoint: "coverage" },
  });
  check(res, { "coverage 200": (r) => r.status === 200 });
}

// One subscriber: hello -> auth -> sub `recorder` (all 20 symbols), every `snap` and `d` on it
// measured; a server `ping` is answered; closed after DURATION.
export function subscriber() {
  const session = SESSIONS[(__VU - 1) % SESSIONS.length];
  const ws = new WebSocket(WS_URL, ["cv.v1.json"], { headers: { Origin: FIXTURE.origin } });
  let seq = 0;
  let heartbeat = null;
  const send = (t, p, extra) => ws.send(JSON.stringify({ t, id: `r-${++seq}`, ...extra, p }));
  ws.addEventListener("open", () =>
    send("hello", {
      client: "candleviewer-k6",
      client_version: "e16-q04/1",
      shell: "other",
      protocol: "cv.v1",
      encodings: ["structured"],
      capabilities: [],
      locale: "en-GB",
      clock_ms: Date.now(),
    }),
  );
  ws.addEventListener("message", (e) => {
    const raw = e.data;
    const m = JSON.parse(raw);
    if (m.t === "welcome") {
      heartbeat = setInterval(
        () => send("ping", { client_ms: Date.now() }),
        m.p.heartbeat.interval_ms,
      );
      send("auth", { access_token: session.access });
    } else if (m.t === "auth_ok") {
      send("sub", { topics: [{ ch: "recorder", opts: { symbols: SYMBOLS } }] });
    } else if (m.t === "sub_ok") {
      for (const r of m.p.results) check(r, { "recorder sub ok": (x) => x.ok === true });
    } else if ((m.t === "snap" || m.t === "d") && m.ch === "recorder") {
      frames.add(1);
      frameBytes.add(raw.length);
    } else if (m.t === "ping") {
      send("pong", { client_ms: Date.now() }, { id: m.id });
    } else if (m.t === "err" || m.t === "bye" || m.t === "revoked") {
      wsErrors.add(1);
      console.error(`vu ${__VU}: ${m.t} ${JSON.stringify(m.p)}`);
    }
  });
  ws.addEventListener("error", (e) => {
    wsErrors.add(1);
    console.error(`vu ${__VU}: socket error ${e.error}`);
  });
  setTimeout(() => {
    if (heartbeat !== null) clearInterval(heartbeat);
    ws.close(1000);
  }, DURATION_MS);
}
