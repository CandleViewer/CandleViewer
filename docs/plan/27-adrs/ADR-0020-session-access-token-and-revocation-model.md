# ADR-0020 — Session access-token format, WS re-auth cadence, and rotation-family revocation

- Status: **proposed** — owner approval pending (spike E09-K01, timeboxed 3 days)
- Date: 2026-09-25
- Deciders: Owner (`@basiltt`) — see `docs/plan/backlog/all-tickets.json` E09-K01 "Agent-delivery adaptations": owner approval substitutes for Architect/Security-engineer countersignature; recorded here as **owner approval pending** until the owner comments `approved` on issue #134.
- Consulted: `docs/plan/21-database-schema.md` §3.1.4, `docs/plan/24-internal-schemas.md` §15.1, `docs/plan/23-ws-protocol.md` §4.3/§9.5, `docs/plan/20-architecture.md` §5, `docs/plan/06-performance-and-load-standard.md`, `docs/plan/04-security-program.md`, `docs/plan/11-user-stories.md` US-ONB-004/US-ONB-009
- Related: ADR-0010 (auth and RBAC — establishes opaque server-side sessions; this ADR refines the access-token/WS layer that ADR-0010 left at "no JWT in localStorage" without specifying the WS first-frame credential), ADR-0016 (statechart runtime — B16 `auth`×`elevation` chart consumes `elevated_until`/`mfa_satisfied_at` from this model)

## Context and problem statement

ADR-0010 fixed the outer shape (opaque server-side session, `HttpOnly` cookie, mandatory TOTP) but two
downstream documents diverged on the session row shape and TTLs, and neither addresses how a WebSocket
connection — which cannot read an `HttpOnly` cookie into a JS-constructed frame, and per
`20-architecture.md` §5 must never hold a JWT in `localStorage` — authenticates its first frame and
re-authenticates without tearing down subscriptions. This spike answers the six questions in the ticket's
"Scope / Deliverables" with harness evidence (`docs/plan/spikes/E09-K01-harness/`) and reconciles the two
schema documents (`docs/plan/spikes/E09-K01-session-model.md`).

## Decision drivers

- Revocation must be effective within 5 s (US-ONB-009) — checked per request/frame, not just at issue.
- WS re-auth must not storm the connection: at most once per 10 minutes, no reconnect-on-refresh.
- No JWT in `localStorage`; the WS first frame still needs _something_ bearer-shaped to present.
- Idle-lock must freeze order entry without dropping the socket or its subscriptions (US-ONB-004).
- Rotation-family revocation (reused refresh token) must kill the whole family, not just one hop.
- Decision criterion agreed in the ticket: opaque handles win outright if p99 lookup < 2 ms; only
  material latency risk against the API budget in `06-performance-and-load-standard.md` justifies a JWT.

## Considered options

1. **Opaque access token (short-lived, server-side lookup) + opaque refresh token in `HttpOnly` cookie**,
   access token handed to the WS first frame over the wire (not stored in `localStorage`) and refreshed
   via `POST /auth/refresh`.
2. **Signed JWT access token** (`sid`/`jti` claims) with the same refresh-cookie split, revocation via a
   server-side deny-list keyed on `jti`.
3. **Cookie-only** — no separate access token; WS reads the session cookie during the handshake.

## Decision outcome

**Chosen: option 1 — opaque access token, refresh in `HttpOnly` cookie, held in memory only.**

