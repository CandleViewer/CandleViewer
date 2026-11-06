// E42-Q03 (#1216): the audit query matrix [BQ-2]. K01's SCR-135 combinations the API has (its
// `env_action` has no parameter: the environment filter is client-side, D7), plus `ip`, a
// selective and a common `q`, and the unfiltered page: 14, each at page 1 and at a cursor 90 %
// deep into its own time window. Values are the AUDIT-10M dataset's (bench/audit_index/ci_spike.py
// FILTERS and FULLTEXT); the guard tests pin each to K01's SQL text.
// Pure: no k6 import, so node runs it in the guard tests, which also feed every cursor to the
// server's own `decode_cursor` (services/api/candleviewer/audit/cursor.py).

export const SPAN_START = "2026-01-01T00:00:00Z"; // ci_spike.START_TS
export const SPAN_DAYS = 365; // ci_spike.SPAN_DAYS: timestamps are linear in the row number
export const DEEP = 0.9;
const ACTOR = "00000000-0000-4000-8000-000000000007"; // user_07, ci_spike._ACTOR
const ID_MAX = "9223372036854775807"; // bigint max, as text: a JS number cannot hold it

// `sparse`: the filter is selective by construction, so a page (mostly the deep one) may be empty.
export const COMBOS = [
  { name: "unfiltered", cls: "common", params: {} },
  {
    name: "range",
    cls: "common",
    params: { from: "2026-06-01T00:00:00Z", to: "2026-07-01T00:00:00Z" },
  },
  { name: "actor", cls: "common", params: { actor_user_id: ACTOR } },
  { name: "action", cls: "common", params: { action: "orders.submit" } },
  {
    name: "action_range",
    cls: "common",
    params: { action: "admin.user_update", from: "2026-03-01T00:00:00Z" },
  },
  {
    name: "actor_action",
    cls: "common",
    params: { actor_user_id: ACTOR, action: "orders.cancel" },
  },
  {
    name: "actor_action_range",
    cls: "common",
    params: { actor_user_id: ACTOR, action: "orders.cancel", from: "2026-06-01T00:00:00Z" },
  },
  // [BQ-2] The API takes one severity; K01 read `error` and `critical` together.
  { name: "severity", cls: "common", params: { severity: "error" } },
  { name: "severity_actor", cls: "common", params: { severity: "error", actor_user_id: ACTOR } },
  {
    name: "subject",
    cls: "common",
    sparse: true,
    params: { subject_type: "order", subject_id: "obj-12345" },
  },
  {
    name: "outcome_action",
    cls: "common",
    params: { outcome: "denied", action: "auth.login_failed" },
  },
  { name: "ip", cls: "common", params: { ip: "192.0.2.7" } }, // RFC 5737, one of the set's 254
  { name: "q_selective", cls: "q", sparse: true, params: { q: "v424242" } },
  { name: "q_common", cls: "q", params: { q: "field_1" } },
];

const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

// base64url without padding of an ASCII string (the cursor's alphabet, audit/cursor.py).
export function base64url(text) {
  let out = "";
  let bits = 0;
  let value = 0;
  for (let i = 0; i < text.length; i += 1) {
    value = ((value << 8) | text.charCodeAt(i)) & 0xffff;
    bits += 8;
    while (bits >= 6) {
      bits -= 6;
      out += B64[(value >>> bits) & 63];
    }
  }
  return bits > 0 ? out + B64[(value << (6 - bits)) & 63] : out;
}

// A cursor `depth` deep, newest first, into the combination's window ([from, to), or the dataset's
// span): the position of an entry at that time with the largest id, so the page resumes strictly
// before it. The cursor is unsigned and grants nothing (audit/cursor.py), so it is minted here.
export function cursorFor(combo, depth = DEEP) {
  const start = Date.parse(combo.params.from || SPAN_START);
  const end = combo.params.to
    ? Date.parse(combo.params.to)
    : Date.parse(SPAN_START) + SPAN_DAYS * 864e5;
  const ts = new Date(Math.round(end - (end - start) * depth))
    .toISOString()
    .replace("Z", "000+00:00");
  return base64url(`{"v":1,"ts":"${ts}","id":${ID_MAX}}`);
}

export function queryString(params) {
  return Object.entries(params)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join("&");
}

// Every (combination, position) the profile measures, in order, with its query string.
export function plan(limit) {
  return COMBOS.flatMap((c) =>
    [
      ["page1", {}],
      ["deep", { cursor: cursorFor(c) }],
    ].map(([pos, extra]) => ({
      combo: c.name,
      pos,
      cls: c.cls,
      sparse: Boolean(c.sparse),
      query: queryString({ ...c.params, ...extra, limit: String(limit) }),
    })),
  );
}
