# Security Policy

CandleViewer is a **private, self-hosted trading terminal** that holds exchange API credentials and can
place real orders with real capital. Security defects here have direct financial consequences. This policy
is binding on every contributor and every AI agent; it implements Constitution §12
([`CONSTITUTION.md`](CONSTITUTION.md)).

---

## 1. Reporting a vulnerability

**Do not open a public GitHub issue, discussion, pull request or comment for a suspected vulnerability.**

Report privately, in this order of preference:

1. **GitHub Private Vulnerability Reporting** — repository → _Security_ → _Report a vulnerability_
   (preferred; creates a private advisory thread).
2. **Direct message to the owner** `@basiltt` on the project's private channel.

Include, where you can:

- Affected component/path and version or commit SHA.
- Impact: what an attacker achieves (order placement, credential disclosure, RBAC bypass, data loss…).
- Reproduction steps or a minimal proof of concept — **with redacted or synthetic credentials only**.
- Environment (`demo`/`live`/`testnet`, deployment, browser/Electron version).
- Any suggested mitigation.

**Never include real API keys, secrets, session tokens, or captured live traffic containing them.** If a
credential is already exposed, say so in words and rotate it immediately (§5).

**Escalation chain:** reporter → Security engineer (triage) → Owner `@basiltt` (disposition) → a fix
ticket labelled `security` → re-scan proof attached before the ticket closes. A report's lifecycle is
tracked as a private GitHub Security Advisory linked to the fix ticket, so report → fix → re-scan stays
auditable end to end.

### Severity and response SLAs

Severity is assessed against the bug taxonomy owned by `docs/plan/03-testing-strategy.md` §11.3 —
including that table's Triage SLA and Fix-before columns, which this file does not restate (C-16.5). The
table below adds only the security-report-specific commitment: how soon a reporter hears back with an
initial acknowledgement, which is always no later than that severity's §11.3 triage SLA.

| Severity          | Example (security)                                                                                                                                                            | Acknowledgement  |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| **P0 — Critical** | API-key confidentiality breach, withdrawal-permission-off invariant defeated, RBAC bypass, missing native stop-loss, unauthorised order placement, audit-log integrity broken | 1 business hour  |
| **P1 — High**     | Auth/session weakness, exploitable but not yet exploited, partial RBAC scoping gap                                                                                            | 4 business hours |
| **P2 — Medium**   | Defence-in-depth gap without a direct path to capital or credential loss                                                                                                      | 1 business day   |
| **P3 — Low**      | Hardening suggestion, informational finding                                                                                                                                   | 2 business days  |

See §11.3 for the Triage SLA and Fix-before commitment per severity. We also send the reporter a status
update at least once every 2 business days for P0/P1 and once per week for P2/P3 until the fix ships, and
tell them when it ships. A security emergency may also be
handled under the Constitution's 24-hour emergency-amendment path (C-16.1 step 3), with any resulting rule
change re-ratified within 2 weeks.

Because CandleViewer is a private, single-owner deployment **there is no bug-bounty programme** — this is
a deliberate decision, not an omission — and no public disclosure timeline; advisories are published as
private GitHub Security Advisories and, once a fix ships, summarised (without exploit detail) in
`CHANGELOG.md` under _Security_.

### In-scope / out-of-scope

**In scope:** the web app, Electron shell, the FastAPI backend, the Bybit v5 adapter, Postgres/QuestDB/
Parquet storage, the Tailscale-only network path, CI/CD supply chain — the full asset list is
`docs/plan/04-security-program.md` §2. **Out of scope:** physical security of the owner's host, Bybit's
own platform security, the owner's Bybit web-login credentials, any mobile client, multi-tenant/SaaS
concerns, payment processing — the authoritative list is `docs/plan/04-security-program.md` §1.3
(linked, not restated here).

### Safe harbour

Good-faith research by the internal team, contracted pen-testers (Constitution C-15.9, the R4
live-enablement gate in `docs/plan/07-release-and-prr.md` §6), and dependency/security researchers
reporting upstream CVEs is welcome, **against the `demo` environment only**. Testing against the **`live`
environment is explicitly excluded from safe harbour** — it holds real funds and real orders — mirroring
the demo-not-prod rule in `docs/plan/02-definition-of-ready-done.md` §8. Do not test against anyone else's
instance, do not access data that is not yours, do not perform denial-of-service testing, and do not place
orders on accounts you do not own.

---

## 2. Supported versions

CandleViewer is pre-1.0 and deployed from `main`.

