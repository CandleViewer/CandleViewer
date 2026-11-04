// E29-Q03 (#977): the numbers the submit-ack script gates on. Pure, so
// scripts/tests/test_e29_oms_load_tools.py pins each to its source in 06. The backend-added gate
// is report-only until `order_submit_seconds` leaves "planned" (BQ-10; CV_E29_BACKEND_GATE=1 on).
// Calibration (BQ-09): the pack waits one draw before it answers a create and one more before its
// ack frame, so on a delay of at least CALIBRATION_MIN_DELAY_MS the p95 must reach that delay.
export const SUBMIT_ACK_P95_MS = 300; // 06 line 28, budget #4 (demo)
export const BACKEND_ADDED_P95_MS = 50; // 06 section 5.2, line 124
export const CALIBRATION_MIN_DELAY_MS = 100; // BQ-09
export const MAX_PACK_DELAY_MS = 10000; // cvdev order_lane MAX_DELAY_MS
export const PROFILES = ["gate", "calibrate"];

// The `delay_ms` the stack's order_lane.json holds: required, since the backend-added portion is
// the server's submit time less the one draw it waits on the pack.
export function packDelayMs(raw) {
  const s = raw === undefined || raw === null ? "" : String(raw).trim();
  const n = Number(s);
  if (!/^\d+$/.test(s) || n > MAX_PACK_DELAY_MS) {
    throw new Error(
      `CV_E29_PACK_DELAY_MS must be order_lane.json's delay_ms (0..${MAX_PACK_DELAY_MS})`,
    );
  }
  return n;
}

export function profileOf(raw) {
  const p = raw === undefined || raw === "" ? "gate" : String(raw);
  if (!PROFILES.includes(p))
    throw new Error(`CV_E29_PROFILE must be one of ${PROFILES.join(", ")}`);
  return p;
}

export function thresholdsFor(profile, delayMs, backendGate) {
  const t = {
    checks: ["rate==1"],
    oms_ack_missing: ["count==0"],
    oms_submit_refused: ["count==0"],
    oms_submit_acks: ["count>0"],
  };
  if (profile === "calibrate") {
    if (delayMs < CALIBRATION_MIN_DELAY_MS) {
      throw new Error(`calibrate needs a pack delay_ms of at least ${CALIBRATION_MIN_DELAY_MS}`);
    }
    t.oms_submit_ack_ms = [`p(95)>=${delayMs}`];
    return t;
  }
  t.oms_submit_ack_ms = [`p(95)<${SUBMIT_ACK_P95_MS}`];
  if (backendGate) {
    t.oms_backend_added_p95_ms = [`value<=${BACKEND_ADDED_P95_MS}`];
    t.oms_backend_added_missing = ["count==0"]; // no measurement is a failure, never a pass
  }
  return t;
}

// The backend-added p95 in ms from the histogram's p95 in seconds, less the one pack draw the
// server waits on (its jitter is not taken off, so the figure errs high, never low).
export function backendAddedMs(p95Seconds, delayMs) {
  if (p95Seconds === null || p95Seconds === undefined) return null;
  return Math.max(0, p95Seconds * 1000 - delayMs);
}