1. **Storage split.** `cv_refresh` is `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth` (but
   `SameSite=None` for the desktop shell's origin only: C-12.9, ADR-0010 Amendment 1), opaque,
   hashed at rest (`sessions.refresh_token_hash`, unchanged from `21-database-schema.md` §3.1.4). The
   **access token is a second opaque, server-issued handle**, returned in the `POST /auth/login` /
   `POST /auth/refresh` JSON body, held **only in an in-memory JS variable** (never `localStorage`,
   never a second cookie) and passed as the WS `auth` frame's bearer value per `23-ws-protocol.md` §4.3.
   Losing it (tab reload) means re-deriving it from the refresh cookie — an acceptable UX cost that
   keeps it out of any persistent, XSS-exfiltratable store. **At rest, the access-token handle is
   stored the same way as the existing refresh-token handle: hashed (never plaintext) in the
   `access_tokens`/`sessions.access_token_jti` lookup column, per `21-database-schema.md` §3.1.4's
   `refresh_token_hash` pattern; the lookup path compares hashes in constant time
   (`hmac.compare_digest`, not `==`) to avoid a timing side channel on the hot revocation-check path;
   and the raw handle is redacted by the mandatory logging filter (`50-security.md`, C-12.6) — it must
   never appear in structured logs, error messages, or audit `before/after` payloads (only the session
   id / masked handle may).**
2. **Opaque over JWT.** The harness (`test_lookup_p50_p99_under_budget`) measures dict-backed lookup at
   p99 far under the 2 ms decision threshold; the real store backs this with a hash index on
   `sessions.access_token_jti` / a dedicated `access_tokens` table (see reconciliation note), which has
   the same O(1) shape. JWTs are rejected: they would need a deny-list for revocation anyway (buying
   nothing) and add key-rotation operational burden for zero latency benefit at this decision point.
3. **Access-token TTL: 12 minutes.** Chosen so the client's refresh-at-`expires_at - 60s` rule
   (`23-ws-protocol.md` §4.3) yields a refresh/re-auth interval of 11 minutes — satisfying "at
   most once per 10 minutes per connection" **with a 60s margin left over for clock skew and
   early/jittered refresh**, not exactly zero margin. (Revised from an earlier 11-minute draft that
   left zero skew budget between the 60s refresh-ahead margin and the "at least 10 minutes" floor;
   see `CLOCK_SKEW_BUDGET_S` in the harness.) Verified for 20 concurrent connections over a simulated
   hour in `test_ws_reauth_cadence_at_most_once_per_ten_minutes`, which now drives an explicit
   per-connection virtual clock instead of only checking the interval arithmetic. Refresh is **in
   place**: the server returns a new access token over the _existing_ connection; no reconnect is
   triggered.
4. **Idle-lock semantics.** Idle timeout (30 min, `sessions.last_seen_at`) blocks **order-entry-class**
   REST routes and WS actions server-side (RBAC/risk layer, consistent with C-2.21 "statecharts record,
   synchronous code enforces") but does **not** revoke the session or close the WS connection; market-data
   subscriptions continue uninterrupted, satisfying US-ONB-004. Re-authentication (password or step-up MFA
   depending on elapsed idle time) lifts the lock without a new WS handshake.
5. **Rotation-family revocation.** Every refresh issues a new `sessions` row and links it via
   `sessions_rotation` (unchanged shape). Reuse of an already-rotated refresh token walks the family
   (both directions from the reused node) and revokes every member in one pass — proven at 10k
   chained rows in `test_rotation_family_walk_cost_at_10k_rows` (walk is O(family length), not O(table
   size); the store maintains the reverse rotation edge incrementally rather than rebuilding it per
   call, and `test_rotation_family_walk_cost_independent_of_unrelated_rows` asserts the walk cost does
   not scale with unrelated rows in the store), and emits `auth.refresh_reuse_detected` at severity
   `critical` plus an **append-only audit record** (C-2.9) identifying which session was replayed and
   how many family members were killed (`test_rotated_token_reuse_kills_entire_family`). A row's first
   revocation reason/timestamp is preserved even if a later family-wide revoke also covers it, so
   incident forensics can see _why_ each row was first killed.
6. **Step-up field: `mfa_satisfied_at` (timestamp), not `elevated_until`.** A single boundary-owned field
   models "the last moment step-up was proven"; `elevated_until = mfa_satisfied_at + step_up_window`
   (15 min, per `21-database-schema.md`) is _derived_, never stored, matching the B16 statechart's
   note that `elevated_until` is derived from the elevation region rather than stored independently
   (`24-internal-schemas.md` §15.1 statechart-contract callout). `24-internal-schemas.md`'s `Session`
   Pydantic model must drop its own `elevated_until` field and compute it as a property.

### Consequences

Positive:

- Revocation stays instant and centralised (ADR-0010's core guarantee is preserved, not reopened).
- WS re-auth cadence is bounded and provable rather than assumed; no reconnect storms under refresh.
- One step-up field removes an entire class of "which one is authoritative" bugs before E09-T01 freezes.

Negative / risks:

- The access token must be re-derived from the refresh cookie on every fresh page load / tab, costing one
  extra round-trip at startup versus a persisted (but XSS-exposed) token. Accepted per ADR-0010's rationale.
- 12-minute TTL is deliberately tight to the WS cadence budget; if the API latency budget in
  `06-performance-and-load-standard.md` later requires a shorter access-token TTL for other reasons, the
  WS re-auth interval and the 60s skew margin must be re-derived, not left at a stale 10/11 minutes.

### Why not the alternatives

- **JWT access token**: no revocation benefit once a deny-list is required, and the opaque-handle p99 is
  already far inside the 2 ms threshold that was the only condition under which JWT would win.
- **Cookie-only for WS**: a `SameSite=Strict; HttpOnly` cookie is not readable during the WS handshake in
  a way that lets the client construct the required `auth` first frame; the browser does send cookies on
  the handshake request itself, but `23-ws-protocol.md` §4.3 specifies an explicit bearer `auth` frame
  (not implicit cookie auth) so the server can reject the connection cleanly with `4401` rather than
  relying on handshake-time cookie presence, and so the _same_ mechanism re-authenticates in place without
  a new handshake.

## Validation

- `docs/plan/spikes/E09-K01-harness/test_harness.py` — 7 tests, all green, covering every Gherkin scenario
  in the ticket (`uv run pytest docs/plan/spikes/E09-K01-harness -q` from repo root once `services/api`
  exists; run directly with `python -m pytest` from the harness directory today).
- Full reconciliation of `21-database-schema.md` §3.1.4 vs `24-internal-schemas.md` §15.1:
  `docs/plan/spikes/E09-K01-session-model.md`.
- Follow-up edits required before E09-T01/S03 implement this for real: tracked in the reconciliation note
  and must be filed as review comments / follow-up items against E09-T01 and E09-S03 per the ticket's DoD.

## Deferred / open items

- Real Postgres-backed latency measurement (the harness is in-memory; no docker available in this
  environment) — re-run `test_lookup_p50_p99_under_budget`'s scenario against a seeded Postgres instance
  under E09-T01/S03 before the schema is load-tested for real, per `06-performance-and-load-standard.md`.
- WebAuthn / device trust and any second access channel: explicitly out of scope (ticket "Out of scope").