> **Read this before interpreting the table.** CandleViewer is a **private, single-owner, single-tenant**
> system. There is exactly **one** production deployment (the owner's `live` instance) plus one `staging`
> instance, both running the same tagged artefact, both reachable only over Tailscale (C-12.9). There are
> **no** customers, no download distribution, no fleet, and therefore **never two concurrent production
> versions in the wild**. Agents and contributors must not infer from this table that back-porting,
> parallel release branches, or multi-version support matrices exist — they do not, and adding them is
> scope creep (C-1.4).
>
> The table below is kept as a **formality** for two narrow reasons: (1) it tells an external researcher
> which commit a report will be judged against, and (2) it becomes meaningful only if the owner ever runs
> a staging version behind production during a staged rollback (C-15.10). In practice the answer to
> "which version is supported?" is always: **the current `main`, and whatever tag production is pinned
> to right now.**

| Version                                                     | Supported                                                                                     |
| ----------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `main` (latest commit)                                      | ✅ Security fixes                                                                             |
| Latest tagged release `v0.x` (what production is pinned to) | ✅ Security fixes                                                                             |
| Previous tagged release                                     | ⚠️ Critical fixes only, and only while a rollback to it is still the documented recovery path |
| Anything older                                              | ❌ Unsupported — roll forward                                                                 |

**Remediation is always roll-forward on a single line.** A security fix lands on `main`, is tagged, and
production is redeployed. There is no back-port branch, and creating one requires an owner decision.

After 1.0 this policy does not change while the deployment stays single-tenant: the latest tag is the only
supported version. The conventional "latest minor of current major + last minor of previous major" matrix
applies only if CandleViewer is ever distributed to third parties — which is explicitly out of scope
(Constitution §1.3, no multi-tenant/SaaS productisation). Security fixes are released as patch versions and
noted in `CHANGELOG.md` under _Security_.

---

## 3. Security model in one page

- **Exchange:** Bybit v5, USDT linear perpetuals only. Keys are scoped **trade + read**, with
  **withdrawal and transfer permission OFF** and an **IP allowlist** configured. The backend runs a
  **startup and hourly self-check** and refuses to enter trading mode if a key reports withdrawal/transfer
  permission or a missing allowlist (Constitution C-2.8).
- **No withdrawal code exists.** No code path may call a withdrawal, transfer or funding endpoint; a
  Semgrep rule fails CI if one appears.
- **Native stop-loss invariant.** Every position-opening order — including every leg of a multi-account
  fan-out — carries a native exchange-side stop-loss. No flag disables this (C-2.6).
- **Secrets isolation.** Credentials are envelope-encrypted at rest (per-key DEK; KEK from the OS
  keyring/KMS, never in the repo or an image layer) and exist in plaintext only inside
  `services/api/secrets/`, in memory, at signing time. No API, log, metric, trace, error, fixture or
  frontend bundle may contain a key (C-2.7).
- **Authentication:** app-level accounts with **mandatory TOTP 2FA**, independent of Bybit's. Sessions are
  token-based, short-lived, revocable, and cookies are `Secure`/`HttpOnly`/`SameSite=Strict`.
- **Authorisation:** RBAC — **Owner** (full admin), **Manager** (assigned accounts only; trade and view
  own positions; no key or user management; cannot see other managers), **Viewer** (read-only incl.
  audit). Enforced **server-side** at the API boundary and re-checked at the data layer; deny by default.
  Frontend gating is cosmetic (C-2.12).
- **Audit:** every order action, auth event, key-management event, kill-switch use, environment switch and
  rule-engine action is written to an **append-only** audit log (immutable, retained indefinitely) with
  actor, role, account, trade group, order ids and redacted payloads (C-2.9).
- **Risk controls:** per-account profiles (leverage, sizing, SL/TP offsets, max daily risk, allowed
  symbols) enforced server-side; max-daily-loss/drawdown auto-flatten and lockout; owner "FREEZE"
  kill-switch that revokes a manager's trading instantly.
- **Rate limiting:** per-UID token-bucket governor with a reserved headroom (default 30%) for
  risk-critical actions (stops, cancels, flatten); WS subscriptions chunked to ≤10 topics per request.
- **Network:** backend binds to `127.0.0.1`/WSL-internal only. Remote access is **Tailscale-only** with
  per-manager ACLs. No public ingress, port-forwarding, UPnP or third-party tunnel (C-12.9).
- **Application hardening:** strict CSP (no `unsafe-eval`/`unsafe-inline`), parameterised queries, CSRF
  protection on cookie-authed writes, Electron with `contextIsolation: true`, `nodeIntegration: false`,
  `sandbox: true` and navigation allowlists.
- **Environment isolation:** `demo` and `live` use separate credentials, hosts, state and UI chrome;
  switching to live requires explicit typed confirmation and can never be done by hotkey (C-2.11).

---

## 4. Secrets policy

**Rules (non-negotiable):**

1. **Never commit a secret.** No API keys, tokens, passwords, private keys, session cookies, TOTP seeds or
   recovery codes in code, tests, fixtures, comments, commit messages, branch names, issue/PR text,
   screenshots, or documentation. `.env*` files are gitignored; committed examples (`.env.example`) contain
   **placeholders only**.
2. **Secrets live in the secrets module.** Application code obtains signed requests from
   `services/api/secrets/` (`sign(request, account_id)`); there is no `get_secret()` API.
3. **Runtime configuration** comes from environment variables or mounted secret files, never from the
   image, never from the repository.
4. **Redaction is mandatory.** A central logging filter masks credentials, signatures, auth headers,
   session tokens, TOTP codes and key-management request bodies. A unit test asserts the filter against a
   corpus of secret-shaped payloads. Log level never changes redaction behaviour.
5. **Fixtures are redacted.** Recorded Bybit captures in `tests/fixtures/bybit/` must contain no real key,
   signature or UID, and are reviewed like code.
6. **Key rotation** is a first-class admin flow with audit records and must never require a code change.
   Rotate at least every 90 days, and immediately on any suspicion of exposure or on a manager's
   offboarding.
7. **Scanning:** Gitleaks runs over full history and TruffleHog over each diff in the `secrets-scan` CI
   job. Any finding fails the build. Local hooks run `gitleaks protect --staged`.
8. **AI agents may not handle real credentials at all** — see `AGENTS.md` §8.6.

### If a secret is exposed

1. **Revoke it at Bybit immediately** (delete the API key), before anything else.
2. Notify `@basiltt` at once; open a private advisory, not a public issue.
3. Rotate the KEK and re-encrypt remaining keys; invalidate all application sessions.
4. Audit every order and account action in the exposure window using the audit log.
5. Purge the secret from the repository if committed (history rewrite by the owner only) and treat the
   secret as permanently burned regardless.
6. Run the incident process (Constitution C-12.12) and publish a post-mortem in `docs/incidents/`.

---

## 5. Dependency and supply-chain policy

- Licences must be on the allowlist (MIT, Apache-2.0, BSD-2/3, ISC, MPL-2.0, Python-2.0, Unlicense, CC0);
  GPL/AGPL/SSPL/BUSL/commercial-without-licence are denied; unknown licence fails CI.
- Lockfiles are committed; CI installs frozen. Container base images are pinned by digest and rebuilt
  weekly.
- CI gates: CodeQL + Semgrep + Bandit (`sast`), `pip-audit` + `npm audit` + the Dependabot alert
  gate (`sca`), Gitleaks/TruffleHog (`secrets-scan`), Trivy (`container-scan`), licence check. Zero
  high/critical findings may merge.
- Dependency updates are triaged weekly; remediation SLAs match §1's fix targets.
- New dependencies require justification, an allowlisted licence, a maintained upstream, and CODEOWNER
  approval; `packages/chart-engine` additionally requires an ADR.

---

## 6. Security review and testing

- The `security-review` label is applied automatically when a PR touches a security path that
  Constitution C-10.2 lists (the `security-review-label` job of `pr.yml`). Such PRs require approval
  from `@CandleViewer/security`.
- Every epic carries a **STRIDE threat model** before its first implementation ticket leaves Ready.
- Nightly DAST (OWASP ZAP baseline) and a chaos suite covering disconnects, exchange 5xx, rate-limit
  saturation, clock drift, partial fills, SL-attachment failure and process kill.
- **An external penetration test is a hard gate before live trading is enabled (release R4).** All
  high/critical findings must be fixed and re-tested, with owner sign-off (Constitution C-15.9).

---

## 7. Incident response summary

Detect → declare severity (**S1** capital at risk / unprotected position / key compromise / unauthorised
access; **S2** trading degraded; **S3** other) → contain (kill-switch, revoke keys, read-only mode,
disconnect adapters) → eradicate and recover (fix forward or roll back, rotate credentials, reconcile OMS
state against the exchange) → communicate (owner notified immediately for S1/S2) → blameless post-mortem
within 5 working days in `docs/incidents/` with owned, dated action tickets → verify closure at the next
Production Readiness Review.

---

_Questions about this policy: contact `@basiltt`. Last reviewed 2026-09-14._
