// E27-Q03 (#892): the numbers the account scripts gate on, and where each comes from. Pure: no k6
// import, so `test_e27_harness_guards.py` runs it under node and pins every value to its source.
//
// RULED (BQ-07, orchestrator, 2026-11-01, #892 ruling of record 6555033109): the probe's tolerance
// is 5 % (06 section 7.4, line 179), interim, owner ratification on #2701; read p95 < 150 ms (06
// section 2 row 13); the wallet throttle 500 ms (23 section 6.2, line 861).
// PROPOSED, not ruled: the 50 ms throttle tolerance (owner: the 06 owners, Architect and Backend
// leads per 06 line 3; ratified on #2701 or in the results PR). 06 has no wallet row.

export const READ_P95_MS = 150; // RULED, BQ-07: 06 section 2 row 13
export const PROBE_TOLERANCE = 1.05; // RULED, BQ-07: 06 section 7.4, interim (#2701)
export const WALLET_THROTTLE_MS = 500; // RULED, BQ-07: 23 line 861
export const WALLET_THROTTLE_TOL_MS = 50; // PROPOSED: owner the 06 owners (header)
// The compliant manifest's wallet period (`every_ms` 5000, packages/fixtures/accounts/compliant/
// manifest.json): what the stream actually sends. Read from the pack, not chosen here.
export const COMPLIANT_WALLET_PERIOD_MS = 5000;

// The no-burst baseline p95 of the probe, from its own run (median of 3, 06 section 7.4). There is
// no default: a run without the baseline would gate on an absolute number that only looks like
// the ruled 5 %, so it stops before it starts.
export function probeBaselineMs(raw) {
  const n = Number(raw);
  if (raw === undefined || raw === null || String(raw).trim() === "" || !(n > 0) || !isFinite(n)) {
    throw new Error(
      "CV_E27_PROBE_BASELINE_P95_MS must be the no-burst baseline p95 in ms (a positive number): " +
        "the 5 % gate has no meaning without it (qa/plans/e27/chaos.md, E27-L2)",
    );
  }
  return n;
}

export function probeThreshold(raw) {
  return `p(95)<=${probeBaselineMs(raw) * PROBE_TOLERANCE}`;
}

// The wallet gates, for a stream whose per-account period is `periodMs`:
// - floor (topic gap: any two `wallet` frames on one connection): no two frames closer than the
//   throttle less the tolerance, read as the p5 gap;
// - pacing (account gap: two frames carrying one account's balance): the median within one
//   throttle of the period (the gateway may hold a frame back by up to its throttle), so a stream
//   that is too slow, too fast or silent fails. Per account, so several accounts streaming out of
//   phase on one topic do not shrink it.
// A period at or above the throttle cannot exercise the throttle: `throttleExercised` says so, and
// the plan records it (finding F9) rather than reading the floor as a throttle test.
export function walletFloor() {
  return [`p(5)>=${WALLET_THROTTLE_MS - WALLET_THROTTLE_TOL_MS}`];
}

export function walletPacing(periodMs) {
  return [`p(50)>=${periodMs - WALLET_THROTTLE_MS}`, `p(50)<=${periodMs + WALLET_THROTTLE_MS}`];
}

export function throttleExercised(periodMs) {
  return periodMs < WALLET_THROTTLE_MS;
}
