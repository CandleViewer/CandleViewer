/* Custom k6 metrics of the E17-Q03 client, and the summary JSON the Python verdict reads.
 *
 * Plain names, no tags: a tagged submetric only reaches handleSummary through a threshold, and the
 * families here are a closed set. Every sample is recorded in the steady window only (`steady()`),
 * so warm-up (connect, snapshots, bar fill) never enters a number.
 */
import { Counter, Trend } from "k6/metrics";
import { helloTrendName, splitHellos } from "./skew.js";

export const FAMILIES = ["book", "trades", "bars", "footprint", "heatmap"];
/** `meta.reason` of a `snap` (23 7.4); anything else is counted as `other` (an unknown reason is accepted). */
export const SNAP_REASONS = [
  "initial",
  "client_resync",
  "upstream_desync",
  "upstream_reconnect",
  "backpressure",
  "reconfigure",
  "instrument_revision",
  "replay_seek",
  "generation_swap",
  "history_repair",
  "other",
];
export const CLASSES = ["healthy", "lagging", "saturated", "overflowing"];
const HOLD_FAMILIES = ["book", "bars"];

const counter = (name) => new Counter(name);
const trend = (name) => new Trend(name);

export const M = {
  gaps: counter("cv_seq_gaps"),
  unplannedCloses: counter("cv_unplanned_closes"),
  authFailures: counter("cv_auth_failures"),
  subRefused: counter("cv_sub_refused"),
  errors: counter("cv_errors"),
  resyncsSent: counter("cv_resyncs_sent"),
  reauthOk: counter("cv_reauth_ok"),
  connectionsUp: counter("cv_connections_up"),
  spFrames: counter("cv_sp_frames"),
  imprecise: counter("cv_imprecise_values"),
  /** The hello's clock skew, absolute ms, recorded at the welcome. `clockSkew` is the server's
   * `clock_skew_ms` as it came (on one host the hello's transit, not drift); `clockSkewCorrected` is
   * it less half the hello's round trip `helloRtt` (`skew.js`): what the validity guard judges, or
   * `clockSkew` for a run that injects a send delay. */
  clockSkew: trend("cv_clock_skew_ms"),
  clockSkewCorrected: trend("cv_clock_skew_corrected_ms"),
  helloRtt: trend("cv_hello_rtt_ms"),
  clientLag: trend("cv_client_lag_ms"),
  rwKibS: trend("cv_rw_kib_s"),
  resnapKib: trend("cv_resnap_kib"),
  resnapMs: trend("cv_resnap_ms"),
  desyncPerCh: trend("cv_desync_per_ch"),
  tickTrades: trend("cv_tick_decode_ms_trades"),
  /** The window a paced stream holds an update for: the interval between two releases on the reference
   * symbol's stream. A merged book frame carries its newest update's stamp and a bars frame none, so
   * the oldest update's age is not on the wire for them; trades have it (`cv_tick_decode_ms_trades`). */
  hold: Object.fromEntries(HOLD_FAMILIES.map((f) => [f, trend(`cv_hold_ms_${f}`)])),
  snap: Object.fromEntries(SNAP_REASONS.map((r) => [r, counter(`cv_snap_${r}`)])),
  cls: Object.fromEntries(CLASSES.map((c) => [c, counter(`cv_class_${c}`)])),
  bytes: Object.fromEntries(FAMILIES.map((f) => [f, counter(`cv_bytes_${f}`)])),
  frames: Object.fromEntries(FAMILIES.map((f) => [f, counter(`cv_frames_${f}`)])),
  release: Object.fromEntries(FAMILIES.map((f) => [f, trend(`cv_release_decode_ms_${f}`)])),
};

/** Each VU's own pair of hello trends, `[{ raw, rtt }]` by `__VU - 1` (`skew.js` `helloTrendName`),
 * made in the init context as k6 makes every metric: the guard reads the minimum-RTT hello. */
export function helloTrends(vus) {
  return Array.from({ length: vus }, (_, i) => ({
    raw: trend(helloTrendName("raw", i + 1)),
    rtt: trend(helloTrendName("rtt", i + 1)),
  }));
}

/** The run's timeline, absolute epoch ms, set by the runner: warm-up ends and the run ends together
 * on every VU, so the server scrapes (t0, t1) bound the same window k6 measures. */
export function clock(env) {
  const steadyAt = Number(env.STEADY_AT_MS);
  const endAt = Number(env.END_AT_MS);
  return { steadyAt, endAt, steady: () => Date.now() >= steadyAt };
}

const TRENDS = ["p(50)", "p(95)", "p(99)", "max", "count"];
export const summaryTrendStats = TRENDS;

/** The JSON the verdict reads: every `cv_*` metric by kind, each VU's hello as a pair (`hellos`), plus
 * the bytes k6 read off the wire. */
export function summarize(data, extra) {
  const trends = {};
  const counters = {};
  for (const [name, m] of Object.entries(data.metrics)) {
    if (!name.startsWith("cv_")) continue;
    const v = m.values;
    if (m.type === "trend") {
      trends[name] = {
        count: v.count,
        p50: v["p(50)"],
        p95: v["p(95)"],
        p99: v["p(99)"],
        max: v.max,
      };
    } else if (m.type === "counter") {
      counters[name] = v.count;
    }
  }
  const recv = data.metrics.data_received;
  const wire = recv ? recv.values.count : 0;
  return { schema: 1, ...splitHellos(trends), counters, wire_bytes: wire, ...extra };
}
