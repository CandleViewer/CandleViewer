# ADR-0036 — Dev-only account-fixture transport (`CV_ACCOUNT_FIXTURE`) and its fence

- Status: **proposed**. main-orchestrator accepted all ten decisions on 2026-10-16, interim under the owner's
  delegation (#2893, issuecomment-6225372045); the owner ratifies (C-3.4) before S7, the per-request guard,
  merges, which is this record's decision deadline (`docs/plan/27-adrs/README.md:5`). The slices before S7
  (S2, S3, S5, S6 and S8) land under the interim rulings.
- Date: 2026-10-16
- Deciders: Owner (`@basiltt`) through main-orchestrator. Consulted: hcl-worker-1 (owner of #836) on
  decision 3; the Security engineer through the `security-review` label on #2893.
- Numbering note: 0031 is reserved by E45-K01 (`ADR-0031-resilience-and-chaos`, not on `main`), and 0035 is the
  last on `main`, so this record takes the next free number.
- Related: #2893 (this record and the STRIDE note are its slice S1), #833 (E27-Q01), #2962 (the pack), #836
  (E27-T03), #1006 (E38-T01), #2877 (E29-X01), #837, #896, #899, #848, #2086, #2240, #3005, #3007; E45-K01;
  ADR-0009, ADR-0023.
- Evidence: the read-only design pass in #2893's claim comment (issuecomment-6224549087); every `file:line` holds
  on `main` at `09216133` (first checked at `945fb43d`). Module paths (`settings.py`, `exchange/...`)
  are under `services/api/candleviewer/`; `README.md` is the pack README (`packages/fixtures/accounts/`);
  `deploy-staging.yml` and `_job-*.yml` are under `.github/workflows/`, `24-internal-schemas.md` under
  `docs/plan/`, `e27-accounts-test-plan.md` under `qa/plans/` and `test_image_boot_path.py` under
  `services/api/tests/unit/architecture/`. The rest are repository paths.

## Context and problem statement

#833 shipped the E27 fault-injection pack as data (`packages/fixtures/accounts/` and the test-side resolver
`services/api/tests/_account_fixtures.py`). Nothing answers a signed REST call or a private WS on a running
stack, so manual QA, the E27-Q02 specs and the plan's §11 dry run cannot reach the hostile key states. On
`main`:

- **No per-account client.** The only `BybitRestClient` built is the public one
  (`exchange/bybit/service.py:98-103`; `services/api/tests/chaos/ingestion/_rig.py:18-20`), and
  `subscribe_private` is declared only (`exchange/base/ports.py:176`). The seam exists: the client takes
  `transport` and `wall_clock` (`exchange/bybit/rest.py:184`, `:187`) and hands the transport to httpx once
  (`:208-215`).
- **No dev/test environment.** `Environment` is `live | demo | testnet`, "never inferred, always explicit"
  (`settings.py:71-80`); `Settings` never reads `CV_ENV`, as its fields take the `CV_` prefix
  (`settings.py:165`), the environment field is `environment` (`:177`) and no field is named `env`; staging
  is demo (`qa/plans/e09-auth-rbac-test-plan.md:150-151`).
- **Key ids are encrypted.** Only `key_id_last4` is plaintext
  (`migrations/versions/0017_exchange_accounts_api_keys.py:116-117`); the clear id exists only inside M2
  (`secrets/broker.py:199-200`) and per signature (`exchange/bybit/signer.py:60-62`).
- **#2086's clock is not E27's.** It moves auth time and runs only on a keyless testnet
  (`auth/testnet_clock.py:1-9`; `settings.py:141-153`). It refuses on the environment and on env-held keys,
  never on a stored key, though plan §9.5 says "while an exchange key is stored"
  (`qa/plans/e27-accounts-test-plan.md:606`).
- **The image fence is structural only.** The image copies `candleviewer/` and the synthetic sample alone
  (`infra/images/Dockerfile.api:22`, `:55`, `:59-60`); the wheel packages `candleviewer` alone
  (`services/api/pyproject.toml:66-67`). Nothing asserts a dev-only module is absent, and staging runs that
  image (`.github/workflows/main.yml:172-174`; `deploy-staging.yml:104-105`).

The danger is one mis-set variable: if the stub answered for a real key, the key-info reply would show an
empty `Wallet` group and the C-2.8 check would pass without exchange contact, a switch gating a safety
invariant (C-4.14).

## Decision (proposed)

1. **Placement (C-3.4).** All fixture code lives in a new top-level dev-only package,
   `services/api/cvdev/account_fixture/`, outside the wheel and every `Dockerfile.api` stage, importable in a
   checkout and in pytest. The composition root reaches it through one module,
   `candleviewer/account_fixture_wiring.py`, which imports `cvdev` lazily, only when `CV_ACCOUNT_FIXTURE` is
   set, and refuses boot ("this build carries no fixture transport") when the package is absent. `Settings`
   declares the variable, since pydantic-settings ignores an undeclared process variable (an undeclared `.env`
   entry is refused: `extra="forbid"`, `settings.py:164-175`), so a release image refuses a mis-set variable.
   `cvdev` never ships, so it is not an M-module: it gets no CONSTITUTION §3 row and no
   `docs/plan/module-contracts.toml` entry. The rule is two bans, not an allow-list: it never imports
   `secrets` (C-3.2), nor `audit`, which is protected too (C-3.3, `services/api/.importlinter:653-661`); its
   boot record goes through an injected sink, as `auth/testnet_clock.py:104-117` does. The import-linter root
   (Enforcement) holds both bans, for direct imports only (import-linter's `protected` contract). The slices
   use `settings`, `auth.testnet_clock` (decision 5), `net.read_only_gate`, `storage`, `observability`, the
   adapter (`exchange/bybit`: service, rest, key_info, mapping, models, config) and `accounts.verification`.
   S13's load check, if it stays in `cvdev`, gets its M2 the way the composition root does, from
   `admin/wiring.py:84` with a `cvdev`-owned store: the one sanctioned indirect route to an M2, offline and
   CLI-only. Otherwise it moves to the test tree.
2. **dev/test is structural:** `cvdev` importable, `CV_ENVIRONMENT=demo`, `CV_FEED=synthetic` and no
   `CV_BYBIT_API_*`. The wiring module refuses the first (decision 1); `Settings` refuses the rest at load, in a
   field validator modelled on #2086's (`settings.py:486-520`), so a refusal never echoes `CV_BYBIT_API_KEY`
   (#2728). Any `CV_BYBIT_API_*` refuses boot rather than being ignored (ruling 2), and live and testnet are
   both refused (C-2.11).
3. **One account-client factory**, agreed with the owner of #836 (hcl-worker-1) and recorded in ruling 3
   (#2893, issuecomment-6225372045). #836 lands its narrow seam first, in its slice "2a3" as the rulings'
   scope guidance names it (`SIGNED_REST_BASES`,
   `ExchangeBybitService.key_verification_calls`, `key_verify.py`; not on `main` yet, consumed by
   `accounts/selfcheck.py:134-137`). S4 then generalises it to
   `account_rest_client(env, credential_id, *, uid, purpose, endpoint_class)` over the same M2 signing path
   (`exchange/bybit/service.py:47-52`), taking the injected transport and the fixture `wall_clock` in fixture
   mode; `key_verification_calls` becomes a thin consumer in the same PR. #1006 (E38-T01, environment
   capability matrix and demo host routing in the adapter) touches the same per-environment hosts, and #2877
   (E29-X01) and #848 consume the connector seam below, so S4 lands only once the owners of #1006 and #2877
   also agree that this is the one account-client factory (#836's owner did, ruling 3), as the claim comment
   planned (C-4.15). Production passes no transport, so `_request` (`exchange/bybit/rest.py:325-503`) gains
   no branch. The private socket stays with #2877 and #848; S4 adds only an injectable connector seam, on the
   pattern of `public_socket_factory` (`exchange/bybit/service.py:91-96`).
4. **Key-id guard, with no new M2 capability.** An exact boot check would need M2 to decrypt and compare key
   ids, in every release image. Instead the boot guard (S8) reads `(env, key_id_last4)` of unrevoked rows only
   (`revoked_at IS NULL`; `migrations/versions/0017_exchange_accounts_api_keys.py:141`) and refuses any such
   key outside demo and any demo key whose tail is not a pack tail (tails are unique, `README.md:32`); it
   cannot reuse the caller-pinned ports (`storage/repositories/accounts.py:175-189`, `:279-295`). Per request
   (S7), `X-BAPI-API-KEY` (`exchange/bybit/rest.py:357`) must equal a pack key id exactly; otherwise the call is
   never answered and both the transport and the process read-only gate latch with
   `reason_code=account_fixture_guard` (`net/read_only_gate.py:87`; an existing latch is kept, as
   `accounts/selfcheck.py:154-158` does). **This relaxes #2893's scope item 2 and acceptance 5:** "never
   answers" holds exactly, but "refuses to start" holds except for a real demo key whose tail equals a pack
   tail (Consequences), which S7 refuses on its first call. Ruling 4 accepted the guard; the owner accepts that
   residual when ratifying, and S14 aligns the pack README's guard text (`README.md:388-391`).
5. **A separate fixture clock.** S10 reuses `OffsetFileClock` (`auth/testnet_clock.py:53-80`) on
   `<CV_ACCOUNT_FIXTURE_DIR>/clock` for the stub's scenario and exchange time and the account clients'
   `wall_clock`, so signatures and the stub's server time agree after an advance. It never moves auth time:
   #2086 is unchanged, and plan §9.5's SCR-149 note (`e27-accounts-test-plan.md:626-627`) no longer applies.
6. **Per-key selection.** A signed call answers as the scenario its key id names, unless the switch file
   overrides it (S10). `CV_ACCOUNT_FIXTURE` is the stack default for traffic with no key (a private-WS connect
   before auth, unsigned demo-host calls), so TC-115 (`e27-accounts-test-plan.md:229`, scenario row `:568`)
   runs with `CV_ACCOUNT_FIXTURE=demo_ws_unreachable`, and `rotation_ok`'s two keys (`README.md:149`) share
   one stack.
7. **Scope 9 is split.** The `orderLinkId` echo, the mode-switch stubs and the three overlays are served
   statelessly (S9) and seeded per key through the switch CLI (S10), the documented E27-Q02 path. Stateful
   fills and private-WS order and position pushes become the follow-up #3007, which waits on #2877's private
   topics (`README.md:297-300`).
8. **Scope 10 is verified (S15, ruling 8).** main-orchestrator checked the pack's codes against the official
   v5 error table and posted it on #2893 (issuecomment-6225935988): `10002`, `10004`, `10005`, `110017`,
   `110024` and `110028` hold; `110044` is "Available margin is insufficient", so the pack's
   `leverage_refused_open_position` moves to `110013` ("Cannot set leverage due to risk limit level"); and
   `110026` and `110073` are the margin-mode overlays' codes. Production reads `110044` as a risk-limit tier
   (`exchange/bybit/mapping.py:54`, `24-internal-schemas.md:1605`); #3005 (P1) fixes that mismatch. What
   remains of S15 is pack data: that swap, the `110017` wording and the cleared `code_unconfirmed` flags. The
   reply envelopes come from the recorded corpus and stand.
9. **Stack-level acceptance waits** on #836, #837, #896, #899 and #2877 or #848 (plan §11, pending:
   `e27-accounts-test-plan.md:708-728`). Until then the slices meet acceptance 1, 2 and 4 at the transport and
   pipeline level (S13), and acceptance 5 except decision 4's residual (S8, S7), which ruling 9 counted as
   full; #2893 stays open until S16.
10. **A test-only switch, not a C-4.13 flag,** like `CV_TEST_CLOCK` (`settings.py:264-266`), which is not in
    the flag catalogue (`admin/flags/catalogue.py:25`). A flag is runtime, Owner-toggled and in every build;
    this switch is fixed at boot and its code is not in the release image. Each slice fails closed (until S7
    and S9 land, the transport refuses every request), and it gates no safety invariant (C-4.14): C-2.8 runs
    unchanged, for fixture keys only, and a real key gets no answer, which is never green (SR-E27-18).

### The fence, against E45-K01

E45-K01 (`docs/plan/backlog/E45.json:65`) asks ADR-0031 to fence any test-only hook. This record meets each
point, and is stricter on the first two:

<!-- prettier-ignore -->
| E45-K01 asks | This record |
| --- | --- |
| An explicit setting refused under `live` | `CV_ACCOUNT_FIXTURE`, refused on testnet too (decision 2) |
| A test-only extras group | A package outside the wheel, not an installable extra (decision 1) |
| Absent from the production image | No `COPY` names it, and a set variable refuses boot there |
| Asserted by a CI test | The enforcement list below |

E45-K01 names the E08 fixture-replay mock exchange for exchange-response faults (its layer 1), and an
in-process transport shim in the adapter as one candidate for network faults (layer 2). If ADR-0031 picks that
shim, it can reuse S4's seam and the same fence mechanism (a dev-only package, a wiring module that refuses
boot without it, an image check) rather than adding a second one; that choice is E45-K01's, and decision 2's
demo-only definition need not carry over.

### Enforcement

- **Import confinement (S3):** `.semgrep/cv-dev-module-confined.yml` lets only
  `candleviewer/account_fixture_wiring.py` name `cvdev`. S3 leaves `cv-adapter-isolation.yml` and
  `cv-bybit-vocabulary-leak.yml` covering `cvdev/**`, the stricter state. The serving slice, S9, adds their
  security-reviewed `cvdev/**` exclusions under its own review, because the stub speaks the venue's
  vocabulary. C-2.2 keeps exchange knowledge in the adapter; this record reads it as governing product code,
  as those rules already do for the fixture tooling (`tools/fixtures/**`, E08-T05, #1847) and the test tree
  (`.semgrep/cv-adapter-isolation.yml:20-23`, `:30-32`). The owner confirms that reading when ratifying.
  S3 likewise leaves `cv-untrusted-exchange-response.yml` covering `candleviewer/**` only; whether it reaches
  `cvdev` is the serving slices' decision.
- **Fund paths (S7):** `.semgrep/cv-withdrawal-endpoint-ban.yml` has no `paths:` filter, so it reaches `cvdev`
  unchanged (C-2.8). The stub serves only the pack's paths (any other gets a logged non-2xx), and its P0
  tripwire keys on the `/v5/asset/` prefix, which the pack never serves, so no withdraw or transfer literal is
  ever written in `cvdev`.
- **Image check (S3):** `tools/ci/check_image_no_dev_modules.py`, in `main.yml` before the push (`:164-176`)
  and in the offline boot smoke (`_job-security.yml:496-509`): `find_spec("cvdev")` is `None`, and a boot with
  `CV_ACCOUNT_FIXTURE=compliant` and the structural values (`CV_ENVIRONMENT=demo`, `CV_FEED=synthetic`, no
  `CV_BYBIT_API_*`) exits non-zero with the exact package-absent message. Any other exit, a `Settings`
  refusal included, fails the check. The `main.yml` step is the binding one: S3 adds it before the push with
  no `if:` of its own, so it runs on every image push (the workflow runs on any `services/api/**` change,
  `.github/workflows/main.yml:22-28`). The boot-smoke run is a PR-time early warning only: it sits in the
  `trivy` job, which runs only `if: inputs.image_changed` (`_job-security.yml:484`), and
  `.github/workflows/pr.yml:98-102` sets that for the image paths alone. S3 adds `services/api/cvdev/**` and
  `services/api/candleviewer/account_fixture_wiring.py` to that filter; if it cannot, it names the gap: a PR
  that touches the fence then meets the image check only after merge, before the push.
- **No `secrets` or `audit` import (S3):** `cvdev` becomes a second import-linter root, `root_packages` in
  place of `root_package = candleviewer` (`services/api/.importlinter:10`, emitted by
  `scripts/gen_importlinter_contracts.py:40`), so the existing `protected-secrets` and `protected-audit`
  contracts (`services/api/.importlinter:644-661`, C-3.2, C-3.3) cover it with no second allow-list. If the
  architecture job cannot import `cvdev`, S3 ships an AST test instead and records why.
- **`COPY` assertion (S3):** `test_image_boot_path.py` (#2555; its Dockerfile parse is at `:70-79`) fails if a
  `COPY` source names `cvdev` or `packages/fixtures/accounts`.
- **Compose (S14):** the fixture override builds `target: builder` only and never names a published image
  (`scripts/tests/test_compose_fixture_override.py`), so no documented path mounts `cvdev` into a release image.
- **Types and coverage (S2):** `mypy --strict` covers `cvdev` too (`_job-py.yml:76` names `candleviewer`
  only), and so does coverage (`services/api/pyproject.toml:159`, `:164`).

### Slices

| #   | Slice                                                   | After                                                                             |
| --- | ------------------------------------------------------- | --------------------------------------------------------------------------------- |
| S1  | This record and the STRIDE note                         | —                                                                                 |
| S2  | `Settings` gate and a fail-closed loader                | S1                                                                                |
| S3  | Release images carry no `cvdev`; its import is confined | S2                                                                                |
| S4  | Account REST client and private-socket seams            | S2, #836's seam (2a3), agreement of the #836, #1006 and #2877 owners (decision 3) |
| S5  | The pack resolver moves into `cvdev`                    | S2                                                                                |
| S6  | The plan §9.6 request log                               | S2                                                                                |
| S7  | Host, key-id and signature guards                       | S5, S6                                                                            |
| S8  | Boot guard: a non-fixture key refuses start             | S2, S5                                                                            |
| S9  | Serve the pack over the REST stub                       | S7, S8                                                                            |
| S10 | Fixture clock and per-key switching                     | S9, S4                                                                            |
| S11 | `reduceOnly` matcher for `close_rejected`               | S5                                                                                |
| S12 | Private-WS fixture socket                               | S7, S10, S4                                                                       |
| S13 | Scenario load check through the stub                    | S9 to S12                                                                         |
| S14 | Fixture compose override (builder stage only)           | S8 to S10, S12                                                                    |
| S15 | Apply the verified v5 codes to the pack (decision 8)    | S11                                                                               |
| S16 | Stack-level acceptance; fixture clock in E27 timers     | S13, S14, #836, #837, #896, #899, #2877/#848                                      |

Order (the rulings' scope guidance): S1 to S3 and S5 to S8 first, then S4 after #836's seam; the rest may wait
behind the E29 OMS lane.

## Consequences

- Good: one fence for all fixture code; a release image as built refuses a mis-set variable; production
  requests gain no branch; C-2.8 runs unchanged.
- Bad: a second top-level package needs its own type, coverage and Semgrep reach; rules that include only
  `services/api/candleviewer/**` (such as `.semgrep/cv-no-debug-probe-in-prod.yml:53-55`) are extended in S3
  or the gap is recorded. The repo-wide withdrawal rule needs nothing (Enforcement).
- Risk: the image fence holds for the image as built. Its venv's editable `.pth` names `/build`
  (`_job-security.yml:500-501`) and it runs from `/app` (`infra/images/Dockerfile.api:53`), so a bind mount of
  `cvdev` there or a `PYTHONPATH` entry would make the stub importable again. S14's compose tests keep the
  documented path on the builder stage, and the boot and per-request guards still refuse a real key.
- Risk: a guard trip latches the process read-only until the offending key row is revoked and the stack
  restarts (fail closed, by design; both boot checks skip revoked rows); a refused call is retried as the
  client allows (`exchange/bybit/config.py:65`), so one refusal can log several lines.
- Residual: a real key whose last 4 characters equal a pack tail (about 44 in 62^4) passes boot and is refused
  exactly on its first call (decision 4).

## Alternatives rejected

- **`candleviewer/exchange/bybit/`:** it ships in the wheel and the image; a setting would be the only fence.
- **`tests/` or `tools/fixtures/`:** neither is on the API's `sys.path` in a stack.
  `.semgrep/cv-no-debug-probe-in-prod.yml:41-42` also bans `tests` imports in `candleviewer/**`, though its
  non-live carve-out (`:47-52`) would let a guarded one through.
- **A `dev` value in `Environment`, or reading `CV_ENV`** (decision 2): `Environment` selects hosts, keys
  and the storage namespace (P9, `settings.py:71-80`), so a fourth value reaches every module that branches
  on it; `CV_ENV`, 20-architecture.md §7.2's name for what the code reads as `CV_ENVIRONMENT`, is not
  read by `Settings` (Context).
- **Each consumer builds its own signed client** (decision 3), with #2893 only threading the transport
  through: #836, #837 and #2877 would each need a fixture hook, so the fence would have one entry point per
  consumer.
- **An exact boot check in M2:** a decrypt-and-compare capability in every release image, for what the
  per-request check already gives.
- **Widening #2086's clock to demo:** staging is demo, so staging could run a moved auth clock.
- **One scenario per stack:** it cannot serve `rotation_ok`'s two keys or Group D's accounts.

## References

- [`E27-accounts.md` §12](../../security/threat-models/E27-accounts.md), the STRIDE note for this transport;
  [the pack README](../../../packages/fixtures/accounts/README.md) (#2962), its guards at `README.md:381-393`;
  [the E27 test plan](../../../qa/plans/e27-accounts-test-plan.md) §9.3 to §9.7 and §11.
- CONSTITUTION C-2.2, C-2.8, C-2.11, C-3.2, C-3.4, C-4.13, C-4.14, C-4.15.
