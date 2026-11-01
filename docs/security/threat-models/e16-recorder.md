# E16 — STRIDE threat model: Recorder and storage subsystem

- Ticket: E16-X01 (issue #407)
- Owner: Security engineer (CODEOWNER)
- Status: Draft - pending owner approval (Agent-delivery adaptation: Security/Architect/backend-lead sign-off is replaced by owner approval, recorded in section 9)
- Extends `docs/plan/04-security-program.md` section 5.8 (S1-S6) and `docs/security/threat-models/E07-storage.md` (S10-S21, storage tier). Threat ids here are prefixed `R-` to avoid collision.
- Classification of this document: internal (it enumerates weaknesses; no credentials or host details).

## 1. Scope and assumptions

Components modelled (data model: `docs/plan/21-database-schema.md` section 3.6, migration `0007_recorder`, E16-T01; policy: ADR-0015):

<!-- prettier-ignore-start -->

| Id | Component | Ticket | Role |
| --- | --- | --- | --- |
| C1 | `RecordingPolicy` | E16-T02 | Computes the effective recorded set (explicit list + open chart + open position), 60 s grace, auto-record triggers |
| C2 | `StreamWriter` | E16-T03 | Batched QuestDB ILP writes, bounded 1 GB WAL spill and recovery |
| C3 | `RetentionManager` | E16-T06 | Policy resolution, dry-run preview, reaper, purge |
| C4 | `RollOffJob` | E16-T05 | Verified hot-to-cold Parquet export, weekly compaction |
| C5 | `DiskBudget` | E16-T07 | Measured growth, projection, disk-pressure ladder (75/80/90 %) |
| C6 | Archive importer | E16-T10 | Resumable bulk import of Bybit public trade archives |
| C7 | `recording` REST surface | E16-T08 | `/admin/recorder/*` (OpenAPI tag `recording`), permission 51 `recording:write` |
| C8 | `recorder` WS topic | E16-T08 | Status/progress fan-out to the web app |

Attacker model (all four are modelled):
- **A1** lower-privileged authenticated user (Viewer, or Manager outside their scope).
- **A2** compromised browser session of any role.
- **A3** malicious or corrupted remote archive (Bybit public archive, or an archive substituted in transit/at rest).
- **A4** operational mistake by the Owner (mis-set retention, wrong env flag, import of a huge range).

**Explicit assumption:** the product is reachable only over Tailscale (TB-1, `04-security-program.md` section 4). An unauthenticated internet attacker reaching the API is NOT modelled. If the network boundary changes (public exposure, shared tailnet), this assumption must be re-examined and this model re-run.

Out of scope: implementing controls (becomes work on E16-T02/T03/T05/T06/T07/T08/T10), the shipped-code review (E16-X02), the pen-test (E43).

## 2. Data-flow diagram and trust boundaries

Boundaries follow `04-security-program.md` section 4 (TB-1 browser/Tailscale to API, TB-3 backend to data stores, TB-7 backend to Bybit).

```text
 Browser (A1/A2) --TB-1--> [C7 REST /admin/recorder/*] --RBAC+step-up--> [C1 RecordingPolicy]
        ^                          |                                        |  chart-open / position signals
        |  TB-1                    v                                        v
 [C8 WS topic recorder] <---- status ---- [C5 DiskBudget] <--measure-- (recording volume V-REC)
                                           |  pause/resume ladder
 Bybit WS/REST --TB-7--> bus --> [C2 StreamWriter] --ILP (TB-3)--> QuestDB hot  (V-REC)
                                   | spill (bounded WAL, V-REC)
                                   v
 [C4 RollOffJob] --verify+atomic rename--> Parquet cold (V-REC) + checksum manifest
 [C3 RetentionManager/reaper] --audited delete--> hot partitions / Parquet files
 Bybit public archive (A3) --TB-7--> [C6 importer] --staging dir--> verify --> hot/cold
 All destructive actions --write-ahead--> audit log (Postgres, hash-chained, volume V-OS)
```

Key structural facts: recorded data lives on a volume (V-REC) separate from the OS/Postgres/audit volume (SR-096); `recording_sessions`, `recording_gaps`, retention policy and pins live in Postgres (audited), data lives in QuestDB/Parquet.

## 3. Rating scale

L = likelihood, I = impact (H/M/L). Risk: Critical (H/H), High, Medium, Low. Residual is after the listed control. "Detect" names the metric/audit event that would reveal the threat (SR-125); "none" is recorded where no detection exists.

## 4. STRIDE enumeration

New requirements are named `E16-FR-nn` and are raised as findings against the owning ticket (section 7). Existing controls: SR-094 (checksum manifest), SR-096 (storage guard), SR-097 (no user paths), SR-099 (pins honoured, dry-run, audited deletes), SR-125 (security metrics), SR-154 (chaos incl. disk-full), permission 51 (`recording:write`, Owner + step-up).

### 4.1 Spoofing

| T | Comp | Threat | A | L | I | Risk | Control | Residual | Detect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R-S1 | C1, C7 | Forged auto-record trigger: a chart-open signal for a symbol the actor cannot otherwise record (or for a symbol outside the instrument registry) | A1, A2 | M | M | Medium | Triggers derive server-side from the authenticated WS subscription/position state, never from a client-supplied "record" flag (C-12.4); symbol validated against the instruments registry; **E16-FR-01** server-side per-session cap on distinct auto-record symbols (`CV_RECORDER_MAX_AUTO_PER_SESSION`, default 20) and start rate (`CV_RECORDER_AUTO_START_RATE_PER_MIN`, default 10), keyed by the server-side session id the caller passes (`RecordingPolicy.on_chart_opened`) | Low | `recorder_auto_record_started_total{reason}`; audit `recording.auto_start` |
| R-S2 | C7 | Session replay / stolen cookie used to call recorder endpoints | A2 | L | H | Medium | Session binding + TOTP (ADR-0010); destructive calls need fresh step-up (permission 51) | Low | step-up failure metric (SR-125) |
| R-S3 | C6 | Archive host spoofed (DNS/redirect) to serve attacker data as a Bybit archive | A3 | L | M | Low | Allow-listed archive host, TLS verification, no redirects off-host; **E16-FR-02** | Low | `recorder_import_rejected_total` |
| R-S4 | C8 | Client subscribes to another user's recorder topic | A1 | L | L | Low | Server-side topic ACL on subscribe (C-12.4) | Low | WS permission-failure metric |

### 4.2 Tampering

| T | Comp | Threat | A | L | I | Risk | Control | Residual | Detect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R-T1 | C3, C7 | Retention policy edited (e.g. `hot_days=0`, un-pin) so deletion removes data; or gap rows edited/deleted so absent data appears present | A1, A2, A4 | M | H | High | Policy mutation Owner-only + step-up; policy change and resulting deletion are separate audited steps with dry-run preview; `recording_gaps` is append-only for the app role apart from the kline backfill marker (no DELETE grant, C-5.7); coverage is recomputed from stored data, never trusted alone (**E16-FR-03**: hot-tier coverage of `trades`, `orderbook_delta` and `tickers` is reconciled with the minutes that hold rows and fails closed; residual: the cold tier is trusted via its watermark and manifest, sparse streams are not reconciled, and narrowing the backfill marker's write to its own columns is a follow-up on #1739) | Low | audit `recording.policy_change`; `recorder_coverage_reconcile_mismatch_total{stream}` |
| R-T2 | C6 | Archive file substituted between download and import (TOCTOU) | A3 | M | H | High | Download to private staging dir, hash computed once and verified against the published checksum, import reads only the verified staged file (**E16-FR-04**); imported rows tagged `source=import` | Low | `recorder_import_checksum_fail_total` |
| R-T3 | C4 | Parquet partition silently rewritten after export; manifest regenerated from stale checksum | A2 | L | M | Low | Partitions immutable, atomic rename, manifest written after rename, read refuses mtime after manifest (E07 S14, SR-094) | Low | weekly scrub failure |
| R-T4 | C2 | Spilled WAL file edited between spill and replay | A1 | L | M | Low | WAL directory 0700, owned by the backend user, per-record CRC, replay rejects corrupt frames and records a gap | Low | `recorder_wal_corrupt_frames_total` |
| R-T5 | C1 | Auto-record state flipped to "explicit" to dodge retention pressure | A1 | L | M | Low | `source` column set only by the policy service; DTOs `extra="forbid"` | Low | audit |
| R-T6 | C1, C2 | Cross-env session access: one env's process (demo, testnet) closes, gap-marks or counts another env's open recording session in the shared database, e.g. crash recovery closing a live session as `process_restart` (C-2.11) | A4 | M | H | High | Every session read and write on the recorder's path joins `recorded_symbols` and binds its env (E16-F01 S3d); `SessionConfig.env`, `WriterConfig.env` and `SessionManager`'s config are required, with no env default anywhere on the path; the composition builds the policy, session and writer envs from `settings.environment` and a wiring test proves they agree (S4b) | Low | audit `recorder.stop` carries its env; `recorder_gap_seconds_total` |

### 4.3 Repudiation

| T | Comp | Threat | A | L | I | Risk | Control | Residual | Detect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R-R1 | C3, C7 | Deletion (purge, reaper, pin removal) without an attributable audit entry | A2, A4 | M | H | High | Audit record is written **before** the delete (write-ahead, C-2.9): actor, role, scope, row/file counts, reason; delete aborts if the audit write fails (fail closed); reaper actions carry actor `system:reaper` with the policy version | Low | audit-chain verification (SR-125); alert on delete without matching audit id |
| R-R2 | C3 | Audit entry lost because the data it described was deleted first (audit stored with the data) | A4 | L | H | Medium | Audit lives in Postgres hash-chained on V-OS, not on V-REC; retention deletions never cascade to audit (ADR-0015 point 9); **E16-FR-05** test that purging a symbol leaves its audit rows | Low | chain verification |
| R-R3 | C6 | Import of unattributed data into the record | A4 | M | M | Medium | Import job row records actor, archive URL, checksum, range; imported rows distinguishable | Low | audit `recording.import` |

### 4.4 Information disclosure

| T | Comp | Threat | A | L | I | Risk | Control | Residual | Detect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R-I1 | C7 | Storage responses leak host filesystem paths, volume names or mount points to a Viewer | A1 | M | M | Medium | Responses expose logical ids (dataset/symbol/tier) only (SR-097); RFC 7807 errors strip paths and OS error text; **E16-FR-06** contract test asserting no `/` or drive-letter strings in recorder DTOs for non-Owner | Low | none (test-only) |
| R-I2 | C7, C8 | A Viewer sees which symbols the Owner records or open positions (recorded set reveals trading interest) | A1 | M | M | Medium | `recording:read` limited by role; auto-record entries derived from positions are visible to Owner/scoped Manager only (**E16-FR-07**) | Low | none |
| R-I3 | C2, C6 | Logs include raw payloads, paths or archive URLs with tokens | A1, A2 | L | M | Low | Redaction filter (C-12.6); raw-payload store redacted, 7-day TTL | Low | log-scan CI |
| R-I4 | C4 | Cold Parquet readable by other local users | A1 | L | L | Low | Recorded content is public market data (low sensitivity); dir 0750 backend user | Low | none |

### 4.5 Denial of service

| T | Comp | Threat | A | L | I | Risk | Control | Residual | Detect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R-D1 | C5, C2 | **(Critical, = 04 section 5.8 S2)** Unbounded recording fills the disk, taking the backend and trading down | A4, A1 | H | H | **Critical** | SR-096: recorded data on separate volume; alert 75 %, auto-pause of non-pinned recording at 90 %, trading unaffected when V-REC is full; retention 30 d; per-symbol caps. Tested by the disk-pressure chaos test in **E16-Q04** (SR-154) | Low | `recorder_disk_used_ratio` alert 75/80/90 % |
| R-D2 | C1, C7 | **Aggregate path:** one Viewer opening many charts is individually legitimate but collectively a disk/ILP DoS via auto-record | A1, A2 | H | H | High | 60 s grace period; **E16-FR-01** cap on concurrent auto-recorded symbols (`CV_RECORDER_MAX_AUTO_SYMBOLS`, default 20; manual and position starts never refused by it; an admission cap: no new chart-open start past it, and only a manual entry or position ending under an open chart, or a restart, takes the count over it, never chart opens alone) and a global auto-record budget in `DiskBudget`; auto-recorded + unpinned are first shed; rate-limited start per session (`CV_RECORDER_AUTO_START_RATE_PER_MIN`); per-session denial audits at most 10 a minute | Low | `recorder_auto_record_active` gauge; `recorder_auto_record_refused_total{cause}`; alert when cap hit |
| R-D3 | C6 | Large or hostile import (huge range, decompression bomb) exhausts disk | A3, A4 | M | H | High | Pre-flight size estimate against remaining budget; refuse if projected usage > 80 %; streaming decompress with a ratio and absolute size limit; staging on V-REC under quota; resumable and cancellable; **E16-FR-08** | Low | `recorder_import_bytes_total`; pause ladder |
| R-D4 | C2 | WAL exhaustion: QuestDB down, spill grows | A4 | M | H | High | WAL bounded at 1 GB (ADR-0015 point 8); beyond bound lowest-priority symbols stop first; conservative QuestDB commit-lag (E07 S10); the bound has a performance cost and MUST NOT be optimised away without security review | Low | `recorder_wal_bytes`; alert at 75 % of bound |
| R-D5 | C3 | Reaper starvation: a permanently held read lease (replay/export) blocks partition drop so the disk never shrinks | A1, A2 | M | H | High | Leases carry a TTL (default 1 h), heartbeat-renewed only by live sessions; reaper force-releases expired leases and logs it; **E16-FR-09** reaper priority independent of readers | Low | `recorder_reaper_blocked_partitions` alert |
| R-D6 | C3, C4 | Roll-off/compaction I/O starves live ingestion | A4 | M | M | Medium | Off-peak schedule, I/O rate limit, atomic rename (E07 S16); sampling cadence has a perf cost and must not be tuned away without review | Low | ingestion lag metric |
| R-D7 | C7 | Repeated dry-run/preview or status calls hammer storage metadata | A1, A2 | M | L | Low | Per-user rate limits, cached projections. The recorded-set writes allow 30 a minute per user, admitted once the key, body, query and path id parse and before any store or audit effect (#4868): a malformed request answers 422 or 404 and spends no budget. Its parse cost is bounded by the 4 096-byte body cap, refused with 413 before any parse, and reachable only by an authenticated `recording:write` actor | Low | rate-limit rejection metric |
| R-D8 | C8 | WS topic flood to slow clients | A1 | L | L | Low | Bounded per-client queue, coalesced progress frames (C-2.18) | Low | WS desync rate |

Disk-pressure acceptance thresholds (for E16-Q04): at 75 % an alert fires; at 90 % the recorder pauses non-pinned recording within 60 s; pinned data is never deleted; the order path (submit, cancel, SL) stays functional with V-REC at 100 %; recording resumes only below 85 % (hysteresis).

### 4.6 Elevation of privilege

| T | Comp | Threat | A | L | I | Risk | Control | Residual | Detect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R-E1 | C7 | Viewer or Manager reaches `recording:write` / purge without step-up (missing check, IDOR on symbol scope) | A1, A2 | M | H | **High** | Server-side RBAC on every route (C-12.4); permission 51 is Owner + step-up only; every endpoint test includes forbidden-role and cross-scope cases; E16-X02 reviews | Low | permission-check failure metric |
| R-E2 | C3 | Purge scope widened by client params (wildcards, empty symbol = all) | A1, A2 | M | H | High | Strict pydantic (`extra="forbid"`), explicit enumerated scope, empty/wildcard rejected, dry-run token bound to the exact scope and expiring (**E16-FR-10**) | Low | audit |
| R-E3 | C5, C7 | `CV_TEST_CLOCK` or `CV_ALLOW_SHARED_VOLUME` reachable in production, defeating retention timing or the volume-separation guard (SR-096) | A4 | M | H | High | Startup refuses to boot when either is set and `CV_ENVIRONMENT` is live/demo; flags never read from request input; **E16-FR-11** unit test of the startup guard (`services/api/tests/unit/test_e16_fr11_startup_guard.py`; both refusals are field validators, so the refusal payload carries only the offending field); listed in the deploy checklist | Low | startup failure log; config audit |
| R-E4 | C6, C4 | Path traversal in archive paths (`..`, absolute, symlinks, drive letters, reserved names) writing outside the data dir | A3 | M | H | **High** | See section 5 | Low | `recorder_path_containment_reject_total` |
| R-E5 | C2 | Recorder process runs with rights beyond its volume | A4 | L | M | Low | Dedicated service user; data dirs only | Low | none |

## 5. Path traversal: containment requirements per site

SR-097 forbids user-supplied paths; datasets resolve through a registry. Every filesystem write/delete site must also: resolve the final path, require it inside the configured root (`is_relative_to`), reject symlinks/reparse points in any component, reject absolute paths, drive letters, `..`, NUL and reserved device names, and derive filenames only from validated components (env, symbol `^[A-Z0-9]{2,20}$`, ISO date) - never from archive-provided names.

| Site | Requirement | Test (owner ticket) |
| --- | --- | --- |
| Archive import staging/extraction (C6) | Ignore member names; target built from validated symbol+date; staging dir private to the job | `test_import_rejects_traversal_member_names` incl. `..`, absolute, drive-letter, symlink (E16-T10; AC-08) |
| Parquet export (C4) | Output path built from validated components under the cold root; atomic rename in same dir | `test_export_path_contained_for_hostile_symbol` (E16-T05) |
| Parquet/hot partition deletion (C3) | Targets come from registry ids, re-resolved and containment-checked right before unlink; refuse symlinks; no recursive delete outside root | `test_reaper_never_deletes_outside_root` (E16-T06) |
| REST dataset/symbol params (C7) | No path-like inputs; ids only | `test_recorder_dto_rejects_path_chars` (E16-T08) |

## 6. Abuse-case catalogue (executable by E16-Q01/Q02/Q04)

| Id | Threat | Attack narrative | Expected system response |
| --- | --- | --- | --- |
| AC-01 | R-S1 | Viewer opens a chart for a symbol absent from the registry via a crafted WS subscribe | Subscribe rejected; no recording row; metric shows rejection |
| AC-02 | R-D2 | Viewer scripts opening 200 distinct charts in 5 minutes | Auto-record cap (20) holds, extra symbols live-only with UI note; alert fires; disk growth within budget |
| AC-03 | R-T1 | Manager PATCHes retention to `hot_days=0` | 403; audit failure entry; policy unchanged |
| AC-04 | R-T1 | Owner without fresh step-up submits purge | Step-up required; nothing deleted |
| AC-05 | R-R1 | Force the audit write to fail during purge | Purge aborts, no data deleted, error surfaced |
| AC-06 | R-R2 | Purge symbol X then query audit | Audit entries for X remain and the chain verifies |
| AC-07 | R-I1 | Viewer calls recorder endpoints and provokes errors | No path, mount or OS text in any body; logical ids only |
| AC-08 | R-E4 | Import archive with members `../../x`, `C:\x`, a symlink, and a decompression bomb | Nothing written outside root; bomb stopped at ratio/size limit; clean failure reason |
| AC-09 | R-T2 | Replace the staged archive after download | Hash mismatch, import aborted, file quarantined |
| AC-10 | R-D1 | Fill V-REC to 90 % then 100 % while submitting orders | Recording pauses at 90 % (60 s), alert at 75 %, orders/cancels/SL work, pins intact |
| AC-11 | R-D4 | Stop QuestDB for 1 h under full load | WAL stops at 1 GB, lowest-priority symbols stop first, gaps recorded, replay on recovery |
| AC-12 | R-D5 | Hold a replay lease 24 h at 90 % disk | Lease expires at TTL, reaper frees space |
| AC-13 | R-E2 | Purge with empty symbol / `*` | 422; nothing deleted |
| AC-14 | R-E3 | Start with `CV_TEST_CLOCK` set and `CV_ENVIRONMENT=live` | Boot refuses with a clear error |
| AC-15 | R-D3 | Import a range projected above 80 % of free budget | Refused pre-flight with the projection |

## 7. Findings raised as work

Every threat with no adequate existing control became a ticket against the owning E16 task:

| Finding | Threats | Owning task | Issue |
| --- | --- | --- | --- |
| E16-FR-01 | R-S1, R-D2 | E16-T02 | https://github.com/CandleViewer/CandleViewer/issues/1738 |
| E16-FR-03 | R-T1 | E16-T04 | https://github.com/CandleViewer/CandleViewer/issues/1739 |
| E16-FR-05, -09, -10 | R-R2, R-D5, R-E2 | E16-T06 | https://github.com/CandleViewer/CandleViewer/issues/1740 |
| E16-FR-11 | R-E3 | E16-T07 | https://github.com/CandleViewer/CandleViewer/issues/1741 |
| E16-FR-06, -07 | R-I1, R-I2 | E16-T08 | https://github.com/CandleViewer/CandleViewer/issues/1742 |
| E16-FR-02, -04, -08 | R-S3, R-T2, R-D3, R-E4 | E16-T10 | https://github.com/CandleViewer/CandleViewer/issues/1743 |

Threats with a control but no detection: R-I1, R-I2, R-I4, R-E5 (test-only or none; accepted, see section 8).

## 8. Data classification and residual risk

| Store | Class | Note |
| --- | --- | --- |
| Recorded market data (QuestDB hot, Parquet cold, raw payloads) | public content, internal operational metadata | availability/integrity matter, not confidentiality |
| Coverage/gap metadata, sessions, retention policy | internal, integrity-critical | append-only for app role; reconcilable |
| Audit entries | internal, tamper-evident | hash-chained, on the OS volume, never cascaded |

<!-- prettier-ignore-end -->

Residual risks: all rows Low after controls and findings land. Until the findings ship, R-D2, R-D3, R-E3 stay High. Accepting owner: Owner (repository owner). Performance-costly controls (WAL bound, sampling cadence, lease TTL) must not be removed without security review.

Relax guard (R-I2, E16-T08): an unpin or a lower `retention_days` from a restricted caller on a row that a cause outside the caller's view holds is refused with one constant 403 body whatever the cause, and one denied `retention.change` record names the refusal; that this answer shows a cause outside the caller's view holds the row is an accepted residual of R-I2.

Open item for the owner's security pass (#4868): whether one app-level request-body limit should back every HTTP route, beside the per-operation caps that routes such as the recorded-set writes (4 096 B, R-D7) apply.

## 9. Sign-off

Per the Agent-delivery adaptation, Security engineer / Architect / backend-lead sign-off is replaced by owner approval. Pending: owner approval on this PR. Abuse cases AC-01..AC-15 are handed to E16-Q01 for acceptance as executable.
