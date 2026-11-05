// E29-Q03 (#977): arms one demo account on the account fixture stack for oms_submit_ack.js, as
// docs/ops/runbooks/account-fixture-stack.md does by hand: the account (UID 90000001), its pack
// key `fixture-compliant-0001` (the secret is derived by the pack's rule, packages/fixtures/
// accounts/README.md, never stored), and its default profile able to trade CV_E29_SYMBOL with
// every cap bounded (22 AccountProfileInput). A `403 step_up_required` is answered with the
// password and a code for a TOTP step not used yet, then the held request is sent again unchanged.
// It writes only `{"account_id", "price"}` to CV_E29_ARM_OUT: no token, no summary (C-12.2). The
// price is the ticker's mark (the OMS price band reads it), else the pack corpus's last trade.
/* global __ENV */
import http from "k6/http";
import { sleep } from "k6";
import { guardedBase } from "./lib/guard.js";
import { loadUser, signIn, submitParams } from "./lib/session.js";
import { codeForStep, STEP_S, stepAt } from "../lib/totp.js";

const BASE = guardedBase();
const USER = loadUser();
const SYMBOL = __ENV.CV_E29_SYMBOL || "BTCUSDT";
const KEY_ID = "fixture-compliant-0001";
const UID = "90000001";
const CORPUS_PRICE = "63110.00";
const OUT = __ENV.CV_E29_ARM_OUT || "oms-arm.json";

export const options = { vus: 1, iterations: 1, setupTimeout: "180s" };

function uuid() {
  const h = [...Array(32)].map(() => Math.floor(Math.random() * 16).toString(16));
  h[12] = "4";
  h[16] = ((parseInt(h[16], 16) & 3) | 8).toString(16);
  const s = h.join("");
  return `${s.slice(0, 8)}-${s.slice(8, 12)}-${s.slice(12, 16)}-${s.slice(16, 20)}-${s.slice(20)}`;
}

// The next TOTP step after the last one this run used: the API refuses a replayed step.
function freshCode(s) {
  let step = stepAt(Date.now() / 1000);
  while (step <= s.step) {
    sleep(STEP_S - ((Date.now() / 1000) % STEP_S) + 0.5);
    step = stepAt(Date.now() / 1000);
  }
  s.step = step;
  return codeForStep(USER.seed, step);
}

function call(s, method, path, body, extra) {
  const params = submitParams(s, uuid());
  Object.assign(params.headers, extra || {});
  params.tags = { endpoint: "arm" };
  const text = body === undefined ? null : JSON.stringify(body);
  let r = http.request(method, `${BASE}${path}`, text, params);
  if (r.status === 403 && r.json("code") === "step_up_required") {
    const up = { password: __ENV.CV_E29_PASSWORD, challenge_id: r.json("challenge_id") };
    up.code = freshCode(s);
    const g = http.post(`${BASE}/auth/step-up`, JSON.stringify(up), submitParams(s, uuid()));
    if (g.status !== 200) throw new Error(`step-up ${g.status}`);
    const rotated = g.json("tokens.access_token"); // a step-up that rotates the session
    if (typeof rotated === "string") {
      s.token = rotated;
      params.headers.Authorization = `Bearer ${rotated}`;
    }
    r = http.request(method, `${BASE}${path}`, text, params); // the same body and key
  }
  if (r.status < 200 || r.status > 299) throw new Error(`${method} ${path} ${r.status}`);
  return r;
}

export function setup() {
  const s = signIn(BASE, USER);
  s.step = stepAt(Date.now() / 1000); // the sign-in's step
  const account = call(s, "POST", "/exchange-accounts", {
    exchange: "bybit",
    environment: "demo",
    kind: "main",
    label: "E29 OMS perf",
    exchange_uid: UID,
  }).json("id");
  call(s, "POST", `/exchange-accounts/${account}/keys`, {
    api_key: KEY_ID,
    api_secret: KEY_ID.replace(/-\d{4}$/, "-secret-not-real"),
    label: "compliant",
    expected_uid: UID,
  });
  const profileId = call(s, "GET", `/exchange-accounts/${account}/default-profile`).json(
    "profile_id",
  );
  const path = `/exchange-accounts/${account}/profiles/${profileId}`;
  const current = call(s, "GET", path);
  call(
    s,
    "PUT",
    path,
    {
      name: current.json("name"),
      is_default: true,
      enabled: true,
      trading_enabled: true,
      leverage: "1",
      margin_mode: "cross",
      position_mode: "one_way",
      sizing: { mode: "fixed_qty", qty: __ENV.CV_E29_QTY || "0.001" },
      stop_loss: { unit: "percent", value: __ENV.CV_E29_SL_PERCENT || "1" },
      risk_caps: {
        max_position_notional_usd: "1000000",
        max_daily_loss_usd: "1000000",
        max_open_positions: 50,
        max_concurrent_orders: 500, // the four runs place at most 4 x CV_E29_MAX_ORDERS
        max_leverage_cap: "10",
        max_orders_per_minute: 600, // the script's RATE_MS of 500 is 120 a minute
      },
      allowed_symbols: [SYMBOL],
    },
    { "If-Match": current.headers.Etag || current.headers.ETag },
  );
  const t = http.get(`${BASE}/instruments/${SYMBOL}/ticker`, submitParams(s, uuid()));
  const mark = t.status === 200 ? t.json("mark_price") || t.json("last_price") : null;
  return { account_id: account, price: /^\d{1,12}(\.\d{1,8})?$/.test(mark) ? mark : CORPUS_PRICE };
}

export default function () {}

export function handleSummary(data) {
  return { [OUT]: JSON.stringify(data.setup_data || {}) };
}
