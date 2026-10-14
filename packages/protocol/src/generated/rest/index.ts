// ==========================================================================
// GENERATED FILE — DO NOT EDIT BY HAND.
// Regenerate with `pnpm --filter @candleviewer/protocol generate`.
// Source: docs/plan/22-api-openapi.yaml, via openapi-typescript. Hand edits
// are rejected by the header-guard lint
// (packages/protocol/scripts/check-generated-guard.mjs) and by
// `linguist-generated` in .gitattributes.
// ==========================================================================
/* eslint-disable */

export interface paths {
  "/admin/audit": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Query the append-only audit log
     * @description The audit log is hash-chained (`entry_hash = SHA256(prev_hash || canonical_entry)`), so
     *     tampering is detectable. Entries are never updated or deleted; retention is 2 years.
     *     Access follows `04-security-program.md` §7.2.2 row 49 and SR-067: the Owner sees every
     *     entry with raw payloads; a Manager (`audit:read`) sees only entries where it is the actor,
     *     with `detail`, `ip` and `user_agent` removed — the `actor_user_id` filter is forced
     *     server-side to the caller; a Viewer holds no `audit:read` and gets `403`.
     *
     *     Every state-changing API call, every order sent, every key operation, every kill-switch
     *     transition, every login (success and failure) and every rule arm/disarm produces an entry.
     */
    get: operations["queryAuditLog"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/audit/export": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Export an audit slice as signed NDJSON
     * @description Produces a downloadable NDJSON bundle with a detached signature over the file digest, for offline retention. Export itself is audited.
     */
    post: operations["exportAuditLog"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/audit/verify": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Verify the audit hash chain over a range
     * @description Recomputes the chain and reports the first divergence, if any. Run nightly by a scheduled job and on demand from the Admin screen. Owner only (`04-security-program.md` §7.2.2 row 49a): a Manager holding `audit:read` is refused with `403`.
     */
    post: operations["verifyAuditChain"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/backups": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List backup runs */
    get: operations["listBackups"];
    put?: never;
    /**
     * Trigger a backup run
     * @description Backups are always encrypted at rest (age/AES-256) and never contain plaintext API
     *     secrets — the key material is exported only as its wrapped form, so a restore on a host
     *     without the KEK cannot trade. `verify: "true` schedules an automatic restore-into-scratch"
     *     verification after the dump completes.
     */
    post: operations["createBackup"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/backups/{backupId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        backupId: components["parameters"]["BackupId"];
      };
      cookie?: never;
    };
    /** Get a backup run */
    get: operations["getBackup"];
    put?: never;
    post?: never;
    /** Delete a backup artefact */
    delete: operations["deleteBackup"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/backups/{backupId}/restore": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        backupId: components["parameters"]["BackupId"];
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Restore from a backup (owner, step-up)
     * @description Restores into the running deployment. Trading is force-disabled for the duration and must be re-enabled explicitly afterwards, so a restore can never silently resume order flow against stale OMS state (21-database-schema.md section 8.2). Asynchronous.
     */
    post: operations["restoreBackup"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/backups/{backupId}/verify": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        backupId: components["parameters"]["BackupId"];
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Verify a backup by restoring it into a scratch namespace
     * @description Restores into an isolated scratch database/namespace, runs integrity assertions (row counts, hash-chain verification, migration version) and discards it. Never touches live data.
     */
    post: operations["verifyBackup"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/capacity": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Ingestion, storage and rate-budget headroom
     * @description Projects disk exhaustion from the current recorded-symbol set and retention policy (~0.5-0.75 GB/day/symbol at 200-depth) and reports per-UID rate-budget utilisation, so the owner can see a limit approaching instead of discovering it at a rejection.
     */
    get: operations["getCapacity"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/feature-flags": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List feature flags with their resolved values
     * @description Flags gate risky or incomplete surfaces (live trading enablement, node-graph rule editor,
     *     WS order entry, Tauri shell, heatmap v2). Kinds: `boolean`, `percentage` (rollout),
     *     `variant` (string choice). Per-user overrides are supported for staged rollout to the
     *     owner before managers.
     */
    get: operations["listFeatureFlags"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/feature-flags/{flagKey}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        flagKey: string;
      };
      cookie?: never;
    };
    get?: never;
    /**
     * Set a feature flag's value and overrides
     * @description `trading.live_enabled` is special-cased: enabling it requires `reason` and a recorded
     *     pen-test reference (`evidence_url`), per the R4 release gate in `07-release-and-prr.md`.
     *     Without them the call fails with `validation_failed` / `gate_evidence_required`.
     */
    put: operations["setFeatureFlag"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/health": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Full system health report
     * @description Aggregate of every subsystem probe. `overall` is the worst component state. This backs
     *     the System-health screen and the `system` WS topic; Prometheus scrapes the same
     *     underlying gauges from `/metrics` (not part of this API surface).
     */
    get: operations["getHealth"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/incidents": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Open and recent operational incidents
     * @description Read-model over `system_events` at `error` and `critical` severity, grouped into incidents with first/last occurrence and affected component.
     */
    get: operations["listIncidents"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/jobs/{jobId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        jobId: string;
      };
      cookie?: never;
    };
    /**
     * Poll an asynchronous job (refresh, export, backup, verification, simulation)
     * @description Uniform polling surface for every `202`-returning endpoint in this API.
     */
    get: operations["getJob"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/log-level": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    /**
     * Temporarily raise or lower the log level for one subsystem
     * @description Scoped to a closed set of subsystem logger namespaces (never the root logger). The override
     *     self-reverts after `ttl_seconds` (default 900, max 3600) and is deliberately not persisted
     *     across restarts. Audited as `settings.change`; a denied attempt is audited too. Cannot
     *     enable body logging (that stays behind `CV_LOG_BODIES_UNTIL`).
     */
    put: operations["setLogLevelOverride"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/overview": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Admin landing dashboard roll-up
     * @description Counts and headline state across users, accounts, keys nearing expiry, recorder health, storage headroom and open incidents.
     */
    get: operations["getAdminOverview"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/recorder/compact": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Compact Parquet cold-tier partitions
     * @description Merges small files produced by the export job into target-sized partitions (21-database-schema.md section 5.4). Asynchronous; poll `GET /admin/jobs/{jobId}`.
     */
    post: operations["compactRecorder"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/recorder/import": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Import public trade archives into the cold tier (E16-T10)
     * @description Downloads the exchange's public daily trade archives for `symbol` over `[from, to]` (inclusive UTC dates, at most 366 days), verifies each file, and writes trades to the Parquet cold tier. Recorded data wins: rows inside a recorded window are discarded and reported. Imported windows are labelled archive-derived and cover `trades` only. Resumable and idempotent per day: a re-run skips finished days. Asynchronous; poll `GET /admin/jobs/{jobId}` (`kind: archive_import`); `result` carries the import summary. One import at a time (409 `job_running`). Audited as `recorder.import`.
     */
    post: operations["importTradeArchive"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/recorder/purge": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Irreversibly delete recorded data (owner, step-up)
     * @description Destructive and irreversible. Requires an elevated session, a mandatory reason, and an explicit `confirm_symbol` echo that must equal the symbol being purged. Pinned symbols are refused unless `include_pinned` is set. Always audited with the exact window deleted.
     */
    post: operations["purgeRecordedData"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/security/summary": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Security posture roll-up
     * @description Key ages and expiry, IP-whitelist drift, withdrawal-permission verification results, failed-login and denied-request counts, MFA enrolment coverage, and the last audit-chain verification. Owner-only; never includes secret material.
     */
    get: operations["getSecuritySummary"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/support-bundle": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Generate a secret-scanned, size-capped diagnostic bundle (E04-S02)
     * @description Starts a background job (concurrency 1) that writes a zip to the local machine only; never
     *     uploaded. Window max 24 h. The assembled bundle is secret-scanned before being moved into place;
     *     a hit fails the job with `BUNDLE_SECRET_DETECTED` and leaves no archive. Capped (default 200 MB)
     *     newest-first; the manifest states what was truncated. Audited as `health.diagnostics_exported`;
     *     a denied attempt is audited too. Error codes: BUNDLE_SECRET_DETECTED, BUNDLE_WINDOW_TOO_LARGE,
     *     BUNDLE_ALREADY_RUNNING, BUNDLE_DISK_INSUFFICIENT.
     */
    post: operations["createSupportBundle"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/admin/support-bundle/{job_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Support bundle job status and local download path */
    get: operations["getSupportBundle"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/alerts": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List alert definitions */
    get: operations["listAlerts"];
    put?: never;
    /**
     * Create an alert
     * @description Alerts reuse the rule IR condition language but may only use notification actions —
     *     an alert can never place an order. `trigger_mode` is `once` (fire and disable),
     *     `every_time`, or `once_per_bar`. Channels are `in_app`, `desktop`, `email`, `webhook`.
     */
    post: operations["createAlert"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/alerts/{alertId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        alertId: components["parameters"]["AlertId"];
      };
      cookie?: never;
    };
    /** Get an alert */
    get: operations["getAlert"];
    /** Replace an alert */
    put: operations["updateAlert"];
    post?: never;
    /** Delete an alert */
    delete: operations["deleteAlert"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/alerts/{alertId}/enabled": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        alertId: components["parameters"]["AlertId"];
      };
      cookie?: never;
    };
    get?: never;
    /** Enable or disable an alert */
    put: operations["setAlertEnabled"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/alerts/deliveries": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List alert deliveries (the notification inbox) */
    get: operations["listAlertDeliveries"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/alerts/deliveries/{deliveryId}/ack": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        deliveryId: components["parameters"]["DeliveryId"];
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Acknowledge a delivered alert */
    post: operations["ackAlertDelivery"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/alerts/deliveries/ack-all": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Acknowledge every unacknowledged delivery */
    post: operations["ackAllAlertDeliveries"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/auth/login": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Authenticate with username/email + password
     * @description Step 1 of login. If the user has an enrolled MFA method (`totp` or `webauthn`) the
     *     response is `200` with `status: "mfa_required` and a short-lived (`5 min`) `mfa_token`;"
     *     no session is created yet. Otherwise a full `TokenBundle` is returned and the
     *     `cv_refresh` cookie is set.
     *
     *     Failures are deliberately uniform (`unauthenticated`) whether the user is unknown,
     *     the password is wrong, or the account is disabled — no user enumeration.
     *     Five consecutive failures lock the account for 15 minutes (`user_status = locked`).
     */
    post: operations["authLogin"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/auth/logout": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Revoke the current session (or all sessions) */
    post: operations["authLogout"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/auth/mfa/enroll": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Begin enrolment of a new MFA method for the current user
     * @description Returns a TOTP provisioning URI + QR payload, or a WebAuthn creation challenge.
     *     The method stays `pending` until confirmed via `POST /auth/mfa/enroll/confirm`.
     */
    post: operations["authMfaEnroll"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/auth/mfa/enroll/confirm": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Confirm a pending MFA enrolment */
    post: operations["authMfaEnrollConfirm"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/auth/mfa/methods/{methodId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        methodId: components["parameters"]["MethodId"];
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    post?: never;
    /**
     * Remove an MFA method
     * @description Requires a fresh password re-authentication header `X-Reauth-Password`. The last remaining method cannot be removed while `mfa_required` is set on the user.
     */
    delete: operations["authMfaDeleteMethod"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/auth/mfa/recovery": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Complete an MFA challenge with a single-use recovery code
     * @description Consumes one `recovery_codes` row. Consumption is audited and raises a `security.mfa_recovery_used` system event; the user is forced to re-enrol TOTP on the next login when fewer than three codes remain.
     */
    post: operations["authMfaRecovery"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/auth/mfa/verify": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Complete the MFA challenge and obtain tokens
     * @description Step 2 of login. Accepts a TOTP code, a WebAuthn assertion, or a single-use recovery
     *     code. Six failed attempts invalidate the `mfa_token`. Recovery-code use is written to
     *     the audit log with severity `warning` and raises an in-app alert.
     */
    post: operations["authMfaVerify"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/auth/password": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    /**
     * Change the current user's password
     * @description Revokes all other sessions on success. Argon2id, minimum 12 characters, checked against a local breached-password list.
     */
    put: operations["authChangePassword"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/auth/refresh": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Rotate the refresh token and mint a new access token
     * @description Reads the opaque refresh token from the `cv_refresh` cookie (browser/Electron) or from
     *     the JSON body (non-browser clients — kept so a future mobile client works unchanged,
     *     arch P1). Tokens are single-use: presenting a token that has already been rotated
     *     revokes the **entire session family** and returns `refresh_token_invalid` (reuse
     *     detection), logging a `critical` audit entry.
     */
    post: operations["authRefresh"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/auth/session": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Introspect the current session
     * @description Returns the caller identity, effective permissions, granted account scope, kill-switch state and server time — the bootstrap call the web app makes on load.
     */
    get: operations["authGetSession"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/auth/sessions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List active sessions for the current user */
    get: operations["authListSessions"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/auth/step-up": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Elevate the current session for one action class with password and TOTP
     * @description Requires the caller's **password and a TOTP code** (owner decision #1778 AE). The password is verified first (same Argon2id path and lockout counters as login), then the code. A missing `password` is `422`; any wrong factor is the same `401 mfa_invalid` and never reveals which one failed. Grants a **5-minute** server-side grace for `action_class` on the current session (24-internal-schemas.md section 15.2/15.3; the ticket value of 5 minutes supersedes the earlier 15). `live_enablement` and `killswitch` are no-grace classes: the response is `single_use: true` and no window is opened. Three consecutive invalid codes downgrade the session to read-only for 5 minutes (`403 session_read_only` on every write). Endpoints that require elevation return `403` with `code: step_up_required` until this succeeds. Always audited (`auth.step_up_granted`, `auth.step_up_failed`, `auth.session_readonly_downgrade`).
     */
    post: operations["authStepUp"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/chart-templates": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List chart templates
     * @description A template captures chart type, bar type, footprint settings, indicator stack, colour overrides and scale behaviour, independent of symbol.
     */
    get: operations["listChartTemplates"];
    put?: never;
    /** Create a chart template */
    post: operations["createChartTemplate"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/chart-templates/{templateId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        templateId: components["parameters"]["TemplateId"];
      };
      cookie?: never;
    };
    /** Get a chart template */
    get: operations["getChartTemplate"];
    /** Replace a chart template */
    put: operations["updateChartTemplate"];
    post?: never;
    /** Delete a chart template */
    delete: operations["deleteChartTemplate"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/detectors/config": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Current thresholds for the estimated detectors */
    get: operations["getDetectorConfig"];
    /** Update detector thresholds */
    put: operations["setDetectorConfig"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/detectors/methodology": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Plain-language description of how each estimated signal is derived
     * @description Backs the "(estimated)" disclosure affordance required on every heuristic signal. Bybit's public feed is anonymous and aggregated, so iceberg, stop-run, absorption and exhaustion are inferences, not observations; this endpoint states the inputs, the assumption and the known false-positive modes for each, and the UI links to it from every estimated badge.
     */
    get: operations["getDetectorMethodology"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/drawings": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List the caller's drawings for a symbol
     * @description Drawings are stored in **chart space** (time + price), never pixels, so they survive
     *     zoom, bar-type changes and DPI changes. Only the caller's live (not soft-deleted) drawings
     *     are returned, ordered by `id` ascending, so a cursor walk is stable.
     *
     *     `symbol` is required. Without `layout_id` the result holds the caller's drawings on that
     *     symbol in **both** scopes (symbol-global and layout-scoped). With `layout_id` the result is
     *     narrowed to that layout, and the call returns `404` when the id is not one of the caller's
     *     live layouts (always the case until layouts ship, E15-T01).
     *
     *     `limit` is 1..500 (default 100). `cursor` is opaque, bound to the `symbol`/`layout_id`
     *     scope it was issued for and valid for one hour; a malformed, mismatched or expired cursor
     *     returns `400 invalid_cursor`.
     */
    get: operations["listDrawings"];
    put?: never;
    /**
     * Create a drawing
     * @description The server mints a UUIDv7 `id`. The body is limited to 64 KiB (`413 payload_too_large`).
     *     A non-null `layout_id` must name one of the caller's live layouts, otherwise
     *     `422` rule `layout_not_found` (every non-null value until layouts ship, E15-T01).
     *     The `ETag` response header carries the `updated_at` token for later `If-Match` use.
     *
     *     `Idempotency-Key`: the same key with the same body replays the stored 2xx response with
     *     `Idempotency-Replayed: true`; the same key with a different body is `409 idempotency_key_reuse`.
     *     Replay storage is best-effort and bounded; correctness never depends on it.
     */
    post: operations["createDrawing"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/drawings/{drawingId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        drawingId: components["parameters"]["DrawingId"];
      };
      cookie?: never;
    };
    get?: never;
    /**
     * Replace a drawing
     * @description Full replacement. `symbol` and `tool` are immutable (`422` rule `immutable_field`). The body
     *     is limited to 64 KiB (`413 payload_too_large`).
     *
     *     `If-Match` is optional: the quoted `updated_at` token (a `W/` prefix or the bare token is
     *     also accepted). A stale or unparseable value returns `412 version_conflict`; when absent the
     *     last write wins. A drawing that is missing, soft-deleted or owned by another user returns
     *     the same `404`.
     */
    put: operations["updateDrawing"];
    post?: never;
    /**
     * Delete a drawing
     * @description Soft delete (the row is purged by retention later). No precondition. A drawing that is
     *     missing, already deleted or owned by another user returns the same `404`.
     */
    delete: operations["deleteDrawing"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/drawings/batch": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Create/update/delete many drawings in one call
     * @description The chart engine batches drawing mutations during a drag with a 500 ms debounce, so a single
     *     call carries all affected shapes.
     *
     *     Processing order: (1) the body is limited to 1 MiB and `operations` to 200 items, otherwise
     *     `413 payload_too_large`, checked before per-operation validation; (2) the whole body is
     *     validated (`422`, up to 20 field errors such as `operations.3.drawing.tool`; each `id` may
     *     appear at most once per batch, else rule `duplicate_id`); (3) the operations are applied in
     *     order inside **one transaction**. The first operation that cannot be applied rolls the
     *     whole batch back and returns `409 conflict` with `errors[0] = {field: "operations.<i>", rule, message}`,
     *     where `rule` is one of:
     *
     *     - `target_unavailable` — an `update`/`delete` target is missing, soft-deleted or owned by
     *       another user (indistinguishable by design);
     *     - `version_conflict` — the operation's `if_match` is stale;
     *     - `id_unavailable` — a `create` id is already used by any row of any owner in any state
     *       (ids are never reused; re-create under a new id).
     *
     *     `create.id` is optional (client UUIDv7 recommended); `update` and `delete` require `if_match`,
     *     the `updated_at` token of the version being replaced or removed. The result lists the
     *     created, updated and deleted ids in operation order.
     *
     *     `Idempotency-Key` behaves as on `createDrawing`.
     */
    post: operations["batchUpsertDrawings"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/exchange-accounts": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List exchange accounts visible to the caller
     * @description Owners see every account; managers and viewers see only accounts granted through
     *     `user_account_access`. Balances are served from the cached wallet snapshot maintained
     *     by the private-WS `wallet` stream; `balance_stale` is `true` when the snapshot is
     *     older than 10 s.
     */
    get: operations["listExchangeAccounts"];
    put?: never;
    /**
     * Register a Bybit main or sub account
     * @description Registers the account shell. **API keys are supplied separately** via
     *     `POST /exchange-accounts/{accountId}/keys`, which performs mandatory permission
     *     verification before the account can leave `pending`. Registering a `sub` account
     *     requires `parent_account_id`; Bybit caps sub-accounts at 5 (20 with Business KYC)
     *     and the server rejects the 6th with `conflict`.
     */
    post: operations["createExchangeAccount"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/exchange-accounts/{accountId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        accountId: components["parameters"]["AccountId"];
      };
      cookie?: never;
    };
    /** Get one exchange account */
    get: operations["getExchangeAccount"];
    put?: never;
    post?: never;
    /**
     * Deactivate an exchange account
     * @description Revokes its keys locally, stops private streams, and marks it `disabled`. Refused with `conflict` while it holds a non-flat position or open orders.
     */
    delete: operations["deleteExchangeAccount"];
    options?: never;
    head?: never;
    /**
     * Update label, enabled flag, active profile, position/margin mode
     * @description Changing `position_mode` or `margin_mode` proxies to Bybit
     *     (`POST /v5/position/switch-mode`, `switch-isolated`, `account/set-margin-mode`) and
     *     fails with `conflict` when the account holds open positions or active orders.
     */
    patch: operations["updateExchangeAccount"];
    trace?: never;
  };
  "/exchange-accounts/{accountId}/fee-rate": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        accountId: components["parameters"]["AccountId"];
      };
      cookie?: never;
    };
    /**
     * Current maker/taker fee rate for the account
     * @description Proxies `GET /v5/account/fee-rate` (5 req/s cap) with a 15-minute cache. This is the only authoritative fee source — the public fee schedule is unscrapable (digest 06 §17).
     */
    get: operations["getFeeRate"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/exchange-accounts/{accountId}/keys": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        accountId: components["parameters"]["AccountId"];
      };
      cookie?: never;
    };
    /**
     * List API keys for an account (metadata only)
     * @description Secrets are never returned. `key_id_masked` shows the first 4 and last 4 characters only.
     */
    get: operations["listApiKeys"];
    put?: never;
    /**
     * Attach an API key, verifying permissions before it is accepted
     * @description **Mandatory verification pipeline** — the key is only persisted if every check passes:
     *
     *     1. `GET /v5/user/query-api` with the candidate credentials.
     *     2. `permissions.Wallet` must NOT contain `Withdraw` — withdrawal is always OFF
     *        (owner decision #5). A key with withdrawal rights is rejected with
     *        `validation_failed` / `key_withdraw_permission`.
     *     3. Required scopes present: `ContractTrade` + `Order` + `Position` for a trade key;
     *        read-only keys must have none of them and are stored with `read_only: "true`."
     *     4. `unified` must be true (UTA) and the UID must equal `exchange_account.exchange_uid`.
     *     5. IP whitelist must be non-empty when `require_ip_whitelist` is set in settings
     *        (default true for `live`); the deployment egress IP must be inside it.
     *     6. Expiry, if set, must be at least 14 days away, else a warning is attached.
     *     7. A signed no-op probe (`GET /v5/account/wallet-balance`) must return `retCode=0`
     *        within the `recv_window`, which also validates clock sync.
     *
     *     The secret is envelope-encrypted (AES-256-GCM DEK, wrapped by the KEK from the OS
     *     keyring / age-encrypted file) before it touches disk; the plaintext exists only in
     *     request-scoped memory. The full verification result is stored as
     *     `permission_snapshot` and re-checked nightly.
     */
    post: operations["createApiKey"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/exchange-accounts/{accountId}/keys/{keyId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        accountId: components["parameters"]["AccountId"];
        keyId: components["parameters"]["KeyId"];
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    post?: never;
    /**
     * Revoke a stored API key
     * @description Local revocation only — CandleViewer never deletes keys on Bybit. Revoking the last active trade key drops the account to `key_status: missing` and halts its private streams.
     */
    delete: operations["revokeApiKey"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/exchange-accounts/{accountId}/keys/{keyId}/rotate": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        accountId: components["parameters"]["AccountId"];
        keyId: components["parameters"]["KeyId"];
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Rotate an API key with zero-downtime overlap
     * @description Two-phase rotation: the new credentials go through the same verification pipeline as
     *     `createApiKey`; on success the old key moves to `rotating` and both remain usable for
     *     `overlap_seconds` (default 300) while in-flight requests drain, then the old key is
     *     marked `revoked`. Private WS connections are re-authenticated with the new key at the
     *     start of the overlap. The rotation is recorded in `api_key_rotations`.
     */
    post: operations["rotateApiKey"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/exchange-accounts/{accountId}/keys/{keyId}/test": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        accountId: components["parameters"]["AccountId"];
        keyId: components["parameters"]["KeyId"];
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Re-run the verification pipeline against a stored key
     * @description Read-only diagnostics used by the Admin - Accounts screen "Test connection" button and
     *     by the nightly job. Runs signed probes for REST (`wallet-balance`, `query-api`) and, if
     *     `include_ws` is set, opens a throwaway private WS connection and asserts `auth` succeeds.
     *     Never places orders.
     */
    post: operations["testApiKey"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/exchange-accounts/{accountId}/profiles": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        accountId: components["parameters"]["AccountId"];
      };
      cookie?: never;
    };
    /** List per-account trading profiles */
    get: operations["listAccountProfiles"];
    put?: never;
    /** Create a per-account profile (leverage, sizing, offsets, risk caps, allowed symbols) */
    post: operations["createAccountProfile"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/exchange-accounts/{accountId}/profiles/{profileId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        accountId: components["parameters"]["AccountId"];
        profileId: components["parameters"]["ProfileId"];
      };
      cookie?: never;
    };
    /** Get a per-account profile */
    get: operations["getAccountProfile"];
    /**
     * Replace a per-account profile
     * @description `require_native_stop` cannot be set to `false` — the safety invariant (owner decision,
     *     cross-cutting consequence #3) is enforced server-side and the field is accepted only as
     *     `true`. Attempting `false` returns `validation_failed` / `native_stop_mandatory`.
     */
    put: operations["updateAccountProfile"];
    post?: never;
    /**
     * Delete a per-account profile
     * @description Refused with `conflict` when the profile is the account's active profile or is referenced by an armed rule.
     */
    delete: operations["deleteAccountProfile"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/executions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List fills
     * @description Fill-level history from the private WS `execution` stream, reconciled against `GET /v5/execution/list`. One Bybit message may bundle several fills; each is stored individually keyed by `exec_id`.
     */
    get: operations["listExecutions"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/executions/closed-pnl": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Realised PnL per closed position (journal source)
     * @description Mirrors `GET /v5/position/closed-pnl`, backfilled nightly and used to seed journal entries.
     */
    get: operations["listClosedPnl"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/health/live": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Liveness probe
     * @description Process is up. Never touches the database — used by the container orchestrator.
     */
    get: operations["getLiveness"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/health/ready": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Readiness probe
     * @description Dependencies reachable and migrations applied. Returns `503` when not ready so traffic is withheld.
     */
    get: operations["getReadiness"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/indicator-presets": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List saved indicator presets */
    get: operations["listIndicatorPresets"];
    put?: never;
    /** Save an indicator preset */
    post: operations["createIndicatorPreset"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/indicator-presets/{presetId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        presetId: components["parameters"]["PresetId"];
      };
      cookie?: never;
    };
    get?: never;
    /** Replace an indicator preset */
    put: operations["updateIndicatorPreset"];
    post?: never;
    /** Delete an indicator preset */
    delete: operations["deleteIndicatorPreset"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/indicators": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Indicator catalogue with parameter schemas
     * @description Machine-readable descriptor per indicator (id, display name, where it renders, parameter JSON Schema, whether it is computed client-side in a worker or server-side from `orderflow_metrics`, and whether it is `estimated`). The chart settings dialogs render their forms from this, so adding an indicator never requires a frontend release.
     */
    get: operations["listIndicators"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/instruments": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List tradable instruments (Bybit USDT linear perpetuals)
     * @description Served from the locally cached `instruments-info` snapshot, refreshed every 12 h and on
     *     demand. `category` is fixed to `linear` in v1; any other value is rejected with
     *     `unsupported_category`. Instrument metadata is version-tracked (`revision`) because
     *     tick size, leverage tiers and funding interval change occasionally (digest 08).
     *     Response `meta` reports `cache_age_s` and `stale_since` so clients can surface a stale
     *     banner if a refresh is overdue or failing.
     */
    get: operations["listInstruments"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/instruments/{symbol}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        symbol: components["parameters"]["SymbolPath"];
      };
      cookie?: never;
    };
    /** Get one instrument, including risk-limit tiers */
    get: operations["getInstrument"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/instruments/{symbol}/ticker": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        symbol: components["parameters"]["SymbolPath"];
      };
      cookie?: never;
    };
    /**
     * Latest ticker snapshot (24h stats, mark/index, funding, OI)
     * @description Bootstrap value for the ticker widget; live updates arrive on the WS `ticker.{symbol}` topic.
     */
    get: operations["getTicker"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/instruments/refresh": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Force a refresh of the instrument cache from Bybit */
    post: operations["refreshInstruments"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/invites/{inviteToken}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        inviteToken: string;
      };
      cookie?: never;
    };
    /**
     * Resolve an invitation token (unauthenticated)
     * @description Returns only the minimum needed to render the acceptance form - the invited display name and the role being offered. It never reveals whether other users exist, and an expired or consumed token is indistinguishable from an unknown one (`404`), per 04-security-program.md section 7.3.
     */
    get: operations["getInvite"];
    put?: never;
    /**
     * Set the password and start TOTP enrolment (unauthenticated)
     * @description Consumes the single-use token and parks the password hash; the account stays `invited` until `confirmInvite`. The body carries only `password` - a `role`/`roles` field is refused with `403` and audited (role immutability). Unknown, expired, redeemed and revoked tokens all return the same `404`.
     */
    post: operations["redeemInvite"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/invites/{inviteToken}/confirm": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        inviteToken: string;
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Verify the first TOTP code and activate the account (unauthenticated)
     * @description Activates the account and returns the one-time recovery codes. No session is minted.
     */
    post: operations["confirmInvite"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/journal/analytics": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Aggregate performance analytics over journal entries
     * @description Server-computed statistics for the Analytics screen: equity curve, win rate, expectancy,
     *     profit factor, average R, drawdown, and breakdowns by symbol, tag, session hour,
     *     day-of-week, side and account. `group_by` selects which breakdowns are materialised.
     */
    get: operations["getJournalAnalytics"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/journal/tags": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List journal tags with usage counts */
    get: operations["listJournalTags"];
    put?: never;
    /** Create a journal tag */
    post: operations["createJournalTag"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/journal/trades": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List journal entries
     * @description One entry per closed trade group (or per closed position when a trade originated
     *     outside CandleViewer and was adopted during reconciliation). Entries are created
     *     automatically and then enriched by the user with notes, tags, screenshots and a rating.
     */
    get: operations["listJournalTrades"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/journal/trades/{journalTradeId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        journalTradeId: components["parameters"]["JournalTradeId"];
      };
      cookie?: never;
    };
    /** Get a journal entry with notes and execution breakdown */
    get: operations["getJournalTrade"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    /**
     * Update the user-authored fields of a journal entry
     * @description Computed fields (PnL, R-multiple, MFE/MAE, durations) are read-only and recomputed from executions; only `rating`, `tags`, `setup`, `mistakes` and `checklist` are writable.
     */
    patch: operations["updateJournalTrade"];
    trace?: never;
  };
  "/journal/trades/{journalTradeId}/context": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        journalTradeId: components["parameters"]["JournalTradeId"];
      };
      cookie?: never;
    };
    /**
     * Market context around a journalled trade, for the review chart
     * @description Bars, footprint and the trade's own fills over a window padded around entry and exit, in one call, so the journal review chart paints without a burst of separate market-data requests. `coverage` reports honestly when recording did not span the whole window rather than silently returning a shorter series.
     */
    get: operations["getJournalTradeContext"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/journal/trades/{journalTradeId}/notes": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        journalTradeId: components["parameters"]["JournalTradeId"];
      };
      cookie?: never;
    };
    /** List notes on a journal entry */
    get: operations["listJournalNotes"];
    put?: never;
    /** Add a note (markdown, optional chart snapshot reference) */
    post: operations["createJournalNote"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/layout-presets": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Built-in and user-saved workspace layout presets */
    get: operations["listLayoutPresets"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/market/bars": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Bars of any supported type (time, tick, volume, range, delta, renko, p&f, heikin-ashi)
     * @description Single entry point for every non-time bar construction, all built locally from the
     *     recorded trade tape (digest 08 §17 — time/tick/volume/range/delta bars are all LOCAL).
     *     `bar_type` selects the algorithm and `param` supplies its single scalar parameter:
     *
     *     | bar_type      | param meaning                                   | example        |
     *     |---------------|-------------------------------------------------|----------------|
     *     | `time`        | interval string, same enum as `/market/klines`  | `5`            |
     *     | `tick`        | trades per bar                                  | `1000`         |
     *     | `volume`      | base-asset volume per bar                       | `50`           |
     *     | `range`       | high-low range in ticks                         | `40`           |
     *     | `delta`       | absolute cumulative signed volume per bar       | `25`           |
     *     | `renko`       | brick size in ticks, or `atr:14` for ATR bricks | `30` / `atr:14`|
     *     | `pnf`         | `box:reversal` in ticks                         | `10:3`         |
     *     | `heikin_ashi` | underlying time interval                        | `5`            |
     *
     *     Non-time bars are **not** anchored to wall-clock; each bar carries `open_time` and
     *     `close_time` derived from its first/last trade.
     *
     *     **Ordering and identity (#2014).** A bar's identity is `(series, generation, index)`
     *     (21 §4.8, 24 §3.1). The response serves exactly one generation: the series' current
     *     generation, pinned for the whole request (ADR-0033 Decision 2), never a mix. Non-time
     *     `bars` are ordered by the stored key `(t, generation, index)` ascending (#2017; for one
     *     pinned generation this is `(generation, index)` order); time bars by `t`. `t` MAY
     *     repeat for non-time bars (an N-threshold print yields N volume bars or renko bricks with
     *     one open time; two tick bars can open in the same ms). Clients MUST key bars by
     *     `(generation, index)`, never by `t`. Every bar returned here carries `index` and
     *     `generation` (they stay optional in the shared `Bar` schema only because
     *     `/market/klines` also uses it). Pagination follows C3 and the `MarketCursor` parameter;
     *     if the pinned generation was swapped since the cursor was issued, the server returns
     *     `invalid_cursor` and the client restarts. A request whose window starts before
     *     `recording_started_at` returns `no_data_recorded` (422) rather than silently
     *     substituting REST klines, because tick-accurate construction is impossible there.
     *     **Precedence:** when a non-time window both starts before `recording_started_at` and
     *     exceeds a hard window cap, `no_data_recorded` wins — it is the more
     *     specific data-availability fact, and the client cannot fix it by paginating.
     *
     *     **Paging (#2045, E12-T05).** A request without `cursor` is served as its first page:
     *     the oldest `limit` bars of the window, oldest→newest, with `meta.has_more` and a
     *     server-issued `meta.next_cursor` when more remain; the client continues with that cursor
     *     until `has_more` is false. Every read fetches at most `limit + 1` rows, so the work per
     *     request is bounded whatever the window. `bar_window_too_large` (422) is reserved for the
     *     hard window caps (E12 STRIDE SR-E12-02): time bars span at most 400 days; non-time bars
     *     at most 31 days and an estimated 250 000 bars. Cursor semantics are stated once, on the
     *     `MarketCursor` parameter. A page that would exceed the response ceiling (SR-E12-01)
     *     returns 422 `response_too_large`.
     */
    get: operations["getBars"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/market/data-coverage": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * What data exists locally for a symbol, per stream and tier
     * @description The UI calls this before rendering a historical window so it can grey out ranges that
     *     were never recorded, rather than showing a misleading empty chart. Returns contiguous
     *     covered intervals per `stream_kind` with the storage tier that holds them.
     */
    get: operations["getDataCoverage"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/market/footprint": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Footprint (bid/ask volume per price level per bar) with imbalance analysis
     * @description Returns one `cells` array per bar, keyed by tick-rounded price, plus per-bar POC/value
     *     area and the detected diagonal/stacked imbalances and unfinished auctions.
     *
     *     Defaults follow digest 08 §3: diagonal imbalance ratio 300 %, minimum stack 3,
     *     value area 70 %. Cells are aggregated from `publicTrade` using the taker side `S`
     *     directly — no aggressor reconstruction is needed on Bybit.
     *
     *     Response size is bounded: `bars × price_levels` must be ≤ 200 000 cells, else `400`
     *     with `validation_failed` / `footprint_window_too_large`. The UI paginates by bar.
     */
    get: operations["getFootprint"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/market/footprint/recompute": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Rebuild footprint cells for a symbol and window from the recorded tape
     * @description Used after a price-grouping or imbalance-parameter change, or to repair a window flagged by gap detection (24-internal-schemas.md section 13.3). Asynchronous; poll with `GET /admin/jobs/{jobId}`.
     */
    post: operations["recomputeFootprint"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/market/funding": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Funding-rate history
     * @description From Bybit `GET /v5/market/funding/history` (limit ≤200) cached locally. The funding
     *     interval is instrument-specific (`funding_interval_minutes`; 8 h common, some 1/2/4 h) —
     *     never assume 8 h. `predicted` marks the current unsettled rate, which Bybit exposes only
     *     through the ticker (`fundingRate`); it is flagged `estimated: "true`."
     */
    get: operations["getFundingHistory"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/market/heatmap": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Historical DOM liquidity heatmap (resting size by price over time)
     * @description Reconstructs resting liquidity from recorded book deltas into a time × price grid.
     *     `time_bucket_ms` and `price_grouping` control the grid; the response is a dense matrix
     *     plus its axes so the WebGL engine can upload it as a texture in one step.
     *     Colour convention is a client concern (green = bid, red = ask by owner decision #10).
     */
    get: operations["getHeatmap"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/market/klines": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Time-based OHLCV candles
     * @description Returns closed candles from the local store, oldest→newest. The in-progress candle is
     *     included only when `include_open=true` and is flagged `confirm: "false` (Bybit `confirm`"
     *     semantics, digest 06 §9 — never treat an unconfirmed candle as closed).
     *
     *     Sources, in priority order: (1) locally recorded trade tape aggregated by the bar
     *     builder, (2) Bybit REST `kline` backfill for windows that predate recording, (3) Parquet
     *     cold tier for windows older than the QuestDB hot retention. Each response states which
     *     tiers were touched in `meta.sources`, and `meta.recording_started_at` tells the UI where
     *     native (tick-accurate) data begins — before that point delta/footprint fields are null.
     *     Bars built from the tape are reported as `tape` in `meta.sources`.
     *
     *     **Paging (#2045, E12-T05).** A request without `cursor` is served as its first page:
     *     the oldest `limit` bars of the window, oldest→newest, with `meta.has_more` and a
     *     server-issued `meta.next_cursor` when more remain; the client continues with that cursor
     *     until `has_more` is false. Every read fetches at most `limit + 1` rows, so the work per
     *     request is bounded whatever the window. `bar_window_too_large` (422) is reserved for the
     *     hard window caps (E12 STRIDE SR-E12-02): time bars span at most 400 days; non-time bars
     *     at most 31 days and an estimated 250 000 bars. Cursor semantics are stated once, on the
     *     `MarketCursor` parameter. A page that would exceed the response ceiling (SR-E12-01)
     *     returns 422 `response_too_large`.
     */
    get: operations["getKlines"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/market/liquidations": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Recorded liquidation prints and clusters
     * @description Sourced from the `allLiquidation.{symbol}` WS topic (the legacy `liquidation` topic is
     *     retired — digest 06 §9). Bybit batches at most one push per symbol per 500 ms, so
     *     counts are lower bounds on distinct liquidation events. `cluster_window_ms` groups
     *     prints into liquidation cascades for the cluster overlay.
     */
    get: operations["getLiquidations"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/market/metrics": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Derived order-flow & regime metrics time series
     * @description One endpoint for every scalar derived series, selected by the repeated `metric` query
     *     parameter. Each series is returned with its own parameter echo so charts are
     *     reproducible. Metrics whose computation is heuristic carry `estimated: "true` at the"
     *     series level (arch P10).
     *
     *     Supported metrics and their defaults (digest 08):
     *     `cvd` (anchor=session), `delta`, `min_max_delta`, `trades_per_sec` / `volume_per_sec` /
     *     `book_updates_per_sec` (windows 1 s/5 s/30 s), `tape_acceleration` (1 s vs 300 s
     *     baseline, alert >3×), `imbalance_ratio`, `absorption` (min_volume, max_price_move 1
     *     tick), `exhaustion` (lookback 5 bars), `iceberg` (min_reload_count 3,
     *     size_tolerance_pct 0.2, **estimated**), `stop_run` (max_bars_to_reverse 3,
     *     reversal_pct 0.5, **estimated**), `adx` (14), `atr` (14), `hurst` (R/S window 256),
     *     `regime` (combined ADX/Hurst classification), `vwap` (+1σ/2σ bands),
     *     `open_interest_delta`, `funding_basis`, `liquidation_intensity`.
     */
    get: operations["getMetrics"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/market/open-interest": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Open-interest history from the local store
     * @description Backfilled from Bybit `GET /v5/market/open-interest` (5min…1d intervals, limit ≤200/page) and continuously extended from the recorded `tickers` stream at higher resolution.
     */
    get: operations["getOpenInterestHistory"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/market/orderbook": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Current order-book snapshot (bootstrap for the DOM)
     * @description Returns the backend's maintained book at the requested depth with its
     *     sequence numbers (`u`, `seq`). The client uses this to seed the DOM and then follows
     *     `book.{symbol}.{depth}` deltas on the WS; on any sequence gap it re-calls this endpoint
     *     (arch P5 — no checksum exists on Bybit, resync is drop-and-rebuild).
     */
    get: operations["getOrderbookSnapshot"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/market/profile": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Volume / delta / TPO profile for a period
     * @description Builds a price histogram over the requested window. `kind=volume` sums traded volume,
     *     `kind=delta` sums signed volume, `kind=tpo` counts discrete time periods touching each
     *     price (classic 30-minute letters, `tpo_period_minutes` configurable).
     *
     *     Value area uses the single-step expansion algorithm (expand toward the heavier adjacent
     *     row until the target percentage is reached) — documented as an accepted approximation of
     *     the textbook two-row TPO expansion (digest 08 §4, open question #9).
     *
     *     `split=session|composite|fixed` controls whether one profile or one profile per
     *     sub-period is returned; `naked_poc` marks prior-period POCs that have not been retraded.
     */
    get: operations["getProfile"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/market/regime/explain": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Current market-regime classification with its contributing sub-signals
     * @description Returns the classification plus each sub-signal's value, weight and contribution, so the regime badge is explainable rather than an opaque verdict.
     */
    get: operations["explainRegime"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/market/trades": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Historical time & sales (recorded tape), optionally clustered
     * @description Raw recorded prints, newest-first. `cluster_window_ms` merges same-side same-price
     *     (±`cluster_tolerance_ticks`) prints inside the window into one display print — the
     *     split-fill aggregation of digest 08 §12.2, deliberately distinct from resting-side
     *     iceberg detection. `min_size` implements the big-trade filter used by the tape widget.
     */
    get: operations["getTrades"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/me": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Current identity, role, effective permissions and account grants
     * @description Single bootstrap call for the app shell. Returns the authenticated user, their role, the flattened effective permission set (the same closed vocabulary used by `x-rbac.permissions`), and the accounts they may read/trade. The UI uses this to decide which affordances to render; it is never the authorisation control itself (04-security-program.md section 7.3).
     */
    get: operations["getMe"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/me/keymap": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Resolved hotkey bindings for the active profile
     * @description Flattened view of the active `HotkeyProfile`, used by the hotkey cheatsheet (SCR-013) and the command palette (SCR-012).
     */
    get: operations["getMyKeymap"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/me/limits": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Effective rate-limit and risk-cap budget for the caller
     * @description Per-account rate budget (20-architecture.md section 4.3) and the risk caps that currently apply to the caller, so the order ticket can show remaining headroom before a submission is attempted.
     */
    get: operations["getMyLimits"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/me/preferences": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Read own effective settings
     * @description Alias of `GET /settings` scoped to the calling user; kept as a distinct operation because the app shell fetches it alongside `/me` on boot.
     */
    get: operations["getMyPreferences"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    /** Patch own settings */
    patch: operations["updateMyPreferences"];
    trace?: never;
  };
  "/me/sessions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List own active sessions */
    get: operations["listMySessions"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/me/sessions/{sessionId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        sessionId: string;
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    post?: never;
    /**
     * Revoke one of own sessions
     * @description Revoking the current session is equivalent to logout. Revocation terminates any WebSocket connection bound to that session immediately (23-ws-protocol.md section 9.5).
     */
    delete: operations["revokeMySession"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/notifications": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Unified notification history (alerts, rule fires, order events, system)
     * @description Read-model union over `alert_deliveries`, `rule_events`, `order_events` and `system_events`, filtered to what the caller may see. Live equivalents arrive on the `alerts`, `rules`, `orders` and `system` WS topics; this endpoint is the scroll-back history behind them.
     */
    get: operations["listNotifications"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/onboarding/checklist": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * First-run / setup checklist state (E09-S06)
     * @description Drives SCR-019. Every step state is evaluated server-side from read-only probes run with the caller's own identity (US-ONB-007: no step may be faked client-side). Each probe has a 250 ms budget; a probe that times out or fails yields `state=error` for that step only, and an owning epic that has not shipped yields `state=pending` with a feature-flag reason.
     */
    get: operations["getOnboardingChecklist"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/onboarding/checklist/dismiss": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Dismiss the completed checklist summary (persisted per user)
     * @description Only accepted once every step is `ok`; otherwise 409. Stored server-side so the card stays gone on every device.
     */
    post: operations["dismissOnboardingChecklist"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/onboarding/complete": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Mark the onboarding wizard finished for the caller */
    post: operations["completeOnboarding"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/orders": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List orders across the caller's accounts
     * @description Reads the local OMS mirror, which is reconciled against Bybit
     *     (`GET /v5/order/realtime` + `order/history`) and updated live from the private WS
     *     `order` stream — the WS stream, never the REST ack, is the source of truth for state
     *     (digest 06 §19).
     */
    get: operations["listOrders"];
    put?: never;
    /**
     * Place an order on a single account
     * @description Single-account convenience wrapper over the trade-group machinery: the server creates a
     *     one-leg trade group internally so that every order — single or fanned-out — shares one
     *     state machine, one audit trail and one journal linkage.
     *
     *     **Invariants enforced server-side:**
     *     * The account's active profile must allow the symbol, otherwise `risk_limit_breached`.
     *     * Price is snapped/validated against `tick_size`; qty against `qty_step`/min/max
     *       (`tick_size_violation` / `lot_size_violation`).
     *     * A native exchange-side stop-loss is mandatory for entry intents
     *       (`require_native_stop`, arch P4). If the request omits `stop_loss`, the account
     *       profile's SL offset is applied; if the profile has none either, the request is
     *       rejected with `validation_failed` / `native_stop_required`.
     *     * `Idempotency-Key` is REQUIRED. The server derives a deterministic `orderLinkId`
     *       (≤36 chars) from it, so a retried request can never double-submit.
     *     * The kill-switch, if engaged for the account or globally, rejects with
     *       `trading_disabled` before anything reaches the exchange.
     *
     *     The response is an **acknowledgement of acceptance into the OMS**, not a fill. Terminal
     *     state arrives on the WS `orders` / `executions` topics.
     */
    post: operations["placeOrder"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/orders/{orderId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        orderId: components["parameters"]["OrderId"];
      };
      cookie?: never;
    };
    /** Get one order with its event timeline */
    get: operations["getOrder"];
    put?: never;
    post?: never;
    /**
     * Cancel a single order
     * @description Maps to `POST /v5/order/cancel`. Cancelling an already-terminal order is idempotent and returns `202` with the current state rather than an error.
     */
    delete: operations["cancelOrder"];
    options?: never;
    head?: never;
    /**
     * Amend price, quantity, trigger or attached TP/SL
     * @description Maps to `POST /v5/order/amend`. Amendment is refused with `order_not_amendable` when the
     *     order is terminal or already has a cancel/amend in flight. Omitted fields are left
     *     untouched; sending `null` for `take_profit`/`stop_loss` clears them — except that an
     *     entry order's stop-loss can never be cleared while the leg is open (arch P4), which
     *     returns `validation_failed` / `native_stop_required`.
     *
     *     Amending only one side of a TP/SL pair breaks Bybit's OCO pairing (digest 06 §19); the
     *     server therefore re-sends both sides whenever either changes, and records the paired
     *     amend in `order_events`.
     */
    patch: operations["amendOrder"];
    trace?: never;
  };
  "/orders/{orderId}/diagnostics": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        orderId: components["parameters"]["OrderId"];
      };
      cookie?: never;
    };
    /**
     * Full lifecycle trace for one order
     * @description Returns the ordered `order_events` chain plus the exchange request/response pairs (with credentials and signatures redacted) and the reconciliation verdict. This is the "why did my order do that" surface; it is the only place the raw retCode and retMsg from Bybit are exposed, and it is audited on read.
     */
    get: operations["getOrderDiagnostics"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/orders/cancel-all": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Cancel all open orders matching a filter
     * @description Fans out `POST /v5/order/cancel-all` per account (Bybit rate cost: 1 req/s per account
     *     for `linear` cancel-all — the fan-out scheduler serialises accordingly). Partial
     *     success is normal and reported per account; the HTTP status is `207`-style `200` with
     *     per-account results rather than an all-or-nothing error.
     */
    post: operations["cancelAllOrders"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/permissions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List every permission code the server recognises
     * @description Used by the admin UI to render the role matrix; the list is static per release and matches `x-permissions` in this document.
     */
    get: operations["listPermissions"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/positions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List positions across the caller's accounts
     * @description Mirrors Bybit `GET /v5/position/list`, kept live by the private WS `position` stream.
     *     `aggregate=true` collapses legs of the same symbol across accounts into one synthetic
     *     row (with a per-account breakdown) for the portfolio view.
     */
    get: operations["listPositions"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/positions/{positionId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        positionId: components["parameters"]["PositionId"];
      };
      cookie?: never;
    };
    /** Get one position */
    get: operations["getPosition"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/positions/{positionId}/close": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        positionId: components["parameters"]["PositionId"];
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Close a position (fully or partially)
     * @description Issues a reduce-only order of the opposite side. `order_type: "market` is the flatten"
     *     button; `limit` with `price` is a controlled exit. `pct` closes a fraction, `qty` an
     *     absolute amount; exactly one of the two is required. Attached TP/SL of the closed
     *     portion is cancelled automatically to avoid orphan conditional orders.
     */
    post: operations["closePosition"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/positions/{positionId}/leverage": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        positionId: components["parameters"]["PositionId"];
      };
      cookie?: never;
    };
    get?: never;
    /**
     * Set leverage for the position's symbol on its account
     * @description Maps to `POST /v5/position/set-leverage` (10 req/s). Bybit applies leverage per symbol per account, not per position; the change therefore affects future orders on that symbol too.
     */
    put: operations["setPositionLeverage"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/positions/{positionId}/reverse": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        positionId: components["parameters"]["PositionId"];
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Reverse a position (flatten and open the opposite side)
     * @description Executed as a single order of `2 × size` in one-way mode, or as an explicit close +
     *     open pair in hedge mode (`positionIdx` 1/2 cannot cross). The new side receives a
     *     native stop derived from the account profile, satisfying arch P4; if the profile cannot
     *     produce one, the reversal is rejected before any order is sent.
     */
    post: operations["reversePosition"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/positions/{positionId}/tpsl": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        positionId: components["parameters"]["PositionId"];
      };
      cookie?: never;
    };
    get?: never;
    /**
     * Set take-profit / stop-loss / trailing stop on a position
     * @description Maps to `POST /v5/position/trading-stop`. Notes that the contract enforces:
     *
     *     * **Trailing stop is a price distance on Bybit, not a percentage.** A percentage or
     *       ATR-based request is translated server-side into a price distance using the current
     *       mark price / ATR, and both the requested unit and the resolved distance are echoed.
     *     * Sending only one of TP/SL breaks Bybit's OCO pairing, so the server always re-asserts
     *       both sides; pass `null` explicitly to clear one.
     *     * `tpsl_mode: Partial` requires `tp_size`/`sl_size` that match the position size rules.
     *     * The stop-loss cannot be cleared while `require_native_stop` is set on the account
     *       profile — `validation_failed` / `native_stop_required`.
     */
    put: operations["setPositionTpSl"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/positions/close-all": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Flatten every position matching a filter
     * @description The "flatten all" panic control. Independent of the kill-switch, which additionally blocks new orders.
     */
    post: operations["closeAllPositions"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/recording/retention-policies": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List retention policies per stream kind */
    get: operations["listRetentionPolicies"];
    /**
     * Replace the retention policy set
     * @description Policies are evaluated most-specific-first (per-symbol beats global). Pinned symbols are exempt unless a policy sets `applies_to_pinned: true`. Changes take effect at the next nightly retention sweep; `apply_now=true` triggers an immediate sweep.
     */
    put: operations["setRetentionPolicies"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/recording/sessions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List recording sessions (contiguous recording runs)
     * @description A session opens when recording starts and closes on stop, crash or restart. Sessions are the unit that replay sessions are created from.
     */
    get: operations["listRecordingSessions"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/recording/status": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Recorder health — per-symbol lag, drop counts, resyncs, connection state
     * @description Primary data source for the Recorder/System-health screens and the `recorder` WS topic.
     *     `resyncs_last_hour` counts book rebuilds forced by sequence gaps; a non-zero
     *     `dropped_messages` is an incident (chaos-test assertion in 03-testing-strategy.md).
     */
    get: operations["getRecordingStatus"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/recording/storage": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Disk budget — usage per tier, per symbol, growth rate and projection */
    get: operations["getStorageUsage"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/recording/symbols": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List the recorded-symbol list
     * @description The list is **empty by default** (owner decision #4). Entries appear either because a
     *     user added them (`reason: "manual`) or because auto-record triggered on an open chart or"
     *     an open position. Auto-record entries expire when their trigger disappears, unless
     *     pinned.
     */
    get: operations["listRecordedSymbols"];
    put?: never;
    /**
     * Add a symbol to the recorded list (start recording)
     * @description Starts the ingestion subscriptions for the requested streams. Book depth 200 at 100 ms
     *     is the default for footprint/heatmap fidelity; depth 500 is allowed but the response
     *     carries an estimated disk-rate warning (~0.5–0.75 GB/day/symbol compressed at depth 200).
     *     Adding a symbol already present is idempotent and returns `200` with the existing row.
     */
    post: operations["addRecordedSymbol"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/recording/symbols/{recordedSymbolId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        recordedSymbolId: components["parameters"]["RecordedSymbolId"];
      };
      cookie?: never;
    };
    /** Get one recorded-symbol entry */
    get: operations["getRecordedSymbol"];
    put?: never;
    post?: never;
    /**
     * Stop recording a symbol
     * @description Stops subscriptions and closes the open recording session. Data is retained and remains
     *     replayable unless `purge_data=true`, which schedules an irreversible delete across
     *     QuestDB and Parquet (audited, owner-only). Removal is refused with `conflict` while an
     *     auto-record trigger is still active (open chart or open position) unless `force=true`.
     */
    delete: operations["removeRecordedSymbol"];
    options?: never;
    head?: never;
    /**
     * Change streams, depth, retention or pin state
     * @description `pinned: true` means "keep forever" and nulls `retention_days`. Un-pinning restores the
     *     global default (30 days) unless an explicit value is supplied. Narrowing `streams` stops
     *     those subscriptions but does **not** delete already-recorded data — use
     *     `DELETE /recording/symbols/{id}?purge_data=true` for that.
     */
    patch: operations["updateRecordedSymbol"];
    trace?: never;
  };
  "/recording/symbols/{recordedSymbolId}/pin": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        recordedSymbolId: components["parameters"]["RecordedSymbolId"];
      };
      cookie?: never;
    };
    get?: never;
    /**
     * Pin (keep forever) or unpin a recorded symbol
     * @description Convenience endpoint for the one-click pin toggle in the Recorder screen; equivalent to PATCH with `{pinned}`.
     */
    put: operations["pinRecordedSymbol"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/replay/sessions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List the caller's replay sessions */
    get: operations["listReplaySessions"];
    put?: never;
    /**
     * Create a tick-replay session over recorded data
     * @description Replay injects recorded events into the *same* normalizer → book → bar → order-flow
     *     chain as live ingestion (arch P2), so every derived view is bit-identical to what was
     *     seen live. The session is addressed by its `id` on the WS: subscribing with
     *     `replay_session_id` set routes market-data topics from the replay clock instead of the
     *     live clock.
     *
     *     `speed` is a multiplier (0.1–100) or `step` for manual frame-stepping. `paper_account_id`
     *     optionally attaches the paper matcher so orders can be practised against the replayed
     *     book; fills are simulated locally and never reach Bybit.
     *
     *     A window lacking recorded coverage is rejected with `no_data_recorded` (422) —
     *     `GET /market/data-coverage` tells the UI in advance.
     */
    post: operations["createReplaySession"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/replay/sessions/{replayId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        replayId: components["parameters"]["ReplayId"];
      };
      cookie?: never;
    };
    /** Get a replay session */
    get: operations["getReplaySession"];
    put?: never;
    post?: never;
    /** Destroy a replay session and free its buffers */
    delete: operations["deleteReplaySession"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/replay/sessions/{replayId}/control": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        replayId: components["parameters"]["ReplayId"];
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Play, pause, seek, step or change speed
     * @description `step` advances by `step_events` events or `step_ms` of replay time (exactly one of the
     *     two). `seek` repositions `cursor_ts`; the engine rebuilds book state from the nearest
     *     preceding snapshot, so a seek is never cheaper than a snapshot interval (60 s).
     */
    post: operations["controlReplaySession"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/risk/lockouts/{accountId}/override": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        accountId: components["parameters"]["AccountId"];
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Clear a risk lockout on an account (owner, step-up)
     * @description Lockouts are set automatically when a `RiskCaps` threshold is breached. Clearing one is an owner-only, step-up-gated, always-audited action; the reason is mandatory and is written to the audit chain.
     */
    post: operations["overrideRiskLockout"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/risk/summary": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Aggregate risk, cap utilisation and lockout state
     * @description Cross-account risk roll-up. A Manager sees only granted accounts; a Viewer sees the aggregate only when granted read on **every** account it covers (04-security-program.md section 7.2 row 29), otherwise `403 account_scope_denied` - a partial aggregate would be a misleading number, so it is refused rather than silently narrowed.
     */
    get: operations["getRiskSummary"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/roles": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List roles and their permission codes */
    get: operations["listRoles"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/rules": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List rules */
    get: operations["listRules"];
    put?: never;
    /**
     * Create a rule
     * @description A rule is stored as an **IR** (intermediate representation) — the single executable form
     *     produced by *both* editors (form/condition-list and node-graph), per owner decision #11.
     *     `editor` records which editor last authored it, purely so the UI can reopen it in the
     *     right surface; it never changes execution. `graph_layout` holds node coordinates for the
     *     node editor and is ignored by the engine.
     *
     *     Creating a rule always stores it as version 1 in `mode: "disabled`. Arming is a separate,"
     *     audited call (`PUT /rules/{id}/mode`), and `simulate` mode is the mandatory intermediate
     *     step in the Definition of Done for any rule that can send orders.
     */
    post: operations["createRule"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/rules/{ruleId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        ruleId: components["parameters"]["RuleId"];
      };
      cookie?: never;
    };
    /** Get a rule with its active IR */
    get: operations["getRule"];
    /**
     * Update a rule, creating a new version
     * @description Every save creates an immutable new `rule_versions` row (`version = previous + 1`) with
     *     a SHA-256 `ir_hash`. An **armed** rule keeps executing its previously active version
     *     until the new version is explicitly activated via `PUT /rules/{id}/active-version`,
     *     so saving can never silently change live behaviour.
     */
    put: operations["updateRule"];
    post?: never;
    /**
     * Delete a rule
     * @description Refused with `conflict` while the rule is `armed`; disarm first. Versions and run history are retained for audit.
     */
    delete: operations["deleteRule"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/rules/{ruleId}/active-version": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        ruleId: components["parameters"]["RuleId"];
      };
      cookie?: never;
    };
    get?: never;
    /** Activate (or roll back to) a specific rule version */
    put: operations["setActiveRuleVersion"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/rules/{ruleId}/compile": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        ruleId: components["parameters"]["RuleId"];
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Compile an editor model into canonical rule IR
     * @description Accepts either editor's native model and returns canonical IR plus its `ir_hash`. Compiling the form model and the graph model of the same rule MUST produce an identical hash; that equality is the round-trip guarantee asserted by the contract tests in 24-internal-schemas.md section 11.4.
     */
    post: operations["compileRule"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/rules/{ruleId}/mode": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        ruleId: components["parameters"]["RuleId"];
      };
      cookie?: never;
    };
    get?: never;
    /**
     * Disable, simulate or arm a rule
     * @description `armed` is the only mode that can send orders. Arming requires: a validated active
     *     version with zero errors, at least one completed simulation run on that exact
     *     `ir_hash`, no open validation warnings of class `safety`, and — when the rule contains
     *     order-sending actions — `orders:write` on every bound account. The transition is
     *     audited and broadcast on the `rules` WS topic. Arming a rule whose scope includes the
     *     `live` environment additionally needs `rules:arm_live` (dangerous, owner-seeded) and a
     *     fresh one-shot step-up (`live_enablement`); refusals use `permission_required` /
     *     `step_up_required`.
     */
    put: operations["setRuleMode"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/rules/{ruleId}/runs": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        ruleId: components["parameters"]["RuleId"];
      };
      cookie?: never;
    };
    /** List rule runs (live firings and simulations) */
    get: operations["listRuleRuns"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/rules/{ruleId}/simulate": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        ruleId: components["parameters"]["RuleId"];
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Dry-run a rule against recorded history or a replay session
     * @description Replays the rule over historical data using the same engine and the same IR, emitting
     *     the actions it *would* have taken without sending anything to the exchange. This is the
     *     gate a rule must pass before it can be armed (Definition of Done, 02-definition-of-ready-done.md).
     *
     *     Either `from`/`to` (history window over recorded data) or `replay_session_id` must be
     *     supplied. Long simulations run asynchronously: "the response is `202` with a `job_id`"
     *     and results are polled from `GET /rules/{ruleId}/runs`.
     */
    post: operations["simulateRule"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/rules/{ruleId}/versions": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        ruleId: components["parameters"]["RuleId"];
      };
      cookie?: never;
    };
    /** List a rule's versions */
    get: operations["listRuleVersions"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/rules/{ruleId}/versions/{versionId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        ruleId: components["parameters"]["RuleId"];
        versionId: components["parameters"]["VersionId"];
      };
      cookie?: never;
    };
    /** Get one rule version including its full IR */
    get: operations["getRuleVersion"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/rules/accounts": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Accounts the caller may scope a rule to
     * @description Only accounts the caller holds a view grant on; an ungranted account is absent (never a 403 row), so account existence does not leak (E35-S04 AC2).
     */
    get: operations["listRuleAccounts"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/rules/runs/{runId}/events": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        runId: components["parameters"]["RunId"];
      };
      cookie?: never;
    };
    /**
     * Event timeline of a single rule run
     * @description Per-evaluation trace — condition outcomes, guard suppressions, actions attempted and their results. This is the debugging surface for "why did/didn't my rule fire".
     */
    get: operations["listRuleRunEvents"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/rules/validate": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Validate an IR without saving it
     * @description Static analysis used by both editors on every keystroke-debounce. Checks schema
     *     conformance, variable existence, type compatibility, action-parameter completeness,
     *     unreachable branches, missing guards, and the `require_native_stop` invariant. Returns
     *     errors **and** warnings; warnings do not block saving but do block arming.
     */
    post: operations["validateRule"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/rules/vocabulary": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * The closed vocabulary both rule editors build against
     * @description Enumerates every legal signal, operator, action and guard in the rule IR (24-internal-schemas.md section 11.6), with types, units and permission requirements. The form editor and the node-graph editor both render their palettes from this single response, which is what keeps the two editors round-trip compatible.
     */
    get: operations["getRuleVocabulary"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/scanner": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Rank instruments by order-flow and volatility criteria
     * @description Evaluates the requested filter set over the most recent values in `orderflow_metrics` and `tickers`. Only instruments with active recording can be scanned on recorded-history criteria; others are returned with `coverage: "live_only"` so the UI can explain the gap rather than show a blank row.
     */
    get: operations["runScanner"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/schemas/rule-ir.json": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** JSON Schema of the rule IR (generated from the pydantic models) */
    get: operations["getRuleIrSchema"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/session/environment": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Switch the calling session between live and demo
     * @description Switching *to* `live` requires an elevated session (`/auth/step-up`) and the `live_trading` feature flag to be on; otherwise `403 step_up_required` or `403 live_trading_disabled`. The switch is audited and is broadcast on the `system` WS topic so every pane re-badges consistently.
     */
    post: operations["setSessionEnvironment"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/settings": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get the caller's settings (merged with deployment defaults)
     * @description Returns the effective settings object: deployment defaults overlaid with user overrides.
     *     `_meta.overridden` lists which keys came from the user so the UI can show a "reset to
     *     default" affordance.
     */
    get: operations["getSettings"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    /**
     * Update the caller's settings (partial, deep merge)
     * @description Only leaf keys present in the body are changed. Sending `null` for a leaf resets it to
     *     the deployment default. `trading.one_click_armed` can only be set through the arming
     *     endpoint — attempting it here returns `validation_failed`.
     */
    patch: operations["updateSettings"];
    trace?: never;
  };
  "/settings/arm": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Arm or disarm one-click trading and obtain an arm token
     * @description One-click trading (DOM click-trade, chart click-trade, hotkey fire) is **off by default**
     *     and must be explicitly armed, mirroring Bookmap's arm/lock pattern (digest 09 §1). Arming
     *     returns an `arm_token` with a TTL (`arm_timeout_seconds`, default 300 s, max 3600 s); the
     *     token must accompany any order request flagged `one_click` and is single-session.
     *     Disarming, session end, kill-switch engagement or a risk-cap breach invalidates it
     *     immediately.
     */
    post: operations["armOneClickTrading"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/settings/hotkey-audit": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Audit a destructive hotkey binding change (hotkey.trading_binding_changed)
     * @description The UI posts this when a trading (destructive) command is rebound. The server appends an audit record (C-2.9) attributed to the session principal; actor, role and time are never taken from the body.
     */
    post: operations["recordHotkeyBindingAudit"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/settings/hotkeys": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List hotkey profiles */
    get: operations["listHotkeyProfiles"];
    put?: never;
    /**
     * Create a hotkey profile
     * @description Conflict detection runs server-side: "two bindings sharing the same `keys` within an"
     *     overlapping `scope` are rejected with `conflict` and the offending pair named. Bindings
     *     whose action can send an order must set `requires_arm: "true` — the server rewrites"
     *     `false` to `true` and returns a warning header rather than silently accepting an unsafe
     *     binding.
     */
    post: operations["createHotkeyProfile"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/settings/hotkeys/{hotkeyProfileId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        hotkeyProfileId: components["parameters"]["HotkeyProfileId"];
      };
      cookie?: never;
    };
    get?: never;
    /** Replace a hotkey profile */
    put: operations["updateHotkeyProfile"];
    post?: never;
    /**
     * Delete a hotkey profile
     * @description The active profile cannot be deleted; activate another first.
     */
    delete: operations["deleteHotkeyProfile"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/settings/hotkeys/{hotkeyProfileId}/activate": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        hotkeyProfileId: components["parameters"]["HotkeyProfileId"];
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Make a hotkey profile active */
    post: operations["activateHotkeyProfile"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/system/build": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Build and version information
     * @description Backs the About dialog and the Electron update check. Available to any authenticated user; it exposes no infrastructure detail beyond version and commit.
     */
    get: operations["getBuildInfo"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/telemetry/frontend": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Push one aggregated frontend performance sample (E04-T06)
     * @description ADR-0014 §2 field telemetry. One pre-bucketed payload per 10 s per session (never raw samples);
     *     the server adds bucket counts into `fe_*` histograms labelled only by `screen`, a sitemap route id
     *     (closed `R-nnn` pattern, capped at 8 series). Bodies over 4096 bytes, unknown fields and wrong types are
     *     rejected with 400; more than one push per 10 s (burst 2) per session is rejected with 429. Every
     *     rejection increments `telemetry_rejected_total{reason}` and is never logged verbatim. No symbol,
     *     account or free-form string is accepted (threat A-17).
     */
    post: operations["postFrontendTelemetry"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/trade-groups": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List trade groups (multi-account fan-outs) */
    get: operations["listTradeGroups"];
    put?: never;
    /**
     * Place one ticket across N accounts (fan-out) with per-leg overrides
     * @description The core multi-account primitive (owner decision #5). One intent → one leg per targeted
     *     account, each sized and bracketed by **that account's** profile, with optional per-leg
     *     overrides.
     *
     *     **Resolution order per leg** (later wins): account profile → request-level defaults →
     *     `legs[].overrides`. The server returns the fully resolved parameters per leg in the
     *     response so the UI can show exactly what will be sent *before* fills arrive.
     *
     *     **Execution semantics**
     *     * `atomicity: best_effort` (default) — every leg is attempted; failures are reported
     *       per leg and the group ends `partially_open`.
     *     * `atomicity: all_or_none` — legs are pre-validated (risk caps, balances, instrument
     *       filters, rate budget) and the group is abandoned without sending anything if any leg
     *       fails validation. True cross-account atomicity is impossible once orders are sent, so
     *       a post-send failure triggers `compensate: "flatten_filled` when requested."
     *     * Fan-out is scheduled against a **per-UID** rate budget (Bybit limits are per-UID and
     *       shared across keys, digest 06 §13); `max_concurrent_legs` bounds parallelism, default 5.
     *     * Every leg carries a native exchange-side stop (arch P4). A leg whose resolved
     *       parameters would have no stop is rejected at validation, never sent.
     *
     *     **Algo orders.** `algo` selects an emulated execution strategy — Bybit exposes none of
     *     these through the public API (digest 09 §2/§6): `oco` (race two orders, cancel the loser
     *     on the WS fill notice), `iceberg` (client-side slicing; `orderType=Iceberg` does not
     *     exist on `/v5/order/create`), `twap` (timed slices), `chase` (repeated cancel/replace to
     *     stay at the touch), `scaled` (ladder of N limits, equal/linear/geometric distribution).
     *     Child orders are created with `intent: "algo_child` and linked to the leg."
     */
    post: operations["createTradeGroup"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/trade-groups/{tradeGroupId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        tradeGroupId: components["parameters"]["TradeGroupId"];
      };
      cookie?: never;
    };
    /** Get a trade group with all legs and resolved parameters */
    get: operations["getTradeGroup"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/trade-groups/{tradeGroupId}/amend": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        tradeGroupId: components["parameters"]["TradeGroupId"];
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Amend every live order in a trade group (optionally per leg)
     * @description Applies the same amendment to all non-terminal orders of the group, or per-leg values when `legs` is supplied. Reports per-leg outcome; a leg whose order is already terminal is reported `ok: true, affected: 0`.
     */
    post: operations["amendTradeGroup"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/trade-groups/{tradeGroupId}/cancel": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        tradeGroupId: components["parameters"]["TradeGroupId"];
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Cancel every live order in a trade group
     * @description Optionally also flattens whatever already filled (`flatten_filled: true`), which issues reduce-only market closes per leg — used by the "abort" button in the ticket.
     */
    post: operations["cancelTradeGroup"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/trade-groups/preview": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Dry-run a fan-out - resolved per-account sizing, risk and rejections
     * @description Runs the full fan-out pipeline (24-internal-schemas.md section 9.3 sizing, 9.4 fan-out) **without submitting anything**, returning exactly what each leg would send. Legs that would be rejected (cap breach, symbol not allowed, insufficient margin, rate budget exhausted) are returned with their reason so the ticket can show them before the user commits. Never mutates state and is therefore safe to call on every keystroke; it is rate-limited rather than idempotency-keyed.
     */
    post: operations["previewTradeGroup"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/trading/kill-switch": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Current kill-switch state */
    get: operations["getKillSwitch"];
    put?: never;
    /**
     * Engage or release the kill-switch
     * @description Engaging immediately (a) refuses all new order/amend requests with `trading_disabled`,
     *     (b) optionally cancels all open orders, (c) optionally flattens all positions with
     *     reduce-only market orders, and (d) disarms every `armed` rule. Scope is `global`
     *     (whole deployment) or a specific account set.
     *
     *     Managers may engage the switch for accounts in their own scope; only the owner may
     *     engage it globally or **release** it. Bybit's dead-man's-switch
     *     (`POST /v5/order/disconnected-cancel-all`) is armed separately by the OMS for `inverse`
     *     only — it is not available for `linear`, so the local kill-switch is the operative
     *     control here.
     *
     *     Every transition writes a `critical` audit entry and broadcasts a `system` WS frame.
     */
    post: operations["setKillSwitch"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/users": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List users */
    get: operations["listUsers"];
    put?: never;
    /**
     * Invite a user
     * @description Creates a user in `invited` state and returns a one-time invite link valid for 72 h. No password is set by the owner.
     */
    post: operations["createUser"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/users/{userId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        userId: components["parameters"]["UserId"];
      };
      cookie?: never;
    };
    /** Get a user */
    get: operations["getUser"];
    put?: never;
    post?: never;
    /**
     * Disable a user (soft delete)
     * @description Sets `status=disabled`, revokes all sessions and all account grants. Rows are never
     *     hard-deleted — the audit log and journal reference them. Passing `?purge=true`
     *     additionally anonymises PII after the 90-day retention window.
     */
    delete: operations["deleteUser"];
    options?: never;
    head?: never;
    /**
     * Update a user (status, roles, MFA requirement, display name)
     * @description The owner cannot demote or disable their own account — the last `owner` is protected (`conflict`).
     */
    patch: operations["updateUser"];
    trace?: never;
  };
  "/users/{userId}/account-access": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        userId: components["parameters"]["UserId"];
      };
      cookie?: never;
    };
    /** List the exchange accounts a user may see/trade */
    get: operations["listUserAccountAccess"];
    /**
     * Replace a user's account-access grants
     * @description This is the isolation boundary between managers. Changes take effect on the next request; existing WS subscriptions for revoked accounts are force-closed with an `unsubscribed` frame (see 23-ws-protocol.md §9).
     */
    put: operations["setUserAccountAccess"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/users/{userId}/invite": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        userId: string;
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Revoke open invites and mint a new link (shown once) */
    post: operations["reissueInvite"];
    /** Revoke the pending invitation */
    delete: operations["revokeInvite"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/users/{userId}/mfa/reset": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        userId: components["parameters"]["UserId"];
      };
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Owner-initiated TOTP reset (owner, step-up `users`)
     * @description Revokes the target's TOTP methods and all their sessions. Does not cancel orders or flatten positions and reveals no secret. Self-reset is refused. Audited as `auth.mfa_reset_by_owner`. When the position state is unavailable the request must carry `acknowledge_unknown_positions: true`, otherwise `409 positions_unknown`.
     */
    post: operations["resetUserMfa"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/users/{userId}/mfa/reset-preview": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        userId: components["parameters"]["UserId"];
      };
      cookie?: never;
    };
    /** Show the target's open-position state before an owner TOTP reset */
    get: operations["previewMfaReset"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/users/{userId}/roles": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        userId: components["parameters"]["UserId"];
      };
      cookie?: never;
    };
    get?: never;
    /** Replace a user's role set */
    put: operations["setUserRoles"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/users/invites": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List pending invitations */
    get: operations["listPendingInvites"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/watchlists": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List own watchlists */
    get: operations["listWatchlists"];
    put?: never;
    /** Create a watchlist */
    post: operations["createWatchlist"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/watchlists/{watchlistId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        watchlistId: string;
      };
      cookie?: never;
    };
    get?: never;
    /** Replace a watchlist */
    put: operations["updateWatchlist"];
    post?: never;
    /** Delete a watchlist */
    delete: operations["deleteWatchlist"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/workspaces": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** List the caller's workspaces */
    get: operations["listWorkspaces"];
    put?: never;
    /** Create a workspace */
    post: operations["createWorkspace"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/workspaces/{workspaceId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspaceId: components["parameters"]["WorkspaceId"];
      };
      cookie?: never;
    };
    /** Get a workspace with its layouts */
    get: operations["getWorkspace"];
    /** Replace a workspace's metadata */
    put: operations["updateWorkspace"];
    post?: never;
    /** Delete a workspace and its layouts */
    delete: operations["deleteWorkspace"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/workspaces/{workspaceId}/export": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspaceId: components["parameters"]["WorkspaceId"];
      };
      cookie?: never;
    };
    /**
     * Export a workspace as a portable bundle
     * @description The bundle is self-contained and contains no credentials, account identifiers or PnL figures - only presentation state - so it is safe to share. Import is `POST /workspaces` with `from_bundle`.
     */
    get: operations["exportWorkspace"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/workspaces/{workspaceId}/layouts": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspaceId: components["parameters"]["WorkspaceId"];
      };
      cookie?: never;
    };
    /** List layouts in a workspace */
    get: operations["listLayouts"];
    put?: never;
    /**
     * Create a layout (pane grid)
     * @description A layout is a grid of panes; each pane declares its kind (`chart`, `dom`, `tape`,
     *     `footprint`, `heatmap`, `orders`, `positions`, `journal`, `rules`, `watchlist`,
     *     `metrics`), its symbol, its linked symbol-group colour, and a reference to a chart
     *     template. Panes are persisted verbatim so the Electron shell can restore the exact
     *     workspace on launch.
     */
    post: operations["createLayout"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/workspaces/{workspaceId}/layouts/{layoutId}": {
    parameters: {
      query?: never;
      header?: never;
      path: {
        layoutId: components["parameters"]["LayoutId"];
        workspaceId: components["parameters"]["WorkspaceId"];
      };
      cookie?: never;
    };
    /** Get a layout */
    get: operations["getLayout"];
    /**
     * Replace a layout
     * @description Called on pane rearrangement with a 2-second debounce. `If-Match` prevents a stale tab from clobbering a newer arrangement made in another window.
     */
    put: operations["updateLayout"];
    post?: never;
    /** Delete a layout */
    delete: operations["deleteLayout"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
}
export type webhooks = Record<string, never>;
export interface components {
  schemas: {
    AccountAccessGrant: components["schemas"]["AccountAccessGrantInput"] & {
      account_label?: string;
      environment?: components["schemas"]["Environment"];
      /** Format: date-time */
      granted_at?: string;
      /** Format: uuid */
      granted_by?: string;
    };
    AccountAccessGrantInput: {
      /** Format: uuid */
      exchange_account_id: string;
      /**
       * @description `trade` implies `read`.
       * @enum {string}
       */
      level: "read" | "trade";
    };
    /** @enum {string} */
    AccountKind: "main" | "sub";
    AccountProfile: components["schemas"]["AccountProfileInput"] & {
      /** Format: date-time */
      created_at?: string;
      /** Format: uuid */
      exchange_account_id?: string;
      /** Format: uuid */
      id?: string;
      is_active?: boolean;
      /** Format: date-time */
      updated_at?: string;
    };
    AccountProfileInput: {
      /** @description Empty means "all instruments permitted by the deployment". */
      allowed_symbols?: components["schemas"]["Symbol"][];
      default_time_in_force?: components["schemas"]["TimeInForce"];
      default_tpsl_mode?: components["schemas"]["TpSlMode"];
      leverage: components["schemas"]["Decimal"];
      name: string;
      /**
       * @description Always true; the safety invariant cannot be disabled (arch P4).
       * @default true
       * @constant
       */
      require_native_stop: true;
      risk_caps?: components["schemas"]["RiskCaps"];
      sizing: components["schemas"]["Sizing"];
      stop_loss?: components["schemas"]["Offset"];
      take_profit?: components["schemas"]["Offset"];
      trailing_stop?: components["schemas"]["Offset"];
    };
    AddRecordedSymbolRequest: {
      /**
       * @default 200
       * @enum {integer}
       */
      depth: 1 | 50 | 200 | 500;
      /** @default false */
      pinned: boolean;
      /** @default 30 */
      retention_days: number | null;
      /**
       * @default [
       *       "trades",
       *       "orderbook_delta",
       *       "tickers",
       *       "liquidations"
       *     ]
       */
      streams: components["schemas"]["StreamKind"][];
      symbol: components["schemas"]["Symbol"];
    };
    AdminOverview: {
      accounts?: {
        enabled?: number;
        keys_expiring_30d?: number;
        keys_invalid?: number;
        total?: number;
      };
      incidents_open?: number;
      recorder?: {
        lag_seconds_p99?: number;
        symbols_degraded?: number;
        symbols_recording?: number;
      };
      storage?: {
        days_until_full?: number | null;
        /** Format: int64 */
        free_bytes?: number;
        /** Format: int64 */
        used_bytes?: number;
      };
      trading?: {
        kill_switch_engaged?: boolean;
        live_enabled?: boolean;
        open_positions?: number;
      };
      users?: {
        active?: number;
        total?: number;
        without_mfa?: number;
      };
    };
    AggregatePosition: {
      accounts?: {
        /** Format: uuid */
        exchange_account_id?: string;
        /** @enum {string} */
        side?: "long" | "short";
        size?: components["schemas"]["Decimal"];
        unrealised_pnl?: components["schemas"]["Decimal"];
      }[];
      gross_size?: components["schemas"]["Decimal"];
      net_size?: components["schemas"]["Decimal"];
      symbol?: components["schemas"]["Symbol"];
      unrealised_pnl?: components["schemas"]["Decimal"];
      weighted_avg_price?: components["schemas"]["Decimal"];
    };
    Alert: components["schemas"]["AlertInput"] & {
      /** Format: date-time */
      created_at?: string;
      fire_count?: number;
      /** Format: uuid */
      id?: string;
      /** Format: date-time */
      last_fired_at?: string | null;
      /** Format: uuid */
      owner_user_id?: string;
      /** Format: date-time */
      updated_at?: string;
    };
    /** @enum {string} */
    AlertChannel: "in_app" | "email" | "webhook" | "push" | "desktop";
    /**
     * @description The condition half of the rule IR, reused by alerts. Alerts have no `actions` block
     *     - the action is always "notify on the configured channels", so an alert can never
     *     place an order regardless of what the user authors.
     */
    AlertConditionIr: {
      conditions: components["schemas"]["RuleCondition"];
      /** @enum {integer} */
      ir_version: 1;
      limits?: components["schemas"]["RuleLimits"];
      trigger: components["schemas"]["RuleTrigger"];
      variables?: {
        [key: string]: components["schemas"]["RuleOperand"];
      };
    };
    AlertDelivery: {
      /** Format: date-time */
      acked_at?: string | null;
      /** Format: uuid */
      alert_id?: string;
      channel?: components["schemas"]["AlertChannel"];
      error?: string | null;
      /** Format: date-time */
      fired_at?: string;
      /** Format: int64 */
      id?: number;
      message?: string;
      severity?: components["schemas"]["Severity"];
      status?: components["schemas"]["DeliveryStatus"];
      symbol?: components["schemas"]["Symbol"] | null;
      title?: string;
    };
    AlertInput: {
      channels: components["schemas"]["AlertChannel"][];
      condition_ir: components["schemas"]["AlertConditionIr"];
      /** @default true */
      enabled: boolean;
      /** Format: uuid */
      exchange_account_id?: string | null;
      /** Format: date-time */
      expires_at?: string | null;
      /** @description Mustache-style placeholders resolved from the rule context. */
      message_template?: string;
      name: string;
      severity?: components["schemas"]["Severity"];
      symbol?: components["schemas"]["Symbol"] | null;
      /**
       * @default once
       * @enum {string}
       */
      trigger_mode: "once" | "every_time" | "once_per_bar";
      /** Format: uri */
      webhook_url?: string | null;
    };
    /** @enum {string} */
    AlgoKind: "none" | "oco" | "iceberg" | "twap" | "chase" | "scaled" | "bracket";
    /**
     * @description Emulated execution algorithms. None of these exist as native Bybit order types on
     *     `/v5/order/create`; all are implemented client-of-exchange-side by the OMS (digest 09).
     */
    AlgoSpec: {
      bracket?: {
        move_stop_to_breakeven_at?: components["schemas"]["Offset"];
        take_profit_levels?: {
          offset?: components["schemas"]["Offset"];
          pct_of_position?: components["schemas"]["Decimal"];
        }[];
      };
      chase?: {
        /** @default false */
        fallback_to_market: boolean;
        /** @default 20 */
        max_chases: number;
        max_slippage_ticks?: number;
        /** @default 0 */
        offset_ticks: number;
        /** @default 250 */
        repricing_interval_ms: number;
      };
      iceberg?: {
        display_qty?: components["schemas"]["Decimal"];
        /** @default 0 */
        randomize_display_pct: number;
        /** @default 100 */
        refresh_on_fill_pct: number;
      };
      kind: components["schemas"]["AlgoKind"];
      oco?: {
        /**
         * @description Max time to cancel the loser after the winner's fill notice arrives on the WS.
         * @default 2000
         */
        cancel_timeout_ms: number;
        other_price?: components["schemas"]["Decimal"];
        other_trigger?: components["schemas"]["TriggerSpec"];
      };
      scaled?: {
        /** @enum {string} */
        distribution?: "equal" | "linear" | "geometric";
        from_price?: components["schemas"]["Decimal"];
        levels?: number;
        /** @description >1 weights size toward `to_price`. */
        skew?: components["schemas"]["Decimal"];
        to_price?: components["schemas"]["Decimal"];
      };
      twap?: {
        duration_seconds?: number;
        /** @description Omit for market slices. */
        limit_offset_ticks?: number;
        /** @default 0 */
        randomize_pct: number;
        slices?: number;
      };
    };
    AmendOrderRequest: {
      price?: components["schemas"]["Decimal"];
      qty?: components["schemas"]["Decimal"];
      stop_loss?: components["schemas"]["Offset"] | null;
      take_profit?: components["schemas"]["Offset"] | null;
      trigger_price?: components["schemas"]["Decimal"];
    };
    AmendTradeGroupRequest: {
      /** @description Per-leg amendments; when present, the top-level fields are ignored for those legs. */
      legs?: {
        /** Format: uuid */
        leg_id: string;
        price?: components["schemas"]["Decimal"];
        qty?: components["schemas"]["Decimal"];
        stop_loss?: components["schemas"]["Offset"] | null;
        take_profit?: components["schemas"]["Offset"] | null;
      }[];
      price?: components["schemas"]["Decimal"];
      stop_loss?: components["schemas"]["Offset"] | null;
      take_profit?: components["schemas"]["Offset"] | null;
      trailing_stop?: components["schemas"]["Offset"] | null;
    };
    ApiKey: {
      /** Format: date-time */
      created_at?: string;
      /** Format: uuid */
      exchange_account_id: string;
      /** Format: date-time */
      expires_at?: string | null;
      /** Format: uuid */
      id: string;
      /** @description First and last 4 characters only. */
      key_id_masked: string;
      label?: string | null;
      /** Format: date-time */
      last_verified_at?: string | null;
      read_only?: boolean;
      status: components["schemas"]["KeyStatus"];
    };
    ApiKeyRotation: {
      new_key?: components["schemas"]["ApiKey"];
      /** Format: uuid */
      old_key_id?: string;
      /** Format: date-time */
      overlap_until?: string;
      /** Format: uuid */
      rotation_id?: string;
      /** @enum {string} */
      state?: "overlapping" | "completed" | "failed";
      verification?: components["schemas"]["KeyVerification"];
    };
    ApiKeyWithVerification: {
      key?: components["schemas"]["ApiKey"];
      verification?: components["schemas"]["KeyVerification"];
    };
    AuditEntry: {
      action?: string;
      /** Format: uuid */
      actor_user_id?: string | null;
      actor_username?: string | null;
      detail?: {
        [key: string]: unknown;
      };
      entry_hash?: string;
      /** Format: int64 */
      id?: number;
      ip?: string | null;
      outcome?: components["schemas"]["AuditOutcome"];
      prev_hash?: string | null;
      request_id?: string | null;
      severity?: components["schemas"]["Severity"];
      subject_id?: string | null;
      subject_type?: string;
      /** Format: date-time */
      ts?: string;
      user_agent?: string | null;
    };
    /** @enum {string} */
    AuditOutcome: "success" | "failure" | "denied";
    AuthenticatedResponse: {
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      status: "authenticated";
      tokens: components["schemas"]["TokenBundle"];
      user: components["schemas"]["User"];
    };
    Backup: {
      checksum_sha256?: string | null;
      encrypted?: boolean;
      error?: string | null;
      /** Format: date-time */
      finished_at?: string | null;
      /** Format: uuid */
      id?: string;
      kind?: components["schemas"]["BackupKind"];
      location?: string;
      /** Format: date-time */
      retention_until?: string | null;
      /** Format: int64 */
      size_bytes?: number | null;
      /** Format: date-time */
      started_at?: string;
      status?: components["schemas"]["BackupStatus"];
      /** Format: date-time */
      verified_at?: string | null;
    };
    /** @enum {string} */
    BackupKind: "pg_basebackup" | "pg_dump" | "questdb_snapshot" | "parquet_sync" | "config_bundle";
    /** @enum {string} */
    BackupStatus: "running" | "ok" | "failed" | "verified" | "restored";
    Bar: {
      c: components["schemas"]["Decimal"];
      /**
       * Format: date-time
       * @description Present for non-time bars.
       */
      close_time?: string;
      /** @description False for the in-progress bar (Bybit `confirm` semantics). */
      confirm?: boolean;
      cvd?: components["schemas"]["Decimal"] | null;
      delta?: components["schemas"]["Decimal"] | null;
      /**
       * Format: int64
       * @description ADR-0033 series generation (= epoch); 0 until ADR-0033 is ratified. Always present on /market/bars.
       */
      generation?: number;
      h: components["schemas"]["Decimal"];
      /**
       * Format: int64
       * @description Bar index, strictly increasing within (series, generation) (24 §3.1). Always present on /market/bars; `t` may repeat for non-time bars (#2014).
       */
      index?: number;
      l: components["schemas"]["Decimal"];
      max_delta?: components["schemas"]["Decimal"] | null;
      min_delta?: components["schemas"]["Decimal"] | null;
      o: components["schemas"]["Decimal"];
      /**
       * Format: date-time
       * @description Bar open time; not unique for non-time bars.
       */
      t: string;
      trades?: number;
      turnover?: components["schemas"]["Decimal"];
      v: components["schemas"]["Decimal"];
    };
    /** @enum {string} */
    BarType: "time" | "tick" | "volume" | "range" | "delta" | "renko" | "pnf" | "heikin_ashi";
    BuildInfo: {
      api_version?: string;
      /** Format: date-time */
      built_at: string;
      commit: string;
      electron_version?: string | null;
      version: string;
      ws_protocol_version?: string;
    };
    BulkAccountResult: {
      requested?: number;
      results?: {
        affected?: number;
        error?: components["schemas"]["LegError"] | null;
        /** Format: uuid */
        exchange_account_id?: string;
        ok?: boolean;
      }[];
      succeeded?: number;
    };
    BulkLegResult: {
      requested?: number;
      results?: {
        affected?: number;
        error?: components["schemas"]["LegError"] | null;
        /** Format: uuid */
        exchange_account_id?: string;
        /** Format: uuid */
        leg_id?: string;
        ok?: boolean;
      }[];
      succeeded?: number;
      /** Format: uuid */
      trade_group_id?: string;
    };
    CancelAllRequest: {
      /** @description Empty = every account in scope. */
      exchange_account_ids?: string[];
      /**
       * @description Protects TP/SL exits from a blanket cancel.
       * @default true
       */
      exclude_reduce_only: boolean;
      intents?: components["schemas"]["OrderIntent"][];
      symbol?: components["schemas"]["Symbol"] | null;
    };
    CapacityReport: {
      ingestion?: {
        dropped_last_hour?: number;
        messages_per_sec?: number;
        queue_depth?: number;
      };
      rate_budget?: {
        /** Format: uuid */
        exchange_account_id?: string;
        label?: string;
        limit_per_minute?: number;
        peak_used_per_minute?: number;
        utilisation_pct?: number;
      }[];
      storage?: {
        /** Format: int64 */
        daily_growth_bytes?: number;
        days_until_full?: number | null;
        /** Format: int64 */
        free_bytes?: number;
        per_symbol?: {
          /** Format: int64 */
          daily_growth_bytes?: number;
          pinned?: boolean;
          retention_days?: number | null;
          symbol?: components["schemas"]["Symbol"];
          /** Format: int64 */
          used_bytes?: number;
        }[];
        /** Format: int64 */
        used_bytes?: number;
      };
    };
    ChangePasswordRequest: {
      /** Format: password */
      current_password: string;
      /** Format: password */
      new_password: string;
    };
    ChartTemplate: components["schemas"]["ChartTemplateInput"] & {
      /** Format: date-time */
      created_at?: string;
      /** Format: uuid */
      id?: string;
      /** Format: uuid */
      owner_user_id?: string;
      /** Format: date-time */
      updated_at?: string;
    };
    ChartTemplateInput: {
      /** @description Chart configuration blob; validated against the chart-engine schema in `26-chart-engine-design.md`. */
      config: {
        bar_type?: components["schemas"]["BarType"];
        /** @enum {string} */
        chart_type?:
          | "candlestick"
          | "hollow_candlestick"
          | "bar"
          | "line"
          | "area"
          | "baseline"
          | "step_line"
          | "equi_volume"
          | "delta_volume"
          | "heikin_ashi";
        colours?: {
          [key: string]: string;
        };
        footprint?: {
          /** @enum {string} */
          cell_type?: "volume" | "bid_ask" | "delta" | "delta_total";
          /** @enum {string} */
          display_mode?: "profile" | "box";
          imbalance_ratio?: number;
          min_stack?: number;
          price_grouping?: number;
          show_unfinished_auctions?: boolean;
        };
        indicators?: {
          code?: string;
          /** @enum {string} */
          pane?: "main" | "sub1" | "sub2" | "sub3";
          params?: {
            [key: string]: unknown;
          };
        }[];
        param?: string;
        price_scale?: {
          auto_fit?: boolean;
          /** @enum {string} */
          mode?: "linear" | "logarithmic" | "percent";
          right_margin_bars?: number;
        };
      } & {
        [key: string]: unknown;
      };
      name: string;
      /** @default false */
      shared: boolean;
    };
    ClosedPnl: {
      avg_entry_price?: components["schemas"]["Decimal"];
      avg_exit_price?: components["schemas"]["Decimal"];
      /** Format: date-time */
      closed_at?: string;
      closed_pnl?: components["schemas"]["Decimal"];
      cum_entry_value?: components["schemas"]["Decimal"];
      cum_exit_value?: components["schemas"]["Decimal"];
      /** Format: uuid */
      exchange_account_id?: string;
      /** Format: uuid */
      id?: string;
      leverage?: components["schemas"]["Decimal"];
      /** Format: date-time */
      opened_at?: string;
      qty?: components["schemas"]["Decimal"];
      side?: components["schemas"]["JournalSide"];
      symbol?: components["schemas"]["Symbol"];
    };
    ClosePositionRequest: {
      arm_token?: string | null;
      order_type: components["schemas"]["OrderType"];
      /** @description 0 < pct <= 100. Mutually exclusive with `qty`. */
      pct?: components["schemas"]["Decimal"];
      price?: components["schemas"]["Decimal"];
      qty?: components["schemas"]["Decimal"];
      time_in_force?: components["schemas"]["TimeInForce"];
    };
    /**
     * @description `not_deployed` = module not built yet; ranks as healthy for `overall`. Rank: down > warning > degraded > healthy.
     * @enum {string}
     */
    ComponentState: "healthy" | "degraded" | "warning" | "down" | "not_deployed";
    CreateApiKeyRequest: {
      /** Format: password */
      api_key: string;
      /** Format: password */
      api_secret: string;
      /** @description Must equal the account's `exchange_uid`; mismatch is rejected. */
      expected_uid?: string;
      label?: string;
      /** @default false */
      read_only: boolean;
    };
    CreateExchangeAccountRequest: {
      environment: components["schemas"]["Environment"];
      exchange: components["schemas"]["ExchangeCode"];
      exchange_uid: string;
      kind: components["schemas"]["AccountKind"];
      label: string;
      /**
       * Format: uuid
       * @description Required when `kind=sub`.
       */
      parent_account_id?: string | null;
    };
    CreateReplaySessionRequest: {
      /** @default false */
      autostart: boolean;
      /**
       * @default 200
       * @enum {integer}
       */
      depth: 1 | 50 | 200 | 500;
      /** Format: date-time */
      from: string;
      /** Format: uuid */
      paper_account_id?: string | null;
      /**
       * @description 0 = as fast as possible (used by rule simulation).
       * @default 1
       */
      speed: number;
      streams?: components["schemas"]["StreamKind"][];
      symbols: components["schemas"]["Symbol"][];
      /** Format: date-time */
      to: string;
    };
    CreateTradeGroupRequest: {
      algo?: components["schemas"]["AlgoSpec"];
      arm_token?: string | null;
      /**
       * @default best_effort
       * @enum {string}
       */
      atomicity: "best_effort" | "all_or_none";
      /**
       * @description Applies when `all_or_none` fails after sending.
       * @default none
       * @enum {string}
       */
      compensate: "none" | "flatten_filled";
      defaults?: {
        price?: components["schemas"]["Decimal"];
        sizing?: components["schemas"]["Sizing"];
        stop_loss?: components["schemas"]["Offset"];
        take_profit?: components["schemas"]["Offset"];
        time_in_force?: components["schemas"]["TimeInForce"];
        tpsl_mode?: components["schemas"]["TpSlMode"];
        trailing_stop?: components["schemas"]["Offset"];
        trigger?: components["schemas"]["TriggerSpec"];
      };
      /** @default entry */
      intent: components["schemas"]["OrderIntent"];
      legs: components["schemas"]["TradeGroupLegInput"][];
      /** @default 5 */
      max_concurrent_legs: number;
      note?: string;
      order_type: components["schemas"]["OrderType"];
      /** @default false */
      reduce_only: boolean;
      /**
       * Format: uuid
       * @description Set when the group originates from the rule engine.
       */
      rule_id?: string | null;
      side: components["schemas"]["OrderSide"];
      symbol: components["schemas"]["Symbol"];
    };
    CreateUserRequest: {
      account_access?: components["schemas"]["AccountAccessGrantInput"][];
      display_name?: string;
      /** Format: email */
      email: string;
      /** @default true */
      mfa_required: boolean;
      /** @description Invites grant `viewer` only (#2109); the owner promotes after activation. */
      roles: "viewer"[];
      username: string;
    };
    DataCoverage: {
      /** Format: date-time */
      generated_at?: string;
      streams?: {
        gaps?: {
          /** Format: date-time */
          from?: string;
          /** @enum {string} */
          reason?:
            | "ws_disconnect"
            | "backend_restart"
            | "retention_purge"
            | "never_recorded"
            | "exchange_outage";
          /** Format: date-time */
          to?: string;
        }[];
        intervals?: {
          /** Format: date-time */
          from?: string;
          /** Format: int64 */
          rows?: number;
          /** @enum {string} */
          tier?: "questdb" | "parquet";
          /** Format: date-time */
          to?: string;
        }[];
        stream?: components["schemas"]["StreamKind"];
      }[];
      symbol?: components["schemas"]["Symbol"];
    };
    DataMeta: components["schemas"]["PageMeta"] & {
      /** @description Requested-range gaps the local cache has no bars for yet (QA defect #1622 blocker 1 / E08-S06 "Cache hit" scenario — `GET /market/klines` is cache-only until a live `KlineFetcher` lands, so it reports holes here instead of silently pretending the exchange was consulted). */
      coverage_holes?: {
        /** @description Gap end, exchange epoch microseconds. */
        end_us: number;
        /** @description Gap start, exchange epoch microseconds. */
        start_us: number;
      }[];
      /** Format: date-time */
      generated_at?: string;
      /** Format: date-time */
      recording_started_at?: string | null;
      /** @description Tiers whose rows are in this response (provenance, 24 §2): `tape` = bars built locally from the recorded trade tape; `questdb` = exchange-kline rows in the hot tier; `parquet` = cold tier; `exchange_rest` = rows just backfilled from Bybit. */
      sources?: ("questdb" | "parquet" | "postgres" | "exchange_rest" | "memory" | "tape")[];
    };
    /**
     * @description Arbitrary-precision decimal transported as a string (convention C6).
     * @example 63120.50
     * @example -0.0004
     * @example 0
     */
    Decimal: string;
    /** @enum {string} */
    DeliveryStatus: "queued" | "sent" | "failed" | "suppressed" | "acked";
    /** @description Thresholds for the estimated detectors. Every detector here is a heuristic over anonymous public data; changing a threshold changes sensitivity, never correctness. */
    DetectorConfig: {
      absorption?: {
        /** @default true */
        enabled: boolean;
        /** @default 1 */
        max_price_move_ticks: number;
        /** @default 3 */
        min_volume_multiple: number;
      };
      big_trade?: {
        absolute_usd?: components["schemas"]["Decimal"];
        /**
         * @default percentile
         * @enum {string}
         */
        mode: "absolute_usd" | "percentile";
        /** @default 99 */
        percentile: number;
      };
      exhaustion?: {
        /** @default true */
        enabled: boolean;
        /** @default 0.5 */
        min_delta_divergence: number;
      };
      iceberg?: {
        /** @default true */
        enabled: boolean;
        /** @default 3 */
        min_reloads: number;
        /** @default 0 */
        price_tolerance_ticks: number;
        /** @default 5000 */
        window_ms: number;
      };
      stop_run?: {
        /** @default true */
        enabled: boolean;
        /** @default 20 */
        lookback_bars: number;
        /** @default 2 */
        penetration_ticks: number;
        /** @default 60 */
        reversal_pct: number;
      };
    };
    DetectorMethodology: {
      /** @description The inference being made, stated plainly. */
      assumption: string;
      confidence_basis?: string | null;
      /** @enum {string} */
      detector: "iceberg" | "stop_run" | "absorption" | "exhaustion" | "big_trade" | "regime";
      display_name?: string;
      false_positive_modes: string[];
      inputs: string[];
    };
    Drawing: {
      /** Format: date-time */
      created_at: string;
      geometry: components["schemas"]["DrawingGeometry"];
      /** Format: uuid */
      id: string;
      label: string | null;
      /** Format: uuid */
      layout_id: string | null;
      locked: boolean;
      /** Format: uuid */
      owner_user_id: string;
      style: components["schemas"]["DrawingStyle"];
      symbol: components["schemas"]["Symbol"];
      tool: components["schemas"]["DrawingTool"];
      /**
       * Format: date-time
       * @description Concurrency token (also the `ETag`). Always serialised `YYYY-MM-DDTHH:MM:SS.ffffffZ` (6 fractional digits) and strictly increasing on every write.
       */
      updated_at: string;
      visible: boolean;
      z_index: number;
    };
    DrawingBatchCreateOp: {
      drawing: components["schemas"]["DrawingInput"];
      /**
       * Format: uuid
       * @description Optional client-chosen id (UUIDv7 recommended); taken ids are `409 id_unavailable`.
       */
      id?: string;
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      op: "create";
    };
    DrawingBatchDeleteOp: {
      /** Format: uuid */
      id: string;
      /**
       * Format: date-time
       * @description `updated_at` token of the version being deleted.
       */
      if_match: string;
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      op: "delete";
    };
    DrawingBatchRequest: {
      /** @description Applied in order. More than 200 items is `413 payload_too_large`. */
      operations: (
        | components["schemas"]["DrawingBatchCreateOp"]
        | components["schemas"]["DrawingBatchUpdateOp"]
        | components["schemas"]["DrawingBatchDeleteOp"]
      )[];
    };
    DrawingBatchResult: {
      created: components["schemas"]["Drawing"][];
      deleted: string[];
      updated: components["schemas"]["Drawing"][];
    };
    DrawingBatchUpdateOp: {
      drawing: components["schemas"]["DrawingInput"];
      /** Format: uuid */
      id: string;
      /**
       * Format: date-time
       * @description `updated_at` token of the version being replaced.
       */
      if_match: string;
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      op: "update";
    };
    /** @description Chart-space geometry (time + price, never pixels). Per-tool point counts and key rules: see `DrawingTool`. */
    DrawingGeometry: {
      /** @description Standard-deviation bands (`anchored_vwap` only). */
      bands?: (1 | 2 | 3)[];
      extend_left?: boolean;
      extend_right?: boolean;
      /** @description Fibonacci levels (fib tools only): unique finite numbers; a duplicate is rule `duplicate_level`. */
      levels?: number[];
      points: components["schemas"]["DrawingPoint"][];
      /** @description Text content (`text` and `callout` only), 1..1000 code points after control-character stripping (LF is kept). */
      text?: string;
    };
    DrawingInput: {
      geometry: components["schemas"]["DrawingGeometry"];
      /**
       * @description Display label, 1..120 code points after control-character stripping.
       * @default null
       */
      label: string | null;
      /**
       * Format: uuid
       * @description Layout scope. A non-null value must be one of the caller's live layouts, else 422 rule `layout_not_found`; every non-null value is refused until layouts ship (E15-T01).
       * @default null
       */
      layout_id: string | null;
      /** @default false */
      locked: boolean;
      /** @description Optional; omitted means no style overrides (stored as `{}`, returned as `{}`). */
      style?: components["schemas"]["DrawingStyle"];
      /** @description Symbol. Additionally limited to at most 20 characters in total (the storage domain `symbol_code`); longer values are `422`. Generators do not carry a `maxLength` next to the `Symbol` pattern, so the server enforces it. */
      symbol: components["schemas"]["Symbol"];
      tool: components["schemas"]["DrawingTool"];
      /** @default true */
      visible: boolean;
      /** @default 0 */
      z_index: number;
    };
    DrawingPoint: {
      /**
       * @description Chart-space price coordinate as a decimal string; may be negative. Stored and returned verbatim, never converted to a float.
       * @example 61200.00
       * @example -12.5
       */
      p: string;
      /**
       * @description RFC 3339 UTC instant with `Z`, at most millisecond precision, years 2000-2099.
       * @example 2026-09-13T12:00:00Z
       * @example 2026-09-13T12:00:00.250Z
       */
      t: string;
    };
    DrawingStyle: {
      colour?: string;
      /** @enum {string} */
      dash?: "solid" | "dashed" | "dotted";
      fill_colour?: string | null;
      fill_opacity?: number;
      font_size?: number;
      width?: number;
    };
    /**
     * @description Drawing tool. **Open-ended for readers:** clients must tolerate values they do not know, so
     *     adding a tool is an additive change (C-6.3). Writers must send one of the listed values.
     *
     *     Required point count per tool (`geometry.points`):
     *
     *     - exactly 1: `horizontal_line`, `vertical_line`, `text`, `anchored_vwap`
     *     - exactly 2: `trendline`, `ray`, `extended_line`, `rectangle`, `ellipse`, `fib_retracement`,
     *       `fib_timezone`, `gann_fan`, `arrow`, `callout`, `measure`, `price_range`, `date_range`
     *     - exactly 3: `parallel_channel`, `triangle`, `fib_extension`, `pitchfork`, `long_position`,
     *       `short_position`
     *     - 2..500: `brush`; 2..100: `polyline`
     *
     *     Tool-specific `geometry` keys (any other combination is `422` rule `property_not_allowed_for_tool`):
     *     `text` is required for `text` and `callout` (rule `text_required`) and forbidden elsewhere;
     *     `levels` only for `fib_retracement`, `fib_extension`, `fib_timezone`; `bands` only for
     *     `anchored_vwap`; `extend_left` / `extend_right` are allowed on every tool.
     *     A horizontal ray is a `horizontal_line` with `extend_left: false` and `extend_right: true`.
     * @enum {string}
     */
    DrawingTool:
      | "trendline"
      | "horizontal_line"
      | "vertical_line"
      | "ray"
      | "extended_line"
      | "parallel_channel"
      | "rectangle"
      | "ellipse"
      | "triangle"
      | "fib_retracement"
      | "fib_extension"
      | "fib_timezone"
      | "pitchfork"
      | "gann_fan"
      | "text"
      | "arrow"
      | "callout"
      | "measure"
      | "long_position"
      | "short_position"
      | "price_range"
      | "date_range"
      | "brush"
      | "polyline"
      | "anchored_vwap";
    EffectiveLimits: {
      accounts?: {
        daily_loss_cap_usd?: components["schemas"]["Decimal"];
        daily_loss_usd?: components["schemas"]["Decimal"];
        /** Format: uuid */
        exchange_account_id?: string;
        /** Format: date-time */
        lockout_until?: string | null;
        open_positions?: number;
        orders_per_minute_limit?: number;
        orders_per_minute_used?: number;
        rate_budget_pct_used?: number;
      }[];
      risk_caps?: components["schemas"]["RiskCaps"];
    };
    /**
     * @description Structural environment selector (arch P9). Mirrors the Postgres type `exchange_env`.
     * @enum {string}
     */
    Environment: "live" | "demo" | "testnet";
    ExchangeAccount: {
      /** Format: uuid */
      active_profile_id?: string | null;
      balance?: components["schemas"]["WalletBalance"] | null;
      balance_stale?: boolean;
      /** @enum {string} */
      connection_state?: "pending" | "connected" | "degraded" | "disconnected" | "disabled";
      /** Format: date-time */
      created_at?: string;
      /** @default true */
      enabled: boolean;
      environment: components["schemas"]["Environment"];
      exchange: components["schemas"]["ExchangeCode"];
      exchange_uid: string;
      /** Format: uuid */
      id: string;
      /** @enum {string} */
      key_status?: "missing" | "pending" | "active" | "rotating" | "expired" | "invalid";
      kind: components["schemas"]["AccountKind"];
      label: string;
      margin_mode?: components["schemas"]["MarginMode"];
      /** Format: uuid */
      parent_account_id?: string | null;
      position_mode?: components["schemas"]["PositionMode"];
      /** Format: date-time */
      updated_at?: string;
    };
    /**
     * @description Exchange identifier. v1 supports Bybit only (locked scope: Bybit USDT linear perpetuals).
     *     Mirrors the Postgres type `exchange_code`; the adapter abstraction
     *     (`24-internal-schemas.md`) exists so a second value can be added without a breaking change.
     * @default bybit
     * @enum {string}
     */
    ExchangeCode: "bybit";
    Execution: {
      /** Format: uuid */
      exchange_account_id?: string;
      exec_id?: string;
      exec_pnl?: components["schemas"]["Decimal"];
      exec_price?: components["schemas"]["Decimal"];
      exec_qty?: components["schemas"]["Decimal"];
      /** @enum {string} */
      exec_type?: "Trade" | "AdlTrade" | "Funding" | "BustTrade" | "Settle";
      exec_value?: components["schemas"]["Decimal"];
      fee?: components["schemas"]["Decimal"];
      fee_coin?: string;
      fee_rate?: components["schemas"]["Decimal"];
      /** Format: uuid */
      id?: string;
      is_maker?: boolean;
      /**
       * @description True when the paper matcher produced this record rather than the exchange. Orthogonal to `environment` (24-internal-schemas.md section 1.2).
       * @default false
       */
      is_paper: boolean;
      /** Format: uuid */
      order_id?: string;
      side?: components["schemas"]["OrderSide"];
      symbol?: components["schemas"]["Symbol"];
      /** Format: uuid */
      trade_group_id?: string | null;
      /** Format: date-time */
      ts?: string;
    };
    FeatureFlag: {
      /** @description Deployment default. */
      default_value?: unknown;
      description?: string;
      key?: string;
      kind?: components["schemas"]["FlagKind"];
      overrides?: {
        /** Format: uuid */
        user_id?: string;
        value?: unknown;
      }[];
      /** Format: date-time */
      updated_at?: string;
      /** Format: uuid */
      updated_by?: string | null;
      /** @description Resolved value for the caller. */
      value?: unknown;
    };
    /** @enum {string} */
    FlagKind: "boolean" | "percentage" | "variant";
    FootprintBar: components["schemas"]["Bar"] & {
      cells?: components["schemas"]["FootprintCell"][];
      imbalances?: components["schemas"]["FootprintImbalance"][];
      poc_price?: components["schemas"]["Decimal"];
      unfinished_auction?: {
        high?: boolean;
        low?: boolean;
      };
      value_area_high?: components["schemas"]["Decimal"];
      value_area_low?: components["schemas"]["Decimal"];
    };
    FootprintCell: {
      /** @description Volume traded into the ask (taker buys). */
      ask_volume: components["schemas"]["Decimal"];
      /** @description Volume traded into the bid (taker sells). */
      bid_volume: components["schemas"]["Decimal"];
      delta?: components["schemas"]["Decimal"];
      price: components["schemas"]["Decimal"];
      total_volume?: components["schemas"]["Decimal"];
      trades?: number;
    };
    FootprintImbalance: {
      /** @enum {string} */
      direction?: "buy" | "sell";
      /** @default false */
      estimated: boolean;
      price?: components["schemas"]["Decimal"];
      ratio?: components["schemas"]["Decimal"];
      stack_size?: number;
      stacked?: boolean;
    };
    FootprintResponse: {
      bar_type?: components["schemas"]["BarType"];
      bars: components["schemas"]["FootprintBar"][];
      meta: components["schemas"]["DataMeta"];
      param?: string;
      price_grouping?: number;
      symbol: components["schemas"]["Symbol"];
      tick_size?: components["schemas"]["Decimal"];
    };
    FrontendTelemetry: {
      engine_version: string;
      fe_dropped_frames_total: number;
      /** @description Edges ms: 4, 8, 12, 16, 20, 33, 50, 100, +Inf (9 slots). */
      fe_frame_time_ms: components["schemas"]["TelemetryBucketCounts"];
      fe_gpu_memory_mb?: number;
      /** @description Edges ms: 0.1, 0.25, 0.5, 1, 2, 4, 5, 10, +Inf (9 slots). */
      fe_ws_decode_ms: components["schemas"]["TelemetryBucketCounts"];
      /** @description Sitemap route id. */
      screen: string;
    };
    HealthReport: {
      alerts_active?: number;
      /** @description null until exchange time sync (E08) lands; never a fabricated 0. */
      clock_offset_ms?: number | null;
      components?: {
        detail?: string;
        /** Format: date-time */
        last_good_at?: string | null;
        latency_ms?: number;
        /** @constant */
        latency_unit?: "ms";
        name?: string;
        state?: components["schemas"]["ComponentState"];
      }[];
      environment?: string;
      git_sha?: string;
      overall?: components["schemas"]["ComponentState"];
      /** Format: date-time */
      server_time?: string;
      uptime_seconds?: number;
      version?: string;
    };
    HeatmapResponse: {
      /** @description Row-major [price][time] resting ask size. */
      ask_matrix?: number[][];
      /** @description Row-major [price][time] resting bid size. */
      bid_matrix?: number[][];
      /** @default false */
      estimated: boolean;
      /** Format: date-time */
      from?: string;
      max_value?: number;
      /** @enum {string} */
      normalize?: "none" | "column" | "window";
      price_grouping?: number;
      prices?: components["schemas"]["Decimal"][];
      symbol?: components["schemas"]["Symbol"];
      time_bucket_ms?: number;
      times?: string[];
      /** Format: date-time */
      to?: string;
    };
    HotkeyBinding: {
      /**
       * @example order.buy_market
       * @example position.flatten
       * @example chart.toggle_footprint
       */
      action: string;
      /** @default false */
      confirm: boolean;
      /** @description Chord notation, e.g. `Ctrl+Shift+F` or a sequence `Esc Esc`. */
      keys: string;
      params?: {
        [key: string]: unknown;
      };
      /**
       * @description Forced true for order-sending actions.
       * @default true
       */
      requires_arm: boolean;
      /** @enum {string} */
      scope: "global" | "chart" | "dom" | "tape" | "orders" | "positions";
    };
    HotkeyBindingAuditInput: {
      acknowledged_unsafe: boolean;
      after: string;
      before: string;
      command_id: string;
    };
    HotkeyProfile: components["schemas"]["HotkeyProfileInput"] & {
      /** Format: uuid */
      id?: string;
      is_active?: boolean;
      /** Format: uuid */
      owner_user_id?: string;
      /** Format: date-time */
      updated_at?: string;
    };
    HotkeyProfileInput: {
      bindings: components["schemas"]["HotkeyBinding"][];
      name: string;
    };
    Incident: {
      /** Format: uuid */
      acknowledged_by?: string | null;
      component: string;
      detail?: string | null;
      /** Format: date-time */
      first_seen_at: string;
      /** Format: uuid */
      id: string;
      /** Format: date-time */
      last_seen_at: string;
      occurrences?: number;
      /** Format: date-time */
      resolved_at?: string | null;
      runbook_ref?: string | null;
      severity: components["schemas"]["Severity"];
      /** @enum {string} */
      status: "open" | "acknowledged" | "resolved";
      title?: string;
    };
    IndicatorDescriptor: {
      /** @enum {string} */
      category?: "trend" | "momentum" | "volatility" | "volume" | "orderflow";
      /**
       * @description `server` indicators are read from `orderflow_metrics` and require recorded history; `client_worker` indicators are computed from bars already in the client.
       * @enum {string}
       */
      compute: "client_worker" | "server";
      defaults?: {
        [key: string]: unknown;
      };
      /**
       * @description True for heuristic signals that infer unobservable intent.
       * @default false
       */
      estimated: boolean;
      id: string;
      name: string;
      /** @enum {string} */
      pane: "price" | "sub" | "both";
      /** @description JSON Schema for this indicator's parameters; the settings form renders from it. */
      params_schema: {
        [key: string]: unknown;
      };
    };
    IndicatorPreset: components["schemas"]["IndicatorPresetInput"] & {
      /** Format: date-time */
      created_at?: string;
      /** Format: uuid */
      id?: string;
      /** Format: uuid */
      owner_user_id?: string;
      /** Format: date-time */
      updated_at?: string;
    };
    IndicatorPresetInput: {
      indicator_code: string;
      /** @default false */
      is_default: boolean;
      name: string;
      params: {
        [key: string]: unknown;
      };
    };
    Instrument: {
      base_coin?: string;
      /** @constant */
      category: "linear";
      /** @example LinearPerpetual */
      contract_type?: string;
      copy_trading?: boolean;
      /** @description Derived: true when `status` is not `Trading` or `PreLaunch`. */
      delisted?: boolean;
      funding_interval_minutes?: number;
      /** Format: date-time */
      launch_time?: string;
      leverage_step?: components["schemas"]["Decimal"];
      max_leverage?: components["schemas"]["Decimal"];
      max_order_qty?: components["schemas"]["Decimal"];
      min_notional_value?: components["schemas"]["Decimal"];
      min_order_qty?: components["schemas"]["Decimal"];
      price_scale?: number;
      qty_step: components["schemas"]["Decimal"];
      quote_coin?: string;
      /** @description Increments whenever Bybit changes the instrument metadata. */
      revision?: number;
      settle_coin?: string;
      /** @enum {string} */
      status?: "Trading" | "PreLaunch" | "Delivering" | "Closed";
      /** @description Human-readable explanation of `status`, for screen readers (#182). */
      status_reason?: string | null;
      symbol: components["schemas"]["Symbol"];
      tick_size: components["schemas"]["Decimal"];
      /** Format: date-time */
      updated_at?: string;
    };
    InstrumentDetail: components["schemas"]["Instrument"] & {
      recorded?: boolean;
      /** Format: date-time */
      recording_started_at?: string | null;
      risk_limit_tiers?: {
        initial_margin?: components["schemas"]["Decimal"];
        maintenance_margin?: components["schemas"]["Decimal"];
        max_leverage?: components["schemas"]["Decimal"];
        risk_limit_value?: components["schemas"]["Decimal"];
        tier?: number;
      }[];
      /**
       * Format: date-time
       * @description When this instrument's cache entry started missing refresh cadence.
       */
      stale_since?: string | null;
    };
    /** @description `PageMeta` extended with instrument-cache freshness so clients can show a stale banner. */
    InstrumentsPageMeta: components["schemas"]["PageMeta"] & {
      /** @description Seconds since this snapshot was last fetched from Bybit. */
      cache_age_s: number;
      /**
       * Format: date-time
       * @description When the cache started missing its refresh cadence; null if fresh.
       */
      stale_since: string | null;
    };
    Job: {
      error?: string | null;
      /** Format: date-time */
      finished_at?: string | null;
      /** Format: uuid */
      id?: string;
      /** @enum {string} */
      kind?:
        | "instrument_refresh"
        | "audit_export"
        | "backup"
        | "backup_verify"
        | "rule_simulation"
        | "retention_sweep"
        | "reconciliation"
        | "archive_import";
      progress_pct?: number;
      result?: {
        [key: string]: unknown;
      } | null;
      /** Format: date-time */
      started_at?: string | null;
      /** @enum {string} */
      status?: "queued" | "running" | "succeeded" | "failed" | "cancelled";
    };
    JournalAnalytics: {
      breakdowns?: {
        group_by?: string;
        rows?: {
          expectancy_r?: components["schemas"]["Decimal"];
          key?: string;
          net_pnl?: components["schemas"]["Decimal"];
          trades?: number;
          win_rate?: components["schemas"]["Decimal"];
        }[];
      }[];
      equity_curve?: {
        equity?: components["schemas"]["Decimal"];
        pnl?: components["schemas"]["Decimal"];
        /** Format: date-time */
        t?: string;
      }[];
      /** Format: date-time */
      generated_at?: string;
      totals?: {
        avg_loss_r?: components["schemas"]["Decimal"];
        avg_win_r?: components["schemas"]["Decimal"];
        breakeven?: number;
        expectancy_r?: components["schemas"]["Decimal"];
        fees?: components["schemas"]["Decimal"];
        gross_loss?: components["schemas"]["Decimal"];
        gross_profit?: components["schemas"]["Decimal"];
        longest_loss_streak?: number;
        longest_win_streak?: number;
        losses?: number;
        max_drawdown?: components["schemas"]["Decimal"];
        max_drawdown_pct?: components["schemas"]["Decimal"];
        net_pnl?: components["schemas"]["Decimal"];
        profit_factor?: components["schemas"]["Decimal"];
        trades?: number;
        win_rate?: components["schemas"]["Decimal"];
        wins?: number;
      };
    };
    /** @enum {string} */
    JournalSide: "long" | "short";
    JournalTrade: {
      avg_entry_price?: components["schemas"]["Decimal"];
      avg_exit_price?: components["schemas"]["Decimal"] | null;
      /** Format: date-time */
      closed_at?: string | null;
      duration_seconds?: number;
      /** Format: uuid */
      exchange_account_id?: string;
      fees?: components["schemas"]["Decimal"];
      gross_pnl?: components["schemas"]["Decimal"];
      /** Format: uuid */
      id?: string;
      max_adverse_excursion?: components["schemas"]["Decimal"];
      max_favourable_excursion?: components["schemas"]["Decimal"];
      notes_count?: number;
      /** Format: date-time */
      opened_at?: string;
      /** @enum {string} */
      outcome?: "win" | "loss" | "breakeven" | "open";
      qty?: components["schemas"]["Decimal"];
      r_multiple?: components["schemas"]["Decimal"] | null;
      rating?: number | null;
      realised_pnl?: components["schemas"]["Decimal"];
      setup?: string | null;
      side?: components["schemas"]["JournalSide"];
      symbol?: components["schemas"]["Symbol"];
      tags?: string[];
      /** Format: uuid */
      trade_group_id?: string | null;
    };
    JournalTradeContext: {
      bars?: components["schemas"]["Bar"][];
      coverage: components["schemas"]["DataCoverage"];
      executions?: components["schemas"]["Execution"][];
      footprint?: components["schemas"]["FootprintBar"][];
      /** Format: date-time */
      from: string;
      /** Format: uuid */
      journal_trade_id: string;
      markers?: {
        /** Format: date-time */
        at?: string;
        /** @enum {string} */
        kind?: "entry" | "exit" | "stop_moved" | "scale_in" | "scale_out" | "rule_fired";
        label?: string;
        price?: components["schemas"]["Decimal"];
      }[];
      symbol: components["schemas"]["Symbol"];
      /** Format: date-time */
      to: string;
    };
    JournalTradeDetail: components["schemas"]["JournalTrade"] & {
      checklist?: {
        [key: string]: unknown;
      }[];
      executions?: components["schemas"]["Execution"][];
      mistakes?: string[];
      notes?: components["schemas"]["Note"][];
      /** Format: uuid */
      rule_id?: string | null;
    };
    /** @enum {string} */
    KeyStatus: "pending" | "active" | "rotating" | "revoked" | "expired" | "invalid";
    KeyTestResult: {
      /** Format: date-time */
      checked_at?: string;
      passed?: boolean;
      rest?: {
        error?: string | null;
        latency_ms?: number;
        ok?: boolean;
        ret_code?: number | null;
      };
      verification?: components["schemas"]["KeyVerification"];
      websocket?: {
        error?: string | null;
        latency_ms?: number | null;
        ok?: boolean;
      };
    };
    KeyVerification: {
      clock_offset_ms?: number;
      ip_whitelist?: string[];
      ip_whitelist_matches_egress?: boolean;
      passed: boolean;
      permissions?: {
        [key: string]: string[];
      };
      probe_ret_code?: number | null;
      uid?: string | null;
      unified?: boolean;
      warnings?: string[];
      /** @description Must be false; a true value causes rejection. */
      withdraw_enabled: boolean;
    };
    KillSwitch: {
      engaged: boolean;
      /** Format: date-time */
      engaged_at?: string | null;
      /** Format: uuid */
      engaged_by?: string | null;
      exchange_account_ids?: string[];
      reason?: string | null;
      /** @enum {string} */
      scope: "global" | "accounts";
    };
    KillSwitchResult: {
      actions?: {
        failures?: {
          [key: string]: unknown;
        }[];
        orders_cancelled?: number;
        positions_flattened?: number;
        rules_disarmed?: number;
      };
      state?: components["schemas"]["KillSwitch"];
    };
    /**
     * @description Bybit-compatible interval codes (minutes, or D/W/M).
     * @enum {string}
     */
    KlineInterval:
      "1" | "3" | "5" | "15" | "30" | "60" | "120" | "240" | "360" | "720" | "D" | "W" | "M";
    KlineResponse: {
      bar_type?: components["schemas"]["BarType"];
      bars: components["schemas"]["Bar"][];
      interval?: string;
      meta: components["schemas"]["DataMeta"];
      symbol: components["schemas"]["Symbol"];
    };
    Layout: components["schemas"]["LayoutInput"] & {
      /** Format: date-time */
      created_at?: string;
      /** Format: uuid */
      id?: string;
      /** Format: date-time */
      updated_at?: string;
      /** Format: uuid */
      workspace_id?: string;
    };
    LayoutInput: {
      grid?: {
        column_fractions?: number[];
        columns?: number;
        /** @default 4 */
        gaps_px: number;
        row_fractions?: number[];
        rows?: number;
      };
      /**
       * @example 1x1
       * @example 2x2
       * @example 3x1
       * @example custom
       */
      grid_preset?: string;
      /** @default false */
      is_default: boolean;
      name: string;
      panes: components["schemas"]["LayoutPane"][];
    };
    LayoutPane: {
      bar_type?: components["schemas"]["BarType"];
      /** Format: uuid */
      chart_template_id?: string | null;
      /** @enum {integer} */
      depth?: 1 | 50 | 200 | 500;
      /** @enum {string} */
      kind:
        | "chart"
        | "dom"
        | "tape"
        | "footprint"
        | "heatmap"
        | "orders"
        | "positions"
        | "journal"
        | "rules"
        | "watchlist"
        | "metrics"
        | "account_summary"
        | "alerts"
        | "replay_controls";
      /**
       * @description Panes sharing a colour follow each other's symbol and crosshair.
       * @enum {string|null}
       */
      link_group?: "red" | "green" | "blue" | "yellow" | "purple" | null;
      param?: string;
      settings?: {
        [key: string]: unknown;
      };
      /** @description `column,row` grid position. */
      slot: string;
      /** @default 1x1 */
      span: string;
      symbol?: components["schemas"]["Symbol"] | null;
    };
    LayoutPreset: {
      description?: string | null;
      /** Format: uuid */
      id: string;
      is_builtin: boolean;
      layout?: components["schemas"]["LayoutInput"];
      name: string;
      pane_count?: number;
      preview_svg?: string | null;
    };
    /** @description Serialised form of the `rejection_code` / `rejection_message` columns on `trade_group_legs`. */
    LegError: {
      /** @description One of the `x-error-codes` slugs; persisted as `rejection_code`. */
      code?: string;
      exchange_ret_code?: number | null;
      /** @description Persisted as `rejection_message`. */
      message?: string;
      retryable?: boolean;
    };
    /** @enum {string} */
    LegStatus:
      | "pending"
      | "submitted"
      | "rejected"
      | "open"
      | "partially_filled"
      | "filled"
      | "cancelled"
      | "closed"
      | "error";
    Liquidation: {
      cluster_size?: number;
      notional_usd?: components["schemas"]["Decimal"];
      price?: components["schemas"]["Decimal"];
      /** @enum {string} */
      side?: "buy" | "sell";
      size?: components["schemas"]["Decimal"];
      symbol?: components["schemas"]["Symbol"];
      /** Format: date-time */
      ts?: string;
    };
    LoginRequest: {
      /** @description Shown in the session list. */
      device_name?: string;
      /** @description Username or email. */
      identifier: string;
      /** Format: password */
      password: string;
    };
    LoginResponse:
      | components["schemas"]["AuthenticatedResponse"]
      | components["schemas"]["MfaChallengeResponse"];
    /** @enum {string} */
    MarginMode: "cross" | "isolated" | "portfolio";
    Me: {
      /** @description Accounts the caller may see, with the granted mode. */
      accounts: {
        environment?: components["schemas"]["Environment"];
        /** Format: uuid */
        exchange_account_id: string;
        label?: string;
        /** @enum {string} */
        mode: "read" | "trade";
      }[];
      onboarding_complete?: boolean;
      /** @description Flattened effective permissions, drawn from the same closed vocabulary as `x-rbac.permissions` on every operation in this file. */
      permissions: string[];
      role: components["schemas"]["RoleName"];
      session?: {
        /** Format: date-time */
        elevated_until?: string | null;
        environment?: components["schemas"]["Environment"];
        /** Format: date-time */
        one_click_armed_until?: string | null;
        /** Format: uuid */
        session_id?: string;
      };
      user: components["schemas"]["User"];
    };
    /** @enum {string} */
    MetricCode:
      | "cvd"
      | "delta"
      | "min_max_delta"
      | "trades_per_sec"
      | "volume_per_sec"
      | "book_updates_per_sec"
      | "tape_acceleration"
      | "imbalance_ratio"
      | "absorption"
      | "exhaustion"
      | "iceberg"
      | "stop_run"
      | "adx"
      | "atr"
      | "hurst"
      | "regime"
      | "vwap"
      | "open_interest_delta"
      | "funding_basis"
      | "liquidation_intensity";
    MetricPoint: {
      /** @description Per-point detail for event-like metrics (iceberg, stop_run, absorption). */
      meta?: {
        [key: string]: unknown;
      };
      /** Format: date-time */
      t: string;
      v: components["schemas"]["Decimal"] | null;
    };
    MetricSeries: {
      /** @description True for heuristic metrics (arch P10). */
      estimated?: boolean;
      metric: components["schemas"]["MetricCode"];
      params?: {
        [key: string]: unknown;
      };
      points: components["schemas"]["MetricPoint"][];
      /**
       * @example base_volume
       * @example index
       * @example ratio
       * @example confidence
       * @example usd
       * @example price
       */
      unit?: string;
    };
    MetricsResponse: {
      bar_type?: components["schemas"]["BarType"];
      meta?: components["schemas"]["DataMeta"];
      param?: string;
      series?: components["schemas"]["MetricSeries"][];
      symbol?: components["schemas"]["Symbol"];
    };
    MfaChallengeResponse: {
      expires_in: number;
      methods: components["schemas"]["MfaMethodKind"][];
      mfa_token: string;
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      status: "mfa_required";
      webauthn_challenge?: {
        [key: string]: unknown;
      } | null;
    };
    MfaEnrollConfirmRequest: {
      code?: string;
      /** Format: uuid */
      method_id: string;
      webauthn_attestation?: {
        [key: string]: unknown;
      };
    };
    MfaEnrollRequest: {
      label?: string;
      /** @enum {string} */
      method: "totp" | "webauthn";
    };
    MfaEnrollResponse: {
      method: components["schemas"]["MfaMethodKind"];
      /** Format: uuid */
      method_id: string;
      otpauth_uri?: string | null;
      /** @description Shown exactly once, on first enrolment. */
      recovery_codes?: string[];
      webauthn_creation_options?: {
        [key: string]: unknown;
      } | null;
    };
    MfaMethod: {
      active?: boolean;
      /** Format: date-time */
      created_at?: string;
      /** Format: uuid */
      id?: string;
      kind?: components["schemas"]["MfaMethodKind"];
      label?: string | null;
      /** Format: date-time */
      last_used_at?: string | null;
    };
    /** @enum {string} */
    MfaMethodKind: "totp" | "webauthn" | "recovery_code";
    MfaVerifyRequest: {
      /** @description TOTP digits or a recovery code. */
      code?: string;
      method: components["schemas"]["MfaMethodKind"];
      mfa_token: string;
      /** @default 0 */
      remember_device_days: number;
      webauthn_assertion?: {
        [key: string]: unknown;
      };
    };
    Note: components["schemas"]["NoteInput"] & {
      /** Format: uuid */
      author_user_id?: string;
      /** Format: date-time */
      created_at?: string;
      /** Format: uuid */
      id?: string;
      /** Format: date-time */
      updated_at?: string;
    };
    NoteInput: {
      /** @description Markdown. */
      body: string;
      /** @description Reference to a stored chart snapshot. */
      snapshot_ref?: string | null;
    };
    Notification: {
      body?: string | null;
      /** Format: date-time */
      created_at: string;
      /** Format: uuid */
      exchange_account_id?: string | null;
      /** Format: uuid */
      id: string;
      /** @enum {string} */
      kind: "alert" | "rule" | "order" | "risk" | "system";
      /** Format: date-time */
      read_at?: string | null;
      /** @description Deep link to the screen that explains this notification. */
      route?: string | null;
      severity: components["schemas"]["Severity"];
      /**
       * Format: uuid
       * @description Id of the originating alert delivery, rule event, order or system event.
       */
      source_id?: string | null;
      symbol?: string | null;
      title: string;
    };
    /** @description A distance expressed in one of several units; resolved server-side to a price. */
    Offset: {
      atr_bar_type?: components["schemas"]["BarType"];
      atr_param?: string;
      /**
       * @description Used when `unit=atr`.
       * @default 14
       */
      atr_period: number;
      unit: components["schemas"]["OffsetUnit"];
      value: components["schemas"]["Decimal"];
    };
    /**
     * @description Unit in which a stop/target distance is expressed.
     *
     *     **Persistence contract.** The Postgres type `offset_unit` holds
     *     `ticks | percent | r_multiple | atr`. The API additionally accepts `price`, meaning
     *     "`value` is an absolute price level, not a distance"; the OMS converts it to a
     *     `ticks` distance from the resolved entry/reference price before persisting, so
     *     `account_profiles.sl_offset_unit` / `tp_offset_unit` never store `price`.
     *     Contract test `enum_parity_offset_unit` asserts this.
     * @enum {string}
     */
    OffsetUnit: "ticks" | "percent" | "r_multiple" | "atr" | "price";
    OnboardingChecklist: {
      complete: boolean;
      dismissed: boolean;
      items: {
        action_route?: string | null;
        /** @enum {string} */
        key: "tailscale" | "totp" | "sub_account" | "api_key" | "profile_limits" | "demo_session";
        reason?: string | null;
        /** @enum {string} */
        state: "ok" | "pending" | "blocked" | "error" | "not_applicable";
        /** Format: date-time */
        unblock_at?: string | null;
      }[];
    };
    Order: {
      algo?: components["schemas"]["AlgoSpec"];
      avg_fill_price?: components["schemas"]["Decimal"] | null;
      close_on_trigger?: boolean;
      /** Format: date-time */
      created_at?: string;
      environment?: components["schemas"]["Environment"];
      /** Format: uuid */
      exchange_account_id: string;
      exchange_order_id?: string | null;
      filled_qty?: components["schemas"]["Decimal"];
      /** Format: uuid */
      id: string;
      intent?: components["schemas"]["OrderIntent"];
      /**
       * @description True when the paper matcher produced this record rather than the exchange. Orthogonal to `environment` (24-internal-schemas.md section 1.2).
       * @default false
       */
      is_paper: boolean;
      /** @description Deterministic, derived from the Idempotency-Key. */
      order_link_id?: string;
      order_type: components["schemas"]["OrderType"];
      /** Format: uuid */
      parent_order_id?: string | null;
      position_idx?: number;
      price?: components["schemas"]["Decimal"] | null;
      qty: components["schemas"]["Decimal"];
      reduce_only?: boolean;
      rejected_reason?: string | null;
      remaining_qty?: components["schemas"]["Decimal"];
      side: components["schemas"]["OrderSide"];
      state: components["schemas"]["OrderState"];
      stop_loss?: components["schemas"]["Decimal"] | null;
      symbol: components["schemas"]["Symbol"];
      take_profit?: components["schemas"]["Decimal"] | null;
      time_in_force?: components["schemas"]["TimeInForce"];
      tpsl_mode?: components["schemas"]["TpSlMode"];
      /** Format: uuid */
      trade_group_id?: string | null;
      /** Format: uuid */
      trade_group_leg_id?: string | null;
      trigger_by?: components["schemas"]["TriggerBy"] | null;
      /** @enum {string|null} */
      trigger_direction?: "rise" | "fall" | null;
      trigger_price?: components["schemas"]["Decimal"] | null;
      /** Format: date-time */
      updated_at?: string;
    };
    OrderbookSnapshot: {
      /** @description [price, size], ascending. */
      asks: components["schemas"]["Decimal"][][];
      /** @description [price, size], descending. */
      bids: components["schemas"]["Decimal"][][];
      /** @enum {integer} */
      depth: 1 | 50 | 200 | 500;
      /**
       * Format: int64
       * @description Cross-topic sequence from Bybit.
       */
      seq: number;
      stale?: boolean;
      symbol: components["schemas"]["Symbol"];
      /** Format: date-time */
      ts: string;
      /**
       * Format: int64
       * @description Monotonic update id from Bybit.
       */
      u: number;
    };
    OrderDiagnostics: {
      events: components["schemas"]["OrderEvent"][];
      /** @description Request/response pairs with credentials, signatures and headers redacted. */
      exchange_calls?: {
        /** Format: date-time */
        at?: string;
        endpoint?: string;
        http_status?: number;
        latency_ms?: number;
        request_redacted?: {
          [key: string]: unknown;
        };
        response_redacted?: {
          [key: string]: unknown;
        };
        ret_code?: number | null;
        ret_msg?: string | null;
      }[];
      order: components["schemas"]["Order"];
      reconciliation?: {
        detail?: string | null;
        /** Format: date-time */
        last_checked_at?: string | null;
        /** @enum {string} */
        verdict?: "in_sync" | "drifted" | "repaired" | "unresolvable";
      };
    };
    OrderEvent: {
      /** Format: date-time */
      event_ts?: string;
      /** Format: int64 */
      id?: number;
      kind?: components["schemas"]["OrderEventKind"];
      payload?: {
        [key: string]: unknown;
      };
    };
    /**
     * @description Append-only OMS event taxonomy. Exact 1:1 mirror of the Postgres type
     *     `order_event_kind` (`21-database-schema.md`, table `order_events`) — no supersets,
     *     no omissions; contract test `enum_parity_order_event_kind` asserts set equality.
     * @enum {string}
     */
    OrderEventKind:
      | "local_create"
      | "submit_attempt"
      | "ack"
      | "reject"
      | "fill"
      | "partial_fill"
      | "amend_request"
      | "amend_ack"
      | "cancel_request"
      | "cancel_ack"
      | "expire"
      | "exchange_push"
      | "reconcile_diff"
      | "error";
    /** @enum {string} */
    OrderIntent:
      | "entry"
      | "stop_loss"
      | "take_profit"
      | "scale_in"
      | "scale_out"
      | "flatten"
      | "reverse"
      | "algo_child";
    /** @enum {string} */
    OrderSide: "buy" | "sell";
    /** @enum {string} */
    OrderState:
      | "new"
      | "pending_submit"
      | "submitted"
      | "accepted"
      | "partially_filled"
      | "filled"
      | "pending_cancel"
      | "cancelled"
      | "pending_amend"
      | "rejected"
      | "expired"
      | "untracked";
    /** @enum {string} */
    OrderType: "market" | "limit";
    OrderWithEvents: components["schemas"]["Order"] & {
      events?: components["schemas"]["OrderEvent"][];
      executions?: components["schemas"]["Execution"][];
    };
    Page: {
      items: unknown[];
      meta: components["schemas"]["PageMeta"];
    };
    PageMeta: {
      /** @description Items in this page (not the total, which is never computed for unbounded sets). */
      count: number;
      has_more: boolean;
      next_cursor?: string | null;
      /** @description Present only where a cheap exact count exists. */
      total?: number | null;
    };
    PlaceOrderRequest: {
      algo?: components["schemas"]["AlgoSpec"];
      /** @description Required when the request originates from one-click/hotkey entry. */
      arm_token?: string | null;
      /** @default false */
      close_on_trigger: boolean;
      /** Format: uuid */
      exchange_account_id: string;
      /** @default entry */
      intent: components["schemas"]["OrderIntent"];
      note?: string;
      order_type: components["schemas"]["OrderType"];
      /**
       * @description Required in hedge mode (1 = long, 2 = short).
       * @enum {integer}
       */
      position_idx?: 0 | 1 | 2;
      /** @description Required for `limit`. */
      price?: components["schemas"]["Decimal"];
      /**
       * Format: uuid
       * @description Override the account's active profile for this order.
       */
      profile_id?: string | null;
      /** @default false */
      reduce_only: boolean;
      side: components["schemas"]["OrderSide"];
      sizing: components["schemas"]["Sizing"];
      stop_loss?: components["schemas"]["Offset"];
      symbol: components["schemas"]["Symbol"];
      take_profit?: components["schemas"]["Offset"];
      time_in_force?: components["schemas"]["TimeInForce"];
      tpsl_mode?: components["schemas"]["TpSlMode"];
      trigger?: components["schemas"]["TriggerSpec"];
    };
    Position: {
      avg_price?: components["schemas"]["Decimal"];
      bust_price?: components["schemas"]["Decimal"] | null;
      /** Format: uuid */
      exchange_account_id: string;
      /** Format: uuid */
      id: string;
      /**
       * @description True when the paper matcher produced this record rather than the exchange. Orthogonal to `environment` (24-internal-schemas.md section 1.2).
       * @default false
       */
      is_paper: boolean;
      leverage?: components["schemas"]["Decimal"];
      liq_price?: components["schemas"]["Decimal"] | null;
      margin_mode?: components["schemas"]["MarginMode"];
      mark_price?: components["schemas"]["Decimal"];
      /** @description False is an alarm condition; the OMS re-asserts the stop and raises a critical alert. */
      native_stop_present?: boolean;
      /** @enum {integer} */
      position_idx?: 0 | 1 | 2;
      position_value?: components["schemas"]["Decimal"];
      r_multiple?: components["schemas"]["Decimal"] | null;
      realised_pnl_session?: components["schemas"]["Decimal"];
      /** @enum {string} */
      side: "long" | "short" | "flat";
      size: components["schemas"]["Decimal"];
      stop_loss?: components["schemas"]["Decimal"] | null;
      symbol: components["schemas"]["Symbol"];
      take_profit?: components["schemas"]["Decimal"] | null;
      tpsl_mode?: components["schemas"]["TpSlMode"];
      /** Format: uuid */
      trade_group_id?: string | null;
      /** @description Price distance, not a percentage (Bybit semantics). */
      trailing_stop?: components["schemas"]["Decimal"];
      unrealised_pnl?: components["schemas"]["Decimal"];
      /** Format: date-time */
      updated_at?: string;
    };
    /** @enum {string} */
    PositionMode: "one_way" | "hedge";
    /** @description RFC 9457 problem detail. `code` mirrors the `x-error-codes` catalogue. */
    Problem: {
      /** @description Stable machine-readable error code from `x-error-codes`. */
      code: string;
      detail?: string;
      /** @description Field-level validation failures. */
      errors?: {
        field?: string;
        message?: string;
        rule?: string;
      }[];
      /** @description Present when the failure originated at Bybit. */
      exchange?: {
        endpoint?: string;
        request_id?: string;
        ret_code?: number;
        ret_msg?: string;
      };
      /** @description Correlation id, `urn:cv:req:{uuid}`; matches the `X-Request-Id` header and the audit entry. */
      instance?: string;
      required_permissions?: string[];
      retry_after_seconds?: number;
      status: number;
      title: string;
      /**
       * Format: uri
       * @description `https://candleviewer.local/errors/{code}`.
       */
      type: string;
    };
    ProfilePeriod: {
      hvn?: components["schemas"]["Decimal"][];
      lvn?: components["schemas"]["Decimal"][];
      /** @description True while this period's POC has not been retraded by a later bar. */
      naked_poc?: boolean;
      /** Format: date-time */
      period_end?: string;
      /** Format: date-time */
      period_start?: string;
      poc_price?: components["schemas"]["Decimal"];
      rows?: components["schemas"]["ProfileRow"][];
      total_volume?: components["schemas"]["Decimal"];
      value_area_high?: components["schemas"]["Decimal"];
      value_area_low?: components["schemas"]["Decimal"];
    };
    ProfileResponse: {
      /** @enum {string} */
      kind?: "volume" | "delta" | "tpo";
      meta?: components["schemas"]["DataMeta"];
      profiles?: components["schemas"]["ProfilePeriod"][];
      /** @enum {string} */
      split?: "composite" | "session" | "fixed";
      symbol?: components["schemas"]["Symbol"];
    };
    ProfileRow: {
      buy_volume?: components["schemas"]["Decimal"];
      delta?: components["schemas"]["Decimal"];
      price?: components["schemas"]["Decimal"];
      sell_volume?: components["schemas"]["Decimal"];
      tpo_count?: number;
      volume?: components["schemas"]["Decimal"];
    };
    PublicTrade: {
      /** @description Number of raw prints merged when clustering is on. */
      cluster_size?: number;
      id?: string;
      is_block_trade?: boolean;
      price?: components["schemas"]["Decimal"];
      /**
       * @description Taker/aggressor side, taken directly from Bybit `S`.
       * @enum {string}
       */
      side?: "buy" | "sell";
      size?: components["schemas"]["Decimal"];
      /** @enum {string} */
      tick_direction?: "PlusTick" | "ZeroPlusTick" | "MinusTick" | "ZeroMinusTick";
      /** Format: date-time */
      ts?: string;
    };
    RecordedSymbol: {
      /** Format: uuid */
      added_by?: string | null;
      /** @enum {integer} */
      depth?: 1 | 50 | 200 | 500;
      /** Format: int64 */
      disk_bytes?: number;
      /** Format: uuid */
      id: string;
      lag_ms?: number;
      pinned?: boolean;
      reason: components["schemas"]["RecordReason"];
      retention_days?: number | null;
      /** Format: int64 */
      rows_last_hour?: number;
      /** Format: date-time */
      started_at?: string | null;
      state: components["schemas"]["RecordingState"];
      streams?: components["schemas"]["StreamKind"][];
      symbol: components["schemas"]["Symbol"];
    };
    RecordedSymbolWithEstimate: components["schemas"]["RecordedSymbol"] & {
      /** @description Planning estimate, replaced by measured rates once the recorder has run for an hour. */
      estimate?: {
        /** @example ~0.5-0.75 GB/day/symbol compressed at depth 200 */
        basis?: string;
        /** Format: int64 */
        daily_bytes_estimate?: number;
        warning?: string | null;
      };
    };
    RecordingSession: {
      /** Format: int64 */
      bytes?: number;
      depth?: number;
      /** Format: date-time */
      ended_at?: string | null;
      gap_count?: number;
      /** Format: uuid */
      id?: string;
      /** Format: uuid */
      recorded_symbol_id?: string;
      /** Format: int64 */
      rows?: number;
      /** Format: date-time */
      started_at?: string;
      state?: components["schemas"]["RecordingState"];
      streams?: components["schemas"]["StreamKind"][];
      symbol?: components["schemas"]["Symbol"];
    };
    /** @enum {string} */
    RecordingState:
      "idle" | "starting" | "recording" | "degraded" | "stopping" | "stopped" | "error";
    RecordingStatus: {
      connections?: {
        /** Format: date-time */
        connected_since?: string | null;
        endpoint?: string;
        last_ping_ms?: number;
        reconnects_last_hour?: number;
        /** @enum {string} */
        state?: "connecting" | "connected" | "degraded" | "disconnected";
        subscribed_topics?: number;
      }[];
      /** Format: date-time */
      generated_at?: string;
      ingest_rate_msgs_per_sec?: number;
      overall?: components["schemas"]["ComponentState"];
      symbols?: {
        /** Format: int64 */
        dropped_messages?: number;
        lag_ms?: number;
        /** Format: date-time */
        last_event_at?: string;
        resyncs_last_hour?: number;
        /** Format: int64 */
        rows_last_hour?: number;
        state?: components["schemas"]["RecordingState"];
        symbol?: components["schemas"]["Symbol"];
      }[];
      /** Format: int64 */
      write_backlog_rows?: number;
    };
    /** @enum {string} */
    RecordReason:
      "manual" | "chart_open" | "position_open" | "rule_dependency" | "alert_dependency";
    RefreshRequest: {
      /** @description Only for clients that cannot use cookies. */
      refresh_token?: string;
    };
    RegimeExplanation: {
      /** Format: date-time */
      as_of?: string;
      confidence?: number;
      /** @enum {string} */
      regime: "trending_up" | "trending_down" | "ranging" | "volatile_expansion" | "compression";
      signals: {
        contribution?: number;
        /** @enum {string} */
        direction?: "supports" | "opposes" | "neutral";
        name?: string;
        value?: number;
        weight?: number;
      }[];
      symbol: components["schemas"]["Symbol"];
    };
    ReplayControlRequest: {
      /** @enum {string} */
      action: "play" | "pause" | "seek" | "step" | "set_speed" | "restart";
      speed?: number;
      step_events?: number;
      step_ms?: number;
      /**
       * Format: date-time
       * @description Required for `seek`.
       */
      to?: string;
    };
    ReplaySession: {
      /** Format: date-time */
      created_at?: string;
      /** Format: uuid */
      created_by?: string;
      /** Format: date-time */
      cursor_ts?: string;
      depth?: number;
      error?: string | null;
      /** Format: date-time */
      from?: string;
      /** Format: uuid */
      id?: string;
      /** Format: uuid */
      paper_account_id?: string | null;
      progress_pct?: number;
      speed?: number;
      state?: components["schemas"]["ReplayState"];
      streams?: components["schemas"]["StreamKind"][];
      symbols?: components["schemas"]["Symbol"][];
      /** Format: date-time */
      to?: string;
    };
    /** @enum {string} */
    ReplayState: "created" | "buffering" | "playing" | "paused" | "finished" | "error";
    /** @description The exact parameters the server computed for a leg, echoed for pre-trade transparency. `leverage`, `stop_loss_price` and `take_profit_price` persist to the `resolved_leverage`, `resolved_sl_price` and `resolved_tp_price` columns on `trade_group_legs`; the remaining fields are the derivation shown to the user and are captured in the leg's `profile_snapshot` JSONB so a historical fan-out can be explained even after the profile is edited. */
    ResolvedLegParams: {
      estimated_fee_usd?: components["schemas"]["Decimal"];
      /** @description Persisted as `resolved_leverage`. */
      leverage?: components["schemas"]["Decimal"];
      notional_usd?: components["schemas"]["Decimal"];
      price?: components["schemas"]["Decimal"] | null;
      qty?: components["schemas"]["Decimal"];
      risk_usd?: components["schemas"]["Decimal"];
      /** @description Human-readable derivation, shown in the ticket's "why this size" tooltip. */
      sizing_explanation?: string;
      /** @description Persisted as `resolved_sl_price`. Never null - the native-stop invariant. */
      stop_loss_price?: components["schemas"]["Decimal"];
      /** @description Persisted as `resolved_tp_price`. */
      take_profit_price?: components["schemas"]["Decimal"] | null;
      trailing_stop_distance?: components["schemas"]["Decimal"] | null;
    };
    /** @enum {string} */
    RetentionAction: "drop" | "archive_parquet" | "downsample" | "pin";
    RetentionPolicy: components["schemas"]["RetentionPolicyInput"] & {
      /** Format: uuid */
      id?: string;
      /** Format: date-time */
      updated_at?: string;
    };
    RetentionPolicyInput: {
      action: components["schemas"]["RetentionAction"];
      /** @default false */
      applies_to_pinned: boolean;
      retain_days: number;
      stream: components["schemas"]["StreamKind"];
      /** @description Null = global default. */
      symbol?: components["schemas"]["Symbol"] | null;
    };
    ReversePositionRequest: {
      arm_token?: string | null;
      /** @default market */
      order_type: components["schemas"]["OrderType"];
      price?: components["schemas"]["Decimal"];
      /** @description Required when `size_mode=custom`. */
      qty?: components["schemas"]["Decimal"];
      /**
       * @default same
       * @enum {string}
       */
      size_mode: "same" | "profile" | "custom";
    };
    RiskCaps: {
      /** @default 60 */
      lockout_minutes_after_breach: number;
      max_consecutive_losses?: number;
      max_daily_loss_pct?: components["schemas"]["Decimal"];
      max_daily_loss_usd?: components["schemas"]["Decimal"];
      max_open_positions?: number;
      max_orders_per_minute?: number;
      max_position_notional_usd?: components["schemas"]["Decimal"];
    };
    RiskSummary: {
      accounts: {
        cap_utilisation_pct?: number;
        daily_loss_cap_usd?: components["schemas"]["Decimal"];
        equity_usd?: components["schemas"]["Decimal"];
        /** Format: uuid */
        exchange_account_id?: string;
        frozen?: boolean;
        label?: string;
        lockout?: {
          /** @enum {string} */
          reason?: "daily_loss" | "consecutive_losses" | "max_positions" | "manual";
          /** Format: date-time */
          since?: string;
          /** Format: date-time */
          until?: string | null;
        } | null;
        open_positions?: number;
        realised_pnl_today_usd?: components["schemas"]["Decimal"];
        unrealised_pnl_usd?: components["schemas"]["Decimal"];
      }[];
      environment?: components["schemas"]["Environment"];
      kill_switch?: components["schemas"]["KillSwitch"];
      /** @enum {string} */
      scope: "global" | "accounts";
      totals?: {
        equity_usd?: components["schemas"]["Decimal"];
        gross_notional_usd?: components["schemas"]["Decimal"];
        open_positions?: number;
        /** @description MUST be zero in steady state; any non-zero value is a violation of the native-stop safety invariant and is surfaced as a critical banner. */
        positions_without_native_stop?: number;
        realised_pnl_today_usd?: components["schemas"]["Decimal"];
        unrealised_pnl_usd?: components["schemas"]["Decimal"];
      };
    };
    Role: {
      description?: string;
      /** Format: uuid */
      id?: string;
      name?: components["schemas"]["RoleName"];
      permissions?: string[];
      user_count?: number;
    };
    /** @enum {string} */
    RoleName: "owner" | "manager" | "viewer";
    RotateApiKeyRequest: {
      /** Format: password */
      api_key: string;
      /** Format: password */
      api_secret: string;
      label?: string;
      /** @default 300 */
      overlap_seconds: number;
    };
    Rule: {
      /** Format: uuid */
      active_version_id?: string | null;
      bindings?: components["schemas"]["RuleBindings"];
      /** Format: date-time */
      created_at?: string;
      /** Format: uuid */
      created_by?: string;
      description?: string | null;
      /** @enum {string} */
      editor?: "form" | "graph";
      fire_count_24h?: number;
      /** Format: uuid */
      id: string;
      /** Format: date-time */
      last_run_at?: string | null;
      last_run_status?: components["schemas"]["RuleRunStatus"] | null;
      mode: components["schemas"]["RuleMode"];
      name: string;
      scope: components["schemas"]["RuleScope"];
      tags?: string[];
      /** Format: date-time */
      updated_at?: string;
      version?: number;
    };
    RuleAction: {
      /** @default false */
      dry_run_only: boolean;
      node_id: string;
      /**
       * @default abort_remaining
       * @enum {string}
       */
      on_error: "abort_remaining" | "continue" | "retry_once";
      /** @description Validated against a per-action JSON Schema. */
      params: {
        [key: string]: unknown;
      };
      /**
       * @default scope_accounts
       * @enum {string}
       */
      targets: "scope_accounts" | "originating_account" | "all_accounts";
      /**
       * @description Order-sending actions (`place_order`, `flatten_*`, `reverse_position`,
       *     `scale_in`, `scale_out`, `modify_*`, `cancel_*`, `reduce_leverage`,
       *     `arm_chase_limit`, `start_*`) require the rule to be `armed` and the author to
       *     hold `orders:write` on every bound account. `widen_stop` additionally requires
       *     an owner with an elevated session - it is the only action that can increase
       *     risk, so it is gated separately from the rest.
       * @enum {string}
       */
      type:
        | "place_order"
        | "modify_stop_loss"
        | "modify_take_profit"
        | "cancel_order"
        | "cancel_all_orders"
        | "move_to_breakeven"
        | "scale_out"
        | "scale_in"
        | "flatten_position"
        | "flatten_all_positions"
        | "reverse_position"
        | "halt_new_orders"
        | "resume_new_orders"
        | "reduce_leverage"
        | "widen_stop"
        | "tighten_stop"
        | "arm_chase_limit"
        | "start_iceberg_slice"
        | "start_twap"
        | "send_notification"
        | "log_journal_tag"
        | "set_variable"
        | "emit_signal"
        | "pause_rule"
        | "enable_rule";
    };
    RuleArithmeticNode: {
      node_id: string;
      /** @enum {string} */
      op: "add" | "sub" | "mul" | "div" | "abs" | "min" | "max" | "neg" | "pct_of";
      operands: components["schemas"]["RuleOperand"][];
    };
    RuleBindings: {
      exchange_account_ids?: string[];
      symbols?: components["schemas"]["Symbol"][];
      trade_group_ids?: string[];
    };
    RuleBooleanNode: {
      children: components["schemas"]["RuleCondition"][];
      /** @description Required for `n_of`. */
      n?: number | null;
      node_id: string;
      /** @enum {string} */
      op: "all_of" | "any_of" | "none_of" | "n_of";
    };
    RuleComparisonNode: {
      left: components["schemas"]["RuleOperand"];
      node_id: string;
      /** @enum {string} */
      op:
        | "gt"
        | "gte"
        | "lt"
        | "lte"
        | "eq"
        | "neq"
        | "between"
        | "outside"
        | "crosses_above"
        | "crosses_below"
        | "changed"
        | "is_true"
        | "is_false"
        | "in_set"
        | "not_in_set";
      right?: components["schemas"]["RuleOperand"];
      /** @description Upper bound for `between` / `outside`. */
      right2?: components["schemas"]["RuleOperand"];
      set_values?: string[];
      /** @description Equality tolerance for float comparisons. */
      tolerance?: number | null;
    };
    /** @description A node in the boolean DAG: a comparison leaf, a boolean combinator, or a temporal window. Every node carries a stable `node_id`, which is what lets the node-graph editor attach coordinates in `graph_layout` without putting cosmetics in the IR. */
    RuleCondition:
      | components["schemas"]["RuleComparisonNode"]
      | components["schemas"]["RuleBooleanNode"]
      | components["schemas"]["RuleTemporalNode"];
    RuleDetail: components["schemas"]["Rule"] & {
      graph_layout?: {
        [key: string]: unknown;
      } | null;
      ir?: components["schemas"]["RuleIr"];
      ir_hash?: string;
      last_simulation?: {
        /** Format: date-time */
        completed_at?: string | null;
        fires?: number | null;
        ir_hash?: string | null;
        /** Format: uuid */
        run_id?: string | null;
      };
    };
    RuleEvent: {
      /** Format: int64 */
      id?: number;
      /** @enum {string} */
      kind?:
        | "evaluated"
        | "suppressed"
        | "action_sent"
        | "action_result"
        | "error"
        | "started"
        | "finished";
      payload?: {
        [key: string]: unknown;
      };
      /** Format: date-time */
      ts?: string;
    };
    RuleInput: {
      bindings?: components["schemas"]["RuleBindings"];
      description?: string;
      /**
       * @default form
       * @enum {string}
       */
      editor: "form" | "graph";
      /** @description Node/edge coordinates for the node-graph editor. Ignored by the engine. */
      graph_layout?: {
        [key: string]: unknown;
      };
      ir: components["schemas"]["RuleIr"];
      name: string;
      note?: string;
      scope: components["schemas"]["RuleScope"];
      tags?: string[];
    };
    /**
     * @description The single executable representation produced by **both** the form editor and the
     *     node-graph editor (owner decision #11). Round-tripping is lossless because
     *     `graph_layout` (cosmetic node coordinates) is stored on the rule, outside the IR,
     *     so compiling either editor's model yields a byte-identical IR and therefore an
     *     identical `ir_hash`.
     *
     *     This object is the *executable core only*. Rule identity and lifecycle
     *     (`id`, `name`, `mode`, `scope`, `editor`, `version`) live on `Rule` / `RuleInput`
     *     and in the `rules` table - they are deliberately not duplicated here, so an IR can
     *     be validated, hashed and compared without carrying database identity.
     */
    RuleIr: {
      actions: components["schemas"]["RuleAction"][];
      conditions: components["schemas"]["RuleCondition"];
      /** @enum {integer} */
      ir_version: 1;
      limits?: components["schemas"]["RuleLimits"];
      trigger: components["schemas"]["RuleTrigger"];
      /** @description Named intermediate expressions, evaluated before `conditions`. */
      variables?: {
        [key: string]: components["schemas"]["RuleOperand"];
      };
    };
    /** @description Safety limiters applied by the engine before any action is dispatched. Named `limits` in the IR (not `guards`) to match 24-internal-schemas.md section 11.2. */
    RuleLimits: {
      /** @default 1000 */
      cooldown_ms: number;
      /** @default 250 */
      evaluation_timeout_ms: number;
      /** @default 5 */
      kill_switch_on_error_count: number;
      /** @default 10 */
      max_actions_per_fire: number;
      max_daily_notional?: components["schemas"]["Decimal"] | null;
      /** @default 500 */
      max_fires_per_day: number;
      /** @default 60 */
      max_fires_per_hour: number;
      max_notional_per_fire?: components["schemas"]["Decimal"] | null;
      /** @default false */
      once: boolean;
      /** @enum {string|null} */
      once_per?: "position" | "day" | "group" | "rule_lifetime" | null;
      /** @default false */
      require_confirmation: boolean;
    };
    /** @description Reference to a value in the metric registry (24-internal-schemas.md section 7.2). `symbol` and `account_id` default to the rule's scope when null. */
    RuleMetricRef: {
      /** Format: uuid */
      account_id?: string | null;
      metric: string;
      params?: {
        [key: string]: unknown;
      };
      symbol?: components["schemas"]["Symbol"] | null;
      timeframe?: string | null;
    };
    /** @enum {string} */
    RuleMode: "disabled" | "simulate" | "armed";
    /**
     * @description A value position in the condition tree. Exactly one form is present:
     *     a metric reference, a constant, or an arithmetic node.
     */
    RuleOperand:
      | components["schemas"]["RuleMetricRef"]
      | {
          const: string | number | boolean;
        }
      | components["schemas"]["RuleArithmeticNode"];
    RuleRun: {
      error_message?: string | null;
      errors?: number;
      /** Format: int64 */
      evaluations?: number;
      /** Format: date-time */
      finished_at?: string | null;
      fires?: number;
      /** Format: uuid */
      id?: string;
      /** @enum {string} */
      kind?: "live" | "simulation";
      /** Format: uuid */
      rule_id?: string;
      /** Format: uuid */
      rule_version_id?: string;
      /** Format: date-time */
      started_at?: string;
      status?: components["schemas"]["RuleRunStatus"];
    };
    /** @enum {string} */
    RuleRunStatus: "running" | "ok" | "error" | "aborted" | "throttled";
    /** @enum {string} */
    RuleScope: "global" | "account" | "symbol" | "position" | "trade_group";
    RuleSimulationResult: {
      actions?: {
        action?: string;
        /** Format: uuid */
        exchange_account_id?: string | null;
        params?: {
          [key: string]: unknown;
        };
        symbol?: components["schemas"]["Symbol"];
        /** Format: date-time */
        ts?: string;
        would_have_succeeded?: boolean;
      }[];
      duration_ms?: number;
      errors?: string[];
      /** Format: int64 */
      evaluations?: number;
      fires?: number;
      /** Format: date-time */
      from?: string;
      hypothetical_pnl_delta_usd?: components["schemas"]["Decimal"] | null;
      /** Format: uuid */
      rule_id?: string;
      /** Format: uuid */
      run_id?: string;
      suppressed_by_guard?: number;
      /** Format: date-time */
      to?: string;
      /** Format: uuid */
      version_id?: string;
    };
    RuleTemporalNode: {
      child: components["schemas"]["RuleCondition"];
      /** @default 1 */
      min_count: number;
      node_id: string;
      /** @enum {string} */
      op: "sustained_for" | "occurred_within" | "count_within" | "stable_for";
      window_ms: number;
    };
    RuleTrigger: {
      /** @description Required for `on_schedule`; 5-field UTC cron. */
      cron?: string | null;
      /** @default 0 */
      debounce_ms: number;
      /** @description Required for `on_timer`. */
      interval_ms?: number | null;
      /** @description Required for `on_metric_change`. */
      metric?: string | null;
      /** @description Required for `on_bar_close`. */
      timeframe?: string | null;
      /** @enum {string} */
      type:
        | "on_price_update"
        | "on_bar_close"
        | "on_order_fill"
        | "on_position_open"
        | "on_position_close"
        | "on_position_update"
        | "on_timer"
        | "on_metric_change"
        | "on_signal"
        | "on_schedule"
        | "pre_trade_check"
        | "on_book_update"
        | "on_liquidation";
    } & (unknown & unknown & unknown & unknown);
    RuleValidationIssue: {
      /** @enum {string} */
      class?: "syntax" | "semantics" | "safety" | "performance";
      /** @enum {string} */
      code?:
        | "schema_error"
        | "unknown_variable"
        | "unknown_function"
        | "type_mismatch"
        | "unreachable_branch"
        | "guard_missing"
        | "missing_action_param"
        | "permission_required"
        | "native_stop_missing"
        | "unsupported_symbol"
        | "unknown_metric"
        | "operator_not_applicable"
        | "cycle_detected"
        | "dangling_port"
        | "orphan_node"
        | "multiple_sinks"
        | "feedback_loop"
        | "native_stop_violation"
        | "high_frequency";
      message?: string;
      path?: string;
      /** @enum {string} */
      severity?: "error" | "warning";
    };
    RuleValidationResult: {
      /** @description True when any error or open safety warning refuses mode=armed. */
      blocks_arming?: boolean;
      errors: components["schemas"]["RuleValidationIssue"][];
      estimated_evaluations_per_minute?: number;
      referenced_actions?: string[];
      referenced_variables?: string[];
      valid: boolean;
      warnings: components["schemas"]["RuleValidationIssue"][];
    };
    RuleVersion: {
      /** Format: date-time */
      created_at?: string;
      /** Format: uuid */
      created_by?: string;
      /** Format: uuid */
      id?: string;
      ir_hash?: string;
      is_active?: boolean;
      note?: string | null;
      /** Format: uuid */
      rule_id?: string;
      version?: number;
    };
    RuleVersionDetail: components["schemas"]["RuleVersion"] & {
      graph_layout?: {
        [key: string]: unknown;
      } | null;
      ir?: components["schemas"]["RuleIr"];
    };
    /** @description The closed vocabulary shared by the form editor, the node-graph editor and the rule engine. Anything absent from this response is not expressible in the IR. */
    RuleVocabulary: {
      actions: {
        /** @default true */
        available: boolean;
        display_name?: string;
        guarded?: boolean;
        id: string;
        idempotent?: boolean;
        /**
         * @description Actions that can widen or remove a stop are flagged so the editors can warn and the engine can gate them behind the owner-only permission.
         * @default false
         */
        loosens_risk: boolean;
        notes?: string;
        params_schema?: {
          [key: string]: unknown;
        };
        required_permissions: string[];
        /** @default false */
        requires_step_up: boolean;
        restriction?: string;
        /** @default false */
        simulate_only: boolean;
        targets?: {
          [key: string]: string;
        };
      }[];
      arm_live_permission?: string;
      guards: {
        id?: string;
        params_schema?: {
          [key: string]: unknown;
        };
      }[];
      ir_version?: string;
      operators: {
        arity?: number;
        id?: string;
        operand_types?: string[];
        result_type?: string;
      }[];
      signals: {
        /** @default true */
        available: boolean;
        /** @enum {string} */
        confidence?: "exact" | "estimated";
        dependencies?: string[];
        description?: string;
        deterministic?: boolean;
        display_name?: string;
        enum_values?: string[];
        /** @default false */
        estimated: boolean;
        id: string;
        missing_dependency?: {
          [key: string]: unknown;
        };
        params_schema?: {
          [key: string]: unknown;
        };
        recorder_action?: {
          [key: string]: unknown;
        };
        /** @default false */
        requires_recording: boolean;
        /** @enum {string} */
        type: "number" | "boolean" | "price" | "quantity" | "duration" | "enum";
        unavailable_reason?: string;
        unit?: string | null;
        valid_range?: string | null;
        warmup_bars?: number;
        when_unavailable?: string;
      }[];
      triggers?: {
        description?: string;
        id?: string;
        required_fields?: string[];
      }[];
      vocabulary_version?: number;
    };
    ScannerRow: {
      /**
       * @description `live_only` means no local history exists for this symbol, so criteria that need recorded history were skipped for this row rather than evaluated as zero.
       * @enum {string}
       */
      coverage: "recorded" | "live_only";
      cvd?: components["schemas"]["Decimal"];
      last_price?: components["schemas"]["Decimal"];
      liquidation_intensity?: components["schemas"]["Decimal"];
      open_interest?: components["schemas"]["Decimal"];
      price_change_pct_24h?: components["schemas"]["Decimal"];
      recording?: boolean;
      symbol: components["schemas"]["Symbol"];
      tape_speed?: components["schemas"]["Decimal"];
      volume_24h?: components["schemas"]["Decimal"];
    };
    SecuritySummary: {
      audit?: {
        chain_intact?: boolean;
        /** Format: int64 */
        entries_total?: number;
        /** Format: date-time */
        last_chain_verification_at?: string | null;
      };
      auth?: {
        active_elevated_sessions?: number;
        denied_requests_24h?: number;
        failed_logins_24h?: number;
        users_without_mfa?: number;
      };
      findings?: {
        code?: string;
        message?: string;
        severity?: components["schemas"]["Severity"];
      }[];
      /** Format: date-time */
      generated_at?: string;
      keys?: {
        age_days?: number;
        /** Format: uuid */
        exchange_account_id?: string;
        /** Format: date-time */
        expires_at?: string | null;
        ip_whitelist_matches_expected?: boolean;
        key_id_prefix?: string;
        /** Format: date-time */
        last_verified_at?: string | null;
        status?: components["schemas"]["KeyStatus"];
        /** @description MUST be false; true raises a critical finding immediately. */
        withdrawal_permission_present?: boolean;
      }[];
    };
    SessionInfo: {
      account_scope: string[];
      allowed_environments?: components["schemas"]["Environment"][];
      api_version?: string;
      /** @description Backend clock minus Bybit server time; |offset| > 1000 ms is an incident. */
      clock_offset_ms?: number;
      /** @description Flags resolved for this user. */
      feature_flags?: {
        [key: string]: unknown;
      };
      kill_switch?: components["schemas"]["KillSwitch"];
      permissions: string[];
      /** Format: date-time */
      server_time: string;
      /**
       * Format: date-time
       * @description Latest live step-up grace-window expiry on this session (E09-S04); null if none.
       */
      step_up_expires_at?: string | null;
      user: components["schemas"]["User"];
    };
    SetFeatureFlagRequest: {
      /**
       * Format: uri
       * @description Required for gated flags such as `trading.live_enabled`.
       */
      evidence_url?: string;
      overrides?: {
        /** Format: uuid */
        user_id: string;
        value: unknown;
      }[];
      reason?: string;
      /** @description Boolean, number (percentage) or string (variant), matching the flag kind. */
      value: unknown;
    };
    SetKillSwitchRequest: {
      /** @default true */
      cancel_open_orders: boolean;
      /** @default true */
      disarm_rules: boolean;
      engaged: boolean;
      exchange_account_ids?: string[];
      /** @default false */
      flatten_positions: boolean;
      reason: string;
      /** @enum {string} */
      scope: "global" | "accounts";
    };
    /** @description Effective settings — deployment defaults overlaid with user overrides. */
    Settings: {
      _meta?: {
        overridden?: string[];
        /** Format: date-time */
        updated_at?: string;
      };
      /** @description SCR-117 preferences (E47-S07); closed enums, presentation-only. */
      accessibility?: {
        always_show_tables?: boolean;
        /** @enum {string} */
        announce_prices?: "off" | "significant" | "always";
        disable_canvas_animation?: boolean;
        /** @enum {string} */
        increased_contrast?: "system" | "on" | "off";
        keyboard_only?: boolean;
        /** @enum {string} */
        reduced_motion?: "system" | "on" | "off";
        thick_focus_ring?: boolean;
        /** @enum {string} */
        verbosity?: "low" | "normal" | "high";
      };
      appearance?: {
        /** @enum {string} */
        density?: "compact" | "comfortable" | "spacious";
        font_scale?: number;
        high_contrast?: boolean;
        reduce_motion?: boolean;
        /** @enum {string} */
        theme?: "dark" | "light" | "system";
      };
      chart?: {
        bar_close_countdown?: boolean;
        crosshair_sync?: boolean;
        default_bar_type?: components["schemas"]["BarType"];
        default_param?: string;
        /** @enum {string} */
        price_scale_mode?: "linear" | "logarithmic" | "percent";
      };
      data?: {
        default_depth?: number;
        max_history_bars?: number;
        stale_badge_after_ms?: number;
      };
      notifications?: {
        desktop_enabled?: boolean;
        email_enabled?: boolean;
        quiet_hours?: {
          [key: string]: unknown;
        } | null;
        webhook_url?: string | null;
      };
      orderflow?: {
        big_trade_k?: number;
        /** @enum {string} */
        big_trade_threshold_mode?: "absolute" | "relative" | "zscore";
        heatmap_ask_colour?: string;
        heatmap_bid_colour?: string;
        imbalance_ratio?: number;
        min_stack?: number;
        value_area_pct?: number;
      };
      trading?: {
        arm_timeout_seconds?: number;
        confirm_flatten?: boolean;
        confirm_market_orders?: boolean;
        default_environment?: components["schemas"]["Environment"];
        default_qty_presets?: components["schemas"]["Decimal"][];
        readonly one_click_armed?: boolean;
      };
    };
    /** @description Deep-merge patch; only present leaves change. `null` resets a leaf to the deployment default. */
    SettingsPatch: {
      [key: string]: unknown;
    };
    SetTpSlRequest: {
      /** @description Arms the trailing stop only once price reaches this level. */
      activation_price?: components["schemas"]["Decimal"];
      sl_size?: components["schemas"]["Decimal"];
      sl_trigger_by?: components["schemas"]["TriggerBy"];
      stop_loss?: components["schemas"]["Offset"] | null;
      take_profit?: components["schemas"]["Offset"] | null;
      tp_size?: components["schemas"]["Decimal"];
      tp_trigger_by?: components["schemas"]["TriggerBy"];
      tpsl_mode?: components["schemas"]["TpSlMode"];
      trailing_stop?: components["schemas"]["Offset"] | null;
    };
    /** @enum {string} */
    Severity: "debug" | "info" | "warning" | "error" | "critical";
    SimulateRuleRequest: {
      exchange_account_ids?: string[];
      /** Format: date-time */
      from?: string;
      /** Format: uuid */
      replay_session_id?: string;
      /** @default 0 */
      speed: number;
      starting_equity_usd?: components["schemas"]["Decimal"];
      symbols?: components["schemas"]["Symbol"][];
      /** Format: date-time */
      to?: string;
      /**
       * Format: uuid
       * @description Defaults to the active version.
       */
      version_id?: string;
    };
    /**
     * @example {
     *       "mode": "risk_based",
     *       "risk_per_trade_usd": "250",
     *       "max_notional_usd": "50000",
     *       "round_to_lot": true
     *     }
     */
    Sizing: {
      max_notional_usd?: components["schemas"]["Decimal"];
      mode: components["schemas"]["SizingMode"];
      notional_usd?: components["schemas"]["Decimal"];
      /** @description Percent of equity (`pct_equity`) or of the position (`pct_position`). */
      pct?: components["schemas"]["Decimal"];
      qty?: components["schemas"]["Decimal"];
      risk_per_trade_pct?: components["schemas"]["Decimal"];
      risk_per_trade_usd?: components["schemas"]["Decimal"];
      /** @default true */
      round_to_lot: boolean;
    };
    /**
     * @description How a request expresses order size.
     *
     *     **Persistence contract.** The Postgres type `sizing_mode`
     *     (`21-database-schema.md` §Enums) holds only the four *resolved* modes
     *     `fixed_qty | fixed_notional | pct_equity | risk_based`. The two extra API values are
     *     **request-time sugar that never reaches the database**; the OMS resolves them before
     *     any row is written, and `orders.requested_qty_mode` / `account_profiles.sizing_mode`
     *     therefore always contain a resolved value:
     *
     *     | API value | Resolution | Stored as |
     *     |---|---|---|
     *     | `pct_position` | `pct` % of the *current open position* qty on that symbol/account (scale-out, flatten-partial). Rejected with `validation_failed` if no position is open. | `fixed_qty` |
     *     | `profile` | Inherit the active `AccountProfile.sizing` block verbatim. | whatever the profile's own mode resolves to |
     *
     *     Contract test `enum_parity_sizing_mode` asserts (a) the DB enum equals this enum minus
     *     `x-db-enum-superset`, and (b) no persisted row ever holds a superset value.
     * @enum {string}
     */
    SizingMode:
      "fixed_qty" | "fixed_notional" | "pct_equity" | "risk_based" | "pct_position" | "profile";
    StorageUsage: {
      /** Format: int64 */
      daily_growth_bytes?: number;
      /** Format: int64 */
      disk_free_bytes?: number;
      /** Format: int64 */
      disk_total_bytes?: number;
      /** Format: int64 */
      disk_used_bytes?: number;
      /** Format: date-time */
      generated_at?: string;
      /** Format: date-time */
      projected_full_at?: string | null;
      symbols?: {
        /** Format: int64 */
        daily_growth_bytes?: number;
        pinned?: boolean;
        symbol?: components["schemas"]["Symbol"];
        /** Format: int64 */
        used_bytes?: number;
      }[];
      tiers?: {
        retention_days?: number | null;
        /** @enum {string} */
        tier?: "questdb" | "parquet" | "postgres";
        /** Format: int64 */
        used_bytes?: number;
      }[];
    };
    /** @enum {string} */
    StreamKind:
      | "trades"
      | "orderbook_delta"
      | "orderbook_snapshot"
      | "tickers"
      | "klines"
      | "liquidations"
      | "open_interest"
      | "funding";
    /**
     * @description Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.
     * @example BTCUSDT
     * @example ETHUSDT
     * @example SOLUSDT
     */
    Symbol: string;
    /** @description Non-cumulative counts per bucket edge plus a trailing `+Inf` slot. */
    TelemetryBucketCounts: {
      counts: number[];
    };
    Ticker: {
      ask1_price?: components["schemas"]["Decimal"];
      ask1_size?: components["schemas"]["Decimal"];
      bid1_price?: components["schemas"]["Decimal"];
      bid1_size?: components["schemas"]["Decimal"];
      funding_rate?: components["schemas"]["Decimal"];
      high_24h?: components["schemas"]["Decimal"];
      index_price?: components["schemas"]["Decimal"];
      last_price?: components["schemas"]["Decimal"];
      low_24h?: components["schemas"]["Decimal"];
      mark_price?: components["schemas"]["Decimal"];
      /** Format: date-time */
      next_funding_time?: string;
      open_interest?: components["schemas"]["Decimal"];
      open_interest_value?: components["schemas"]["Decimal"];
      price_change_pct_24h?: components["schemas"]["Decimal"];
      stale?: boolean;
      symbol?: components["schemas"]["Symbol"];
      /** Format: date-time */
      ts?: string;
      turnover_24h?: components["schemas"]["Decimal"];
      volume_24h?: components["schemas"]["Decimal"];
    };
    /** @enum {string} */
    TimeInForce: "GTC" | "IOC" | "FOK" | "PostOnly";
    TokenBundle: {
      access_token: string;
      /** @description Access-token lifetime in seconds (600). */
      expires_in: number;
      /** @description Refresh-token lifetime in seconds (2592000). */
      refresh_expires_in?: number;
      /** @description Returned only to non-cookie clients that set `cookie_auth:false` on login. */
      refresh_token?: string | null;
      /** @constant */
      token_type: "Bearer";
    };
    /** @enum {string} */
    TpSlMode: "Full" | "Partial";
    TpSlResult: {
      activation_price?: components["schemas"]["Decimal"] | null;
      /** Format: date-time */
      applied_at?: string;
      /** Format: uuid */
      position_id?: string;
      stop_loss?: components["schemas"]["Decimal"] | null;
      take_profit?: components["schemas"]["Decimal"] | null;
      tpsl_mode?: components["schemas"]["TpSlMode"];
      trailing_stop_distance?: components["schemas"]["Decimal"] | null;
      trailing_stop_requested?: components["schemas"]["Offset"] | null;
    };
    TradeGroup: {
      algo?: components["schemas"]["AlgoSpec"];
      /** @enum {string} */
      atomicity?: "best_effort" | "all_or_none";
      client_group_ref?: string;
      /** Format: date-time */
      closed_at?: string | null;
      /** Format: date-time */
      created_at?: string;
      /** Format: uuid */
      created_by?: string;
      /** Format: uuid */
      id: string;
      intent?: components["schemas"]["OrderIntent"];
      /**
       * @description True when the paper matcher produced this record rather than the exchange. Orthogonal to `environment` (24-internal-schemas.md section 1.2).
       * @default false
       */
      is_paper: boolean;
      legs: components["schemas"]["TradeGroupLeg"][];
      note?: string | null;
      /** Format: uuid */
      rule_id?: string | null;
      side: components["schemas"]["OrderSide"];
      status: components["schemas"]["TradeGroupStatus"];
      symbol: components["schemas"]["Symbol"];
      totals?: {
        filled_qty?: components["schemas"]["Decimal"];
        realised_pnl?: components["schemas"]["Decimal"] | null;
        rejected_legs?: number;
        requested_legs?: number;
        submitted_legs?: number;
        target_qty?: components["schemas"]["Decimal"];
      };
      /** Format: date-time */
      updated_at?: string;
    };
    /** @description One account's share of a fan-out. Field names mirror the `trade_group_legs` columns in 21-database-schema.md §3.3.3 one-for-one; the only additions are `orders` (the leg's order ids, a join rather than a column) and `resolved` (the computed parameters, stored as `resolved_*` columns and the `profile_snapshot` JSONB). */
    TradeGroupLeg: {
      /**
       * Format: uuid
       * @description The profile that produced `resolved`. Null when the ticket overrode the profile entirely.
       */
      account_profile_id?: string | null;
      avg_entry_price?: components["schemas"]["Decimal"] | null;
      avg_exit_price?: components["schemas"]["Decimal"] | null;
      /** Format: date-time */
      closed_at?: string | null;
      /** Format: date-time */
      created_at?: string;
      error?: components["schemas"]["LegError"] | null;
      /** Format: uuid */
      exchange_account_id?: string;
      fees_paid?: components["schemas"]["Decimal"];
      filled_qty?: components["schemas"]["Decimal"];
      /** Format: uuid */
      id?: string;
      /** @description True once the exchange has acknowledged a native stop-loss on this leg. The safety invariant (arch P4) requires this to become true for every filled leg; a filled leg with `false` is an alertable condition, not a cosmetic gap. */
      native_sl_confirmed?: boolean;
      /** Format: date-time */
      native_sl_confirmed_at?: string | null;
      orders?: string[];
      realised_pnl?: components["schemas"]["Decimal"] | null;
      resolved?: components["schemas"]["ResolvedLegParams"] | null;
      risk_usd?: components["schemas"]["Decimal"] | null;
      /** @description Deterministic submission order within the group, so a partial fan-out is reproducible. */
      sequence_no?: number;
      status?: components["schemas"]["LegStatus"];
      /** Format: date-time */
      submitted_at?: string | null;
      target_qty?: components["schemas"]["Decimal"];
      /** Format: uuid */
      trade_group_id?: string;
      /** Format: date-time */
      updated_at?: string;
    };
    TradeGroupLegInput: {
      /** Format: uuid */
      exchange_account_id: string;
      /** @description Per-leg overrides layered on top of the account profile and request defaults. */
      overrides?: {
        leverage?: components["schemas"]["Decimal"];
        /** @enum {integer} */
        position_idx?: 0 | 1 | 2;
        price?: components["schemas"]["Decimal"];
        /** Format: uuid */
        profile_id?: string;
        sizing?: components["schemas"]["Sizing"];
        /**
         * @description Keep the leg in the group for auditability but do not send it.
         * @default false
         */
        skip: boolean;
        stop_loss?: components["schemas"]["Offset"];
        take_profit?: components["schemas"]["Offset"];
        time_in_force?: components["schemas"]["TimeInForce"];
        tpsl_mode?: components["schemas"]["TpSlMode"];
        trailing_stop?: components["schemas"]["Offset"];
      };
    };
    /** @description What `POST /trade-groups` would do, without doing it. Mirrors the resolved leg shape used in `TradeGroup.legs` so the ticket renders the preview and the result with one component. */
    TradeGroupPreview: {
      legs: {
        account_label?: string;
        /** Format: uuid */
        account_profile_id?: string | null;
        estimated_margin_usd?: components["schemas"]["Decimal"];
        estimated_risk_usd?: components["schemas"]["Decimal"];
        /** Format: uuid */
        exchange_account_id: string;
        rejection?: {
          /** @enum {string} */
          code?:
            | "cap_breached"
            | "symbol_not_allowed"
            | "insufficient_margin"
            | "rate_budget_exhausted"
            | "account_locked"
            | "key_invalid"
            | "leverage_unavailable"
            | "kill_switch_engaged";
          message?: string;
        } | null;
        resolved?: components["schemas"]["ResolvedLegParams"];
        would_submit: boolean;
      }[];
      totals: {
        accounts_submittable?: number;
        accounts_targeted?: number;
        total_notional_usd?: components["schemas"]["Decimal"];
        total_qty?: components["schemas"]["Decimal"];
        total_risk_usd?: components["schemas"]["Decimal"];
      };
    };
    /** @enum {string} */
    TradeGroupStatus:
      | "draft"
      | "submitting"
      | "partially_open"
      | "open"
      | "closing"
      | "closed"
      | "failed"
      | "cancelled";
    /** @enum {string} */
    TriggerBy: "LastPrice" | "MarkPrice" | "IndexPrice";
    TriggerSpec: {
      /** @enum {string} */
      direction: "rise" | "fall";
      price: components["schemas"]["Decimal"];
      trigger_by?: components["schemas"]["TriggerBy"];
    };
    UpdateExchangeAccountRequest: {
      /** Format: uuid */
      active_profile_id?: string | null;
      enabled?: boolean;
      label?: string;
      margin_mode?: components["schemas"]["MarginMode"];
      position_mode?: components["schemas"]["PositionMode"];
    };
    UpdateJournalTradeRequest: {
      checklist?: {
        [key: string]: unknown;
      }[];
      mistakes?: string[];
      rating?: number | null;
      setup?: string | null;
      tags?: string[];
    };
    UpdateRecordedSymbolRequest: {
      /** @enum {integer} */
      depth?: 1 | 50 | 200 | 500;
      pinned?: boolean;
      retention_days?: number | null;
      streams?: components["schemas"]["StreamKind"][];
    };
    UpdateUserRequest: {
      display_name?: string | null;
      mfa_required?: boolean;
      roles?: components["schemas"]["RoleName"][];
      status?: components["schemas"]["UserStatus"];
    };
    User: {
      /** Format: date-time */
      created_at?: string;
      display_name?: string | null;
      /** Format: email */
      email: string;
      /** Format: uuid */
      id: string;
      /** Format: date-time */
      last_login_at?: string | null;
      mfa_enabled?: boolean;
      mfa_required?: boolean;
      roles: components["schemas"]["RoleName"][];
      status: components["schemas"]["UserStatus"];
      /** Format: date-time */
      updated_at?: string;
      username: string;
    };
    UserSession: {
      /** Format: date-time */
      created_at?: string;
      current?: boolean;
      device_name?: string | null;
      /** Format: date-time */
      expires_at?: string;
      /** Format: uuid */
      id?: string;
      ip?: string | null;
      /** Format: date-time */
      last_seen_at?: string;
      user_agent?: string | null;
    };
    /** @enum {string} */
    UserStatus: "invited" | "active" | "disabled" | "locked";
    UserWithInvite: components["schemas"]["User"] & {
      /** Format: date-time */
      invite_expires_at?: string;
      /** @description One-time link, valid 72 h. Shown once. */
      invite_url?: string;
    };
    WalletBalance: {
      account_im_rate?: components["schemas"]["Decimal"];
      account_mm_rate?: components["schemas"]["Decimal"];
      available_balance?: components["schemas"]["Decimal"];
      /** @example USDT */
      coin?: string;
      equity?: components["schemas"]["Decimal"];
      /**
       * @description True when the paper matcher produced this record rather than the exchange. Orthogonal to `environment` (24-internal-schemas.md section 1.2).
       * @default false
       */
      is_paper: boolean;
      unrealised_pnl?: components["schemas"]["Decimal"];
      /** Format: date-time */
      updated_at?: string;
      wallet_balance?: components["schemas"]["Decimal"];
    };
    Watchlist: components["schemas"]["WatchlistInput"] & {
      /** Format: date-time */
      created_at?: string;
      /** Format: uuid */
      id?: string;
      /** Format: date-time */
      updated_at?: string;
    };
    WatchlistInput: {
      /** @description Column ids shown for this watchlist, in order. */
      columns?: string[];
      name: string;
      symbols: components["schemas"]["Symbol"][];
    };
    Workspace: components["schemas"]["WorkspaceInput"] & {
      /** Format: date-time */
      created_at?: string;
      /** Format: uuid */
      id?: string;
      layout_count?: number;
      /** Format: date-time */
      updated_at?: string;
      /** Format: uuid */
      user_id?: string;
    };
    /** @description Portable, credential-free export of presentation state only. */
    WorkspaceBundle: {
      chart_templates?: components["schemas"]["ChartTemplateInput"][];
      drawings?: components["schemas"]["DrawingInput"][];
      /** Format: date-time */
      exported_at?: string;
      indicator_presets?: components["schemas"]["IndicatorPresetInput"][];
      layouts: components["schemas"]["LayoutInput"][];
      schema_version: string;
      workspace: components["schemas"]["WorkspaceInput"];
    };
    WorkspaceDetail: components["schemas"]["Workspace"] & {
      layouts?: components["schemas"]["Layout"][];
    };
    WorkspaceInput: {
      description?: string;
      /** @default false */
      is_default: boolean;
      name: string;
    };
  };
  responses: {
    /** @description The targeted exchange account is outside the caller's granted scope. */
    AccountScopeDenied: {
      headers: {
        [name: string]: unknown;
      };
      content: {
        "application/problem+json": components["schemas"]["Problem"];
      };
    };
    /** @description Malformed request. */
    BadRequest: {
      headers: {
        [name: string]: unknown;
      };
      content: {
        "application/problem+json": components["schemas"]["Problem"];
      };
    };
    /** @description State conflict. */
    Conflict: {
      headers: {
        [name: string]: unknown;
      };
      content: {
        "application/problem+json": components["schemas"]["Problem"];
      };
    };
    /** @description SR-041: `X-CSRF-Token` missing, not equal to the `__Host-cv_csrf` cookie, or not bound to the current session. Audited (`auth.csrf_refused`) up to a per-session / per-source budget; beyond it the response is identical but carries `Retry-After` and writes no audit record. `detail` never echoes token or cookie values; clients re-read the cookie and retry once. */
    CsrfTokenInvalid: {
      headers: {
        "Retry-After": components["headers"]["RetryAfter"];
        [name: string]: unknown;
      };
      content: {
        "application/problem+json": components["schemas"]["Problem"];
      };
    };
    /** @description The exchange rejected the request. */
    ExchangeError: {
      headers: {
        [name: string]: unknown;
      };
      content: {
        "application/problem+json": components["schemas"]["Problem"];
      };
    };
    /** @description Authenticated but not permitted. On state-changing operations this status may also carry `code: csrf_token_invalid` (SR-041; see `CsrfTokenInvalid`). `detail` never echoes token or cookie values. */
    Forbidden: {
      headers: {
        [name: string]: unknown;
      };
      content: {
        "application/problem+json": components["schemas"]["Problem"];
      };
    };
    /** @description Resource not found (or hidden by scope). */
    NotFound: {
      headers: {
        [name: string]: unknown;
      };
      content: {
        "application/problem+json": components["schemas"]["Problem"];
      };
    };
    /** @description The request body or the number of batch operations exceeds the operation's ceiling (`payload_too_large`). Checked before per-item validation. */
    PayloadTooLarge: {
      headers: {
        [name: string]: unknown;
      };
      content: {
        "application/problem+json": components["schemas"]["Problem"];
      };
    };
    /** @description ETag precondition failed. */
    PreconditionFailed: {
      headers: {
        [name: string]: unknown;
      };
      content: {
        "application/problem+json": components["schemas"]["Problem"];
      };
    };
    /** @description Rate limited. */
    RateLimited: {
      headers: {
        "RateLimit-Limit": components["headers"]["RateLimitLimit"];
        "RateLimit-Remaining": components["headers"]["RateLimitRemaining"];
        "RateLimit-Reset": components["headers"]["RateLimitReset"];
        "Retry-After": components["headers"]["RetryAfter"];
        [name: string]: unknown;
      };
      content: {
        "application/problem+json": components["schemas"]["Problem"];
      };
    };
    /** @description Rule IR failed semantic validation. */
    RuleIrInvalid: {
      headers: {
        [name: string]: unknown;
      };
      content: {
        "application/problem+json": components["schemas"]["Problem"];
      };
    };
    /** @description A dependency is unavailable or data is degraded. */
    ServiceUnavailable: {
      headers: {
        "Retry-After": components["headers"]["RetryAfter"];
        [name: string]: unknown;
      };
      content: {
        "application/problem+json": components["schemas"]["Problem"];
      };
    };
    /** @description Not authenticated. */
    Unauthorized: {
      headers: {
        [name: string]: unknown;
      };
      content: {
        "application/problem+json": components["schemas"]["Problem"];
      };
    };
    /** @description Semantically invalid request. */
    UnprocessableEntity: {
      headers: {
        [name: string]: unknown;
      };
      content: {
        "application/problem+json": components["schemas"]["Problem"];
      };
    };
  };
  parameters: {
    AccountId: string;
    /** @description Restrict to these accounts. Omit for every account in the caller's scope. */
    AccountIdsQuery: string[];
    AlertId: string;
    BackupId: string;
    /** @description Maximum number of bars returned in one page. */
    BarLimit: number;
    /**
     * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
     *     against the session id the server resolves itself (not merely header == cookie). All
     *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
     *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
     *     unbound → `403 csrf_token_invalid`.
     */
    CsrfToken: string;
    /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
    Cursor: string;
    DeliveryId: number;
    DrawingId: string;
    EnvironmentQuery: components["schemas"]["Environment"];
    /** @description Inclusive start of the time window (RFC 3339 UTC). */
    From: string;
    HotkeyProfileId: string;
    /** @description Client-generated UUIDv4. Replays return the original response with `Idempotency-Replayed: true`. */
    IdempotencyKey: string;
    /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
    IdempotencyKeyRequired: string;
    /** @description ETag of the version the client believes it is editing. Omitting it accepts last-write-wins. */
    IfMatch: string;
    JournalTradeId: string;
    KeyId: string;
    LayoutId: string;
    /** @description Page size. */
    Limit: number;
    /** @description The single cursor statement for `/market/klines` and `/market/bars`: an opaque, server-issued cursor from `meta.next_cursor`. Ordering and the cursor are by `(generation, index)` for non-time bars (the cursor carries the last position's `t`, `generation` and `index`, #2017); `/market/klines` and time bars use a `t` position (open time is unique there). Clients must treat the cursor as opaque and never parse it, so the switch is non-breaking. Malformed, expired or foreign -> `invalid_cursor`. A cursor is bound to the request that issued it (route, symbol, interval or `bar_type`+`param`); replaying it on a different request is `invalid_cursor`. Uncursored requests are served as the first page (see the route text). */
    MarketCursor: string;
    MethodId: string;
    OrderId: string;
    PositionId: string;
    PresetId: string;
    ProfileId: string;
    RecordedSymbolId: string;
    ReplayId: string;
    RuleId: string;
    RunId: string;
    SymbolPath: components["schemas"]["Symbol"];
    SymbolQuery: components["schemas"]["Symbol"];
    SymbolQueryOptional: components["schemas"]["Symbol"];
    TemplateId: string;
    /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
    To: string;
    TradeGroupId: string;
    UserId: string;
    VersionId: string;
    WorkspaceId: string;
  };
  requestBodies: never;
  headers: {
    /** @description Opaque version of the returned representation, for `If-Match`. */
    ETag: string;
    /** @description True when the response was replayed from the idempotency store. */
    IdempotencyReplayed: boolean;
    /** @description Requests permitted in the current window. */
    RateLimitLimit: number;
    /** @description Requests remaining in the current window. */
    RateLimitRemaining: number;
    /** @description Seconds until the window resets. */
    RateLimitReset: number;
    /** @description Seconds the client should wait before retrying. */
    RetryAfter: number;
  };
  pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
  queryAuditLog: {
    parameters: {
      query?: {
        /** @description Action codes, e.g. `order.place`, `key.rotate`, `killswitch.engage`. */
        action?: string[];
        actor_user_id?: string;
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        ip?: string;
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        outcome?: components["schemas"]["AuditOutcome"];
        /** @description Full-text search across the detail payload. */
        q?: string;
        severity?: components["schemas"]["Severity"];
        subject_id?: string;
        subject_type?:
          | "user"
          | "exchange_account"
          | "api_key"
          | "order"
          | "trade_group"
          | "position"
          | "rule"
          | "alert"
          | "recording"
          | "replay"
          | "feature_flag"
          | "backup"
          | "setting"
          | "session";
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Audit page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            /** @description Whether the returned slice's hash chain verifies. */
            chain_verified?: boolean;
            items?: components["schemas"]["AuditEntry"][];
          };
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  exportAuditLog: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          /** @default true */
          compress?: boolean;
          /** Format: date-time */
          from: string;
          /** Format: date-time */
          to: string;
        };
      };
    };
    responses: {
      /** @description Export scheduled. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            /** @description Populated once the job completes. */
            download_url?: string | null;
            /** Format: uuid */
            job_id?: string;
          };
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  verifyAuditChain: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody?: {
      content: {
        "application/json": {
          /** Format: int64 */
          from_id?: number;
          /** Format: int64 */
          to_id?: number;
        };
      };
    };
    responses: {
      /** @description Verification result. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            /** Format: date-time */
            checked_at?: string;
            entries_checked?: number;
            /** Format: int64 */
            first_bad_id?: number | null;
            verified?: boolean;
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  listBackups: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        kind?: components["schemas"]["BackupKind"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        status?: components["schemas"]["BackupStatus"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Backups page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["Backup"][];
          };
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  createBackup: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. Replays return the original response with `Idempotency-Replayed: true`. */
        "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          kind: components["schemas"]["BackupKind"];
          note?: string;
          /** @default true */
          verify?: boolean;
        };
      };
    };
    responses: {
      /** @description Backup started. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Backup"];
        };
      };
      403: components["responses"]["Forbidden"];
      409: components["responses"]["Conflict"];
    };
  };
  getBackup: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        backupId: components["parameters"]["BackupId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Backup. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Backup"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  deleteBackup: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        backupId: components["parameters"]["BackupId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Deleted. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      403: components["responses"]["CsrfTokenInvalid"];
      409: components["responses"]["Conflict"];
    };
  };
  restoreBackup: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        backupId: components["parameters"]["BackupId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          components?: ("postgres" | "questdb" | "parquet" | "config")[];
          /** Format: uuid */
          confirm_backup_id: string;
          reason: string;
        };
      };
    };
    responses: {
      /** @description Restore accepted. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            /** Format: uuid */
            job_id?: string;
          };
        };
      };
      403: components["responses"]["Forbidden"];
      409: components["responses"]["Conflict"];
    };
  };
  verifyBackup: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        backupId: components["parameters"]["BackupId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Verification scheduled. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            /** Format: uuid */
            job_id?: string;
          };
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
    };
  };
  getCapacity: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Capacity report. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["CapacityReport"];
        };
      };
    };
  };
  listFeatureFlags: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Flags. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: components["schemas"]["FeatureFlag"][];
          };
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  setFeatureFlag: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        flagKey: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["SetFeatureFlagRequest"];
      };
    };
    responses: {
      /** @description Flag updated. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["FeatureFlag"];
        };
      };
      403: components["responses"]["Forbidden"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  getHealth: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Health report. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HealthReport"];
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  listIncidents: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        status?: "open" | "acknowledged" | "resolved";
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Incidents. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["Incident"][];
          };
        };
      };
    };
  };
  getJob: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        jobId: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Job state. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Job"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  setLogLevelOverride: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          /** @enum {string} */
          level: "debug" | "info" | "warning" | "error" | "critical";
          /** @enum {string} */
          subsystem: "ingestion" | "oms" | "rules" | "recorder" | "api" | "ws";
          /** @default 900 */
          ttl_seconds?: number;
        };
      };
    };
    responses: {
      /** @description Override applied. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            /** @enum {string} */
            level: "debug" | "info" | "warning" | "error" | "critical";
            /** @enum {string} */
            subsystem: "ingestion" | "oms" | "rules" | "recorder" | "api" | "ws";
            ttl_seconds: number;
          };
        };
      };
      400: components["responses"]["BadRequest"];
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
    };
  };
  getAdminOverview: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Overview. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["AdminOverview"];
        };
      };
    };
  };
  compactRecorder: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody?: {
      content: {
        "application/json": {
          older_than_days?: number;
          symbols?: components["schemas"]["Symbol"][];
        };
      };
    };
    responses: {
      /** @description Compaction accepted. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            /** Format: uuid */
            job_id?: string;
          };
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
    };
  };
  importTradeArchive: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          /** Format: date */
          from: string;
          symbol: components["schemas"]["Symbol"];
          /** Format: date */
          to: string;
        };
      };
    };
    responses: {
      /** @description Import accepted. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            /** Format: uuid */
            job_id?: string;
          };
        };
      };
      400: components["responses"]["BadRequest"];
      403: components["responses"]["CsrfTokenInvalid"];
      /** @description An import job is already running. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Problem"];
        };
      };
      /** @description Idempotency-Key reused with a different body, or invalid range (`import_range_invalid`). */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Problem"];
        };
      };
    };
  };
  purgeRecordedData: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          /** Format: date-time */
          before?: string;
          confirm_symbol: components["schemas"]["Symbol"];
          /** @default false */
          include_pinned?: boolean;
          reason: string;
          symbol: components["schemas"]["Symbol"];
        };
      };
    };
    responses: {
      /** @description Purge accepted. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            /** Format: uuid */
            job_id?: string;
          };
        };
      };
      403: components["responses"]["Forbidden"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  getSecuritySummary: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Security summary. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SecuritySummary"];
        };
      };
    };
  };
  createSupportBundle: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          /** Format: date-time */
          from: string;
          /** Format: date-time */
          to: string;
        };
      };
    };
    responses: {
      /** @description Generation started. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            /** Format: uuid */
            job_id: string;
          };
        };
      };
      400: components["responses"]["BadRequest"];
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      /** @description A bundle is already being generated (BUNDLE_ALREADY_RUNNING). */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  getSupportBundle: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        job_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Job status. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            /** @description Local filesystem path. */
            download_path?: string | null;
            error_code?: string | null;
            /** Format: uuid */
            id: string;
            size_bytes?: number | null;
            /** @enum {string} */
            status: "running" | "succeeded" | "failed";
            truncated?: boolean;
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  listAlerts: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        enabled?: boolean;
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        symbol?: components["parameters"]["SymbolQueryOptional"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Alerts page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["Alert"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  createAlert: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. Replays return the original response with `Idempotency-Replayed: true`. */
        "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["AlertInput"];
      };
    };
    responses: {
      /** @description Alert created. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Alert"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      422: components["responses"]["RuleIrInvalid"];
    };
  };
  getAlert: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        alertId: components["parameters"]["AlertId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Alert. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Alert"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  updateAlert: {
    parameters: {
      query?: never;
      header: {
        /** @description ETag of the version the client believes it is editing. Omitting it accepts last-write-wins. */
        "If-Match"?: components["parameters"]["IfMatch"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        alertId: components["parameters"]["AlertId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["AlertInput"];
      };
    };
    responses: {
      /** @description Replaced. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Alert"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      412: components["responses"]["PreconditionFailed"];
    };
  };
  deleteAlert: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        alertId: components["parameters"]["AlertId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Deleted. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  setAlertEnabled: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        alertId: components["parameters"]["AlertId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          enabled: boolean;
        };
      };
    };
    responses: {
      /** @description Updated. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Alert"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  listAlertDeliveries: {
    parameters: {
      query?: {
        alert_id?: string;
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        status?: components["schemas"]["DeliveryStatus"];
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
        unacked_only?: boolean;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Deliveries page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["AlertDelivery"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  ackAlertDelivery: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        deliveryId: components["parameters"]["DeliveryId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Acknowledged. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["AlertDelivery"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
    };
  };
  ackAllAlertDeliveries: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Count acknowledged. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            acknowledged?: number;
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  authLogin: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["LoginRequest"];
      };
    };
    responses: {
      /** @description Authenticated, or an MFA challenge was issued. */
      200: {
        headers: {
          /** @description `cv_refresh` and `__Host-cv_csrf` (SR-041) cookies; present only when `status=authenticated`. */
          "Set-Cookie"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["LoginResponse"];
        };
      };
      401: components["responses"]["Unauthorized"];
      429: components["responses"]["RateLimited"];
      503: components["responses"]["ServiceUnavailable"];
    };
  };
  authLogout: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody?: {
      content: {
        "application/json": {
          /**
           * @description Revoke every session of the current user, not just this one.
           * @default false
           */
          all_sessions?: boolean;
        };
      };
    };
    responses: {
      /** @description Session(s) revoked; `cv_refresh` cleared. */
      204: {
        headers: {
          /** @description Expired `cv_refresh` and `__Host-cv_csrf` cookies */
          "Set-Cookie"?: string;
          [name: string]: unknown;
        };
        content?: never;
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["CsrfTokenInvalid"];
    };
  };
  authMfaEnroll: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["MfaEnrollRequest"];
      };
    };
    responses: {
      /** @description Enrolment started. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["MfaEnrollResponse"];
        };
      };
      400: components["responses"]["BadRequest"];
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
    };
  };
  authMfaEnrollConfirm: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["MfaEnrollConfirmRequest"];
      };
    };
    responses: {
      /** @description Method activated. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["MfaMethod"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["CsrfTokenInvalid"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  authMfaDeleteMethod: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
        /** @description Current password, re-supplied to authorise the destructive change. */
        "X-Reauth-Password": string;
      };
      path: {
        methodId: components["parameters"]["MethodId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Removed. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  authMfaRecovery: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          mfa_token: string;
          recovery_code: string;
        };
      };
    };
    responses: {
      /** @description Authenticated. */
      200: {
        headers: {
          /** @description `cv_refresh` cookie and a fresh `__Host-cv_csrf` cookie (SR-041) */
          "Set-Cookie"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["AuthenticatedResponse"];
        };
      };
      401: components["responses"]["Unauthorized"];
      429: components["responses"]["RateLimited"];
    };
  };
  authMfaVerify: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["MfaVerifyRequest"];
      };
    };
    responses: {
      /** @description MFA accepted; session created. */
      200: {
        headers: {
          /** @description `cv_refresh` cookie and a fresh `__Host-cv_csrf` cookie (SR-041) */
          "Set-Cookie"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["AuthenticatedResponse"];
        };
      };
      401: components["responses"]["Unauthorized"];
      429: components["responses"]["RateLimited"];
    };
  };
  authChangePassword: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ChangePasswordRequest"];
      };
    };
    responses: {
      /** @description Password changed. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["CsrfTokenInvalid"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  authRefresh: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody?: {
      content: {
        "application/json": components["schemas"]["RefreshRequest"];
      };
    };
    responses: {
      /** @description New token bundle issued. */
      200: {
        headers: {
          /** @description Rotated `cv_refresh` cookie and a rotated `__Host-cv_csrf` cookie bound to the new session (SR-041) */
          "Set-Cookie"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["AuthenticatedResponse"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["CsrfTokenInvalid"];
      429: components["responses"]["RateLimited"];
      503: components["responses"]["ServiceUnavailable"];
    };
  };
  authGetSession: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Current session. */
      200: {
        headers: {
          /** @description `__Host-cv_csrf` re-issued for the current session when absent or not verifying (SR-041 recovery path); otherwise absent. */
          "Set-Cookie"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SessionInfo"];
        };
      };
      401: components["responses"]["Unauthorized"];
    };
  };
  authListSessions: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Sessions page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["UserSession"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
    };
  };
  authStepUp: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          /**
           * @description Optional cross-check. The server elevates the class its last `403 step_up_required` challenged on this session; a different value is `400`. Without a pending challenge it is required.
           * @enum {string}
           */
          action_class?: "keys" | "users" | "live_enablement" | "killswitch" | "risk_caps";
          code: string;
          /** Format: password */
          password: string;
        };
      };
    };
    responses: {
      /** @description Elevated. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            action_class: string;
            /** Format: date-time */
            elevated_until: string;
            single_use: boolean;
            /**
             * Format: date-time
             * @description End of the grace window shown in the dialog; null for no-grace classes.
             */
            step_up_expires_at?: string | null;
          };
        };
      };
      400: components["responses"]["BadRequest"];
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      422: components["responses"]["UnprocessableEntity"];
      429: components["responses"]["RateLimited"];
    };
  };
  listChartTemplates: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        /** @description Include templates shared by other users (owner-published defaults). */
        shared?: boolean;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Templates page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["ChartTemplate"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  createChartTemplate: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ChartTemplateInput"];
      };
    };
    responses: {
      /** @description Created. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ChartTemplate"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  getChartTemplate: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        templateId: components["parameters"]["TemplateId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Template. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ChartTemplate"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  updateChartTemplate: {
    parameters: {
      query?: never;
      header: {
        /** @description ETag of the version the client believes it is editing. Omitting it accepts last-write-wins. */
        "If-Match"?: components["parameters"]["IfMatch"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        templateId: components["parameters"]["TemplateId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ChartTemplateInput"];
      };
    };
    responses: {
      /** @description Replaced. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ChartTemplate"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      412: components["responses"]["PreconditionFailed"];
    };
  };
  deleteChartTemplate: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        templateId: components["parameters"]["TemplateId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Deleted. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      403: components["responses"]["CsrfTokenInvalid"];
      409: components["responses"]["Conflict"];
    };
  };
  getDetectorConfig: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Detector configuration. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["DetectorConfig"];
        };
      };
    };
  };
  setDetectorConfig: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["DetectorConfig"];
      };
    };
    responses: {
      /** @description Updated. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["DetectorConfig"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
    };
  };
  getDetectorMethodology: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Methodology notes. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: components["schemas"]["DetectorMethodology"][];
          };
        };
      };
    };
  };
  listDrawings: {
    parameters: {
      query: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Narrow to one layout. Must be one of the caller's live layouts, otherwise 404. */
        layout_id?: string;
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        symbol: components["parameters"]["SymbolQuery"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Drawings page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["Drawing"][];
          };
        };
      };
      /** @description Malformed request. For this operation `code: invalid_cursor` signals a malformed, scope-mismatched or expired `cursor`. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Problem"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  createDrawing: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. Replays return the original response with `Idempotency-Replayed: true`. */
        "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["DrawingInput"];
      };
    };
    responses: {
      /** @description Created. */
      201: {
        headers: {
          ETag: components["headers"]["ETag"];
          "Idempotency-Replayed": components["headers"]["IdempotencyReplayed"];
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Drawing"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      409: components["responses"]["Conflict"];
      413: components["responses"]["PayloadTooLarge"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  updateDrawing: {
    parameters: {
      query?: never;
      header: {
        /** @description ETag of the version the client believes it is editing. Omitting it accepts last-write-wins. */
        "If-Match"?: components["parameters"]["IfMatch"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        drawingId: components["parameters"]["DrawingId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["DrawingInput"];
      };
    };
    responses: {
      /** @description Replaced. */
      200: {
        headers: {
          ETag: components["headers"]["ETag"];
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Drawing"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
      412: components["responses"]["PreconditionFailed"];
      413: components["responses"]["PayloadTooLarge"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  deleteDrawing: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        drawingId: components["parameters"]["DrawingId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Deleted. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  batchUpsertDrawings: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. Replays return the original response with `Idempotency-Replayed: true`. */
        "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["DrawingBatchRequest"];
      };
    };
    responses: {
      /** @description Batch applied. */
      200: {
        headers: {
          "Idempotency-Replayed": components["headers"]["IdempotencyReplayed"];
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["DrawingBatchResult"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      409: components["responses"]["Conflict"];
      413: components["responses"]["PayloadTooLarge"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  listExchangeAccounts: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        environment?: components["parameters"]["EnvironmentQuery"];
        /** @description Include the cached wallet snapshot in each item. */
        include_balance?: boolean;
        kind?: components["schemas"]["AccountKind"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Accounts page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["ExchangeAccount"][];
          };
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  createExchangeAccount: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. Replays return the original response with `Idempotency-Replayed: true`. */
        "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["CreateExchangeAccountRequest"];
      };
    };
    responses: {
      /** @description Account registered in `pending` state. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ExchangeAccount"];
        };
      };
      403: components["responses"]["Forbidden"];
      409: components["responses"]["Conflict"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  getExchangeAccount: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        accountId: components["parameters"]["AccountId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Account. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ExchangeAccount"];
        };
      };
      403: components["responses"]["AccountScopeDenied"];
      404: components["responses"]["NotFound"];
    };
  };
  deleteExchangeAccount: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        accountId: components["parameters"]["AccountId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Deactivated. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
      409: components["responses"]["Conflict"];
    };
  };
  updateExchangeAccount: {
    parameters: {
      query?: never;
      header: {
        /** @description ETag of the version the client believes it is editing. Omitting it accepts last-write-wins. */
        "If-Match"?: components["parameters"]["IfMatch"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        accountId: components["parameters"]["AccountId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["UpdateExchangeAccountRequest"];
      };
    };
    responses: {
      /** @description Updated. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ExchangeAccount"];
        };
      };
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
      409: components["responses"]["Conflict"];
      412: components["responses"]["PreconditionFailed"];
      502: components["responses"]["ExchangeError"];
    };
  };
  getFeeRate: {
    parameters: {
      query?: {
        symbol?: components["schemas"]["Symbol"];
      };
      header?: never;
      path: {
        accountId: components["parameters"]["AccountId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Fee rates. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            /** Format: date-time */
            cached_at?: string;
            items?: {
              maker_fee_rate?: components["schemas"]["Decimal"];
              symbol?: components["schemas"]["Symbol"];
              taker_fee_rate?: components["schemas"]["Decimal"];
            }[];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
      502: components["responses"]["ExchangeError"];
    };
  };
  listApiKeys: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        accountId: components["parameters"]["AccountId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Keys. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: components["schemas"]["ApiKey"][];
          };
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  createApiKey: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        accountId: components["parameters"]["AccountId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["CreateApiKeyRequest"];
      };
    };
    responses: {
      /** @description Key verified and stored. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ApiKeyWithVerification"];
        };
      };
      400: components["responses"]["BadRequest"];
      403: components["responses"]["Forbidden"];
      /** @description Key rejected by the verification pipeline. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Problem"];
        };
      };
      502: components["responses"]["ExchangeError"];
    };
  };
  revokeApiKey: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        accountId: components["parameters"]["AccountId"];
        keyId: components["parameters"]["KeyId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Revoked. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  rotateApiKey: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        accountId: components["parameters"]["AccountId"];
        keyId: components["parameters"]["KeyId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["RotateApiKeyRequest"];
      };
    };
    responses: {
      /** @description Rotation started/completed. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ApiKeyRotation"];
        };
      };
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  testApiKey: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        accountId: components["parameters"]["AccountId"];
        keyId: components["parameters"]["KeyId"];
      };
      cookie?: never;
    };
    requestBody?: {
      content: {
        "application/json": {
          /** @default true */
          include_ws?: boolean;
        };
      };
    };
    responses: {
      /** @description Test result (a failed probe is still a 200 with `passed: false`). */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["KeyTestResult"];
        };
      };
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  listAccountProfiles: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        accountId: components["parameters"]["AccountId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Profiles. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: components["schemas"]["AccountProfile"][];
          };
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  createAccountProfile: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. Replays return the original response with `Idempotency-Replayed: true`. */
        "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        accountId: components["parameters"]["AccountId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["AccountProfileInput"];
      };
    };
    responses: {
      /** @description Profile created. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["AccountProfile"];
        };
      };
      403: components["responses"]["Forbidden"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  getAccountProfile: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        accountId: components["parameters"]["AccountId"];
        profileId: components["parameters"]["ProfileId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Profile. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["AccountProfile"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  updateAccountProfile: {
    parameters: {
      query?: never;
      header: {
        /** @description ETag of the version the client believes it is editing. Omitting it accepts last-write-wins. */
        "If-Match"?: components["parameters"]["IfMatch"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        accountId: components["parameters"]["AccountId"];
        profileId: components["parameters"]["ProfileId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["AccountProfileInput"];
      };
    };
    responses: {
      /** @description Replaced. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["AccountProfile"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      412: components["responses"]["PreconditionFailed"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  deleteAccountProfile: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        accountId: components["parameters"]["AccountId"];
        profileId: components["parameters"]["ProfileId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Deleted. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      403: components["responses"]["CsrfTokenInvalid"];
      409: components["responses"]["Conflict"];
    };
  };
  listExecutions: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Restrict to these accounts. Omit for every account in the caller's scope. */
        exchange_account_ids?: components["parameters"]["AccountIdsQuery"];
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        order_id?: string;
        symbol?: components["parameters"]["SymbolQueryOptional"];
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
        trade_group_id?: string;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Executions page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["Execution"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  listClosedPnl: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Restrict to these accounts. Omit for every account in the caller's scope. */
        exchange_account_ids?: components["parameters"]["AccountIdsQuery"];
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        symbol?: components["parameters"]["SymbolQueryOptional"];
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Closed-PnL page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["ClosedPnl"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  getLiveness: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Alive. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            /** @constant */
            status?: "ok";
          };
        };
      };
      429: components["responses"]["RateLimited"];
      /** @description Process is shutting down and refuses new work. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Problem"];
        };
      };
    };
  };
  getReadiness: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Ready. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            checks?: {
              [key: string]: "ok" | "fail";
            };
            /** @constant */
            status?: "ready";
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
      503: components["responses"]["ServiceUnavailable"];
    };
  };
  listIndicatorPresets: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Presets. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: components["schemas"]["IndicatorPreset"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  createIndicatorPreset: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["IndicatorPresetInput"];
      };
    };
    responses: {
      /** @description Created. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["IndicatorPreset"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  updateIndicatorPreset: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        presetId: components["parameters"]["PresetId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["IndicatorPresetInput"];
      };
    };
    responses: {
      /** @description Replaced. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["IndicatorPreset"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  deleteIndicatorPreset: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        presetId: components["parameters"]["PresetId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Deleted. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  listIndicators: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Catalogue. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: components["schemas"]["IndicatorDescriptor"][];
          };
        };
      };
    };
  };
  listInstruments: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        /** @description Substring match on symbol or base coin, for the symbol picker. */
        q?: string;
        /** @description Restrict to symbols currently in the recorded-symbol list. */
        recorded_only?: boolean;
        sort?: "symbol" | "turnover_24h" | "volume_24h" | "price_change_24h";
        status?: "Trading" | "PreLaunch" | "Delivering" | "Closed";
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Instruments page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["Instrument"][];
            meta?: components["schemas"]["InstrumentsPageMeta"];
          };
        };
      };
      400: components["responses"]["BadRequest"];
    };
  };
  getInstrument: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        symbol: components["parameters"]["SymbolPath"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Instrument. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["InstrumentDetail"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  getTicker: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        symbol: components["parameters"]["SymbolPath"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Ticker. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Ticker"];
        };
      };
      404: components["responses"]["NotFound"];
      503: components["responses"]["ServiceUnavailable"];
    };
  };
  refreshInstruments: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Refresh scheduled. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            /** Format: uuid */
            job_id?: string;
            /** Format: date-time */
            scheduled_at?: string;
          };
        };
      };
      403: components["responses"]["Forbidden"];
      429: components["responses"]["RateLimited"];
    };
  };
  getInvite: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        inviteToken: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Invite is valid. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            display_name: string;
            /** Format: date-time */
            expires_at: string;
            role: components["schemas"]["RoleName"];
          };
        };
      };
      404: components["responses"]["NotFound"];
      /** @description Too many invalid attempts from this address. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  redeemInvite: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        inviteToken: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          password: string;
        };
      };
    };
    responses: {
      /** @description TOTP enrolment started. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            method_id: string;
            otpauth_uri: string;
            secret_base32: string;
          };
        };
      };
      /** @description A role field was supplied; the invited role cannot be changed. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      404: components["responses"]["NotFound"];
      /** @description Password violates the policy. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Too many invalid attempts from this address. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  confirmInvite: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        inviteToken: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          code: string;
          method_id: string;
        };
      };
    };
    responses: {
      /** @description Account active. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            recovery_codes: string[];
            role: components["schemas"]["RoleName"];
            /** @enum {string} */
            status: "active";
          };
        };
      };
      /** @description A role field was supplied. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      404: components["responses"]["NotFound"];
      /** @description Invalid TOTP code. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Too many invalid attempts from this address. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  getJournalAnalytics: {
    parameters: {
      query?: {
        equity_curve_interval?: "trade" | "hour" | "day" | "week";
        /** @description Restrict to these accounts. Omit for every account in the caller's scope. */
        exchange_account_ids?: components["parameters"]["AccountIdsQuery"];
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        group_by?: (
          "symbol" | "tag" | "hour_of_day" | "day_of_week" | "side" | "account" | "setup"
        )[];
        symbol?: components["parameters"]["SymbolQueryOptional"];
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Analytics. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["JournalAnalytics"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  listJournalTags: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Tags. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: {
              colour?: string;
              /** Format: uuid */
              id?: string;
              name?: string;
              usage_count?: number;
            }[];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  createJournalTag: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          /** @default #5B8DEF */
          colour?: string;
          name: string;
        };
      };
    };
    responses: {
      /** @description Tag created. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            colour?: string;
            /** Format: uuid */
            id?: string;
            name?: string;
          };
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      409: components["responses"]["Conflict"];
    };
  };
  listJournalTrades: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Restrict to these accounts. Omit for every account in the caller's scope. */
        exchange_account_ids?: components["parameters"]["AccountIdsQuery"];
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        outcome?: "win" | "loss" | "breakeven";
        side?: components["schemas"]["JournalSide"];
        symbol?: components["parameters"]["SymbolQueryOptional"];
        tag?: string[];
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Journal page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["JournalTrade"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  getJournalTrade: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        journalTradeId: components["parameters"]["JournalTradeId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Entry. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["JournalTradeDetail"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  updateJournalTrade: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        journalTradeId: components["parameters"]["JournalTradeId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["UpdateJournalTradeRequest"];
      };
    };
    responses: {
      /** @description Updated. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["JournalTradeDetail"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
    };
  };
  getJournalTradeContext: {
    parameters: {
      query?: {
        bar_type?: components["schemas"]["BarType"];
        pad_seconds?: number;
        param?: string;
      };
      header?: never;
      path: {
        journalTradeId: components["parameters"]["JournalTradeId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Trade context. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["JournalTradeContext"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  listJournalNotes: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        journalTradeId: components["parameters"]["JournalTradeId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Notes. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: components["schemas"]["Note"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  createJournalNote: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        journalTradeId: components["parameters"]["JournalTradeId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["NoteInput"];
      };
    };
    responses: {
      /** @description Note created. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Note"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  listLayoutPresets: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Presets. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: components["schemas"]["LayoutPreset"][];
          };
        };
      };
    };
  };
  getBars: {
    parameters: {
      query: {
        bar_type: components["schemas"]["BarType"];
        /** @description The single cursor statement for `/market/klines` and `/market/bars`: an opaque, server-issued cursor from `meta.next_cursor`. Ordering and the cursor are by `(generation, index)` for non-time bars (the cursor carries the last position's `t`, `generation` and `index`, #2017); `/market/klines` and time bars use a `t` position (open time is unique there). Clients must treat the cursor as opaque and never parse it, so the switch is non-breaking. Malformed, expired or foreign -> `invalid_cursor`. A cursor is bound to the request that issued it (route, symbol, interval or `bar_type`+`param`); replaying it on a different request is `invalid_cursor`. Uncursored requests are served as the first page (see the route text). */
        cursor?: components["parameters"]["MarketCursor"];
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        include_delta?: boolean;
        include_open?: boolean;
        /** @description Maximum number of bars returned in one page. */
        limit?: components["parameters"]["BarLimit"];
        /** @description Bar-type parameter; see the table above. */
        param: string;
        symbol: components["parameters"]["SymbolQuery"];
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Bars. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["KlineResponse"];
        };
      };
      400: components["responses"]["BadRequest"];
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      422: components["responses"]["UnprocessableEntity"];
      503: components["responses"]["ServiceUnavailable"];
    };
  };
  getDataCoverage: {
    parameters: {
      query: {
        stream?: components["schemas"]["StreamKind"][];
        symbol: components["parameters"]["SymbolQuery"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Coverage report. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["DataCoverage"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  getFootprint: {
    parameters: {
      query: {
        bar_type: components["schemas"]["BarType"];
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        /** @description Diagonal imbalance threshold as a ratio (3 = 300 %). */
        imbalance_ratio?: number;
        /** @description Maximum number of bars returned in one page. */
        limit?: components["parameters"]["BarLimit"];
        /** @description Ignore imbalances whose larger side is below this base-asset volume. */
        min_imbalance_volume?: components["schemas"]["Decimal"];
        min_stack?: number;
        param: string;
        /** @description Merge N ticks per footprint row (1 = native tick resolution). */
        price_grouping?: number;
        symbol: components["parameters"]["SymbolQuery"];
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
        value_area_pct?: number;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Footprint bars. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["FootprintResponse"];
        };
      };
      400: components["responses"]["BadRequest"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  recomputeFootprint: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          bar_type: components["schemas"]["BarType"];
          /** Format: date-time */
          from: string;
          param: string;
          price_grouping?: components["schemas"]["Decimal"];
          symbol: components["schemas"]["Symbol"];
          /** Format: date-time */
          to: string;
        };
      };
    };
    responses: {
      /** @description Rebuild accepted. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            /** Format: uuid */
            job_id?: string;
          };
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  getFundingHistory: {
    parameters: {
      query: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        symbol: components["parameters"]["SymbolQuery"];
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Funding series. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            funding_interval_minutes?: number;
            items?: {
              /** @default false */
              estimated: boolean;
              funding_rate?: components["schemas"]["Decimal"];
              /** @default false */
              predicted: boolean;
              /** Format: date-time */
              t?: string;
            }[];
            symbol?: components["schemas"]["Symbol"];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
      503: components["responses"]["ServiceUnavailable"];
    };
  };
  getHeatmap: {
    parameters: {
      query: {
        depth?: 50 | 200 | 500;
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        /** @description Scale cells to 0..1 per column (`column`), over the whole window (`window`), or not at all. */
        normalize?: "none" | "column" | "window";
        price_grouping?: number;
        symbol: components["parameters"]["SymbolQuery"];
        time_bucket_ms?: 100 | 250 | 500 | 1000 | 5000 | 60000;
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Heatmap matrix. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HeatmapResponse"];
        };
      };
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  getKlines: {
    parameters: {
      query: {
        /** @description The single cursor statement for `/market/klines` and `/market/bars`: an opaque, server-issued cursor from `meta.next_cursor`. Ordering and the cursor are by `(generation, index)` for non-time bars (the cursor carries the last position's `t`, `generation` and `index`, #2017); `/market/klines` and time bars use a `t` position (open time is unique there). Clients must treat the cursor as opaque and never parse it, so the switch is non-breaking. Malformed, expired or foreign -> `invalid_cursor`. A cursor is bound to the request that issued it (route, symbol, interval or `bar_type`+`param`); replaying it on a different request is `invalid_cursor`. Uncursored requests are served as the first page (see the route text). */
        cursor?: components["parameters"]["MarketCursor"];
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        /** @description Attach per-bar delta/CVD/trade-count (requires recorded tape for the window). */
        include_delta?: boolean;
        include_open?: boolean;
        interval: components["schemas"]["KlineInterval"];
        /** @description Maximum number of bars returned in one page. */
        limit?: components["parameters"]["BarLimit"];
        /** @description Which price series to aggregate. */
        price_type?: "trade" | "mark" | "index" | "premium_index";
        symbol: components["parameters"]["SymbolQuery"];
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Candles. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["KlineResponse"];
        };
      };
      400: components["responses"]["BadRequest"];
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      422: components["responses"]["UnprocessableEntity"];
      503: components["responses"]["ServiceUnavailable"];
    };
  };
  getLiquidations: {
    parameters: {
      query: {
        cluster_window_ms?: number;
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        min_notional_usd?: components["schemas"]["Decimal"];
        /** @description Side of the liquidated position (`buy` = short liquidated / buy-side print). */
        side?: "buy" | "sell";
        symbol: components["parameters"]["SymbolQuery"];
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Liquidations page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["Liquidation"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  getMetrics: {
    parameters: {
      query: {
        /** @description Bar grid the metric is sampled on (metrics that are bar-scoped). */
        bar_type?: components["schemas"]["BarType"];
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        /** @description Repeatable. One series per value. */
        metric: components["schemas"]["MetricCode"][];
        param?: string;
        /** @description JSON object of per-metric overrides, e.g. `{"adx":{"period":21},"cvd":{"anchor":"utc_day"}}`. */
        params?: string;
        symbol: components["parameters"]["SymbolQuery"];
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Metric series. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["MetricsResponse"];
        };
      };
      400: components["responses"]["BadRequest"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  getOpenInterestHistory: {
    parameters: {
      query: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        interval?: "5min" | "15min" | "30min" | "1h" | "4h" | "1d";
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        symbol: components["parameters"]["SymbolQuery"];
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description OI series. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: {
              open_interest?: components["schemas"]["Decimal"];
              open_interest_value?: components["schemas"]["Decimal"];
              /** Format: date-time */
              t?: string;
            }[];
            symbol?: components["schemas"]["Symbol"];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  getOrderbookSnapshot: {
    parameters: {
      query: {
        /** @description Levels per side. Mirrors Bybit's supported tiers for `linear`. */
        depth?: 1 | 50 | 200 | 500;
        symbol: components["parameters"]["SymbolQuery"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Book snapshot. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["OrderbookSnapshot"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
      503: components["responses"]["ServiceUnavailable"];
    };
  };
  getProfile: {
    parameters: {
      query: {
        fixed_duration_minutes?: number;
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        /** @description Detect high/low volume nodes (local maxima/minima of the histogram). */
        include_hvn_lvn?: boolean;
        kind: "volume" | "delta" | "tpo";
        price_grouping?: number;
        /** @description Session boundary for `split=session`; crypto has no natural session (digest 08 §5). */
        session_anchor?: "utc_day" | "funding_8h" | "custom";
        /** @description `HH:MM` UTC start when `session_anchor=custom`. */
        session_anchor_time?: string;
        split?: "composite" | "session" | "fixed";
        symbol: components["parameters"]["SymbolQuery"];
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
        tpo_period_minutes?: number;
        value_area_pct?: number;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Profiles. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ProfileResponse"];
        };
      };
      400: components["responses"]["BadRequest"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  explainRegime: {
    parameters: {
      query: {
        symbol: components["parameters"]["SymbolQuery"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Regime explanation. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RegimeExplanation"];
        };
      };
    };
  };
  getTrades: {
    parameters: {
      query: {
        cluster_tolerance_ticks?: number;
        cluster_window_ms?: number;
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        min_size?: components["schemas"]["Decimal"];
        side?: "buy" | "sell";
        symbol: components["parameters"]["SymbolQuery"];
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Trades page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["PublicTrade"][];
          };
        };
      };
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  getMe: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Current identity. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Me"];
        };
      };
      401: components["responses"]["Unauthorized"];
    };
  };
  getMyKeymap: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Active keymap. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            bindings?: components["schemas"]["HotkeyBinding"][];
            /** Format: uuid */
            hotkey_profile_id?: string;
          };
        };
      };
    };
  };
  getMyLimits: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Effective limits. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["EffectiveLimits"];
        };
      };
    };
  };
  getMyPreferences: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Effective settings. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Settings"];
        };
      };
      401: components["responses"]["Unauthorized"];
    };
  };
  updateMyPreferences: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["SettingsPatch"];
      };
    };
    responses: {
      /** @description Updated settings. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Settings"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  listMySessions: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Active sessions. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: components["schemas"]["UserSession"][];
          };
        };
      };
    };
  };
  revokeMySession: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        sessionId: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Revoked. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
    };
  };
  listNotifications: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        kind?: ("alert" | "rule" | "order" | "risk" | "system")[];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        unread_only?: boolean;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Notifications, newest first. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["Notification"][];
          };
        };
      };
    };
  };
  getOnboardingChecklist: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Checklist state. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["OnboardingChecklist"];
        };
      };
    };
  };
  dismissOnboardingChecklist: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Dismissed. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      403: components["responses"]["CsrfTokenInvalid"];
      /** @description Checklist is not complete. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  completeOnboarding: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Marked complete. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      403: components["responses"]["CsrfTokenInvalid"];
    };
  };
  listOrders: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Restrict to these accounts. Omit for every account in the caller's scope. */
        exchange_account_ids?: components["parameters"]["AccountIdsQuery"];
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        intent?: components["schemas"]["OrderIntent"][];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        /** @description Shorthand for the non-terminal state set. */
        open_only?: boolean;
        state?: components["schemas"]["OrderState"][];
        symbol?: components["parameters"]["SymbolQueryOptional"];
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
        trade_group_id?: string;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Orders page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["Order"][];
          };
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  placeOrder: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["PlaceOrderRequest"];
      };
    };
    responses: {
      /** @description Accepted into the OMS; submission to the exchange is in flight. */
      202: {
        headers: {
          ETag: components["headers"]["ETag"];
          "Idempotency-Replayed": components["headers"]["IdempotencyReplayed"];
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["TradeGroup"];
        };
      };
      400: components["responses"]["BadRequest"];
      403: components["responses"]["Forbidden"];
      409: components["responses"]["Conflict"];
      422: components["responses"]["UnprocessableEntity"];
      429: components["responses"]["RateLimited"];
      502: components["responses"]["ExchangeError"];
      503: components["responses"]["ServiceUnavailable"];
    };
  };
  getOrder: {
    parameters: {
      query?: {
        include_events?: boolean;
      };
      header?: never;
      path: {
        orderId: components["parameters"]["OrderId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Order. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["OrderWithEvents"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  cancelOrder: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        orderId: components["parameters"]["OrderId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Cancel accepted. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Order"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
      502: components["responses"]["ExchangeError"];
    };
  };
  amendOrder: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /** @description ETag of the version the client believes it is editing. Omitting it accepts last-write-wins. */
        "If-Match"?: components["parameters"]["IfMatch"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        orderId: components["parameters"]["OrderId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["AmendOrderRequest"];
      };
    };
    responses: {
      /** @description Amend accepted. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Order"];
        };
      };
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
      412: components["responses"]["PreconditionFailed"];
      422: components["responses"]["UnprocessableEntity"];
      502: components["responses"]["ExchangeError"];
    };
  };
  getOrderDiagnostics: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        orderId: components["parameters"]["OrderId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Diagnostics. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["OrderDiagnostics"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  cancelAllOrders: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["CancelAllRequest"];
      };
    };
    responses: {
      /** @description Per-account cancel results. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["BulkAccountResult"];
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  listPermissions: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Permission catalogue. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: {
              /** @example trading */
              category?: string;
              /** @example orders:write */
              code?: string;
              description?: string;
            }[];
          };
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  listPositions: {
    parameters: {
      query?: {
        aggregate?: boolean;
        /** @description Restrict to these accounts. Omit for every account in the caller's scope. */
        exchange_account_ids?: components["parameters"]["AccountIdsQuery"];
        open_only?: boolean;
        symbol?: components["parameters"]["SymbolQueryOptional"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Positions. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            aggregates?: components["schemas"]["AggregatePosition"][];
            items?: components["schemas"]["Position"][];
          };
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  getPosition: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        positionId: components["parameters"]["PositionId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Position. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Position"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  closePosition: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        positionId: components["parameters"]["PositionId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ClosePositionRequest"];
      };
    };
    responses: {
      /** @description Close order accepted. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["TradeGroup"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  setPositionLeverage: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        positionId: components["parameters"]["PositionId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          leverage: components["schemas"]["Decimal"];
        };
      };
    };
    responses: {
      /** @description Leverage applied. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Position"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      422: components["responses"]["UnprocessableEntity"];
      502: components["responses"]["ExchangeError"];
    };
  };
  reversePosition: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        positionId: components["parameters"]["PositionId"];
      };
      cookie?: never;
    };
    requestBody?: {
      content: {
        "application/json": components["schemas"]["ReversePositionRequest"];
      };
    };
    responses: {
      /** @description Reversal accepted. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["TradeGroup"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  setPositionTpSl: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        positionId: components["parameters"]["PositionId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["SetTpSlRequest"];
      };
    };
    responses: {
      /** @description Applied, with resolved prices. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["TpSlResult"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
      422: components["responses"]["UnprocessableEntity"];
      502: components["responses"]["ExchangeError"];
    };
  };
  closeAllPositions: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          /** @default true */
          cancel_open_orders?: boolean;
          exchange_account_ids?: string[];
          symbol?: components["schemas"]["Symbol"];
        };
      };
    };
    responses: {
      /** @description Per-account results. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["BulkAccountResult"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  listRetentionPolicies: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Policies. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: components["schemas"]["RetentionPolicy"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  setRetentionPolicies: {
    parameters: {
      query?: {
        apply_now?: boolean;
      };
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          items: components["schemas"]["RetentionPolicyInput"][];
        };
      };
    };
    responses: {
      /** @description Policies replaced. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: components["schemas"]["RetentionPolicy"][];
          };
        };
      };
      403: components["responses"]["Forbidden"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  listRecordingSessions: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        symbol?: components["parameters"]["SymbolQueryOptional"];
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Sessions page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["RecordingSession"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  getRecordingStatus: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Recorder status. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RecordingStatus"];
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  getStorageUsage: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Storage report. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["StorageUsage"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  listRecordedSymbols: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        pinned?: boolean;
        reason?: components["schemas"]["RecordReason"];
        state?: components["schemas"]["RecordingState"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Recorded symbols page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["RecordedSymbol"][];
          };
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  addRecordedSymbol: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. Replays return the original response with `Idempotency-Replayed: true`. */
        "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["AddRecordedSymbolRequest"];
      };
    };
    responses: {
      /** @description Already recorded; existing entry returned. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RecordedSymbol"];
        };
      };
      /** @description Recording started. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RecordedSymbolWithEstimate"];
        };
      };
      403: components["responses"]["Forbidden"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  getRecordedSymbol: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        recordedSymbolId: components["parameters"]["RecordedSymbolId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Entry. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RecordedSymbol"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  removeRecordedSymbol: {
    parameters: {
      query?: {
        force?: boolean;
        purge_data?: boolean;
      };
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        recordedSymbolId: components["parameters"]["RecordedSymbolId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Stopped. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
      409: components["responses"]["Conflict"];
    };
  };
  updateRecordedSymbol: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        recordedSymbolId: components["parameters"]["RecordedSymbolId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["UpdateRecordedSymbolRequest"];
      };
    };
    responses: {
      /** @description Updated. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RecordedSymbol"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  pinRecordedSymbol: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        recordedSymbolId: components["parameters"]["RecordedSymbolId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          pinned: boolean;
          /** @description Applied when unpinning; defaults to the global retention default (30). */
          retention_days?: number;
        };
      };
    };
    responses: {
      /** @description Pin state updated. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RecordedSymbol"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
    };
  };
  listReplaySessions: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        state?: components["schemas"]["ReplayState"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Replay sessions page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["ReplaySession"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  createReplaySession: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. Replays return the original response with `Idempotency-Replayed: true`. */
        "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["CreateReplaySessionRequest"];
      };
    };
    responses: {
      /** @description Session created. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ReplaySession"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  getReplaySession: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        replayId: components["parameters"]["ReplayId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Session. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ReplaySession"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  deleteReplaySession: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        replayId: components["parameters"]["ReplayId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Destroyed. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
    };
  };
  controlReplaySession: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        replayId: components["parameters"]["ReplayId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ReplayControlRequest"];
      };
    };
    responses: {
      /** @description New session state. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ReplaySession"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  overrideRiskLockout: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        accountId: components["parameters"]["AccountId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          reason: string;
        };
      };
    };
    responses: {
      /** @description Lockout cleared. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RiskSummary"];
        };
      };
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  getRiskSummary: {
    parameters: {
      query?: {
        environment?: components["parameters"]["EnvironmentQuery"];
        /** @description Restrict to these accounts. Omit for every account in the caller's scope. */
        exchange_account_ids?: components["parameters"]["AccountIdsQuery"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Risk summary. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RiskSummary"];
        };
      };
      403: components["responses"]["AccountScopeDenied"];
    };
  };
  listRoles: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Roles. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: components["schemas"]["Role"][];
          };
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  listRules: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        mode?: components["schemas"]["RuleMode"];
        scope?: components["schemas"]["RuleScope"];
        symbol?: components["parameters"]["SymbolQueryOptional"];
        tag?: string;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Rules page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["Rule"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  createRule: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. Replays return the original response with `Idempotency-Replayed: true`. */
        "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["RuleInput"];
      };
    };
    responses: {
      /** @description Rule created (disabled). */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Rule"];
        };
      };
      403: components["responses"]["Forbidden"];
      422: components["responses"]["RuleIrInvalid"];
    };
  };
  getRule: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        ruleId: components["parameters"]["RuleId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Rule. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RuleDetail"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  updateRule: {
    parameters: {
      query?: never;
      header: {
        /** @description ETag of the version the client believes it is editing. Omitting it accepts last-write-wins. */
        "If-Match"?: components["parameters"]["IfMatch"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        ruleId: components["parameters"]["RuleId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["RuleInput"];
      };
    };
    responses: {
      /** @description New version created. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RuleDetail"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      412: components["responses"]["PreconditionFailed"];
      422: components["responses"]["RuleIrInvalid"];
    };
  };
  deleteRule: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        ruleId: components["parameters"]["RuleId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Deleted. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      403: components["responses"]["CsrfTokenInvalid"];
      409: components["responses"]["Conflict"];
    };
  };
  setActiveRuleVersion: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        ruleId: components["parameters"]["RuleId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          note?: string;
          /** Format: uuid */
          version_id: string;
        };
      };
    };
    responses: {
      /** @description Active version changed. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RuleDetail"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
    };
  };
  compileRule: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        ruleId: components["parameters"]["RuleId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          /** @description Optional stored model of the OTHER editor. When present both are compiled and a divergence is reported in `round_trip` (US-RULE-006); the server never reconciles. */
          counterpart_model?: {
            [key: string]: unknown;
          };
          /** @enum {string} */
          editor: "form" | "graph";
          model: {
            [key: string]: unknown;
          };
        };
      };
    };
    responses: {
      /** @description Compiled IR. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            blocks_arming?: boolean;
            ir?: components["schemas"]["RuleIr"];
            ir_hash?: string;
            issues?: components["schemas"]["RuleValidationIssue"][];
            round_trip?: {
              diff: {
                counterpart?: unknown;
                model?: unknown;
                path?: string;
              }[];
              match: boolean;
            };
          };
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      422: components["responses"]["RuleIrInvalid"];
    };
  };
  setRuleMode: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        ruleId: components["parameters"]["RuleId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          mode: components["schemas"]["RuleMode"];
          reason?: string;
        };
      };
    };
    responses: {
      /** @description Mode changed. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Rule"];
        };
      };
      403: components["responses"]["Forbidden"];
      409: components["responses"]["Conflict"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  listRuleRuns: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        kind?: "live" | "simulation";
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        status?: components["schemas"]["RuleRunStatus"];
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
      };
      header?: never;
      path: {
        ruleId: components["parameters"]["RuleId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Runs page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["RuleRun"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  simulateRule: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        ruleId: components["parameters"]["RuleId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["SimulateRuleRequest"];
      };
    };
    responses: {
      /** @description Simulation completed synchronously (short windows). */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RuleSimulationResult"];
        };
      };
      /** @description Simulation scheduled (long windows). */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            /** Format: uuid */
            run_id?: string;
            /** @constant */
            status?: "running";
          };
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  listRuleVersions: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
      };
      header?: never;
      path: {
        ruleId: components["parameters"]["RuleId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Versions page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["RuleVersion"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  getRuleVersion: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        ruleId: components["parameters"]["RuleId"];
        versionId: components["parameters"]["VersionId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Version. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RuleVersionDetail"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  listRuleAccounts: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Granted account ids. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            accounts: string[];
          };
        };
      };
      /** @description No verified session. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Missing rules:read. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
    };
  };
  listRuleRunEvents: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
      };
      header?: never;
      path: {
        runId: components["parameters"]["RunId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Events page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["RuleEvent"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  validateRule: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          ir: components["schemas"]["RuleIr"];
          scope?: components["schemas"]["RuleScope"];
        };
      };
    };
    responses: {
      /** @description Validation report (a failing IR is still a 200 with `valid: false`). */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RuleValidationResult"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  getRuleVocabulary: {
    parameters: {
      query?: {
        /** @description Scope availability to a symbol; metrics needing recorded data for a symbol that is not on the recorded-symbol list are returned `available: false` with the recorder action that would satisfy them. */
        symbol?: string;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Vocabulary. Strong `ETag`, `Cache-Control: private, max-age=60`; varies by the caller's permission set. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RuleVocabulary"];
        };
      };
      /** @description Not modified (`If-None-Match` matched). */
      304: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Engine offline - the registry is empty or not wired. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": {
            [key: string]: unknown;
          };
        };
      };
    };
  };
  runScanner: {
    parameters: {
      query?: {
        /** @description Filter expression set, URL-encoded JSON matching `ScannerFilter`. */
        filters?: string;
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        sort?:
          | "volume_24h"
          | "price_change_pct_24h"
          | "cvd"
          | "tape_speed"
          | "open_interest"
          | "liquidation_intensity";
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Ranked results. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: components["schemas"]["ScannerRow"][];
            meta?: components["schemas"]["DataMeta"];
          };
        };
      };
    };
  };
  getRuleIrSchema: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description JSON Schema (draft 2020-12). */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            [key: string]: unknown;
          };
        };
      };
    };
  };
  setSessionEnvironment: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          environment: components["schemas"]["Environment"];
        };
      };
    };
    responses: {
      /** @description Environment switched. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            environment?: components["schemas"]["Environment"];
          };
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  getSettings: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Settings. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Settings"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  updateSettings: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["SettingsPatch"];
      };
    };
    responses: {
      /** @description Effective settings after the merge. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Settings"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  armOneClickTrading: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          armed: boolean;
          /** @default 300 */
          ttl_seconds?: number;
        };
      };
    };
    responses: {
      /** @description Arm state. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            arm_token?: string | null;
            armed?: boolean;
            /** Format: date-time */
            expires_at?: string | null;
          };
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  recordHotkeyBindingAudit: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["HotkeyBindingAuditInput"];
      };
    };
    responses: {
      /** @description Audit record appended. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  listHotkeyProfiles: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Profiles. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: components["schemas"]["HotkeyProfile"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  createHotkeyProfile: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["HotkeyProfileInput"];
      };
    };
    responses: {
      /** @description Created. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HotkeyProfile"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      409: components["responses"]["Conflict"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  updateHotkeyProfile: {
    parameters: {
      query?: never;
      header: {
        /** @description ETag of the version the client believes it is editing. Omitting it accepts last-write-wins. */
        "If-Match"?: components["parameters"]["IfMatch"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        hotkeyProfileId: components["parameters"]["HotkeyProfileId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["HotkeyProfileInput"];
      };
    };
    responses: {
      /** @description Replaced. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HotkeyProfile"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      409: components["responses"]["Conflict"];
      412: components["responses"]["PreconditionFailed"];
    };
  };
  deleteHotkeyProfile: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        hotkeyProfileId: components["parameters"]["HotkeyProfileId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Deleted. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      403: components["responses"]["CsrfTokenInvalid"];
      409: components["responses"]["Conflict"];
    };
  };
  activateHotkeyProfile: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        hotkeyProfileId: components["parameters"]["HotkeyProfileId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Activated. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HotkeyProfile"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
    };
  };
  getBuildInfo: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Build info. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["BuildInfo"];
        };
      };
    };
  };
  postFrontendTelemetry: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["FrontendTelemetry"];
      };
    };
    responses: {
      /** @description Accepted and aggregated. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      400: components["responses"]["BadRequest"];
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["CsrfTokenInvalid"];
      429: components["responses"]["RateLimited"];
    };
  };
  listTradeGroups: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Inclusive start of the time window (RFC 3339 UTC). */
        from?: components["parameters"]["From"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        status?: components["schemas"]["TradeGroupStatus"][];
        symbol?: components["parameters"]["SymbolQueryOptional"];
        /** @description Exclusive end of the time window (RFC 3339 UTC). Defaults to now. */
        to?: components["parameters"]["To"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Trade groups page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["TradeGroup"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  createTradeGroup: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["CreateTradeGroupRequest"];
      };
    };
    responses: {
      /** @description Trade group accepted; legs are submitting. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["TradeGroup"];
        };
      };
      400: components["responses"]["BadRequest"];
      403: components["responses"]["Forbidden"];
      422: components["responses"]["UnprocessableEntity"];
      429: components["responses"]["RateLimited"];
    };
  };
  getTradeGroup: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        tradeGroupId: components["parameters"]["TradeGroupId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Trade group. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["TradeGroup"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  amendTradeGroup: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        tradeGroupId: components["parameters"]["TradeGroupId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["AmendTradeGroupRequest"];
      };
    };
    responses: {
      /** @description Per-leg amend results. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["BulkLegResult"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  cancelTradeGroup: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        tradeGroupId: components["parameters"]["TradeGroupId"];
      };
      cookie?: never;
    };
    requestBody?: {
      content: {
        "application/json": {
          /** @default false */
          flatten_filled?: boolean;
          /** @description Restrict to these leg ids; omit for all legs. */
          legs?: string[];
        };
      };
    };
    responses: {
      /** @description Per-leg cancel results. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["BulkLegResult"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
    };
  };
  previewTradeGroup: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["CreateTradeGroupRequest"];
      };
    };
    responses: {
      /** @description Resolved preview. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["TradeGroupPreview"];
        };
      };
      403: components["responses"]["Forbidden"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  getKillSwitch: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Kill-switch state. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["KillSwitch"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  setKillSwitch: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. REQUIRED on this operation; also seeds the deterministic exchange `orderLinkId`. */
        "Idempotency-Key": components["parameters"]["IdempotencyKeyRequired"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["SetKillSwitchRequest"];
      };
    };
    responses: {
      /** @description New kill-switch state plus the actions taken. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["KillSwitchResult"];
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  listUsers: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
        /** @description Case-insensitive substring match on username or email. */
        q?: string;
        role?: components["schemas"]["RoleName"];
        status?: components["schemas"]["UserStatus"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Users page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["User"][];
          };
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  createUser: {
    parameters: {
      query?: never;
      header: {
        /** @description Client-generated UUIDv4. Replays return the original response with `Idempotency-Replayed: true`. */
        "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["CreateUserRequest"];
      };
    };
    responses: {
      /** @description User invited. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["UserWithInvite"];
        };
      };
      403: components["responses"]["Forbidden"];
      409: components["responses"]["Conflict"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  getUser: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        userId: components["parameters"]["UserId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description User. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["User"];
        };
      };
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  deleteUser: {
    parameters: {
      query?: {
        purge?: boolean;
      };
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        userId: components["parameters"]["UserId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Disabled. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
      409: components["responses"]["Conflict"];
    };
  };
  updateUser: {
    parameters: {
      query?: never;
      header: {
        /** @description ETag of the version the client believes it is editing. Omitting it accepts last-write-wins. */
        "If-Match"?: components["parameters"]["IfMatch"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        userId: components["parameters"]["UserId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["UpdateUserRequest"];
      };
    };
    responses: {
      /** @description Updated. */
      200: {
        headers: {
          ETag: components["headers"]["ETag"];
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["User"];
        };
      };
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
      409: components["responses"]["Conflict"];
      412: components["responses"]["PreconditionFailed"];
    };
  };
  listUserAccountAccess: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        userId: components["parameters"]["UserId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Grants. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: components["schemas"]["AccountAccessGrant"][];
          };
        };
      };
      403: components["responses"]["Forbidden"];
    };
  };
  setUserAccountAccess: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        userId: components["parameters"]["UserId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          grants: components["schemas"]["AccountAccessGrantInput"][];
        };
      };
    };
    responses: {
      /** @description Grants replaced. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: components["schemas"]["AccountAccessGrant"][];
          };
        };
      };
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  reissueInvite: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        userId: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description New invitation with one-time link. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
    };
  };
  revokeInvite: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        userId: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Revoked. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
    };
  };
  resetUserMfa: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        userId: components["parameters"]["UserId"];
      };
      cookie?: never;
    };
    requestBody?: {
      content: {
        "application/json": {
          /** @default false */
          acknowledge_unknown_positions?: boolean;
        };
      };
    };
    responses: {
      /** @description Reset. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            methods_revoked: number;
            sessions_revoked: number;
            /** Format: uuid */
            target_user_id: string;
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      409: components["responses"]["Conflict"];
    };
  };
  previewMfaReset: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        userId: components["parameters"]["UserId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Preview. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            message: string;
            /** @description Null when the position state is unknown - never a fabricated 0. */
            open_position_count: number | null;
            /** @description Backing store; `not_deployed` until the OMS position store lands. */
            position_source: string;
            /** @enum {string} */
            positions: "known" | "unavailable";
            requires_acknowledge_unknown_positions: boolean;
            /** Format: uuid */
            target_user_id: string;
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
    };
  };
  setUserRoles: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        userId: components["parameters"]["UserId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": {
          roles: components["schemas"]["RoleName"][];
        };
      };
    };
    responses: {
      /** @description Roles replaced. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["User"];
        };
      };
      403: components["responses"]["Forbidden"];
      409: components["responses"]["Conflict"];
    };
  };
  listPendingInvites: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Pending invitations (no tokens). */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items: Record<string, never>[];
          };
        };
      };
    };
  };
  listWatchlists: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Watchlists. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: components["schemas"]["Watchlist"][];
          };
        };
      };
    };
  };
  createWatchlist: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["WatchlistInput"];
      };
    };
    responses: {
      /** @description Created. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Watchlist"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
    };
  };
  updateWatchlist: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        watchlistId: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["WatchlistInput"];
      };
    };
    responses: {
      /** @description Updated. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Watchlist"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
    };
  };
  deleteWatchlist: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        watchlistId: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Deleted. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      403: components["responses"]["CsrfTokenInvalid"];
      404: components["responses"]["NotFound"];
    };
  };
  listWorkspaces: {
    parameters: {
      query?: {
        /** @description Opaque forward cursor from `meta.next_cursor`. Cursors expire after 1 hour. */
        cursor?: components["parameters"]["Cursor"];
        /** @description Page size. */
        limit?: components["parameters"]["Limit"];
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Workspaces page. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Page"] & {
            items?: components["schemas"]["Workspace"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  createWorkspace: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["WorkspaceInput"];
      };
    };
    responses: {
      /** @description Created. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Workspace"];
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  getWorkspace: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspaceId: components["parameters"]["WorkspaceId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Workspace. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["WorkspaceDetail"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  updateWorkspace: {
    parameters: {
      query?: never;
      header: {
        /** @description ETag of the version the client believes it is editing. Omitting it accepts last-write-wins. */
        "If-Match"?: components["parameters"]["IfMatch"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        workspaceId: components["parameters"]["WorkspaceId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["WorkspaceInput"];
      };
    };
    responses: {
      /** @description Updated. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Workspace"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      412: components["responses"]["PreconditionFailed"];
    };
  };
  deleteWorkspace: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        workspaceId: components["parameters"]["WorkspaceId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Deleted. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      403: components["responses"]["CsrfTokenInvalid"];
      409: components["responses"]["Conflict"];
    };
  };
  exportWorkspace: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspaceId: components["parameters"]["WorkspaceId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Workspace bundle. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["WorkspaceBundle"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  listLayouts: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        workspaceId: components["parameters"]["WorkspaceId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Layouts. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": {
            items?: components["schemas"]["Layout"][];
          };
        };
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
  createLayout: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        workspaceId: components["parameters"]["WorkspaceId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["LayoutInput"];
      };
    };
    responses: {
      /** @description Created. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Layout"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      422: components["responses"]["UnprocessableEntity"];
    };
  };
  getLayout: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        layoutId: components["parameters"]["LayoutId"];
        workspaceId: components["parameters"]["WorkspaceId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Layout. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Layout"];
        };
      };
      404: components["responses"]["NotFound"];
    };
  };
  updateLayout: {
    parameters: {
      query?: never;
      header: {
        /** @description ETag of the version the client believes it is editing. Omitting it accepts last-write-wins. */
        "If-Match"?: components["parameters"]["IfMatch"];
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        layoutId: components["parameters"]["LayoutId"];
        workspaceId: components["parameters"]["WorkspaceId"];
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["LayoutInput"];
      };
    };
    responses: {
      /** @description Replaced. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Layout"];
        };
      };
      403: components["responses"]["CsrfTokenInvalid"];
      412: components["responses"]["PreconditionFailed"];
    };
  };
  deleteLayout: {
    parameters: {
      query?: never;
      header: {
        /**
         * @description SR-041 double-submit token. Must equal the `__Host-cv_csrf` cookie, and its MAC must verify
         *     against the session id the server resolves itself (not merely header == cookie). All
         *     comparisons are constant time. Sent by every client, browser or not. Required on every state-changing operation except
         *     the pre-session ones (see the CSRF section of `info.description`). Missing, mismatched or
         *     unbound → `403 csrf_token_invalid`.
         */
        "X-CSRF-Token": components["parameters"]["CsrfToken"];
      };
      path: {
        layoutId: components["parameters"]["LayoutId"];
        workspaceId: components["parameters"]["WorkspaceId"];
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Deleted. */
      204: {
        headers: {
          [name: string]: unknown;
        };
        content?: never;
      };
      401: components["responses"]["Unauthorized"];
      403: components["responses"]["Forbidden"];
      404: components["responses"]["NotFound"];
    };
  };
}
