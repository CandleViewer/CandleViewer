/* The hello's clock skew, corrected for its own transit: the arithmetic of the clock-skew guard.
 *
 * Pure, no k6 imports, so Node loads it too (the unit tests run it: test_e17_ws_harness.py).
 *
 * The welcome's `clock_skew_ms` is the server's clock when it read the hello minus the `clock_ms`
 * the client stamped in it (23 4.2). With k6 and the backend on one host clock that is the hello's
 * transit and queueing, not drift (run 39666312188 on cv-bench-01 read 13, 33 and 14 ms), so a
 * guard on it cannot pass there. The client times the round trip, hello sent to welcome received,
 * and takes half of it off: NTP's one-way estimate. The absolute values are taken here, after the
 * correction, because |raw - rtt / 2| is not |raw| - rtt / 2.
 */

/**
 * `{ raw, rtt, corrected, absRaw, absCorrected }` in ms (raw and corrected signed), or `null` when
 * there is nothing to correct: a welcome without `clock_skew_ms` (23 4.2 leaves it out for a hello
 * without a valid `clock_ms`) or a missing time.
 */
export function correctSkew(rawMs, helloSentMs, welcomeReceivedMs) {
  if (![rawMs, helloSentMs, welcomeReceivedMs].every(Number.isFinite)) return null;
  const rtt = welcomeReceivedMs - helloSentMs;
  const corrected = rawMs - rtt / 2;
  return { raw: rawMs, rtt, corrected, absRaw: Math.abs(rawMs), absCorrected: Math.abs(corrected) };
}

/** VU `vu`'s own trend of its hello's `part`: "raw" (the signed `clock_skew_ms`) or "rtt". k6 pools a
 * metric's samples over every VU, which loses which round trip went with which skew, and the guard
 * reads the minimum-RTT hello: so each VU keeps its one hello (one VU is one connection,
 * `ws_load.js`) in two trends of its own, one sample each (`measure.js` `helloTrends`). */
export const helloTrendName = (part, vu) => `cv_hello_${part}_ms_v${vu}`;
const HELLO_TREND = /^cv_hello_(raw|rtt)_ms_v(\d+)$/;

/** The summary's trends (name -> stats) split into the pooled ones and `hellos`, `[{ vu, raw, rtt }]`
 * in VU order: one for each VU whose welcome was timed. */
export function splitHellos(trends) {
  const pooled = {};
  const byVu = new Map();
  for (const [name, t] of Object.entries(trends)) {
    const m = HELLO_TREND.exec(name);
    if (m === null) {
      pooled[name] = t;
      continue;
    }
    const h = byVu.get(Number(m[2])) || { vu: Number(m[2]) };
    if (t.count > 0) h[m[1]] = t.max;
    byVu.set(h.vu, h);
  }
  const hellos = [...byVu.values()].filter((h) => "raw" in h && "rtt" in h);
  return { trends: pooled, hellos: hellos.sort((a, b) => a.vu - b.vu) };
}
