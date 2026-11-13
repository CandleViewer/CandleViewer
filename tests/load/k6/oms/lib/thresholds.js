// E29-Q03 (#977): the numbers the submit-ack script gates on. Pure, so
// scripts/tests/test_e29_oms_load_tools.py pins each to its source in 06. The backend-added gate
// is report-only until `order_submit_seconds` leaves "planned" (BQ-10; CV_E29_BACKEND_GATE=1 on).
// Calibration (BQ-09): ONE pack draw is timed. The ack is emitted when the create's REST answer
// completes `place` (B01.order.machine.json:137-143, order_steps.py:504); the pack's push frame
// never maps to `ack` (ws_topics.py:151-160). At delay 100 / jitter 10 the p95 is about 110-140 ms,
// so the floor stays one draw: on a delay of at least CALIBRATION_MIN_DELAY_MS it must reach it.
export const SUBMIT_ACK_P95_MS = 300; // 06 budget #4 row (demo); governs over SCR-060's looser 500 ms live figure
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
