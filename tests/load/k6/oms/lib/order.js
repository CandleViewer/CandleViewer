// E29-Q03 (#977): the pure parts of the submit-ack script, so scripts/tests/test_e29_oms_load_tools.py
// asserts their outputs under node: the order body (native SL on every one, C-2.6), the prices, the
// open-order cap, the env numbers, the missing-measurement decision and the summary scrub.
const DECIMAL = /^\d{1,12}(\.\d{1,8})?$/;

function whole(name, raw, dflt, lo, hi) {
  const s = raw === undefined || raw === null || raw === "" ? String(dflt) : String(raw).trim();
  const n = Number(s);
  if (!/^\d+$/.test(s) || n < lo || n > hi) {
    throw new Error(`${name} must be a whole number from ${lo} to ${hi}`);
  }
  return n;
}

export function orderEnv(env) {
  const c = {
    symbol: env.CV_E29_SYMBOL || "BTCUSDT",
    price: env.CV_E29_PRICE || "",
    qty: env.CV_E29_QTY || "0.001",
    slPct: env.CV_E29_SL_PERCENT || "1",
    maxOrders: whole("CV_E29_MAX_ORDERS", env.CV_E29_MAX_ORDERS, 200, 1, 100000),
    runS: whole("CV_E29_RUN_S", env.CV_E29_RUN_S, 120, 1, 86400),
    rateMs: whole("CV_E29_RATE_MS", env.CV_E29_RATE_MS, 500, 10, 600000),
  };
  if (
    !/^[A-Z0-9]{2,16}USDT$/.test(c.symbol) ||
    ![c.price, c.qty, c.slPct].every((x) => DECIMAL.test(x))
  ) {
    throw new Error("CV_E29_SYMBOL, CV_E29_PRICE, CV_E29_QTY and CV_E29_SL_PERCENT must be valid");
  }
  return c;
}

// 1 % either side of the price, which should sit near the mark: buys rest below, sells above.
export function prices(price) {
  const px = (k) => (Number(price) * k).toFixed(8).replace(/\.?0+$/, "");
  return { buy: px(0.99), sell: px(1.01) };
}

// One limit entry, its native SL a percent off the entry (22 PlaceOrderRequest, Offset).
export function orderBody(c, account, i) {
  const p = prices(c.price);
  return {
    exchange_account_id: account,
    symbol: c.symbol,
    side: i % 2 === 0 ? "buy" : "sell",
    order_type: "limit",
    intent: "entry",
    price: i % 2 === 0 ? p.buy : p.sell,
    time_in_force: "GTC",
    sizing: { mode: "fixed_qty", qty: c.qty },
    stop_loss: { unit: "percent", value: c.slPct },
  };
}

// Whether the next tick places an order: the account is ready, the run is on, the cap is not hit.
export function mayFire(ready, now, end, n, maxOrders) {
  return ready && now < end && n < maxOrders;
}

// The backend-added reading: no scrape is a miss that the gate counts, never a pass.
export function backendReading(p95Seconds, delayMs) {
  if (p95Seconds === null || p95Seconds === undefined) return { missing: 1, added: null };
  return { missing: 0, added: Math.max(0, p95Seconds * 1000 - delayMs) };
}

// The summary k6 writes: no session token (C-12.2), and the profile compare_baseline.py checks.
export function summaryOf(data, profile) {
  delete data.setup_data;
  data.cv_profile = profile;
  return data;
}
