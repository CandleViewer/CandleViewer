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
