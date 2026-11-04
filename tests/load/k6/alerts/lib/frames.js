// E40-Q02 (#1203): what one `alerts` subscription must see (23 section 6.2.1, schema 15.7). Pure:
// no k6 import, so scripts/tests/test_e40_alert_load_tools.py runs it under node.
// - order: `s` is +1 per frame on the stream (23 section 3.3); a lower or repeated `s` is out of
//   order, a higher one a gap. A re-snapshot (backpressure, upstream_desync) restarts the count.
// - truncation: a delta carries 1..100 whole deliveries (each with 15.7's required members) and
//   the owner's `unacked_count`; a window is never sent cut short (6.2.1, Backpressure).
// - cadence: the deltas of one 250 ms window leave back to back at its close, so two frames more
//   than BURST_MS apart open a new window, and two windows are WINDOW_MS apart at least.
// PROPOSED, not ruled: the 25 ms floor tolerance and the 400 ms pacing ceiling (owner: the 06
// owners; ratified on #2701 or in the results PR), as E27-Q03 proposed its wallet tolerance.
export const WINDOW_MS = 250; // 23 section 6.2 table, `alerts` default throttle
export const WINDOW_TOL_MS = 25; // PROPOSED
export const PACING_MAX_MS = 400; // PROPOSED: a driven stream closes a window about every 250 ms
export const BURST_MS = 20;
export const MAX_ITEMS = 100; // 23 section 6.2.1, Deltas
const REQUIRED = ["id", "alert_id", "channel", "status", "message", "fired_at_ms"];

export function newState() {
  return { lastS: null, unacked: null, lastAt: null, windowAt: null };
}

export function truncated(p) {
  const items = p && p.deliveries;
  if (!Array.isArray(items) || items.length < 1 || items.length > MAX_ITEMS) return true;
  if (!Number.isInteger(p.unacked_count) || p.unacked_count < 0) return true;
  return items.some((d) => !d || REQUIRED.some((k) => d[k] === undefined || d[k] === null));
}

// One frame of the `alerts` stream at `now` ms. `ackOnly`: nothing but acks changes the set, so
// `unacked_count` never rises between two deltas (a rise is a delta applied out of order).
export function onFrame(st, m, now, ackOnly = true) {
  const out = { kind: "other", issues: [], windowGapMs: null };
  if (m.ch !== "alerts" || (m.t !== "snap" && m.t !== "d")) return out;
  if (m.t === "snap") {
    out.kind = "snap";
    st.lastS = m.s;
    st.unacked = m.p ? m.p.unacked_count : null;
    return out;
  }
  out.kind = "delta";
  if (st.lastS === null) out.issues.push("delta_before_snap");
  else if (m.s <= st.lastS) out.issues.push("out_of_order");
  else if (m.s !== st.lastS + 1) out.issues.push("gap");
  if (truncated(m.p)) out.issues.push("truncated");
  else if (ackOnly && st.unacked !== null && m.p.unacked_count > st.unacked) {
    out.issues.push("unacked_rose");
  }
  if (st.lastAt === null || now - st.lastAt > BURST_MS) {
    if (st.windowAt !== null) out.windowGapMs = now - st.windowAt;
    st.windowAt = now;
  }
  st.lastAt = now;
  st.lastS = m.s;
  if (m.p && Number.isInteger(m.p.unacked_count)) st.unacked = m.p.unacked_count;
  return out;
}
