// BQ-nn markers here: RULED (orchestrator, 2026-11-01, #892 ruling of record 6555033109).
// E27-Q03 (#892) key-verify-burst: every stored key re-verified at the same instant (the nightly
// self-check's worst case), through POST /exchange-accounts/{accountId}/keys/{keyId}/test
// (22 testApiKey: the route the hourly self-check shares its pipeline with; one test per key per
// minute, a second inside the minute is 429).
//
// k6 measures the REST side only: the burst's latency and that no key's answer says "passed" on a
// failed probe. The per-UID exchange budget and the reserve are judged after the run from the stub's
// request log and /metrics (request_log_check.py; qa/plans/e27/chaos.md row E27-L2). The "order path unaffected"
// probe is a signed READ-ONLY call on the same budget class, never an order (BQ-08: no demo keys in
// tests, C-13.5; the substitution is written into the results, not hidden).
/* global __ENV */
import http from "k6/http";
import exec from "k6/execution";
import { check, sleep } from "k6";
import { Counter, Trend } from "k6/metrics";
import { guardedBase } from "./lib/guard.js";
import { auth, loadUsers, signIn } from "./lib/session.js";
import { probeThreshold } from "./lib/thresholds.js";

const BASE = guardedBase(); // BQ-11
const USERS = loadUsers();
// Bursts inside this one run. Not the baseline procedure: the no-burst baseline the 5 % gate
// compares with is the median p95 of 3 separate probe-only runs (06 section 7.4).
const ROUNDS = Number(__ENV.CV_E27_ROUNDS || 3);
// One VU per stored key (a second test of one key inside the minute is a 429). BQ-04: the stack's
// roster decides how many keys exist; set CV_E27_KEYS to that number, 6 only if it is 6.
const KEYS = Number(__ENV.CV_E27_KEYS || 6);
const ROUND_GAP_S = 65; // the per-key test throttle is one a minute (22 testApiKey)
const probeMs = new Trend("e27_order_path_probe_ms", true);
const falsePass = new Counter("e27_false_pass"); // a pass with `rest.ok == false` (plan, E27-L2)
// Throws at init when CV_E27_PROBE_BASELINE_P95_MS is unset or not a positive number: no fallback.
const PROBE_GATE = probeThreshold(__ENV.CV_E27_PROBE_BASELINE_P95_MS);

export const options = {
  setupTimeout: "180s",
  summaryTrendStats: ["avg", "p(50)", "p(95)", "p(99)", "max", "count"],
  scenarios: {
    // One VU per stored key; all start their iteration together, ROUNDS times, ROUND_GAP_S apart.
    burst: {
      executor: "per-vu-iterations",
      vus: KEYS,
      iterations: ROUNDS,
      maxDuration: `${ROUNDS * 120}s`,
      exec: "burst",
    },
    // The read-only probe on the same account set, 1/s, from before the first round to after the last.
    probe: {
      executor: "constant-arrival-rate",
      rate: 1,
      timeUnit: "1s",
      duration: `${ROUNDS * ROUND_GAP_S + 20}s`,
      preAllocatedVUs: 1,
      maxVUs: 2,
      exec: "probe",
    },
  },
  thresholds: {
    checks: ["rate>0.99"],
    e27_false_pass: ["count==0"], // fail closed (qa/plans/e27/chaos.md, E27-L2)
    // BQ-07: the documented tolerance is 5 % (06 section 7.4's gate, `PROBE_TOLERANCE` in
    // lib/thresholds.js) against a no-burst baseline of this same probe: interim, ruled 2026-11-01,
    // owner ratification on #2701. The baseline is passed in; without it the run stops at init.
    e27_order_path_probe_ms: [PROBE_GATE],
  },
};

export function setup() {
  const owner = signIn(BASE, USERS[0], -1);
  const accounts = http
    .get(`${BASE}/exchange-accounts?include_balance=false`, auth(owner))
    .json("items");
  const keys = [];
  for (const a of accounts) {
    const ks = http.get(`${BASE}/exchange-accounts/${a.id}/keys`, auth(owner)).json("items") || [];
    // `id` and `status` are in 22 ApiKey; only active or rotating keys are signable.
    for (const k of ks)
      if (k.status === "active" || k.status === "rotating") keys.push({ account: a.id, key: k.id });
  }
  if (keys.length === 0) throw new Error("no signable stored key: seed the fixture stack first");
  if (keys.length !== KEYS)
    throw new Error(`the stack holds ${keys.length} signable keys; set CV_E27_KEYS=${keys.length}`);
  return { owner, keys }; // BQ-04: seed.ACCOUNTS names 6; fewer is reported, never claimed as 6
}

export function burst(data) {
  const k = data.keys[(exec.vu.idInTest - 1) % data.keys.length];
  if (exec.vu.iterationInScenario > 0) sleep(ROUND_GAP_S); // rounds ROUND_GAP_S apart
  const r = http.post(
    `${BASE}/exchange-accounts/${k.account}/keys/${k.key}/test`,
    JSON.stringify({ include_ws: false }), // the scheduled self-check opens no WS either (22 testApiKey)
    auth(data.owner, { tags: { endpoint: "key_test" } }),
  );
  check(r, { "test answers 200": (x) => x.status === 200 });
  // 22 KeyTestResult: `passed`, `rest.ok`. A verdict that passes while the REST half failed is a defect.
  if (r.status === 200 && r.json("passed") === true && r.json("rest.ok") === false)
    falsePass.add(1);
}

export function probe(data) {
  // Same budget class as the verification (signed REST read). Which read the adapter sends is the
  // stub's to log; this script only times the app's own read of the cached account list.
  // BQ-08: UNVERIFIED that a route exists that signs a read per call; if none, the probe is the
  // account list and the substitution is recorded.
  const r = http.get(
    `${BASE}/exchange-accounts?include_balance=true`,
    auth(data.owner, { tags: { endpoint: "probe" } }),
  );
  probeMs.add(r.timings.duration);
  check(r, { "probe 200": (x) => x.status === 200 });
}

export function handleSummary(data) {
  delete data.setup_data; // setup() returns session tokens: never written to a file (C-12.2)
  return { [__ENV.CV_E27_SUMMARY || "k6-summary-key-verify-burst.json"]: JSON.stringify(data) };
}
