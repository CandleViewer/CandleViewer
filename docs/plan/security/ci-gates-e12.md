# CI security gates for the bar and market-data surface (E12-X03)

> Owner: `@CandleViewer/security`. Ticket: E12-X03 (#453). Threat model:
> `docs/security/threat-models/E12-bars.md` (BR-25, BR-26, AC-12, SR-E12-02/13/16).
> Programme rules: `docs/plan/04-security-program.md` §12.1-§12.2 (scanners, Semgrep composition,
> CI-SEC-006 suppressions) and §16.2 (exception process). This page explains each gate; the rule
> YAML is the source of truth for what is matched.

## How these gates run

- **Semgrep (PR, required `sast` check):** `.github/workflows/_job-security.yml` passes every
  `.semgrep/cv-*.yml` to `semgrep scan`, so the seven rules below are picked up with no workflow
  change; `tools/ci/check_semgrep_rule_tests.py` proves each rule on its `# ruleid:` / `# ok:`
  fixture in `.semgrep/tests/<rule>.py` in the same job. No new required-check name (C-9.1).
- **Rule tests:** `scripts/tests/test_e12_security_gates.py` re-proves each E12 rule on its fixture
  and asserts **zero findings on `services/api/candleviewer`** (skips when `semgrep` is absent).
- **Bandit / CodeQL (PR, `sast`):** Bandit scans all of `services/api/candleviewer` (bars/,
  ingestion/, api/market* included) with `-c services/api/pyproject.toml -ll`; CodeQL's
  `.github/codeql/codeql-config.yml` covers the same tree. Both were already in scope, so this
  ticket changes neither config (see "Bandit and CodeQL").
- **DAST (nightly only):** `.github/workflows/dast-market-nightly.yml` (see "DAST").
- Every rule is path-scoped to the market-data modules (`bars/`, `ingestion/`, `storage/`,
  `api/market*`) or the adapter boundary. That keeps it strict where it matters and quiet elsewhere.

## Precision at merge (AC "rules do not drown the build")

Measured on `main` at the merge base with semgrep 1.178.0. Every rule-file in `.semgrep/` run over
`services/api`: **0 findings**. One pre-existing site was conformed instead of suppressed
(`bars/reader.py:85`, `# nosec` gained `reason=`/`owner=`; comment-only change). Three
**true positives** are excluded by enclosing function, with a `TODO(E12-X03 follow-up)` in
the rule. They are listed under "Known findings" and are not counted as false positives (all three are now fixed).

| Rule | Fixture fire / clean lines | Findings on main | False positives | Precision |
|---|---|---|---|---|
| cv-bybit-category-required | 5 / 5 | 0 | 0 | 100 % |
| cv-no-float-prices | 4 / 4 | 0 (2 TP fixed: #2140, #2141) | 0 | 100 % |
| cv-no-raw-sql-interpolation | 4 / 4 | 0 | 0 | 100 % |
| cv-unbounded-query-window | 2 / 2 | 0 | 0 | 100 % |
| cv-no-debug-probe-in-prod | 25 / 10 | 0 | 0 | 100 % |
| cv-untrusted-exchange-response | 3 / 2 | 0 (1 TP fixed: #2142) | 0 | 100 % |
| cv-nosec-needs-reason-owner | 3 / 2 | 0 (1 conformed) | 0 | 100 % |

**Retro-detection (test plan):** run on the history of `M8`. `cv-no-float-prices` would have
flagged the two float sites below when they landed, and `cv-untrusted-exchange-response` would
have flagged `ingestion/clock.py` (E08). No past category omission, raw-SQL or probe issue exists
in `bars/`/`ingestion/` history; this is recorded explicitly as the ticket asks.

### Known findings (true positives — all fixed 2026-10-10, exclusions removed)

The three sites below were true positives on `main` when the rules landed (#2136). Each was
exempted by its enclosing function only, fixed in its own PR, and the exemption deleted once the
fix merged (#2140 → #2137, #2141 → #2138, #2142 → #2139). The rules now cover the whole files.

| Rule | Site | Why it is real |
|---|---|---|
| cv-no-float-prices | `storage/questdb/repository.py` `write_trades`: `float(price) * float(qty)` | notional computed in binary float before storage |
| cv-no-float-prices | `bars/reader.py` `stored_bar`: `repr(vwap * volume)` | turnover served from a float product |
| cv-untrusted-exchange-response | `ingestion/clock.py` `rest_client_fetcher` | reads raw `/v5/market/time` envelope outside the adapter |

## cv-bybit-category-required

- **What:** a Bybit v5 REST call (`get_public` / `signed_request`) whose literal `params=`/`body=`
  dict, or a dict assigned earlier and passed as `params=`/`body=`, lacks `"category": "linear"`.
  It also flags a call to a categorised `/v5/...` path with no params at all.
- **Why:** **SR-054** (`ci-gate`). Several v5 endpoints silently default the category, so a
  default change or a copy-pasted call could route traffic to an unintended product.
- **Fix:** write `"category": "linear"` literally in the dict at the call site. Do not rely on a
  helper that adds it later: the rule (and the reviewer) must be able to see it.

## cv-no-float-prices

- **What:** `float()` of a price/qty/size/turnover/notional/VWAP/volume/OHLC field, arithmetic
  with a `float(...)` operand, or arithmetic on a name bound from `float()`. Scope: `bars/**`,
  `ingestion/**`, `storage/**`. A bare `float(x)` as a value in a QuestDB row dict, and
  `bars.rows.to_double`, are the documented Decimal -> DOUBLE storage boundary and are allowed.
- **Why:** **SR-E12-13** (exact reproduction of closed bars) and the decimal contract in
  `docs/plan/23-ws-protocol.md` §3.1; R7 data accuracy.
- **Fix:** compute in `Decimal`; convert once at the store boundary with `to_double`; read back
  with `Decimal(repr(x))`.
- **Overlap:** `cv-decimal-discipline` flags `float` *annotations* on price/qty names. This rule
  flags *expressions*. A single line can never match both, so they do not double-fire.

## cv-no-raw-sql-interpolation

- **What:** query text (`SELECT/INSERT/UPDATE/DELETE/WITH ...`) built by f-string, `%`,
  `.format()` or `+` in `bars/**`, `ingestion/**`, `api/market*.py`, `bars_wiring.py`.
- **Why:** **SR-040** / E12 **BR-25**. `symbol`, `param` and window bounds are request-derived.
- **Fix:** use constant text with bound parameters (`$1..$n`, or `:name` with `text()`). An
  identifier must come from a closed allow-list checked in the same function
  (`if kind not in _FAMILIES: raise ...`) or from `storage.sql_identifiers.checked_identifier`.
  The rule recognises both forms.
- **Overlap:** `cv-raw-sql-string-interpolation` owns `execute(f"...")`/`text(f"...")`, and
  `cv-storage-sql-construction` owns `storage/**`. This rule excludes text inside `execute(...)`
  and `text(...)`, so the three never fire on the same line.

## cv-unbounded-query-window

- **What:** in `api/market.py` / `api/market_*.py`, a `read_bars(...)`, `read_klines(...)` or
  `read(..., limit=...)` store read with no earlier `if` against `MAX_TIME_WINDOW_US` /
  `MAX_NON_TIME_WINDOW_US` from `candleviewer.bars.limits` (directly or via a chosen-cap variable).
- **Why:** **SR-E12-02**. Without the cap, one request can scan a year of `bars_*`.
- **Fix:** compare the span with the `bars.limits` constant and return `422 bar_window_too_large`
  before the read, as both routes do today. A locally restated number does not satisfy the rule.

## cv-no-debug-probe-in-prod

- **What:** in `candleviewer/**` (not tests/conftest), any of: a route whose path segment is
  `debug`, `probe`, `perf`, `diag(nostics)`, `__test*`, `test-clock` or `e2e` (a leading `_` is
  allowed, and the segment must be whole, so `/auth/performance` is an ordinary route);
  `freezegun` / `time_machine` / `tests.*` imports; `breakpoint()` or `pdb`. Allowed only inside
  `if settings.environment is not Environment.LIVE:` (or `!=`) with no `else:` branch, or inside
  the keyless-testnet perf gate (below).
- **Why:** **SR-E12-16** / BR-26 / AC-12.
- **No `else:` (#2755):** Semgrep matches an if/else as one block, so a guard written with an
  `else:` would also exempt the `else:` branch, which runs when the guard is false (LIVE, or the
  perf switch off). Every guard therefore takes an `if` with no `else:`; an `if`/`else` around a
  seam is flagged in both branches.
- **Perf gate (#2755):** perf-only routes such as `GET /auth/_perf/argon2-params` (#2097) exist
  only on a keyless testnet (`CV_ENVIRONMENT=testnet`, no exchange key). The rule accepts a
  registration inside an `if` on a call that Semgrep resolves to
  `candleviewer.api.auth_perf.auth_perf_enabled`: `if auth_perf_enabled(settings):`, or a local
  assigned once from that call in the same function (`auth_perf = auth_perf_enabled(...)`, then
  `if auth_perf:`, as `create_app` writes it). It checks where the call comes from, not what a
  name is. These stay flagged: a function of the same name that the file defines or imports from
  another module; a relative import, which Semgrep does not resolve (import the gate by its
  absolute path); `auth_perf = True`; a local holding the raw `settings.auth_perf_enabled` field,
  which skips the build-time re-check that `auth_perf_enabled()` repeats; a reassigned local;
  `if not auth_perf:`; and any `if`/`else`. The import of the gate in the fixture is therefore
  load-bearing. The gate is stricter than the environment guard, so it also exempts the other
  seams inside it.
- **Limit:** the rule reads the path literal at the registration (`@router.<verb>(...)` and
  `add_api_route(...)`). `include_router(..., prefix=...)`, `mount(...)` and a path held in a
  constant are not read. The #2097 route is declared that way (`ARGON2_PARAMS_PATH` in
  `api/auth_perf.py`, mounted by `create_app` only inside `if auth_perf:`), so it is not flagged.
  Its RBAC is enforced by the deny-by-default build gate (RBAC-CON-003) and its switch-only mount
  by the `create_app` test `test_create_app_mounts_the_params_route_only_with_the_switch_on`, not
  by Semgrep. Semgrep also cannot follow a router factory to its gated mount: the same route with
  a literal path in that factory is flagged. Register it inside the gate, or suppress it as under
  "Requesting an exception" once those two controls cover the mount.
- **Limit (perf gate):** the local is followed by Semgrep's `symbolic_propagation`, which ends at
  a reassignment and at a `for`/`while` loop between the assignment and the `if`. Such a site is
  flagged (fail closed): call `auth_perf_enabled(...)` in the `if` itself. Name resolution is
  Semgrep's and follows file order: a same-named `def` nested in the calling function, or placed
  after the real import, does not replace the import and is not seen. The rule catches an
  accidental ungated route; it is not a defence against a deliberate shadow of the gate.
- **Note:** at merge no such seam exists in the backend. The E12-Q03 probe and the SCR-046
  feed have not landed, and health checks use `register_*_probe` functions, not routes. The rule
  therefore implements the documented pattern. The web-bundle half of AC-12 (SCR-046 in a
  production JS build) belongs to the frontend build check, not this Python rule.
- **Fix:** move the seam under `tests/`, or register it inside the environment guard (a perf
  route: inside the perf gate) as an `if` with no `else:`.

## cv-untrusted-exchange-response

- **What:** outside `exchange/bybit/**` and `exchange/base/**`, a subscript or `.get()` of a raw
  v5 envelope key (`result`, `retCode`, `retMsg`, `retExtInfo`, `nextPageCursor`, `timeNano`,
  `timeSecond`), or `.json()` on a response-named object.
- **Why:** **SR-040** / SR-040b. The scope is the same boundary as `cv-adapter-isolation` and
  `cv-bybit-vocabulary-leak`.
- **Fix:** parse in the adapter into a domain model, and consume that model.

## cv-nosec-needs-reason-owner

- **What:** a `# nosec` in `bars/**`, `ingestion/**`, `api/market*.py`, `bars_wiring.py` without
  a Bandit id **and** `reason=<token>` **and** `owner=@<handle>[/<team>]`. Example:
  `# nosec B608 reason=table-from-closed-allowlist owner=@CandleViewer/backend`.
- **Why:** §12.1 ("`# nosec` requires an inline justification") and **SR-156**. Bandit itself
  accepts a bare `# nosec`, so this gate is the enforcement point. Semgrep `# nosemgrep` already
  needs `reason/owner/review` under CI-SEC-006 (`tools/ci/suppressions.py`).

## Bandit and CodeQL

- Bandit already scans every M7/M8 package (`bandit -c services/api/pyproject.toml -r
  services/api/candleviewer -ll`, `[tool.bandit] exclude_dirs = ["tests"]`). B608 (SQL
  construction) is the relevant test here, and it is on by default. Nothing is skipped for these
  packages, and this ticket adds no skip.
- CodeQL (`.github/codeql/codeql-config.yml`, `python` + `javascript-typescript`) runs the
  action's default query suite and already covers `services/api/**`. The config has only
  `paths-ignore` for docs/research and Semgrep fixtures, so there is nothing to widen. Adding the
  `security-extended` pack is repo-wide (every language and package), so it is out of this
  ticket's market-data scope and left to DevSecOps (E43), as is moving the full analysis to
  nightly.
- **Suppression policy:** every `# nosec` names the Bandit test id plus `reason=` and `owner=`
  (enforced in E12 paths by `cv-nosec-needs-reason-owner`). Every `# nosemgrep` follows
  CI-SEC-006 (`reason`, `owner`, `review` ≤ 180 days). `# noqa: S…` stays paired with its
  `# nosec` on the same line.

## DAST

- **Workflow:** `.github/workflows/dast-market-nightly.yml`, triggered by `schedule` (03:47 UTC)
  and `workflow_dispatch` only, **never on PR**. It runs against the compose stack that
  `dast-rules-nightly` / `dast-storage-nightly` use. "Staging" in the ticket is E17's target; when
  that exists, change `urls`/`targetUrl` in the plan.
- **Plan:** `.zap/market-data.yaml`. OpenAPI import of `22-api-openapi.yaml`, scoped to
  `/market/klines` and `/market/bars`; active scan with SQLi/command-injection/XSS rules at Low
  threshold. Authentication uses the low-privilege bearer `ZAP_LOWPRIV_TOKEN` (CI secret, seeded
  read-only demo user, never committed). Rotate it with the other ZAP fixture credentials each
  release cycle and whenever a maintainer with secret access leaves.
- **Tuning for expected 4xx:** `alertFilter` marks two alerts as false positives on these two
  paths only: 90022 when the evidence is our problem+json codes (`validation_failed`,
  `bar_window_too_large`, `no_data_recorded`, `response_too_large`), and 10049 (non-cacheable
  4xx). Injection and disclosure rules are never filtered.
- **Baseline:** `.zap/market-data-baseline.json` (empty at merge). `security/zap/baseline_gate.py`
  fails the job on any High/Medium alert whose `pluginId METHOD path` key is not in the baseline.
  It also fails on a baseline entry without `reason`/`owner`/`review`, or one past its review date.
- **Triage SLA:** the SR-134 clock applies: triage within 48 h (the market-data read path feeds
  charts, not orders, but a High is treated as order-path severity), and within 7 days for a
  Medium. The resolution is either a fix, or a baseline entry plus a §16.2 exception (for High).

## SCA and secrets

- **E12 dependencies:** `git log -- services/api/pyproject.toml` shows E12 added only
  coverage-floor entries (E12-T01 #1906). No decimal, compression or Parquet library was added:
  `decimal` is stdlib, and `pyarrow`/`duckdb` predate E12 (E07-T04 #1630). pip-audit
  (`_job-security.yml`, `uv.lock`) and gitleaks (whole repo, including `packages/fixtures/**` and
  bench artefacts) already gate them, so no change is needed.
- **Fixture-data licence check:** a manifest exists (`packages/fixtures/bybit/<date>/manifest.json`)
  with `source`/`host`/`capture_date` fields but no licence field. Bybit API responses are
  recorded data, not a licensed package, so `license-scan` does not apply. **Gap:** a
  per-fixture-provenance licence attestation needs a manifest schema change owned by the fixture
  bank (E08-T05 lineage), so this ticket does not add it.

## Requesting an exception

1. Fix the code if you can. Every rule above names its fix.
2. If you cannot, add an inline `# nosemgrep: <rule-id> reason=<token> owner=@<handle>
   review=YYYY-MM-DD` (≤ 180 days, CI-SEC-006), or a justified `# nosec` (above). Tag
   `security-review`.
3. For a High finding, or a suppression that outlives one release, also add a row to
   `04-security-program.md` §16.2 (Owner + Security approval, expiry, tracking ticket) and, for
   scanner findings, `security/accepted-risks.yaml`.
