// E29-Q03 (#977): what the submit-ack script reads. Pure (no k6 import), so
// scripts/tests/test_e29_oms_load_tools.py runs it under node.
// - BQ-01: the timer stops at the first `orders` delta (23 section 6.2.3, 15.1) carrying the
//   order's `order_link_id` with `change` `ack` or `reject`; no other step, and no snapshot.
// - The 202 (22 OrderAcceptance) names the order in `order` or in its entry leg.
// - `order_submit_seconds` is read before and after the run, at p95 by the Prometheus rule.
export const ACKED = new Set(["ack", "reject"]);
export const MAX_SEEN = 4096; // acks held for a 202 still in flight; the oldest go first

// [{link, kind, at}] for every ack or reject the frame carries.
export function acksOf(m, at) {
  if (!m || m.ch !== "orders" || m.t !== "d" || !m.p || !Array.isArray(m.p.orders)) return [];
  return m.p.orders
    .filter((o) => o && typeof o.order_link_id === "string" && ACKED.has(o.change))
    .map((o) => ({ link: o.order_link_id, kind: o.change, at }));
}

export function linkOf(body) {
  if (!body) return null;
  if (body.order && typeof body.order.order_link_id === "string") return body.order.order_link_id;
  const legs = (body.trade_group && body.trade_group.legs) || [];
  for (const leg of legs) {
    for (const o of leg.order_details || []) {
      if (o && typeof o.order_link_id === "string") return o.order_link_id;
    }
  }
  return null;
}

// Pairs a submit with its first ack, whichever lands first: `add*` give {ms, kind} or null.
export function newMatcher() {
  return { sent: new Map(), seen: new Map() };
}

export function addSent(mt, link, t0) {
  const ack = mt.seen.get(link);
  if (ack === undefined) {
    mt.sent.set(link, t0);
    return null;
  }
  mt.seen.delete(link);
  return { ms: ack.at - t0, kind: ack.kind };
}

export function addAck(mt, a) {
  const t0 = mt.sent.get(a.link);
  if (t0 === undefined) {
    if (!mt.seen.has(a.link)) {
      if (mt.seen.size >= MAX_SEEN) mt.seen.delete(mt.seen.keys().next().value);
      mt.seen.set(a.link, a);
    }
    return null;
  }
  mt.sent.delete(a.link);
  return { ms: a.at - t0, kind: a.kind };
}

// Submits with no ack after `timeoutMs`: dropped and counted, so a lost ack is a miss.
export function expire(mt, now, timeoutMs) {
  let n = 0;
  for (const [link, t0] of mt.sent) {
    if (now - t0 > timeoutMs) {
      mt.sent.delete(link);
      n += 1;
    }
  }
  return n;
}

// A UUIDv4 from 16 random bytes (the Idempotency-Key).
export function uuidV4(bytes) {
  const b = Array.from(bytes).slice(0, 16);
  if (b.length !== 16) throw new Error("16 bytes are needed");
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = b.map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

// The `<name>_bucket` series of a /metrics body, summed over their other labels: [[le, count]]
// sorted by `le` (`+Inf` last), or null when the family is absent (never read as 0).
export function histogram(text, name) {
  const re = new RegExp(`^${name}_bucket\\{([^}]*)\\} ([0-9.e+-]+)$`, "gm");
  const by = new Map();
  for (let m = re.exec(text); m !== null; m = re.exec(text)) {
    const le = /(?:^|,)le="([^"]+)"/.exec(m[1]);
    if (!le) continue;
    const bound = le[1] === "+Inf" ? Infinity : Number(le[1]);
    by.set(bound, (by.get(bound) || 0) + Number(m[2]));
  }
  if (by.size === 0) return null;
  return [...by.entries()].sort((a, b) => a[0] - b[0]);
}

export function delta(before, after) {
  if (after === null) return null;
  const was = new Map(before || []);
  return after.map(([le, c]) => [le, c - (was.get(le) || 0)]);
}

// The q-quantile of cumulative buckets, in the buckets' unit; null for no observation. Past the
// last finite bound it answers that bound, as Prometheus does.
export function quantile(q, buckets) {
  if (!buckets || buckets.length === 0) return null;
  const total = buckets[buckets.length - 1][1];
  if (!(total > 0)) return null;
  const rank = q * total;
  let prevLe = 0;
  let prevC = 0;
  for (const [le, c] of buckets) {
    if (c >= rank) {
      if (le === Infinity) return prevLe;
      return c === prevC ? le : prevLe + ((le - prevLe) * (rank - prevC)) / (c - prevC);
    }
    prevLe = le === Infinity ? prevLe : le;
    prevC = c;
  }
  return prevLe;
}
