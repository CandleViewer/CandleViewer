# ADR-0043 — Feature flags may not gate a security control: the registry's refusal and its fences (C-4.14, #1085)

- Status: **accepted** in the #1085 BQ ruling of 2026-11-03 (comment 6602836897; its BQ-1 gave this record its
  number), by main-orchestrator under the Owner's delegation (#2701 comment 6284192190). It decides nothing new: C-4.14
  is the rule, and the mechanism is on `main` (E42-T03, E42-X03). This record names it, its fences and its limits, so
  the next "just one auth flag" meets a written answer.
- Date: 2026-11-03
- Deciders: Owner (`@basiltt`) through main-orchestrator (the delegation on #2701); the Security engineer through the
  `security-review` label (C-10.2); the architect as CODEOWNER of `docs/plan/`. Author: virtarix-worker-4.
- Consulted: `docs/security/threat-models/e42-admin.md` (§3.2, §4.6 AD-E03, §11 SR-E42-07, §13.1 AD-F09); US-ADMIN-007;
  `21-database-schema.md` 10.7 (the flag list); ADR-0036, ADR-0037 and ADR-0038 (flags and switches that gate no check).
- Numbering note: the ticket names ADR-0023 for this record, which is the exchange adapter, and lets the Architect fold
  it into the admin re-auth record. It stays apart because the two have different citers (SR-E42-12 and AD-E01 against
  SR-E42-07, AD-E03 and AD-F09). If the Architect prefers one record, it folds into ADR-0042 as decision 7.
- Related: C-4.13, C-4.14; #964 (E42-T03), #2928 (the registry), #3221 and #3376 (its composition into the app), #3893
  (the Semgrep rule), #3943 (the boot refusal's test), #1026 (E42-X03); SR-E42-07; AD-E03, AD-F09; ADR-0042.
- Evidence: every `file:line` holds on `main` at `d023df0f6`. Module paths are under `services/api/candleviewer/`.

## Context and problem statement

US-ADMIN-007 and C-4.14 say there is no flag that disables the native stop-loss, RBAC, audit or the withdrawal
self-check. A flag is the cheapest way to change behaviour, and sooner or later a change will want one that touches
authentication, a permission check or a risk limit "just for now". Review alone does not hold that line across many
authors and agents. The ticket asks for a "compile-time registry"; in Python that means import time and construction
time.

## Decision drivers

1. A flag change is an Owner action that needs no deploy; a control it can switch off is a control an attacker with a
   stolen Owner session can switch off (AD-S05).
2. The line must hold without anyone remembering it: by construction first, by a gate second, by review last.
3. A flag store that cannot be read must leave the system safe, not open (AD-D02).
4. Every fence has a test that fails when the fence is removed.

## Considered options

- **(a)** A registry that refuses a security gate at import and at construction, composed into the app, plus a Semgrep
  rule against flag lookups in the safety modules.
- **(b)** Review and a written rule only.
- **(c)** A runtime allowlist the Owner edits.

## Decision outcome

Option (a), in five parts.

1. **The registry refuses a security gate.** `Category` names what a flag may gate; eight members are `DENIED`:
   authentication, RBAC, audit, the native stop-loss, risk limits, the withdrawal check, the rate-limit reserve and
   demo/live isolation (`admin/flags/registry.py:41-68`). `FlagSpec` refuses a definition that declares one when it is
   built, so its module fails at import (`:105`, `:130-137`), and `FlagRegistry` checks every spec again when it is
   constructed (`:171-179`). The error names the flag, the category and C-4.14. `test_the_denied_category_truth_table`
   walks all 8,192 category sets (`test_flag_registry.py:56`), and `test_registry_rechecks_every_spec_at_startup`
   forces a spec past its own constructor and still expects the refusal (`:78`).
2. **The app composes the registry, so a refused definition stops boot.** `FeatureFlagsRuntime` builds it with no I/O
   (`FeatureFlagsRuntime.__init__` in `flags_wiring.py`), and `create_app` composes that runtime (`build_feature_flags`
   in `app.py`; first #3221, then #3376).
   `test_create_app_refuses_a_denied_flag` smuggles a definition for each of the eight categories into the catalogue and
   expects `create_app()` to raise; its control case boots with an allowed one (`test_flag_create_app_refusal.py`,
   #3943).
3. **No flag lookup in a safety module.** The Semgrep rule `cv-admin-no-flag-lookup` (`.semgrep/`, #3893; severity
   ERROR) refuses the flag API, a flag-named call or object, and every catalogue key as a string literal in the paths
   its `paths.include` lists: `auth/`, `audit/`, `oms/`, `risk/`, `secrets/` and `exchange/` under
   `services/api/candleviewer/`, plus `ws/permissions.py`, `rules/manager.py`, `admin/http.py` and
   `api/deny_by_default.py`. It carries fixtures for those paths, and `test_flag_lookup_rule.py` holds its key list
   equal to the catalogue, so a flag added there fails until the rule names it.
4. **Safety flags ignore overrides and fail closed.** The live gate and the kill-switch-class flags take no per-user or
   per-role override (`FlagSpec.overridable`, `registry.py:118-123`; `test_safety_flags_ignore_every_override_and_fail_closed`,
   `test_flag_resolver.py:108`). When the store cannot be read, a flag resolves to its `restrictive` value: the order
   kill switch and maintenance mode engaged and `trading.live_enabled` off (`registry.py:4-14`; `resolver.py:75-76`).
   The ingestion kill switch has no restrictive value, so it resolves to its default: a store outage does not engage
   it. The halt that does engage stays safe (AD-D02, accepted Low): cancels, flatten and native stops are never refused
   (C-2.6).
5. **Process settings follow the same line.** A setting that bounds a safety control has no off value:
   `20-architecture.md` §7.2's configuration rows for the replay loop share, the OMS price band and the sign-in failure
   floor say "no off value (C-4.14)". ADR-0036 (a process switch), ADR-0037 decision 12 and ADR-0038 decision 2e each
   say that their switch gates no check.

## Limits

Categories are self-declared (AD-F09). The registry cannot see what a call site does with a flag, and a spec can claim
`UI_SURFACE` for a flag that reaches further (`trading.one_click` is declared so, `admin/flags/catalogue.py:61`);
nothing checks the declaration against what the flag's readers do. The Semgrep rule is the second fence for that, and
review is the third. The rule is a pattern: it reads names and imports, so a safety module that receives a flag's value
through an argument is outside it, and a lookup moved into a module the rule does not cover is a review matter. One
flag reaches an auth-adjacent edge that way today: the CSRF guard, outside the rule's paths, receives
`desktop.backend_connection` as an injected callable (`create_app` in `app.py`, wired as `feature_flags.backend_connection`; used by `expose_csrf_token` in `api/csrf.py`
and the CORS gate `cors_on`), and the flag adds the CORS headers and the `X-CSRF-Token` response header, never a
check (ADR-0038 2e). Its third effect, the desktop cookie attributes (ADR-0038 4b, slice S4), is unbuilt at `main`:
`api/sessions.py` sets `SameSite=Strict` only. That is why
each fence above names the paths it covers.

## Consequences

- A new auth, RBAC, audit, stop-loss, risk, withdrawal, rate-reserve or isolation flag cannot be defined: the build
  fails at import and the app does not boot.
- Adding a flag is a code change in the catalogue, reviewed against the allowlist, and extends the Semgrep key list in
  the same change (`test_flag_lookup_rule.py`).
- **What to do instead** when someone wants a flag on a security control: change the code. The invariant is not
  optional, and a rollout that needs a switch belongs on the feature around the control, never on the control.

## Why not the alternatives

**(b) Review only.** It fails silently: a flag added in a large change reads as routine, and the stolen-session case
(AD-S05) is exactly the one where an Owner-reachable switch matters.

**(c) A runtime allowlist.** The Owner would edit the set that bounds the Owner's own session. Definitions are code, so
a change to what a flag may gate is a reviewed change.

## Validation

- `tests/unit/admin/test_flag_registry.py` (the truth table; the startup recheck), `test_flag_create_app_refusal.py`,
  `test_flag_resolver.py` (overrides, fail-closed values), `test_flag_catalogue.py` and `test_flag_lookup_rule.py`.
- The Semgrep rule and its fixtures under `.semgrep/tests/cv-admin-no-flag-lookup/`, run by the `semgrep-bandit` job.

## References

- CONSTITUTION C-4.13, C-4.14, C-2.6. `docs/plan/04-security-program.md` §7.2.2 (the capability rows).
- `docs/security/threat-models/e42-admin.md` §3.2, AD-E03, AD-F09, SR-E42-07, AC-ADM-13 and AC-ADM-14.
- ADR-0036, ADR-0037, ADR-0038, ADR-0042.
