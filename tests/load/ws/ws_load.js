/* E17-Q03 (#568): the k6 WS load profiles A, B and C and the W5 phases, one script.
 *
 *   k6 run -e PORT=<p> -e PROFILE=A -e PROFILES=tests/load/ws/profiles.json -e TOKENS=<tokens.json> \
 *     -e VECTORS=packages/fixtures/golden/cvwb/vectors.json -e STEADY_AT_MS=<epoch> -e END_AT_MS=<epoch> \
 *     -e SUMMARY=<out.json> [-e WS_PATH=/api/v1/ws] tests/load/ws/ws_load.js
 *
 * The target is ONLY the loopback fixture backend `python -m bench.ws.fixture_app` starts (recorded
 * corpus, no credentials, never an exchange host, C-13.5); it is refused otherwise. Its WebSocket path is
 * the profile table's `ws_path` (`/ws`), or `WS_PATH` where the gateway is mounted under a prefix. `bench/ws/runner.py`
 * sets the timeline (warm-up ends and the run ends at an absolute time on every VU, so its `/metrics`
 * scrapes bound the window k6 measures), reads the summary JSON written here and judges it; the
 * thresholds below mirror the targets so k6's own output names a missed metric too.
 *
 * One VU is one connection (`profiles.json`: users x connections, plus one probe VU on its own user
 * that re-subscribes the reference workspace to time a full re-snapshot).
 */
/* global __ENV, __VU, open */
import { fail } from "k6";
import { Connection } from "./lib/client.js";
import { checkVectors } from "./lib/cvwb.js";
import { M, clock, summarize, summaryTrendStats } from "./lib/measure.js";
import { resolve, topicsFor, wsUrl } from "./lib/profile.js";

const PORT = __ENV.PORT || "8080";
const BASE = `http://127.0.0.1:${PORT}`;
if (!/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(BASE))
  fail(`refusing non-loopback target ${BASE}`);

const TABLE = JSON.parse(open(__ENV.PROFILES));
const TOKENS = JSON.parse(open(__ENV.TOKENS));
const VECTORS = JSON.parse(open(__ENV.VECTORS));
const NAME = __ENV.PROFILE;

/** The resolved profile with the runner's per-run overrides (the runner reads the same ones). */
function profile() {
  const p = resolve(TABLE, NAME);
  for (const [env, key] of [
    ["RTT_DELAY_MS", "rtt_delay_ms"],
    ["REAUTH_AFTER_S", "reauth_after_s"],
    ["PROBE_EVERY_S", "probe_every_s"],
  ]) {
    if (__ENV[env] !== undefined) p[key] = Number(__ENV[env]);
  }
  if (__ENV.FAMILIES !== undefined) p.families = __ENV.FAMILIES.split(",").filter(Boolean);
  if (__ENV.WS_PATH !== undefined) p.ws_path = __ENV.WS_PATH;
  return p;
}
const P = profile();
const CLOCK = clock(__ENV);
const CONNECTIONS = P.users * P.connections;
const TH = TABLE.thresholds;
const GATED =
  P.gate_on === "including" ? "cv_tick_decode_ms_trades" : "cv_release_decode_ms_trades";

export const options = {
  scenarios: {
    clients: {
      executor: "per-vu-iterations",
      vus: CONNECTIONS + (P.probe ? 1 : 0),
      iterations: 1,
      maxDuration: `${Math.ceil((CLOCK.endAt - Date.now()) / 1000) + 120}s`,
    },
  },
  thresholds: {
    cv_seq_gaps: ["count==0"],
    cv_unplanned_closes: ["count==0"],
    cv_auth_failures: ["count==0"],
    cv_errors: ["count==0"],
    cv_sub_refused: ["count==0"],
    cv_client_lag_ms: [`p(95)<${TH.client_lag_p95_ms}`],
    [GATED]: [
      `p(95)<${TH.tick_p95_ms}`,
      `p(99)<${TH.tick_p99_ms}`,
      `p(95)<${TH.local_tick_p95_ms}`,
    ],
    cv_rw_kib_s: [`max<${TH.bandwidth_kib_s}`],
    ...(P.probe
      ? { cv_resnap_kib: [`max<${TH.resnapshot_kib}`], cv_resnap_ms: [`max<${TH.resnapshot_ms}`] }
      : {}),
  },
  summaryTrendStats,
};

export function setup() {
  const bad = checkVectors(VECTORS);
  if (bad.length > 0)
    throw new Error(`the CVWB port disagrees with the golden vectors: ${bad.join("; ")}`);
  if (Date.now() >= CLOCK.steadyAt - 2000)
    throw new Error("k6 was ready too late: warm-up is over, the timeline is lost");
}

export default function () {
  try {
    connect();
  } catch (e) {
    M.errors.add(1); // a VU that dies before its socket opens must not leave a lighter load unseen
    throw e;
  }
}

function connect() {
  const idx = __VU - 1;
  const probe = P.probe && idx === CONNECTIONS;
  const user = probe ? P.users : Math.floor(idx / P.connections);
  const tokens = TOKENS[`u${user}`][probe ? 0 : idx % P.connections];
  const shape = probe ? { ...P, symbols: 1, bars_symbols: 1, footprint_symbols: 1 } : P; // the probe: the reference symbol's workspace
  new Connection({
    id: __VU,
    url: wsUrl(PORT, P.ws_path),
    base: BASE,
    origin: TABLE.origin,
    subprotocol: TABLE.subprotocol,
    tokens: { access: tokens.access, refresh: tokens.refresh },
    topics: topicsFor(TABLE, shape),
    clock: CLOCK,
    role: probe ? "probe" : "conn",
    rttDelayMs: P.rtt_delay_ms,
    reauthAfterS: P.reauth_after_s || 0,
    probeEveryS: P.probe_every_s,
    refSymbol: TABLE.reference_symbol,
    traceSp: __ENV.TRACE_SP === "1",
  }).start();
}

export function handleSummary(data) {
  const out = summarize(data, { profile: NAME, connections: CONNECTIONS, probe: Boolean(P.probe) });
  const frames = Object.entries(out.counters)
    .filter(([k]) => k.startsWith("cv_frames_"))
    .reduce((n, [, v]) => n + v, 0);
  return {
    [__ENV.SUMMARY]: JSON.stringify(out),
    stdout: `ws_load ${NAME}: ${CONNECTIONS} connections, ${frames} frames in the steady window\n`,
  };
}
