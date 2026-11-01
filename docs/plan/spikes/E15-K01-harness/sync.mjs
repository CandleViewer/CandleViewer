// THROWAWAY SPIKE HARNESS (E15-K01 #371). SyncBus-shaped fan-out (BQ-12): one `sync {groupId, timeRange,
// crosshair}` message per frame (26 §6, at most one per frame), delivered to N panes that each map the time
// to their own bar index (binary search over 100k bar times) and update their crosshair and window state.
const N_BARS = 100_000;
const T0 = Date.UTC(2026, 0, 1);

export function makeSubscribers(n) {
  return Array.from({ length: n }, (_, k) => {
    const t = new Float64Array(N_BARS);
    for (let i = 0; i < N_BARS; i += 1) t[i] = T0 + i * 60_000 * (1 + (k % 3)); // panes on 1m, 2m, 3m
    return { k, t, state: null };
  });
}

function find(t, x) {
  let lo = 0,
    hi = t.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (t[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** Applies one sync message to every subscriber; returns the per-pane results (what a worker would need). */
export function fanOut(subs, msg) {
  const out = [];
  for (const s of subs) {
    const a = find(s.t, msg.timeRange[0]),
      b = find(s.t, msg.timeRange[1]),
      c = find(s.t, msg.crosshair.t);
    s.state = {
      k: s.k,
      groupId: msg.groupId,
      from: a,
      to: b,
      cursor: c,
      x: (c - a) / (b - a || 1),
      price: msg.crosshair.price,
    };
    out.push(s.state);
  }
  return out;
}

export function syncMessage(i) {
  const t = T0 + (20_000 + i) * 60_000;
  return {
    groupId: "g1",
    timeRange: [t - 300 * 60_000, t + 30 * 60_000],
    crosshair: { t, price: 6_000_000 + (i % 400) },
  };
}
