// E40-Q02 (#1203) soak: 200 armed alerts on the CI stack, with the pass/fail checks of BQ-06.
// REPORT-ONLY for now (blocker #5745 (E35-T15)): the rules metric source has no production producer yet (E12/E18-E25
// adapters push into `PushedMetricSource`), so nothing fires here until that bridge lands; the
// workflow's CV_E40_SOAK_GATE switches the verdict on. Two profiles (CV_E40_SOAK_PROFILE): `smoke` (10 minutes, nightly) and `24h`
// (86 400 s, workflow_dispatch only). This script arms, samples and disarms; soak_check.py then
// judges the rows: every firing has its delivery row (sum of fire_count == delivery rows), no
// outbox row is dead, and at least one alert fired (a silent soak is not a pass). Memory is
// sampled from the API's /metrics (process_resident_memory_bytes) and REPORTED ONLY on the first
// runs: the envelope is a number the owner sets (BQ-06), never a default here.
//
// Each alert is `every_time` with a 60 s cooldown, on a condition that holds on every price
// update (last_price > 0), so each fires about once a minute once price updates reach the rules.
/* global __ENV */
import http from "k6/http";
import { check, sleep } from "k6";
import { Trend } from "k6/metrics";
import { guardedBase } from "./lib/guard.js";
import { auth, loadUsers, scrape, signIn } from "./lib/session.js";

const BASE = guardedBase();
const USERS = loadUsers();
const PROFILES = { smoke: 600, "24h": 86400 };
const PROFILE = __ENV.CV_E40_SOAK_PROFILE || "smoke";
if (!(PROFILE in PROFILES)) throw new Error(`CV_E40_SOAK_PROFILE must be smoke or 24h`);
const DURATION_S = PROFILES[PROFILE];
const ALERTS = 200; // the ticket's 200 armed alerts, spread over the Owners
const SAMPLE_S = PROFILE === "smoke" ? 30 : 300;
const SYMBOL = __ENV.CV_E40_SOAK_SYMBOL || "BTCUSDT";

const rss = new Trend("alerts_soak_rss_bytes"); // report only (BQ-06)
const outboxDepth = new Trend("alerts_soak_outbox_depth"); // report only

export const options = {
  setupTimeout: "600s",
  teardownTimeout: "600s",
  summaryTrendStats: ["min", "p(50)", "max", "count"],
  scenarios: {
    sampler: { executor: "constant-vus", vus: 1, duration: `${DURATION_S}s`, gracefulStop: "5s" },
  },
  thresholds: { checks: ["rate==1"] },
};

function alertBody(i) {
  return {
    name: `e40-soak-${i}`,
    symbol: SYMBOL,
    trigger_mode: "every_time",
    cooldown_seconds: 60,
    channels: ["in_app"],
    condition_ir: {
      ir_version: 1,
      trigger: { type: "on_price_update", debounce_ms: 250 },
      conditions: { node_id: "c1", op: "gt", left: { metric: "last_price" }, right: { const: 0 } },
    },
    message_template: `e40 soak ${i}`,
  };
}

export function setup() {
  const sessions = USERS.map((u) => signIn(BASE, u));
  const owned = sessions.map(() => []);
  for (let i = 0; i < ALERTS; i += 1) {
    const k = i % sessions.length;
    const headers = { "Idempotency-Key": `e40-soak-${__ENV.CV_E40_RUN_ID || "local"}-${i}` };
    const r = http.post(
      `${BASE}/alerts`,
      JSON.stringify(alertBody(i)),
      auth(sessions[k], { headers }),
    );
    check(r, { "alert armed (201)": (x) => x.status === 201 });
    if (r.status === 201) owned[k].push(r.json("id"));
  }
  return { owned, steps: sessions.map((s) => s.step) };
}

export default function () {
  const v = scrape(BASE, "process_resident_memory_bytes");
  check(v, { "the API's RSS is exposed": (x) => x !== null });
  if (v !== null) rss.add(v);
  const d = scrape(BASE, "cv_outbox_depth");
  if (d !== null) outboxDepth.add(d);
  sleep(SAMPLE_S);
}

// Disarm before soak_check.py reads the rows, so no firing lands between its two counts. The
// setup tokens may have expired by now (24 h): each Owner signs in again on a fresh TOTP step.
export function teardown(data) {
  USERS.forEach((u, k) => {
    const s = signIn(BASE, u, data.steps[k]);
    for (const id of data.owned[k]) {
      const r = http.put(
        `${BASE}/alerts/${id}/enabled`,
        JSON.stringify({ enabled: false }),
        auth(s),
      );
      check(r, { "alert disarmed (200)": (x) => x.status === 200 });
    }
  });
}

export function handleSummary(data) {
  delete data.setup_data; // session tokens: never written to a file (C-12.2)
  return { [__ENV.CV_E40_SUMMARY || "k6-summary-alerts-soak.json"]: JSON.stringify(data) };
}
