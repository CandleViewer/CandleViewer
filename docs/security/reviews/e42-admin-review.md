# E42 security review — admin routes, elevation, audit, flags, lifecycle, destructive paths (E42-X02)

- Ticket: E42-X02 (#1220), the white-box review of the E42 admin area (epic #63). Threat model:
  `docs/security/threat-models/e42-admin.md` (E42-X01, #890; cited `TM`). Abuse cases:
  `docs/security/abuse-cases/e42-admin.md` (cited `AC`; AC-ADM-01..35 and UL-AC01..16 are E42-X03's,
  #1026). Route matrix: `services/api/tests/contract/rbac/matrix.yaml` (cited `M`). Security program:
  `docs/plan/04-security-program.md` (cited `04`).
- Reviewed against `main` at `f79d6fa372099940759672d08956072d916b913f` (2026-11-04), the pin. Code paths are
  relative to `services/api/candleviewer/` and test paths to `services/api/tests/`; paths that start with
  `services/`, `docs/`, `infra/`, `apps/`, `packages/`, `security/`, `.semgrep/` or `.github/` are from the
  repository root. Line numbers are those of the pin. CI evidence is the pin's own merge-queue run of the `pr`
  workflow, **41821199189** (success; integration shards 1–4 jobs 126548559423, 126548559420, 126548559395,
  126548559204), and the `main` push run 41833436744 (success).
- Method: one current-state white-box review at the pin (ruling BQ-2, BQ-5), split into eight areas, each read by
  an independent agent reviewer: routes and RBAC, elevation, audit, flags, user lifecycle, destructive paths,
  copy, and the TM §4 re-read with the SAST/SCA triage. STRIDE per boundary, `04` §11.3's per-route questions,
  a written locking argument plus the stress tests for each concurrency claim, and mutation probes in scratch
  worktrees (never the reviewed tree) for the flag refusal and for this PR's two new tests. Evidence is a named
  test on `main` that a removed control turns red, with its `M` row; lens records, design text and local builds
  are not evidence (BQ-4). The ruling of record is the orchestrator's BQ ruling on #1220 (2026-11-03 11:55Z).
- Disclosure: open findings carry only id, severity, area, status and tracker (`SECURITY.md` §1, C-12.13). Their
  STRIDE class, likelihood and impact, scenario, mechanism and location are held in the private record
  (maintainers) until each is fixed (ruling BQ-3). A finding fixed on `main` may be described as the control its
  PR built.

> **Status: review complete at the pin; sign-off PENDING (§8).** Critical: none. High: none. Medium: one
> (E42-R-10). Low: sixteen. No High or Critical is open, so no BQ-3 remediation issue is due. This record is
> re-pinned when E42-S03 (#1134), E42-S04 (#1135) and E42-S05 (#1024) merge: their client halves, their copy as
> built and their e2e are WAITING here (BQ-5). D2 is decided by this record under the sign-off (§3).

Verdict key: **HOLDS** (the control is in code and a named test fails when it is removed) · **FINDING** (an open
finding, public form only, §2) · **WAITING** (blocked on the named issue) · **N/A** (does not apply at the pin,
reason given) · **known** (an accepted residual or a gap the TM already routes to a tracker; not a new finding).

## 1. Verdicts

### 1.1 Area 1: every admin route (Gherkin 1), the generated table

The table is generated from `create_app()` at the pin by walking `app.router` as `served_operations` does
(`api/deny_by_default.py:62-83`), not written by hand (the ticket's technical note). Permissions are the
packaged contract's `x-rbac`; step-up classes come from `DANGEROUS_ROUTES` and `HANDLER_GATED_ROUTES`
(`api/step_up.py:624-760`); the `M` line, state and outcomes (owner / manager with grant / manager without grant
/ viewer / unauthenticated) from `M`. Guard key: **G** `admin_router` (`admin/http.py:134-233`, records
`admin.area_entered` ahead for allowed and denied callers, counts `authz_denied_total`); **E**
`auth.scopes.enforce` (records `rbac.denied`); **A** the audit-read guard (`audit/access.py:135-163`, records
`admin.audit_denied` under the per-user budget); **O** a handler-local check.

The verdict column covers the declared permission, deny-by-default and the denial record. The success record of
an allowed call is its own control row in §1.2.

<!-- prettier-ignore -->
| Method path | x-rbac | Guard / denial record | Step-up | Handler | M row (state; outcomes) | Verdict (permission, deny-by-default, denial record) |
| --- | --- | --- | --- | --- | --- | --- |
| GET /admin/audit | audit:read (self) | A / admin.audit_denied | — | api/audit.py:563 | M:22 exec; allow/allow/allow/403/401 | HOLDS |
| POST /admin/audit/chain-breaks/{firstBadId}/acknowledge | killswitch:write, Owner-only | A / admin.audit_denied | killswitch (no-grace, handler) | api/audit.py:863 | M:28 exec; allow/403/403/403/401 | HOLDS |
| POST /admin/audit/export | audit:export | A / admin.audit_denied | audit (handler) | api/audit.py:977 | M:37 exec; allow/403×3/401 | HOLDS |
| GET /admin/audit/exports/{jobId} | audit:export | A / admin.audit_denied | audit (handler, after the requester check) | api/audit.py:1095 | M:43 exec; allow/403×3/401 | HOLDS |
| GET /admin/audit/signing-keys | audit:read, Owner-only | A / admin.audit_denied | — | api/audit.py:944 | M:49 exec; allow/403×3/401 | HOLDS |
| POST /admin/audit/verify | audit:read, Owner-only | A / admin.audit_denied | none by design | api/audit.py:744 | M:55 exec; allow/403×3/401 | HOLDS |
| GET /admin/backups | backups:read | G | — | api/admin_backups.py:169 | M:61 exec | HOLDS |
| POST /admin/backups | backups:write | G | none by design | api/admin_backups.py:208 | M:67 exec | HOLDS |
| GET /admin/backups/{backupId} | backups:read | G | — | api/admin_backups.py:185 | M:73 exec | HOLDS |
| DELETE /admin/backups/{backupId} | backups:write | G | backups (no-grace, handler) | api/admin_backup_delete.py:91 | M:79 exec | HOLDS |
| POST /admin/backups/{backupId}/download | backups:write | G | backups (no-grace, handler) | api/admin_backup_links.py:83 | M:85 exec | HOLDS |
| GET /admin/backups/{backupId}/download/{token} | backups:read after the token | O / backup.downloaded | none: the token is the gate | api/admin_backup_download.py:156 | M:91 exec; allow×5 (the token gates) | HOLDS |
| POST /admin/backups/{backupId}/verify | backups:write | G | none by design | api/admin_backup_verify.py:73 | M:104 exec | HOLDS |
| GET /admin/capacity | admin:read | G | — | api/admin_overview.py:101 | M:110 exec | HOLDS |
| PUT /admin/capacity/subaccount-tier | admin:write | G | none by contract | api/admin_capacity.py:136 | M:116 exec | HOLDS |
| GET /admin/feature-flags | flags:read | G | — | api/feature_flags.py:177 | M:124 exec | HOLDS |
| PUT /admin/feature-flags/{flagKey} | flags:write | G | flags / killswitch / live_enablement (handler) | api/feature_flags.py:251 | M:130 exec | HOLDS |
| GET /admin/health | admin:read | G | — | api/admin_ops.py:105 | M:136 exec | HOLDS |
| GET /admin/incidents | admin:read | G | — | api/admin_ops.py:112 | M:142 exec | HOLDS |
| POST /admin/incidents/{incidentId}/acknowledge | admin:write | G | — | api/admin_ops.py:144 | M:148 exec | HOLDS |
| GET /admin/jobs/{jobId} | admin:read | G (+ requester-only export jobs) | — | api/admin_jobs.py:60 | M:154 exec | HOLDS |
| POST /admin/keys/audit-signing/rotate | keys:manage, Owner-only | E / rbac.denied | keys (handler) | api/audit_signing_keys.py:195 | M:160 not_executable | HOLDS (cells via the dedicated tests) |
| POST /admin/keys/kek-rewrap | keys:manage, Owner-only | E / rbac.denied | keys (handler) | api/admin_kek.py:115 | M:169 not_executable | HOLDS (as above) |
| PUT /admin/log-level | admin:write | O / settings.change (denied) | — | api/log_level.py:47 | M:178 not_executable (501) | HOLDS; not counted, known, routed to #2836 |
| GET /admin/overview | admin:read | G | — | api/admin_overview.py:97 | M:186 exec | HOLDS |
| POST /admin/recorder/compact | recording:write | O / recorder.compact | none by design | api/recorder_admin.py:368 | M:206 exec | HOLDS; not counted, known, routed to #2836 |
| POST /admin/recorder/import | recording:write | O / recorder.import | none by design | api/recorder_admin.py:267 | M:212 exec | HOLDS; not counted, known, routed to #2836 |
| POST /admin/recorder/purge | recording:write + Owner-only | O / retention.purge | recorder_purge (no-grace, handler) | api/recorder_purge.py:171 | M:218 exec | HOLDS; not counted, known, routed to #2836 |
| GET /admin/statecharts | admin:read | G | — | api/admin_statecharts.py:165 | M:232 exec | HOLDS |
| GET /admin/statecharts/{machineKey} | admin:read | G | — | api/admin_statecharts.py:198 | M:238 exec | HOLDS |
| GET /admin/statecharts/{machineKey}/export | admin:read | G | — | api/admin_statecharts.py:216 | M:247 exec | HOLDS |
| POST /admin/support-bundle | admin:read | O / health.diagnostics_exported (denied) | — | api/support_bundle.py:73 | M:255 exec | HOLDS; not counted, known, routed to #2836 |
| GET /admin/support-bundle/{job_id} | admin:read | O / no denial record | — | api/support_bundle.py:132 | M:261 exec | known, pinned strict-xfail, routed to #2836 (SR-E42-09) |
| POST /admin/view-as | users:write | G, then admin.view_as_refused | users (handler) | api/view_as.py:392 | M:267 exec | HOLDS |
| GET /auth/session/view-as | self | session only | — | api/view_as.py:182 | M:438 exec; allow×4/401 | HOLDS |
| DELETE /auth/session/view-as | self | session + CSRF | none by contract | api/view_as.py:214 | M:444 exec | HOLDS |
| POST /auth/step-up | self | session | the elevation itself | api/step_up.py:895 | M:456 exec | HOLDS |
| GET /health/live | public | — | — | api/health_report.py:81 | M:703 exec | HOLDS (state word only) |
| GET /health/ready | public | — | — | api/health_report.py:85 | M:709 exec | HOLDS |
| GET /invites/{inviteToken} | public | per-IP throttle, uniform 404 | — | api/invites.py:432 | M:773 exec | HOLDS |
| POST /invites/{inviteToken} | public | as above | — | api/invites.py:478 | M:779 exec | HOLDS |
| POST /invites/{inviteToken}/confirm | public | as above | — | api/invites.py:511 | M:785 exec | HOLDS |
| DELETE /me/sessions/{sessionId} | self | own-session check → 404, denial recorded | — | api/sessions.py:1733 | M:1017 exec | HOLDS |
| POST /users | users:write | E / rbac.denied | users (handler) | api/invites.py:312 | M:1624 exec | HOLDS; the MFA field known, routed to #3086 (AD-F10) |
| GET /users/invites | users:write | E | — | api/invites.py:352 | M:1630 exec | HOLDS |
| GET /users/{userId} | users:read | E (before lookup) | — | api/users.py:1227 | M:1636 exec | HOLDS |
| PATCH /users/{userId} | users:write | E | users (handler) | api/users.py:1279 | M:1648 exec | HOLDS |
| DELETE /users/{userId} | users:write | E | users (handler) | api/users.py:905 | M:1642 exec | HOLDS |
| GET /users/{userId}/account-access | users:read | E | — | api/users.py:783 | M:1654 exec | HOLDS |
| PUT /users/{userId}/account-access | users:write | E | users (handler) | api/users.py:831 | M:1660 exec | HOLDS |
| POST /users/{userId}/invite | users:write | E | users (handler) | api/invites.py:365 | M:1666 exec | HOLDS |
| DELETE /users/{userId}/invite | users:write | E | users (handler) | api/invites.py:390 | M:1672 exec | HOLDS |
| GET /users/{userId}/mfa/reset-preview | users:write | E | — | api/step_up.py:1005 | M:1684 exec | HOLDS |
| POST /users/{userId}/mfa/reset | users:write | E | users (handler) | api/step_up.py:1032 | M:1678 exec | HOLDS |
| PUT /users/{userId}/roles | users:write | E | users (handler) | api/users.py:655 | M:1690 exec | HOLDS |
| GET /users/{userId}/sessions | users:read | E | — | api/users.py:1411 | M:1696 exec | HOLDS |
| DELETE /users/{userId}/sessions/{sessionId} | users:write | E | users (handler) | api/users.py:1428 | M:1702 exec | HOLDS |
| POST /admin/backups/{backupId}/restore | backups:write | — | backups (pre-registered) | not mounted | M:97 not_mounted | WAITING (blocked on #3084) |
| POST /admin/reconciliation/{accountId} | contract | — | — | not mounted | M:192 not_mounted | WAITING (blocked on #914) |
| POST /admin/reconciliation/{accountId}/resolve | contract | — | — | not mounted | M:199 not_mounted | WAITING (blocked on #914) |
| GET /admin/security/summary | audit:read | — | — | not mounted | M:225 not_mounted | WAITING (E43-S02) |
| GET /me/sessions | self | — | — | not mounted | M:1011 not_mounted | N/A (`GET /auth/sessions` is served) |
| GET /permissions | users:read | — | — | not mounted | M:1104 not_mounted | N/A at the pin |
| GET /roles | users:read | — | — | not mounted | M:1289 not_mounted | N/A at the pin |
| GET /users | users:read | — | — | not mounted | M:1617 not_mounted | N/A at the pin |

Counts: 57 served and 8 declared but not mounted. Under `/admin` and `/users`: 48 served (45 `executed`, 3
`not_executable`) and 5 not mounted, which are `M`'s 53 rows (BQ-1). Six `/admin` routes were missing from TM §1.3
and are reviewed here: `acknowledgeAuditChainBreak`, the signing-key list and rotation, `rewrapKek` and the two
`/admin/reconciliation/*` routes. Suites green at the pin: `contract/rbac/test_route_matrix.py` with
`test_admin_http.py`, `test_deny_by_default.py` and `test_dangerous_route_registry.py` (1210 passed);
`tests/security/admin` (2055 passed, 150 strict xfail).

### 1.2 Area 1: the route controls

<!-- prettier-ignore -->
| Control | Verdict | Evidence (test + M row) | 04 SR | TM row |
| --- | --- | --- | --- | --- |
| Every served route has a declared permission; the build fails otherwise | HOLDS | `test_deny_by_default.py:21`; `test_route_matrix.py:101`, :318; M rows of §1.1 | SR-017, SR-018 | AD-S06 |
| Deny-by-default at runtime (undeclared → 403) | HOLDS | `test_deny_by_default.py:32` | SR-017, SR-018 | AD-S06 |
| Per-actor cells match `M` for every route | HOLDS | `test_route_matrix.py:263` (all in-scope rows, the unauthenticated actor included) | SR-018 | AD-E05 |
| Every `/admin` or `/users` route is on G or classified in `OWN_GUARD` | HOLDS | `security/admin/_cells.py` `OWN_GUARD`; `test_cells_none.py:18`; Semgrep `cv-admin-route-guarded` | SR-E42-09 | AD-R01 |
| Denial recorded: G routes | HOLDS | `test_admin_http.py:94`; `test_cells_{none,stale,fresh}.py:30` | SR-060, SR-125 | AD-R01 |
| Denial recorded: E, A and own-guard routes | HOLDS but for one route, known, routed to #2836 | `test_cells_*.py:30`; `GET /admin/support-bundle/{job_id}` pinned strict-xfail | SR-E42-09 | AD-R01 |
| Denial counted (`authz_denied_total`) on own-guard routes | known, routed to #2836 | `test_cells_stale.py:37` strict-xfails (audit-read guard, recorder, support bundle) | SR-125 | AD-R01 |
| An allowed call on every /admin or /users route writes an audit record | FINDING: E42-R-01, E42-R-02 (open) | — | SR-060 | AD-R01 |
| A step-up class on every dangerous write | HOLDS | `test_dangerous_route_registry.py:168`, :326, :638, :664, :674, :683, :693; `test_cells_{none,stale,fresh}.py:18` | SR-025 | AD-E01, AD-E02, TM §3.3 |
| Server: 404 for an unknown route, 403 for a known one | HOLDS | `test_deny_by_default.py:49`; `test_admin_http.py:94` | SR-018 | AD-I01 |
| Client: 404 for `/admin/**` to non-owners, admin code not loaded | HOLDS | `apps/web/test/routes/rbac.test.ts:37`, :49; `guards.test.ts:43`, :61 (the lazy `AdminRouteElement`) | SR-017 | AD-I01 |
| Every RBAC-disabled UI control maps to a server refusal (the ticket's accessibility check) | N/A at the pin (no such control in the admin client on `main`); WAITING on #1023, #1134, #1135, #1024 | — | SR-017 | client STRIDE |
| Self-scope routes (view-as get and end, own sessions) | HOLDS | M:438, :444, :1017 cells; the own-session check in `api/sessions.py` | SR-026 | AD-S06 |

Findings: E42-R-01 (Low, open, private record) and E42-R-02 (Low, open, #2836) fall in this area; this pass
filed none new. E42-R-04 (Low, TB-4 client to API, open, private record) is listed with them.

### 1.3 Area 2: the elevation model (Gherkin 4, as ruled under BQ-9)

There is no admin token on `main`. Elevation is the per-class step-up grace, held as server state on the session
row; SCR-149's window is retired under D8 (ruled: per-action step-up, #2701 ledger 2 row 12; its ADR is #1085).
"Admin token TTL" is read as the step-up grace window.

<!-- prettier-ignore -->
| Control | Verdict | Evidence | 04 SR | TM row |
| --- | --- | --- | --- | --- |
| E-1 The grace expiry is computed by the server at grant (`now + GRACE_WINDOW`, `auth/step_up.py:571-573`), stored on the session row (`_elevate`, :314-331); a replayed code cannot refresh it (:732) | HOLDS | `test_stepup_invite_abuse.py:43` (AC-STEP-02); `test_step_up_router.py:337`; M:456 | SR-021, SR-025 | AD-S02, AD-E12, AD-T10 |
| E-2 Elevation is bound to its session and its class, read only from the caller's own row (`auth/step_up.py:734-743`, :778-787) | HOLDS | `test_stepup_invite_abuse.py:32` (AC-STEP-01); M:456 | SR-025 | AD-T10; AC-ADM-04 |
| E-3a A client expiry in the step-up body is refused whole (`extra="forbid"`, `api/step_up.py:150-153`); no grant | HOLDS | `test_step_up_route_hardening.py:69`; `security/admin/test_elevation_client_expiry.py:49`; M:456 | SR-025 | AD-T10 |
| E-3b A client expiry in a header or a cookie changes nothing; the decision comes from the row (`api/step_up.py:396-436`, :794-829) | HOLDS (this PR) | `security/admin/test_elevation_client_expiry.py:49` (`test_x02_a_client_supplied_expiry_changes_nothing_and_the_lapsed_write_is_challenged`), real `create_app()` stack, fixed clock | SR-025 | AD-T10 |
| E-4 The next dangerous write after the window lapses is `403 step_up_required` and recorded as `auth.step_up_required` (`api/step_up.py:426-427`; `auth/step_up.py:616-624`; `statechart/bindings/b16_session.py:380-390`) | HOLDS | `test_step_up_router.py:283`; `test_cells_stale.py:18`, :30; `test_elevation_client_expiry.py:49` (one new record, class `users`); M:1624 | SR-025 | AD-E12, AD-S05 |
| E-5a `POST /auth/session/extend` moves only the idle deadline, never `expires_at`, never lifts a lock (`api/sessions.py:1358-1381`; `auth/session_service.py:808-822`) | HOLDS | `test_extend.py:24`, :111; M:432 | SR-024 | AD-S05 |
| E-5b Extend leaves the step-up grace unchanged (`storage/repositories/sessions_sqlalchemy.py:152-155` sets `last_seen_at` only) | HOLDS over HTTP (this PR) | `test_elevation_client_expiry.py:49`: a mutant whose session touch re-stamps the elevations turns it red. The test runs on the in-memory store; the SQL statement's own pin (`unit/storage/test_sessions_sqlalchemy.py:310`) is a carry | SR-024, SR-025 | AD-S05 |
| E-6 The admin area's `reauth_age_s` is observability only, never a gate (`admin/http.py:26-35`) | HOLDS | `test_admin_http.py:288`; M admin rows | SR-E42-12 | AD-E01 |
| O-1 `auth_stepup_failures_total` exists, is scraped and goes up by one per failed step-up (`auth/metrics.py:161-164`; `auth/step_up.py:560`) | HOLDS | `test_observability.py:203`; `test_admin_abuse_cases.py:150` | SR-125 | AD-S02, AD-D10 |
| O-1b An alert on `auth_stepup_failures_total` | known, routed to #2746 (the lockout alert stands in, TM :1016) | `test_observability.py:41` records the gap | SR-125 | AD-D10 |
| O-2 `authz_denied_total{permission}` is counted before the record by the admin guard (`admin/http.py:156`) and by `enforce`, with an alert and a missing-series guard (`infra/prometheus/alerts/system_ticket.yml:252-253`; `metric_guards.yml:337-338`) | HOLDS | `test_admin_http.py:160`; `test_observability.py:184`; `test_admin_abuse_cases.py:625`; `test_cells_stale.py:37` | SR-125 | AD-D06 |
| O-3 `admin.access_denied` is `admin.area_entered` with outcome `denied` (`admin/http.py:9-13`) | HOLDS | `test_admin_http.py:94`; M admin rows | SR-062, SR-125 | AD-D06 |
| O-4 A `403 step_up_required` is counted by no metric | known, accepted (X03-F3, #1026 decision D6) | — | SR-125 | X03-F3 |

Findings: E42-R-03 (Low, 2 The elevation model, open, #2799) falls in this area; this pass filed none new.

### 1.4 Area 3: the audit read side

<!-- prettier-ignore -->
| Control | Verdict | Evidence (test + M row / CI) | 04 SR | TM row |
| --- | --- | --- | --- | --- |
| No mutation path: query, verify, signing keys and download only SELECT, and write only appended records (`audit/query.py:366-481`) | HOLDS | `integration/audit/test_audit_guard_cv_app.py:353`, :427 (CI shard 2); M:22-60, all six `/admin/audit*` rows `executed` | SR-066, SR-E42-08 | AD-T01 |
| Manager scoping in the repository layer, in the SQL of every page, whatever filter was sent | HOLDS | `unit/storage/test_audit_query_statements.py:74`; `test_audit_query_page.py::test_restricted_scope_returns_only_the_callers_rows` (CI shard 2); `test_audit_router.py:601`, :1218, :1283; cross-actor recorded :991, :1010; Owner-only filters refused and recorded :772, :1231; M:22-27 | SR-067 | AD-I07, AD-R06 |
| Export is signed: the active key, the digest of the file as written, a write-ahead signing record | HOLDS | `test_audit_export_route.py:439`; `test_export_job.py:161`, :267, :291; M:37-46 | SR-067, SR-E42-15 | AD-T13, AD-R12 |
| Export is range-limited: a 31-day window, row and byte caps | HOLDS | `test_audit_export_route.py:385` (`over_31_days`); `test_export_job.py:197`; `test_export_writer.py:265`, :275; M:37-41 | SR-E42-08 | AD-D03 |
| Export is rate-limited: 5 starts an hour, single flight, 20 downloads an hour | HOLDS; the measured cross-check WAITING (blocked on #1216) | `test_audit_export_route.py:354`, :255, :340; `test_audit_export_download.py:313`, :294; M:37-46 | SR-E42-08 | AD-D03, AD-I09 |
| Redaction at write time, preserved on export | HOLDS | `test_redact_actions_access.py:47`, :65; `integration/audit/test_audit_repository.py:99` (CI shard 4); `test_export_writer.py:170` (each exported line recomputes to the stored `entry_hash`) | SR-069 | AD-I02 |
| On-demand verify: span cap, per-user rate, single-flight slot, deadline and `admin.audit_verify` records (`api/audit.py:744-861`) | HOLDS (AD-F04's verify part built) | `test_audit_router.py:595`; M:55 | SR-E42-08 | AD-R07, AD-D04 |
| E42-R-13 | FINDING: Low, 3 The audit read side, open | n/a | n/a | n/a |

Findings: E42-R-06, E42-R-08, E42-R-09 (Low, open, private record) fall in this area; this pass filed E42-R-13
(Low, open, private record).

### 1.5 Area 4: append-only enforcement, independent of the application (Gherkin 2, as ruled under BQ-10)

As `cv_app` only the grant layer can refuse: the missing privilege ends the statement before any trigger runs
(TM §3.1). The trigger layer is shown by roles that hold the privilege. "The attempt is itself recorded"
(US-ADMIN-008) is met for v1 by the Postgres server log's ERROR and STATEMENT lines, outside the database the
statement targets, accepted under the sign-off (ruling BQ-10); AD-F08's alert (#3196) is the tracked complement.

<!-- prettier-ignore -->
| Control | Verdict | Evidence (test / CI) | 04 SR | TM row |
| --- | --- | --- | --- | --- |
| Append-only as `cv_app`: UPDATE, DELETE and TRUNCATE refused by grant, rows unchanged (a real session as the role) | HOLDS | `integration/audit/test_audit_guard_cv_app.py:353` (cv_app holds exactly SELECT and INSERT), :427; `test_audit_repository.py:132`; CI shards 2 and 4 | SR-066; C-5.7 | AD-T01 |
| Append-only via privileged roles: the trigger refuses | HOLDS | `integration/audit/test_audit_guard_privileged_role.py:97` (a privileged role that is not the owner; the TM's owed case, now met); the owner case `_assert_guard_enforces` run by `test_audit_guard_cv_app.py:448`, :464, :473; `test_audit_repository.py:126` (`test_truncate_refused_even_for_owner`); CI shards 2 and 4 | SR-066 | AD-T01 |
| The owner role or a superuser removes the trigger layer | known, accepted residual AD-F14, routed to #1238 | detection only: `test_audit_repository.py:112` (`test_superuser_tamper_is_located`) | SR-068 | AD-T02 |
| The refused statement is recorded: every compose file keeps the ERROR and STATEMENT lines (`log_min_messages`, `log_min_error_statement` at most `error`; `infra/compose/docker-compose.yml:60-61`), none turns off the postgres log output, no migration or bootstrap SQL sets a server log level | HOLDS (this PR) | `unit/storage/test_postgres_server_log.py:80`, :90, :96, with :30 and :52; a mutant adding `log_min_error_statement=panic` to the base compose file turns :80 red | SR-066 | AD-T01 (BQ-10), AD-F08 (#3196) |
| Chain order under concurrent inserts | HOLDS | `integration/audit/test_audit_repository.py:263` (`test_two_connection_inserts_link_in_id_order`, 1,000 inserts on two connections, one raw), :244, :252, :314, :338; CI shard 4 (job 126548559204) | SR-063, SR-E42-10 | AD-R04 |

Locking argument for chain order (a held control). Every insert into `audit_log` runs the BEFORE INSERT trigger
`audit_chain()`, which takes the transaction-scoped chain lock, draws `id` from `audit_log_id_seq` under it, then
reads the head by `ORDER BY id DESC LIMIT 1` (`0045_audit_chain_hardening.py:69-90`); the app path takes the same
lock before its INSERT (`storage/repositories/audit_sqlalchemy.py:309-348`). The lock is released at the end of the
transaction, after the commit is visible; at READ COMMITTED each statement in the trigger takes a fresh snapshot,
so the next holder reads the previous holder's committed row as head; ids drawn under the lock from a `CACHE 1`
sequence increase in lock order. A rollback or an `ON CONFLICT DO NOTHING` leaves only an id gap, and verify
never assumes consecutive ids. The argument rests on READ COMMITTED (AD-F26) and `CACHE 1` (AD-F27, pinned by
:263), both known Low residuals. The stress test alone, or the argument alone, would not be enough.

Findings: none in this area.

### 1.6 Area 5: the flag registry (Gherkin 3)

<!-- prettier-ignore -->
| Control | Verdict | Evidence | 04 SR | TM row |
| --- | --- | --- | --- | --- |
| A definition declaring a security-gating category is refused when built (`admin/flags/registry.py:105`, :130; `DENIED` :59) | HOLDS | `unit/admin/test_flag_registry.py::test_the_denied_category_truth_table`, `::test_registry_rechecks_every_spec_at_startup`; `test_flag_create_app_refusal.py::test_every_security_category_is_denied`; mutants dropping RBAC from `DENIED`, or emptying it, are killed | SR-E42-07; C-4.14 | AD-E03, AD-F09 |
| Startup fails: `create_app` refuses such a definition (`flags_wiring.py:270`; `main.py:400`) | HOLDS | `test_flag_create_app_refusal.py::test_create_app_refuses_a_denied_flag` (×8) with the control `::test_the_same_definition_with_an_allowed_category_boots`; `security/admin/test_admin_abuse_cases.py::test_ac_adm_13_create_app_refuses_a_flag_that_gates_authentication`; two mutants killed (the recheck removed: 10 red; bad specs dropped and booting: 8 red) | SR-E42-07 | AD-E03, AC-ADM-13 |
| Semgrep `cv-admin-no-flag-lookup`: the fixtures pass | HOLDS | `tools/ci/check_semgrep_rule_tests.py` at CI's pinned Semgrep: 0 failures over 35 `ruleid` lines; CI job 126548559980; `unit/admin/test_flag_lookup_rule.py` holds the rule's key list to the catalogue | SR-E42-07, SR-156 | AD-E03, AC-ADM-14 |
| Same rule: 0 hits on `main` | HOLDS | scan of `services/api/candleviewer` at the pin: 191 files in scope, 0 results, 0 errors | SR-E42-07 | AC-ADM-14 |
| Same rule: a planted violation turns it red | HOLDS | in a scratch copy, one import added to `admin/http.py` and one flag read added to `auth/step_up.py`: exit 1, exactly the 2 planted lines reported; the unmodified copy exits 0 | SR-E42-07 | AC-ADM-14 |
| No auth, RBAC or audit module reads a flag (as enforced) | FINDING: E42-R-07 (Low, open); E42-R-10 (Medium, open) | — | SR-E42-07 | AD-E03, AD-F09, N5 |
| Maintenance mode is step-up gated: release needs the no-grace `killswitch` class, engage needs `flags` (`admin/flags/policy.py:24`; `writes.py:184-185`; `api/step_up.py:680-682`) | HOLDS | `test_flag_policy.py::test_one_step_up_class_from_the_key_and_the_row_as_stored`; `test_flag_writes.py::test_a_release_refused_at_the_gate_records_and_writes_nothing`, `::test_a_release_is_judged_on_the_locked_row_not_a_cached_or_earlier_read`; `test_admin_abuse_cases.py::test_ac_adm_07_…`; two mutants killed; M:130 | SR-E42-01, SR-E42-02 | AD-D02, AD-E02, AC-ADM-07 |
| Maintenance mode fails closed: starts engaged, an unknown reading engages, a dead poll latches it (`admin/flags/maintenance.py:68`, :140, :83-88) | HOLDS | `test_flag_maintenance.py::test_the_gate_starts_engaged_and_opens_once_both_flags_are_read`, `::test_a_fail_closed_reading_engages_the_gate_without_side_effects`; `test_flag_wiring_poll_supervision.py::test_a_poll_that_dies_latches_the_gate_closed_counts_and_logs_its_class`; `unit/test_order_entry_gate_wiring.py`; three mutants killed | SR-E42-02 | AD-D02 |

Sanctioned reads: the CSRF module reads the `desktop.backend_connection` state per request (`api/csrf.py:182`); the
flag only adds headers, under ADR-0038 (accepted), known, routed to #3931 (the flag's removal).
`trading.oms_enabled` gates OMS admission in the restrictive direction (ruling Q3 on #913), known, routed to #4227
(its removal). SR-E42-07 stands as: the rule and the boot-refusal test are on `main` (AC-ADM-13 met; AC-ADM-14's
fixtures and zero hits met); SR-E42-07 stays open on E42-R-07 and E42-R-10.

Findings: E42-R-07 (Low, open, private record); this pass filed E42-R-10 (Medium, open, private record).

### 1.7 Area 6: the user lifecycle

<!-- prettier-ignore -->
| Control | Verdict | Evidence | 04 SR | TM row |
| --- | --- | --- | --- | --- |
| Last-owner floor under concurrency (a locking argument plus the E42-T04 and E42-T09 stress tests) | HOLDS as tested; E42-R-05 (Low, open, private record) | `integration/admin/test_user_lifecycle_pg.py::test_concurrent_demote_and_disable_keep_owner`; `test_user_admin_pg.py::test_ten_parallel_demotions_one_wins`, `::test_patch_disable_vs_demote_keeps_owner`; `test_admin_abuse_pg.py::test_ul_ac03_…`, `::test_ac_adm_28_…`; M:1690, :1648, :1642; CI run 41821199189 | SR-055 | UL-F13, AD-D01 |
| Owner floor on a single request (route pre-check plus store) | HOLDS | `unit/api/test_users_delete.py::test_last_owner_409`; `test_user_admin_routes.py::test_last_owner_demotion_is_409_with_one_owner_floor_denial`, `::test_patch_disable_of_the_last_owner_is_409_and_audit_down_503` | SR-055 | UL-F13 |
| The actor re-read under the owner lock (#2593) | HOLDS | `test_user_lifecycle_pg.py::test_disable_of_the_last_active_owner_by_a_disabled_owner_is_refused_first` | SR-055 | UL-F13 |
| An anonymised user is never changed again, an enable included | HOLDS | `integration/admin/test_user_purge_pg.py::test_an_anonymised_user_is_never_enabled`, `::test_an_anonymised_user_is_never_changed`, `::test_route_refuses_to_enable_an_anonymised_user`; `test_user_admin_routes.py::test_an_anonymised_user_is_not_enabled`; M:1648 | — | L4, UL4-E1 |
| Anonymisation overwrites the identity columns, recorded ahead | HOLDS | `unit/storage/test_user_purge.py::test_anonymise_writes_the_surrogate_and_nulls_pii_with_users_anonymise_ahead`; `test_user_purge_pg.py::test_users_anonymise_ahead` | — | UL4-I1, UL-F7 |
| A re-enable racing the reaper keeps the user | HOLDS | `test_user_purge.py::test_reenable_racing_reaper_keeps_user`; `test_user_purge_pg.py::test_reenable_racing_reaper_keeps_user` | — | UL-F5, UL4-T2 |
| Grant change: the `grants_changed` push, then a `revoked` frame on live subscriptions, also when the store call is cut off | HOLDS | `test_users_account_access_put.py::test_put_replaces_the_grants_and_pushes_after_the_commit`; `contract/rbac/test_scope_and_ws.py::test_in_flight_subscription_gets_revoked_when_the_grant_is_withdrawn`; `unit/ws/test_subscriptions.py::test_registry_grants_changed_pushes_revoked_and_audits`; `test_account_access_service.py::test_cancel_during_the_store_call_pushes_and_still_cancels`; M:1660 | SR-074, SR-189 | UL2-I1, UL-AC08 |
| No `grants_version` (R7 on #965) | N/A | zero occurrences under `services/`, `packages/`, the OpenAPI file and `23-ws-protocol.md` at the pin | — | — |
| A role change re-evaluates live WS sockets after the commit | HOLDS | `test_users_router.py::test_put_roles_registry_pushes_permission_change_to_live_socket`, `::test_put_roles_push_after_the_commit_is_counted`, `::test_put_roles_push_failure_after_the_commit_is_200_logged_and_counted` | SR-074 | UL3-E1 |
| Disable: REST refused, WS closed with 4403 within the bound | HOLDS | `security/auth/test_disable_user_e2e.py::test_rest_401_ws_4403_within_5s`; `test_disable_user_drill.py::test_a_disable_through_the_route_reaches_the_socket_within_the_sr029_bound`; M:1642 | SR-029 | L1, UL1-S1 |
| Delete with purge: disable first, the schedule written ahead | HOLDS | `test_users_delete.py::test_audit_down_503`; `test_user_purge.py::test_schedule_and_anonymise_records_carry_no_pii` | — | L4, UL4-R1 |
| Invites: token stored hashed, single use, expiry, throttle; a disabled invitee cannot finish | HOLDS | `test_admin_abuse_cases.py::test_ac_adm_27_a_spent_invite_link_answers_as_an_unknown_one`; `test_admin_abuse_pg.py::test_ul_ac14_a_disabled_invitee_cannot_complete_the_old_invite`; M:779, :785, :1666, :1672 | SR-055 | UL-AC14 |
| `createUser` accepts `mfa_required: false` | known, routed to #3086 | — | SR-E42-13 | AD-F10 |
| The two-step `invited` → `disabled` → `active` | known, routed to #2710 | — | — | UL-F3 |
| Unbind: the open-order count on grant removal | WAITING (the #2648 re-route; known UL-F9) | — | — | UL-F9, UL-AC15 |
| View-as on the server: read-only, a 30-minute server expiry, WS action frames refused, every refusal recorded | HOLDS | `test_admin_abuse_cases.py::test_ac_adm_22_view_as_cannot_mutate`; `test_view_as_sweeper.py::test_expiry_ends_without_any_request`; `unit/ws/test_view_as_frames.py::test_a_viewing_sessions_action_frame_is_refused_recorded_and_the_socket_stays`; `test_view_as_gate.py::test_held_write_refused_view_as_expired_and_changes_nothing`; M:267, :438, :444 | SR-E42-03 | AD-E04, AD-I05 |
| The overdue-purge alert | known, open on #2650 (UL-F6) | — | — | UL-F6, UL4-D1 |

The written locking argument for the last-owner row is held in the private record. The concurrency verdict rests
on that argument and the stress tests together (the ticket's technical note).

Findings: E42-R-05 (Low, open, private record) falls in this area; this pass filed E42-R-11 and E42-R-12 (Low,
open, private record).

### 1.8 Area 7: destructive paths (Gherkin 5)

<!-- prettier-ignore -->
| Control | Verdict | Evidence (test + M row / CI) | 04 SR | TM row |
| --- | --- | --- | --- | --- |
| Restore refused while maintenance mode is off, whatever the client sends (service) | HOLDS | `unit/admin/test_restore_guard.py::test_maintenance_off_is_409_maintenance_mode_required_and_creates_no_job`, `::test_preconditions_are_checked_in_the_contract_order` | SR-E42-04 | AD-D08 |
| The same, at the route | WAITING (blocked on #3084, D7) | M:97 `not_mounted` | SR-E42-04 | AD-D08 |
| An unknown or unreadable maintenance state is never read as on | HOLDS | `test_restore_guard.py::test_unknown_maintenance_is_503_store_unavailable_never_treated_as_on`, `::test_flag_store_outage_never_reads_as_maintenance_on`; `integration/admin/test_restore_guard_pg.py::test_precondition_matrix_against_postgres_flags_and_audit` (CI run 41821199189) | — | AD-D08 |
| Unknown or open positions need explicit acknowledgement | HOLDS | `test_restore_guard.py::test_unreadable_positions_are_unknown_never_zero`, `::test_any_open_position_needs_its_acknowledgement` | — | AD-D08 |
| The restore digest equals the digest the append-only `backup.run` record bound | HOLDS (service) | `test_restore_guard.py::test_a_backup_whose_digest_differs_from_its_bound_record_is_not_usable`, `::test_a_usable_status_with_its_bound_digest_is_compared_in_constant_time` | SR-E42-05 | AD-T05 |
| Backup location and identity columns write-once; `cv_app` cannot delete rows | HOLDS | `integration/storage/test_backups_write_once_pg.py::test_target_path_and_kind_are_write_once`, `::test_checksum_is_set_once_from_null_then_frozen`, `::test_cv_app_cannot_delete_a_row_so_it_cannot_swap_one` (CI run 41821199189) | SR-E42-05 | AD-T05 |
| One restore admitted at a time, under the backups admission lock | HOLDS | `test_restore_guard.py::test_two_concurrent_restores_admit_one` | — | AD-D08, AD-D09 |
| Every restore attempt recorded before its answer (C-2.9) | HOLDS | `test_restore_guard.py::test_every_attempt_is_recorded_before_the_answer_at_severity_error`, `::test_audit_failure_is_503_and_starts_no_job` | — | AD-R10 |
| The restore executor is reachable only through the guard | HOLDS | `test_restore_guard.py::test_the_executor_is_reachable_only_through_the_guard`, `::test_no_guard_is_built_without_the_revocations_check` | SR-E42-04 | AD-E07 |
| Restore uses the newest conclusive verification record | WAITING (blocked on #3084; BK-14 wires it) | — | SR-E42-05 | AD-T05, TM §6 step 3 |
| D7: later revocations survive a restore, or the restore is refused | WAITING (blocked on #3084) | — | SR-E42-04 | AD-E07, AD-R05, AD-I11 |
| Trading halt held outside the replaced database; maintenance re-checked when the executor starts | WAITING (blocked on #3319) | port contract only | SR-E42-04 | TM §6 step 7, AD-D02 |
| The restore's no-grace step-up spent once; the idempotency key recorded after admission | WAITING (blocked on #3084) | M:97 `not_mounted` | SR-025 | AD-S08, AD-T11 |
| Download link single use (lookup and spend in one event-loop step) | HOLDS | `unit/admin/test_download_links.py::test_consume_is_single_use_under_concurrency`, `::test_a_spend_is_once_and_an_expired_or_discarded_link_is_never_spent`; `test_admin_backup_download_router.py::test_a_link_serves_the_artefact_once_as_an_attachment_then_is_410`; M:91 | — | AD-I04 |
| Download link short-lived (5 minutes, server clock) | HOLDS | `test_download_links.py::test_expiry_is_five_minutes_on_the_server_clock`; M:91 | — | AD-I04 |
| Only the token hash is kept, compared in constant time | HOLDS | `test_download_links.py::test_only_the_hash_is_stored`, `::test_every_held_hash_is_compared_in_constant_time` | — | AD-I04 |
| The token stays out of access logs, records and metric labels | HOLDS | `unit/observability/test_backup_token_never_logged.py::test_access_log_line_never_carries_the_token`, `::test_off_mesh_record_and_metric_label_carry_the_route_template` | SR-069 | AD-I04 |
| Link issue: Owner only, a no-grace `backups` step-up, 10 an hour | HOLDS | `test_admin_backup_links_router.py::test_issue_spends_one_fresh_backups_code_per_link`, `::test_manager_and_viewer_get_403_never_a_challenge`, `::test_eleventh_link_in_an_hour_is_429_before_any_challenge`; M:85 | SR-025 | AD-I04, AD-S08 |
| A link ends when the grant that minted it ends (session family, disable, unlock) | HOLDS | `unit/admin/test_backup_fetch.py::test_the_events_that_end_the_grant_end_the_link_after_its_spend`, `::test_a_link_ends_at_any_unlock_of_its_session_chain` | — | AD-I04 |
| Backup delete: step-up, write-ahead record, last-usable and in-use refusals under the lock | HOLDS (service and route; production answers 501 until #3319) | `test_backup_deletion.py::test_a_delete_records_ahead_then_removes_the_rows_artefact_then_marks_it`, `::test_conflicts_are_refused_in_the_contract_order_each_recorded_first`, `::test_two_deletes_of_a_kinds_last_two_verified_backups_keep_one`; `test_admin_backup_delete_router.py::test_delete_spends_one_fresh_backups_code`, `::test_manager_and_viewer_get_403`; M:79 | SR-095 | AD-T05, AD-S08 |
| Maintenance step-up and fail-closed | HOLDS | as §1.6's two maintenance rows | SR-E42-02 | AD-D02 |
| Export limits: 31-day range, row and byte caps, single flight, 5 an hour, 20 downloads an hour | HOLDS (built and unit-tested) | as §1.4; `test_audit_export_route.py::test_a_request_the_contract_refuses_is_422_naming_no_value`, `::test_one_export_at_a_time_and_none_while_a_rotation_runs`; M:37, :43 | SR-E42-08 | AD-D03 |
| Export limits measured under load (the ticket's performance note, cross-checked with E42-Q03) | WAITING (blocked on #1216) | no admin export scenario under `tests/load` at the pin | SR-E42-08 | AD-D03, TM §7 |

Findings: none in this area.

### 1.9 TM §12.1 control checklist

<!-- prettier-ignore -->
| Control | 04 and model ids | Verdict at the pin | Test ids |
| --- | --- | --- | --- |
| Deny by default and the route matrix | SR-017, SR-018; D1 | HOLDS | `test_deny_by_default.py:21`, :32, :49; `test_route_matrix.py:263` |
| The audited admin guard | SR-060; SR-E42-09 | HOLDS for the guard; the denial budget known, routed to #2836 | `test_admin_http.py:94`; Semgrep `cv-admin-route-guarded` |
| Per-class step-up on every dangerous operation | SR-025; SR-E42-01, SR-E42-02 | HOLDS | `test_dangerous_route_registry.py:168`, :326; `test_flag_routes.py::test_a_refused_step_up_answers_the_refusal_and_writes_nothing`; `test_audit_export_download.py` |
| Request-bound, single-use no-grace grants | SR-025 | HOLDS for the binding; the spend record not complete at the pin: E42-R-03 (Low, open, #2799) | `test_step_up_binding_router.py:122`, :128; `test_step_up_grant_race_pg.py:173` |
| Append-only audit: grants | SR-066; C-5.7 | HOLDS; the same pin for each new append-only table known, routed to #3196 | `test_audit_guard_cv_app.py:353`, :427 |
| Append-only audit: triggers | SR-066 | HOLDS; the owed privileged non-owner case is met | `test_audit_guard_privileged_role.py:97`; `test_audit_repository.py:126` |
| The flag registry's refusal | C-4.14; SR-E42-07 | HOLDS for the boot refusal and the rule; SR-E42-07 open on E42-R-07, E42-R-10 | `test_flag_create_app_refusal.py:57`; `.semgrep/cv-admin-no-flag-lookup.yml` |
| A server-side view-as context | SR-E42-03 | HOLDS (server); the client WAITING (blocked on #1134) | §1.7's view-as row |
| A restore keeps revocations and its own record | SR-093; SR-E42-04, SR-E42-05 | WAITING (blocked on #3084, #3319) | `test_restore_drill.py:204` proves consistency only |
| Session and grace limits | SR-012, SR-024, SR-041; SR-E42-12 | HOLDS; D8 ruled | `test_stepup_invite_abuse.py:43`; `test_admin_http.py:288`; `test_elevation_client_expiry.py:49` |
| The referenced Highs | E04 H4; E16 R-E1 | referenced (the E04 and E16 records); the purge row of §1.1 holds | E04's bundle secret scan; `api/step_up.py` purge Owner check |

### 1.10 SR-E42-01..16

<!-- prettier-ignore -->
| Id | 04 trace | Status at the pin | Evidence |
| --- | --- | --- | --- |
| SR-E42-01 | SR-025; AD1 | met (#3160) | `test_dangerous_route_registry.py:168`, :638 |
| SR-E42-02 | SR-025; AD1 | met: the class and the handler test | `test_flag_routes.py::test_a_refused_step_up_…`; `test_flag_writes.py` (§1.6) |
| SR-E42-03 | SR-026; AD2 | met (server, #3085); client WAITING on #1134 | §1.7's view-as row |
| SR-E42-04 | SR-093; AD3 | open; WAITING on #3084 (D7); the service guard holds | §1.8 |
| SR-E42-05 | SR-093, SR-095; AD7 | in part: the digest binding and write-once columns hold; origin authentication known, routed to E42-T05 (#966) and #3319 (AD-S11, AD-F07) | §1.8 |
| SR-E42-06 | SR-066; AD5 | open, known, routed to #3196 | — |
| SR-E42-07 | C-4.14; AD9 | open on E42-R-07, E42-R-10; the rule and the boot-refusal test are on `main` | §1.6 |
| SR-E42-08 | SR-067; AD8 | met at the pin (export part #889 S10; verify part built); the measured cross-check WAITING on #1216 | §1.4 |
| SR-E42-09 | SR-060, SR-125; AD8 | open, known, routed to #2836 | §1.2 |
| SR-E42-10 | SR-063 | met: the proofs passed in the pin's CI integration lane | `test_audit_repository.py:263` (job 126548559204) |
| SR-E42-11 | SR-060, SR-062 | met: every listed action registered (AD-F17); `admin.session_elevated` dropped under D8 | `audit/actions.py` registrations with `test_redact_actions_access.py` |
| SR-E42-12 | SR-024, SR-025; AD4 | ruled: per-action step-up (#2701 ledger 2 row 12); ADR #1085 records it | `test_admin_http.py:288`; `test_elevation_client_expiry.py:49` |
| SR-E42-13 | SR-020 | open, known, routed to #3086 | — |
| SR-E42-14 | SR-074 | met (#3136, #3221) | `test_system_filter.py:120`, :128, :223; `test_system_topic_roles.py:154` |
| SR-E42-15 | SR-067 | met | `test_export_signer.py`; `test_export_job.py:161`; `test_audit_export_route.py:439` |
| SR-E42-16 | SR-067 | met | `test_export_key_kek.py`; `test_export_key_boot.py`; `test_rotation_run.py` |

### 1.11 Counts

Rows by first verdict word (a row that holds with a WAITING cross-check counts as HOLDS):

<!-- prettier-ignore -->
| Section | Rows | HOLDS | FINDING | WAITING | N/A | known |
| --- | --- | --- | --- | --- | --- | --- |
| §1.1 Area 1, the route table | 65 | 56 | 0 | 4 | 4 | 1 |
| §1.2 Area 1, the route controls | 13 | 10 | 1 | 0 | 1 | 1 |
| §1.3 Area 2, the elevation model | 13 | 11 | 0 | 0 | 0 | 2 |
| §1.4 Area 3, the audit read side | 8 | 7 | 1 | 0 | 0 | 0 |
| §1.5 Area 4, append-only enforcement | 5 | 4 | 0 | 0 | 0 | 1 |
| §1.6 Area 5, the flag registry | 8 | 7 | 1 | 0 | 0 | 0 |
| §1.7 Area 6, the user lifecycle | 17 | 12 | 0 | 1 | 1 | 3 |
| §1.8 Area 7, destructive paths | 23 | 17 | 0 | 6 | 0 | 0 |
| **Total** | **152** | **124** | **3** | **11** | **6** | **8** |

The three FINDING rows carry five of the seventeen ids; the rest are listed at each area's foot and in §2.

## 2. Findings

Ids are public and stable, ordered by severity, then id. None is Critical or High (with the two overrides of §3
applied), so none needs a BQ-3 remediation issue before the epic. A finding's tracker is an existing public
issue where the TM already routes the gap in public; otherwise it is the private record, where its STRIDE class,
L×I, mechanism, location and regression test are held until it is fixed.

<!-- prettier-ignore -->
| Id | Severity | Area | Status | Tracker |
| --- | --- | --- | --- | --- |
| E42-R-10 | Medium | 5 The flag registry (Gherkin 3) | open | private record |
| E42-R-01 | Low | 1 Every admin route (Gherkin 1) | open | private record |
| E42-R-02 | Low | 1 Every admin route (Gherkin 1) | open | #2836 |
| E42-R-03 | Low | 2 The elevation model | open | #2799 |
| E42-R-04 | Low | TB-4 client to API | open | private record |
| E42-R-05 | Low | 6 The user lifecycle | open | private record |
| E42-R-06 | Low | 3 The audit read side | open | private record |
| E42-R-07 | Low | 5 The flag registry (Gherkin 3) | open | private record |
| E42-R-08 | Low | 3 The audit read side | open | private record |
| E42-R-09 | Low | 3 The audit read side | open | private record |
| E42-R-11 | Low | 6 The user lifecycle | open | private record |
| E42-R-12 | Low | 6 The user lifecycle | open | private record |
| E42-R-13 | Low | 3 The audit read side | open | private record |
| E42-R-14 | Low | copy | open | E42-D03 / #1023 |
| E42-R-15 | Low | copy | open | E42-D04 / #1135 |
| E42-R-16 | Low | copy | open | E42-D04 / #1135 |
| E42-R-17 | Low | copy | open | #1238 |

Counts: Critical 0 · High 0 · Medium 1 · Low 16 · open 17. E42-R-10 and E42-R-07 bear on the same control
(Gherkin 3's rule) and are cross-referenced in the private record. E42-R-17 is a copy item resting on the known
AD-T02 / AD-F14 residual (routed to #1238), which it does not re-rate.

Not rated, and not findings:
- **Lead L-1** (the rules/server area): routed to E35-T11 as a binding precondition; the `ud.demotion` copy is
  re-verified when E35-T11 binds (§4).
- **Observation O-1** (audit): a defence-in-depth note, held in the private record with no id.
- **The restore "today" copy carry** (§4): known, routed to #3084 (AD-E07).

Dispositions (fixed / mitigated / accepted-risk with Owner sign-off) are the sign-off's (§8). Every finding gets
a regression test at the right layer before it closes (the ticket's test plan); fixes land on the owning
branches, not in this PR.

## 3. D2, the owner-equivalent band-raise (ruling BQ-8)

**Not adopted.** The rows stay on E27's plain L×I matrix, tagged **OE** where the outcome is owner-equivalent.
Most owner-equivalent outcomes in this epic are configuration the Owner can set back (roles, grants, flags,
maintenance) and already carry impact H; E27's raised band was for value leaving an account. The one that cannot
be set back, a restore, is already High and gated by D7 (#3084).

Two overrides bind every rating in this record and in the TM:
1. `SECURITY.md` :45: a finding in the P0 class (an RBAC failure, audit-log integrity broken, API-key
   confidentiality, the withdrawal-off invariant, a missing native stop, unauthorised order placement) is
   **Critical / P0 whatever its row's L×I**.
2. `04` :318 (U3) and :334 (D1), both **Critical at M×H**, apply to the same shapes here: a missing role check on a
   route, or an admin API callable by a lower role.

No E42-R finding falls under either override. AD-E12's accepted Medium falls due for review when the D8 ADR
(#1085) lands, or on 2027-02-04, whichever comes first. With D2 not adopted, AD-E12 does not go back to the
Owner on #2701; #2701 keeps only AD-E01's acceptance if it is still owed (ruling BQ-7). TM §1.4 and §5.2, and
`04` §5.15, record D2 in this PR's model re-read.

## 4. Copy review

SCR-146's sign-off asks for the restore impact copy to be reviewed by security; the ticket extends it to delete,
unbind, purge and flag-change copy, where an understated consequence is a finding. Reviewed: E42-D03 §14, E42-D04
§7, §9, §10 and §14, E42-D05 §8.2, and the strings built on `main` (S01). The copy of S02–S05 and S08 as built is
WAITING (blocked on #1023, #1134, #1135, #1024, #1137).

<!-- prettier-ignore -->
| Copy key | Verdict | Evidence (test id + M row) | 04 SR | TM row |
| --- | --- | --- | --- | --- |
| D03 `dlg.delete` | FINDING: E42-R-14, Low, copy, open | — | SR-029 | AD-D01 |
| D03 `dlg.disable` | HOLDS (design); as built WAITING (blocked on #1023) | `integration/admin/test_user_lifecycle_pg.py::test_disable_revokes_all_live_sessions_and_grants_in_one_transaction`; `unit/admin/test_user_disable.py::test_disable_disarms_the_users_armed_rules_through_b9_and_closes_their_scope`; M:1642 | SR-029 | UL-F rows |
| D03 `dlg.enable` | HOLDS (design) | `unit/api/test_user_admin_routes.py::test_enable_no_regrant`, `::test_reenable_cancels_a_pending_purge`; M:1648 | — | UL-F rows |
| D03 `dlg.mfa_reset` | HOLDS for "nothing is cancelled or flattened"; the sign-out half WAITING (no named test) | `test_step_up_router.py::test_reset_never_calls_oms_cancel_or_flatten`; M:1678 | SR-025 | — |
| D03 `dlg.revoke`, `dlg.reissue` | HOLDS (design) | `test_invites_router.py::test_revoke_and_reissue_invalidate_old_link`; M:1666, :1672 | — | — |
| D03 `ud.demotion` | HOLDS at the pin; re-verify when E35-T11 binds | M:1690 | — | AD-E06 |
| D03 `unbind.*` | HOLDS (design) | the contract as D03 cites it; M:1660 | SR-029 | — |
| D03 `va.*` (view-as) | WAITING (blocked on #1134) | — | SR-E42-03 | AD-E04 |
| D03 `band.*`, `gate.*`, `strip.locked`, `strip.unlock_again`, `announce.admin_*`, `save.*_locked` (variant (a)) | N/A as built (D8 ruled per-action step-up); A-copy-2 | S01 renders `band.grace` only | SR-E42-12 | AD-E01, AD-F06 |
| D04 §7 `tamper.*` | HOLDS (design); as built WAITING (blocked on #1135) | the verify runner the design cites | SR-066, SR-068 | AD-T02 |
| D04 `audit.append_only`, `rec.immutable` | FINDING: E42-R-17, Low, copy, open (known, routed to #1238); `rec.immutable` as built WAITING (blocked on #1135) | `test_audit_guard_cv_app.py::test_cv_app_cannot_rewrite_audit_history`, `::test_cv_app_cannot_defeat_the_audit_guard` | SR-066 | AD-T02, AD-F14 |
| D04 §8 `export.*` | FINDING: E42-R-16, Low, copy, open; the rest WAITING (blocked on #1135) | M:37 | SR-E42-08 | AD-I rows |
| D04 §9 `flags.*`, `dlg.flag.*`, `dlg.engage.*`, `dlg.release.*` | HOLDS for the 17 listed flags; FINDING: E42-R-15, Low, copy, open | `unit/admin/test_flag_catalogue.py`; `test_flag_maintenance.py::test_the_order_kill_switch_also_engages_the_gate`; M:124, :130 | SR-E42-07 | AD-E03 |
| D04 §10 `maint.list`, `maint.stays`, `dlg.maint_on.*`, `dlg.maint_off.body` | HOLDS (design) | `test_flag_maintenance.py::test_entering_maintenance_cancels_algos_and_notifies_once`, `::test_the_recorder_pauses_only_when_keep_recorder_is_false`, `::test_orders_are_refused_within_200_ms_of_the_write`; M:130 | — | — |
| D04 `maint.fail_closed`, `banner.maintenance_fail_closed` | HOLDS (design) | `unit/admin/test_flag_resolver.py`; M:124 | — | AD-D02 |
| D05 `backup.dl.warning`, `dl.who`, `dl.ready`, `dl.close_warning`, `dl.expired` | HOLDS (design); as built WAITING (blocked on #1024) | `test_backup_fetch.py::test_a_link_serves_once_then_is_410_with_one_link_reused_record`, `::test_an_expired_link_never_spent_is_410_with_no_record`, `::test_a_link_lives_no_longer_than_a_read_only_window`; M:85, :91 | — | AD-I04 |
| D05 `backup.del.*`, `admin.last_backup` | HOLDS (design) | `unit/storage/test_backups_sqlalchemy.py::test_counts_as_usable_is_a_verified_status_with_verified_at_and_no_deleted_at`; `test_admin_backup_delete_router.py::test_the_last_verified_backup_of_a_kind_is_409_last_usable_backup`; M:79 | SR-095 | — |
| D05 §8.2 `restore.impact.*`, `restore.positions.*` | WAITING (blocked on #3084, D7); route M:97 `not_mounted` | the service guard, `test_restore_guard.py::test_maintenance_off_is_409_maintenance_mode_required_and_creates_no_job` | SR-E42-04 | AD-E07, AD-R05 |
| D05 `machine.ack.*` (latch) | WAITING (blocked on #1137); its acknowledge route is not in `M` | — | — | — |
| S01 as built (`apps/web/src/features/admin/overview/copy.ts`) | HOLDS: the strings match D03/D04/D05; withdrawal, tamper, break-glass, drift and backup strip items stay out until their sources exist (CG-7, CG-8) | the S01 unit suite on `main` | — | — |
| S01 shell: no admin window, no countdown | HOLDS | `apps/web/src/features/admin/shell/AdminArea.tsx` (per-action step-up); `packages/ui/src/components/AdminLayout.tsx:20-21` (the grace line only) | SR-E42-12 | AD-T10 |

Copy changes owed (the owners are the design tickets; A-copy-3 to A-copy-6 are the public form of E42-R-14 to
E42-R-17):
- **A-copy-1** (ruling, "Add"): `docs/plan/14-screens-catalogue.md` SCR-149, cited by the ruling at `:3062` and at
  the pin at `:3074-3084`. The Type line (`:3076`, "admin token is older than 15 minutes … unlock for 15 minutes
  of activity"), the A11y line (`:3078`, "for how long the resulting token is valid"), the Performance line
  (`:3079`, "the token's TTL (15 min) is server-issued") and the `:3084` checklist items ("token's validity
  window", "countdown/freshness indicator") still describe the retired window, against the `:3082` "Retired under
  D8" line. Rewrite them to the per-action step-up text of `:3082`, or mark the entry retired.
- **A-copy-2**, E42-D03 §14: mark the variant (a) keys retired under D8 (`band.unlocked`, `band.left`,
  `band.left_final`, `band.locked`, `strip.locked`, `strip.unlock_again`, `announce.admin_5min`,
  `announce.admin_1min`, `announce.admin_locked`, `gate.body`, `gate.body_held`, `gate.cancel_note`,
  `save.not_saved_locked`, `save.locked_hint`), so no later story builds a promise of a window the server does
  not hold.
- **A-copy-3** (E42-R-14), E42-D03 `dlg.delete`: say what Delete also does now (it signs the user out, removes
  their account access and disarms their rules), and that Enable, which cancels the deletion, restores neither
  access nor rules (matching `dlg.enable`).
- **A-copy-4** (E42-R-15), E42-D04 §9: the group table and the "Affects order entry" notes list 17 flags, the
  registry at the pin has 19. Add `trading.oms_enabled` and `trading.trade_groups`, each with a group, the
  "Affects order entry" note and a consequence line in its Change dialog.
- **A-copy-5** (E42-R-16), E42-D04 `export.dlg.pii`: name all the personal data in the file (actor names and
  addresses, session ids, free-text reasons; personal fields in before/after states are hashed), not only actor
  IP addresses.
- **A-copy-6** (E42-R-17), E42-D04 `audit.append_only` and `rec.immutable`: scope the claim to what the
  application guarantees, consistent with `tamper.failed.meaning`, for example "Nothing in CandleViewer can edit
  or delete this record; a tamper check detects a change made outside it." Catalogue item C5 stays met. This
  is how `rec.immutable` holds as built given the accepted AD-T02 / AD-F14 residual (ruling, "Add").
- **Carry, restore "today" copy** (WAITING on #3084): if the restore route mounts before the security list
  (CG-7), `restore.impact.security_today` states outright what a restore brings back, per TM §6 (known, routed to
  #3084, AD-E07).

## 5. SAST/SCA triage

Configuration at the pin: `_job-security.yml` runs under `pr.yml` on `pull_request` and `merge_group`. Semgrep runs
the registry packs (`p/python`, `p/typescript`, `p/react`, `p/electron-desktop-app`, `p/docker`,
`p/github-actions`, `p/secrets`, `p/owasp-top-ten`, `p/sql-injection`, `p/jwt`, `p/insecure-transport`) plus the 65
`.semgrep/cv-*.yml` rules, whose fixtures run first; the auth pack (`security/semgrep/auth/`, 10 rules) runs in the
security-auth step with its suppression policy. Bandit runs with tests excluded at `-ll`; CodeQL with
`.github/codeql/codeql-config.yml`; pip-audit and `pnpm audit` are gated by `tools/ci/security_gate.py`.

<!-- prettier-ignore -->
| Check | Verdict | Evidence (run 41821199189) | 04 SR | TM row |
| --- | --- | --- | --- | --- |
| The SAST gate (registry packs plus the 65 `cv-*` rules) green on `main` | HOLDS | job 126548559980 | SR-156 | AD-E11 |
| Bandit | HOLDS | job 126548559980 | SR-156 | — |
| CodeQL, gated by `tools/ci/security_gate.py` | HOLDS | job 126548559725 | SR-156 | — |
| pip-audit on the locked `services/api` requirements | HOLDS | job 126548559669 | SR-130, SR-156 | — |
| `pnpm audit` | HOLDS | job 126548559669 | SR-156 | — |
| Licence allowlist and the freeze-manifest check | HOLDS | job 126548559669 | SR-130, SR-136 | — |
| The secrets scan (tree and history) | HOLDS | jobs 126548559832, 126548559789 | SR-142, SR-146 | — |
| Container scan | HOLDS | job 126548559712 | SR-131 | — |
| Every suppression under `admin/`, `auth/`, `audit/`, `api/` carries a reason | HOLDS | read at the pin; the suppression-policy step in job 126548559669 | SR-156 | — |
| Accepted-risk entries touching E42 code still key to the code they accept | HOLDS | `security/accepted-risks.yaml:97`, :109, :116 match `auth/login_service.py:126`, `auth/mfa_service.py:119`, `api/exchange_keys.py:365`; the register-pins step in job 126548559669 | SR-156 | — |
| The flag-lookup rule: fixtures, zero hits, a planted violation red | HOLDS (§1.6); enforcement open on E42-R-07, E42-R-10 | job 126548559980; §1.6 | SR-156, SR-E42-07 | AD-E03 |

Triage of the annotations under `services/api/candleviewer/{admin,auth,audit,api}` (40 in all; there is no
`users/` package, the user routes are `api/users.py`). No finding is suppressed without a reason, and there is no
`# nosec` and no bare suppression in scope.
- **Auth-pack `nosem:` (24)**, each with reason, owner and review date: `api/profile_writes.py:369`, :422, :474,
  :503; `api/profiles.py:199`, :219, :237; `api/exchange_accounts.py:466`, :603, :684, :915; `api/exchange_keys.py:335`,
  :398, :455; `api/scanner.py:443`, :451, :462; `api/indicator_presets.py:327`, :335, :346; `api/view_as.py:214`, :392;
  `api/users.py:905`; `api/csrf.py:194`. Review dates run 2027-03-25 to 2027-04-15.
- **Due soonest, before the R3 gate:** three `no-adhoc-authz` entries reviewed by **2026-12-31**:
  `api/instruments.py:93`, `api/market.py:129`, `audit/access.py:96`.
- **`nosemgrep` (1):** `api/oms_reads.py:389` (`cv-no-debug-probe-in-prod`), with reason, owner and review
  2027-04-27.
- **`noqa` with a code and a reason:** `auth/models.py:110` (S105, reviewed 2027-03-25), `admin/breakglass.py:411`
  (UP046), `auth/hashing.py:48` (E501, an encoded hash cannot be wrapped), and the E501s on suppression lines.
- **Hygiene, not a finding:** `noqa: E501` with no reason of its own on `api/instruments.py:93`, `api/market.py:129`,
  `audit/access.py:96` and `api/oms_reads.py:389`; each sits on a line whose suppression carries a reason.
- **`type: ignore[...]` (7)** and **`pragma: no cover` (2)**, each with a reason: `admin/http.py:70`,
  `admin/flags/push.py:35`, `admin/flags/maintenance.py:57`, `admin/ops/incidents.py:84`,
  `admin/overview/fanout.py:61`, `api/order_entry_gate.py:84`, `api/openapi_publish.py:112`; `api/audit.py:912`,
  `audit/actions.py:441`.
- **Exceptions:** `security/accepted-risks.yaml` holds 22 entries, none expired at 2026-11-04. The four in
  E42-adjacent code (the three CodeQL hashing entries above and the `0002_rbac_seed.py:146` bootstrap print) expire
  2027-03-25. Cross-cutting watch: one dependency entry expires 2026-11-14 and ten on 2026-11-20; none is a
  runtime dependency of `services/api`.

## 6. DAST, drills and the repeatable checks

<!-- prettier-ignore -->
| Item | Where it runs | State at the pin |
| --- | --- | --- |
| ZAP admin profile: role matrix (Viewer, Manager), the Owner's purge refusals with no step-up | `.github/workflows/dast-admin-nightly.yml` (E42-X03, #1026), plan `.zap/admin-surface.yaml`, baseline `.zap/admin-surface-baseline.json`; low-privilege roles through `_dast-low-priv.yml` | merged, nightly; the last green run on `main` is read at the sign-off (§8) |
| Semgrep rules for the admin area: `cv-admin-no-flag-lookup`, `cv-admin-route-guarded`, `cv-admin-mutation-audited`, `cv-admin-no-secret-log`, with fixtures under `.semgrep/tests/` | CI `security / semgrep-bandit` | merged and green (job 126548559980); the flag rule mutation-probed (§1.6) |
| RBAC assertion tests: the route matrix and the per-cell suites | `contract/rbac/test_route_matrix.py`; `tests/security/admin` | merged and green (§1.1) |
| Abuse cases AC-ADM-01..35, UL-AC01..16 | `tests/security/admin`, `tests/integration/admin` (E42-X03) | merged; X02 re-read the verdicts, carries below |
| Append-only, chain order and the last-owner races on a real Postgres session | CI integration lane, shards 1–4 | green at the pin (run 41821199189) |
| The disable-user drill (SR-029) | `security/auth/test_disable_user_drill.py` | green |
| The restore drill | `test_restore_drill.py:204` | consistency only; D7's cases WAITING on #3084 |
| This PR's new pins, each mutation-checked | `security/admin/test_elevation_client_expiry.py:49`; `unit/storage/test_postgres_server_log.py:80`, :90, :96 | green; each named mutant turns it red (§1.3, §1.5) |
| The staged DAST pass and the pen-test | E43 | out of scope; this record is its input |

Carries to the abuse-case owner (E42-X03, #1026; `AC` is not edited here):
- AC-ADM-14: the fixtures and zero hits are met; its enforcement verdict follows E42-R-07 and E42-R-10.
- AC-ADM-30: becomes "200; `test_admin_http.py:288` pins it" under D8 as ruled.
- UL-AC12, UL-AC13: met by #2650 (`test_user_purge_pg.py::test_users_anonymise_ahead`,
  `::test_reenable_racing_reaper_keeps_user`; `test_user_purge.py::test_reenable_racing_reaper_keeps_user`).
- UL-AC15: the unbind's open-order count still needs an owner after #2648 closed (UL-F9).

Public-safe pins proposed by the areas, all for guarantees that hold (none is in this PR): a generated-table test
that every served `/admin`, `/users`, `/invites`, `/me/sessions`, `/auth/step-up`, `/auth/session/view-as` and
`/health` operation has an `M` row matching its `x-rbac`; G-router membership by route list; a static lock-order
check over the owner-only lifecycle store methods; `PATCH`, `PUT /roles` and `DELETE` refusing a self-target
before any store call; the restore guard refusing with maintenance off even when every acknowledgement is sent;
a backup link presented with another user's bearer is unknown and unspent; the import of `candleviewer.main`
failing on a denied flag definition; the flag rule's `paths.include` scope pinned.

## 7. Residuals and re-ratings

No rating moves in this review (TM O7). D2 is not adopted, so no OE row changes band (§3).

<!-- prettier-ignore -->
| Row | Residual at the pin | Level | Disposition / review |
| --- | --- | --- | --- |
| AD-E01 (AD-F06) | D8 ruled per-action step-up: admin reads need no fresh re-auth; SCR-149 amended (A-copy-1) | Medium | accepted under RR-17 (disposition A); review when ADR #1085 records D8, and by 2027-02-25 |
| AD-E12 | One `users` or `flags` grace grant allows further writes of its class for 5 minutes, each recorded | Medium | accepted; review when the D8 ADR lands, or 2027-02-04, whichever first |
| AD-S05 | A stolen or unattended Owner session drives the admin area | Medium | not accepted; D8 ruled and #3085's server side landed; the re-rating is the sign-off's (§8) |
| AD-S05, AD-I05, AD-E04 | view-as rows after #3085 | unchanged | the re-rating is the sign-off's |
| AD-T02 (AD-F14) | The owner role or a superuser can rewrite audit history consistently until #1238 | Medium until #1238 | accepted (RR-17); the copy of E42-R-17 rests on it and does not re-rate it |
| AD-R04 (AD-F26, AD-F27) | Chain order rests on READ COMMITTED and `CACHE 1` | Low | known; `CACHE 1` pinned by `test_audit_repository.py:263` |
| AD-R05, AD-E07 | Restore rolls back security state | High until #3084 | no restore route can mount before D7, so not an open residual and not accepted |
| AD-D03 | The export, link and fetch hourly limits are in-process, as AD-D09 says of `createBackup` | unchanged | recorded for the TM re-read; the measured cross-check WAITING on #1216 |
| AD-T01 (BQ-10) | "Recorded" is the Postgres server-log line for v1 | — | accepted under the sign-off; AD-F08's alert (#3196) is the complement |

The TM rows made stale by later merges (the six new routes, AD-E10 since #5265, the AD-F04, AD-F07, AD-F17 and
AD-F22 states, the D8 restatement in §5.2 and SR-E42-12, the moved cite at TM :446 to `test_audit_repository.py:126`)
and `04` §5.15 (:606, :609, :614-615, :622) are corrected in this PR's model re-read, not in this record.

## 8. Sign-off

> **PENDING.** Under the delegation (#1778, as on #494 for E16-X02) the Security-engineer sign-off is the
> orchestrator's: PASS, PASS WITH CONDITIONS or FAIL, posted on #1220 and on the epic #63, with its conditions
> named. D2 (§3) and the BQ-10 acceptance (§1.5) are decided under it.

Verdict of record: _(left for the sign-off)_

Inputs for the sign-off: §2's seventeen open findings and their dispositions (the details in the private record);
§7's AD-S05, AD-I05 and AD-E04 re-ratings; the last green `dast-admin-nightly` run; and the re-pin when #1134,
#1135 and #1024 merge. Owner items stay on #2701: D7, D8's ADR (#1085) and RR-17. The independent reviews of this
PR (an Opus security lens and a `code-reviewer` pass, ruling BQ-7) are recorded on the PR.

## 9. Gherkin and Definition of Done

<!-- prettier-ignore -->
| Acceptance criterion | Verdict | Where |
| --- | --- | --- |
| Every admin route is accounted for: a declared permission, deny-by-default, an audit entry on success and on denial; a route missing one is a finding | permission, deny-by-default and the denial record HOLD on every served route (one known, #2836); the success record: E42-R-01, E42-R-02 (open) | §1.1, §1.2 |
| The audit log is immutable in practice, not just in intent | HOLDS, as amended below | §1.5 |
| No flag can weaken a security control | startup fails: HOLDS; "no auth, RBAC or audit module contains a flag lookup": open on E42-R-07, E42-R-10 | §1.6 |
| Elevation cannot be extended by the client | HOLDS, as amended below | §1.3 |
| (failure) A destructive path missing a precondition: restore with maintenance off is refused regardless of the UI | HOLDS at service level; the route WAITING on #3084 | §1.8 |
| All Critical/High findings closed or accepted with Owner sign-off before the epic closes | none is Critical or High | §2 |
| Security sign-off comment on this ticket and the epic | PENDING | §8 |

AC text amendments (notes; the plan JSON is the orchestrator's, who edits it when this record lands):
- **Gherkin 2** (ruling BQ-10): "Given a direct database connection as the application role, When UPDATE and DELETE
  are attempted on audit_log, Then both fail on grants; And, as a privileged role that holds the privilege, both
  fail on the trigger; And the refused statement is recorded as the ERROR and STATEMENT lines of the Postgres
  server log, accepted for v1 under the security sign-off, with AD-F08's alert (#3196) as the tracked
  complement." A refused statement rolls back, so it can leave nothing in the chain itself.
- **Gherkin 4** (ruling BQ-9, D8 ruled): "When a client sends an expiry for the step-up grace window in a body, a
  header or a cookie, or extends its session, Then the window stays where the server fixed it at grant, And the
  next dangerous write after it lapses is answered 403 step_up_required and recorded as auth.step_up_required."
  "Admin token TTL" reads as the per-class step-up grace window; there is no admin token.

<!-- prettier-ignore -->
| Definition of Done item | State | Where |
| --- | --- | --- |
| Findings recorded with STRIDE category, likelihood/impact and disposition | recorded; for open findings the STRIDE and L×I are in the private record until fixed (ruling BQ-3); dispositions are the sign-off's | §2, §8 |
| Every Critical/High finding has a linked remediation ticket, Done before the epic closes | none is Critical or High | §2 |
| Controls traced to `04` requirement ids | each verdict row names its SR id; SR-E42-01..16 traced in §1.10 | §1 |
| Automated checks (Semgrep, ZAP, RBAC assertion tests) merged and running in CI | merged and running: four `cv-admin-*` rules, `dast-admin-nightly`, the route matrix and the admin suites, and this PR's three new pins | §6 |
| Security-engineer sign-off comment on this ticket and on the epic | PENDING | §8 |
