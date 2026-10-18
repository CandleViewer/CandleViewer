.PHONY: bench-journal audit-bench governance dev dev-down test gen gen-check contracts up down reset arch security audit-net ci-gate-fixture alert-drill alert-drill-stop

# E02-T01: root convenience targets delegating to pnpm/uv (20-architecture.md
# §5 Tooling). Thin wrappers only — the pnpm/turbo task graph and the uv/ruff
# commands remain the single source of truth (AGENTS.md §4); this Makefile
# never redefines what they do.
#
# E02-T12: the full dev loop promised by 20-architecture.md §5 — bring up the
# compose stack against `demo` with the synthetic feed (`CV_FEED=synthetic`,
# no Bybit credentials needed), then start the web Vite dev server against
# it. Teardown is `make dev-down` (equivalent to `make down`, named
# separately so the pairing with `make dev` is obvious to a new joiner).
dev:
	$(MAKE) up
	pnpm --filter @candleviewer/web dev

dev-down:
	$(MAKE) down

test:
	pnpm test
	uv run --project services/api pytest -m "not integration"

gen:
	pnpm generate
	uv run --project services/api python services/api/scripts/generate_protocol_models.py
	uv run --project services/api python tools/statechart/render_catalogue.py
	uv run --project services/api python tools/contracts/extract_ws_schemas.py
	uv run --project services/api python tools/contracts/gen_ws_constants.py
	uv run --project services/api python tools/errorcodes/generate.py

# E17-T01: offline WS contract gates (23-ws-protocol.md 16.5): bundle freshness,
# constants freshness and the blocking `ws_message_schemas` gate.
contracts:
	uv run --project services/api python tools/contracts/extract_ws_schemas.py --check
	uv run --project services/api python tools/contracts/gen_ws_constants.py --check
	uv run --project services/api python tools/contracts/validate_ws_schemas.py --draft 2020-12
	uv run --project services/api python tools/contracts/check_error_registry.py

# E03-T05: generated-code freshness gate (ADR-0013 binding rule 3). Runs
# `make gen` twice to assert determinism (CI-GEN-003), then fails on any
# diff/untracked output under packages/protocol (CI-GEN-001/002). Same
# script the `gen` step of `.github/workflows/pr.yml` runs in CI.
gen-check:
	python tools/ci/check_gen_freshness.py

# E02-T08: local compose stack (`core` + `obs` profiles by default; add
# `--profile cold` for MinIO). `up` waits for all-healthy via
# infra/scripts/healthcheck.sh; `down` stops containers but keeps volumes;
# `reset` also removes named volumes for a clean-state rebuild.
up:
	docker compose -f infra/docker-compose.dev.yml --profile core --profile obs up -d
	infra/scripts/healthcheck.sh core obs

down:
	docker compose -f infra/docker-compose.dev.yml --profile core --profile obs --profile cold down

reset:
	docker compose -f infra/docker-compose.dev.yml --profile core --profile obs --profile cold down -v


# E02-T06: module-boundary architecture gate (CONSTITUTION.md §3, C-3.1..C-3.5,
# §9 #18). Regenerates/checks services/api/.importlinter against
# docs/plan/module-contracts.toml, runs dependency-cruiser (frontend) and
# import-linter (backend). Wired into `pnpm verify`.
arch:
	pnpm arch

# E02-X02: single local entry point for everything the security lane
# (.github/workflows/_job-security.yml) runs, reduced through the same
# tools/ci/security_gate.py policy. Tools unrunnable on this machine
# (no Windows semgrep wheel, no docker) report SKIPPED with a reason
# rather than being silently treated as clean (CI-SEC-005 semantics).
security:
	python tools/ci/run_security_local.py

# GOV-001 (CODEOWNERS coverage check) + GOV-002 (rule-reference link check) +
# GOV-003 (single-source-of-truth duplication check). Stdlib-only Python; runs
# before any package manager is scaffolded (E02). Wired into the `governance`
# job invoked by `pr-metadata` (job creation: E01-Q02). See CONSTITUTION.md
# C-16.4 / C-16.5, C-8.1 / C-10.1.
governance:
	python scripts/check_codeowners_coverage.py --repo-root .
	python scripts/check_rule_refs.py --repo-root .
	python scripts/check_sot_duplication.py --repo-root .

# E09-T04: CI-on-host mesh-binding audit (20-architecture.md "WSL hazards" —
# "0.0.0.0 binding leak via portproxy ... verified by a make audit-net check
# in CI-on-host"). Runs the same BindingSelfCheck the app's boot/hourly
# self-check uses against this host's real listening sockets; exits
# non-zero if anything is bound off-mesh.
audit-net:
	uv run --project services/api python tools/ci/audit_net.py

# E03-Q01: regenerate/run the black-box CI-gate fixtures
# (tests/ci-gates/PLAN.md). `ci-gate-fixture` with no NAME runs all of them;
# `make ci-gate-fixture NAME=E03-GT-16b` runs just one case id, so a fixture
# can be re-checked on demand as the gates it targets evolve, without a
# long-lived scratch branch.
ci-gate-fixture:
	python tests/ci-gates/run_fixtures.py $(if $(NAME),--case $(NAME),)


# E04-T05: fire the SyntheticAlert Page end to end (needs `make up`); stop with alert-drill-stop.
alert-drill:
	python infra/alertmanager/alert_drill.py fire

alert-drill-stop:
	python infra/alertmanager/alert_drill.py stop

# E42-K01: audit_log index-strategy spike. Authoritative measurement is the CI job
# `integration / audit-query-plan` (label a PR `run-audit-spike` or dispatch CI; ~27 min at 10 M rows;
# CV_AUDIT_SPIKE_ROWS overrides size). Locally it needs Postgres via CV_TEST_PG_DSN; see docs/plan/spikes/E42-K01.md.
audit-bench:
	cd services/api && uv run pytest tests/integration/audit/test_query_plan_spike.py -m "integration and perf" --no-cov -rA -s -p no:randomly

# E41-K01: journal analytics tier benchmark (scratch Postgres DSN; needs duckdb/pyarrow/psycopg).
bench-journal:
	cd services/api && uv run python -m bench.journal_analytics.run --dsn "$(DSN)"

# E12-Q02: regenerate the bar golden banks (E12-T04 day + E12-Q02 tapes). Dry run (prints a diff
# summary, exits 1 if goldens would change) unless WRITE=1 CV_GOLDEN_REASON="why" (WRITE=1 only). Refused under CI.
golden-update:
	cd services/api && uv run python -m bench.bar_determinism.regen_goldens --suite all $(if $(filter 1,$(WRITE)),--write,)
