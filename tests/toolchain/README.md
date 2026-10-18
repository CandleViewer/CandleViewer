# tests/toolchain — automated toolchain regression pack (E02-Q03)

Guards `CONSTITUTION.md` §9's quality-gate table and the C-9.2/C-9.3/C-9.4 invariants it protects
against silent decay: a contract exception added "just for now", a coverage `omit` entry that never
expires, a renamed task whose documentation row rotted, a coverage floor quietly lowered over many
PRs. `E02-Q01` verified these once, by hand, when the E02 epic closed; this pack makes that
verification mechanical and repeatable so it survives every future PR — not just the one that
closed E02.

## Run it

```sh
pnpm test:toolchain
# equivalent to:
python -m pytest tests/toolchain -q && python -m tests.toolchain.pack
```

- The `pytest` half runs `tests/toolchain/test_pack.py` — fixture-driven unit tests, one positive
  (passes on the real repo tree) and one negative (an injected violation on a `tmp_path` fixture is
  caught) per assertion.
- The `python -m tests.toolchain.pack` half runs the pack directly against the real repo, prints a
  PASS/FAIL line per gate to stdout/stderr, and writes `reports/toolchain-regression.json`
  (gate status, violation count, violation messages, overall pass/fail) for dashboard aggregation
  (`docs/plan/03-testing-strategy.md` §15).
- Runtime is a few seconds (well under the ticket's 3-minute budget); it starts no Docker
  containers and makes no network calls — every check is a static assertion against files already
  in the repo tree.

Non-zero exit on any violation. Nightly CI scheduling (C-9.2) is out of scope for this ticket and is
owned by the release-pipeline epic (E03); this pack is written so wiring it into a workflow job is a
one-line `run:` step once that epic lands.

## What each check asserts

| Check (registered in `pack.ALL_CHECKS`) | Rule           | What it asserts                                                                                                                                                                                                                                                                                                                                                                  | Reuses                                                                                                                   |
| --------------------------------------- | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `gate-registration`                     | C-9.1          | Every §9 gate name is required on `main`, run by a lane `ci-required` judges, or listed with a reason in `pending_checks` in `.github/branch-protection.json`.                                                                                                                                                                                                                   | `scripts/check_required_check_reconciliation.py` (imported, not re-implemented — C-16.5)                                 |
| `agents-commands`                       | `AGENTS.md` §4 | Every documented root command resolves in the real turbo/package.json task graph.                                                                                                                                                                                                                                                                                                | `scripts/check-agents-commands.mjs` (run as a subprocess)                                                                |
| `coverage-floors`                       | C-9.4          | `quality-gates.json` coverage thresholds meet or exceed the floors named in §9 itself, for every package §9 names — a direct assertion against the Constitution's numbers, not only a diff against `main` (that diff is `tools/ci/quality_gates.py`, run by `pnpm gate:threshold-guard`).                                                                                        | hardcoded `CONSTITUTION_COVERAGE_FLOORS` table                                                                           |
| `coverage-omit-provenance`              | C-9.4          | Every `[tool.coverage.run] omit = [...]` list in any `pyproject.toml` has a preceding comment with a ticket reference and a date, and (if it names an `expires:` date) that date has not passed.                                                                                                                                                                                 | —                                                                                                                        |
| `architecture-contracts`                | E02-T06        | `services/api/.importlinter` and `.dependency-cruiser.js` each declare at least one contract/rule, and any `ignore_imports`/`ignoreImports` exception is preceded by an `ADR-NNNN` reference.                                                                                                                                                                                    | —                                                                                                                        |
| `flaky-quarantine-age`                  | C-9.3          | Every `@pytest.mark.flaky` / `.flaky(...)` marker carries a `ticket: <KEY>` and `quarantined: YYYY-MM-DD`, and the quarantine is at most 10 **working** days old.                                                                                                                                                                                                                | scan patterns from `tools/ci/flaky_quarantine_report.py`; adds the working-day expiry check that script does not perform |
| `compose-invariants`                    | E02-T08        | The base compose file's published ports are loopback-bound, images are sha256-digest-pinned, and every service has a healthcheck. Only the base file is linted — override files (`docker-compose.dev.yml`, `.vps.yml`) legitimately omit fields they inherit via `docker compose -f base -f override` merge, so linting them standalone would flag correct usage as a violation. | `infra/scripts/lint_compose.py` (static-only; never starts Docker)                                                       |

## Extending the pack

1. Add a new `check_<name>(repo_root: Path = REPO_ROOT) -> list[Violation]` function in `pack.py`
   that returns one `Violation(rule, message)` per problem found (empty list == pass). Name the rule
   id and the file in every message — a red run must say what to fix without re-reading this file.
2. Register it in `ALL_CHECKS` with a `"<name> (<rule id>)"` display name.
3. Add a fixture-driven positive test (asserts `[]` on `pack.REPO_ROOT`) and at least one negative
   test (builds a minimal broken tree under `tmp_path`, asserts the expected violation string
   appears) in `test_pack.py`.
4. If the new check reuses an existing script/module's logic, dynamically import it (see
   `_import_check_reconciliation` / `_import_lint_compose` for the pattern) rather than
   re-implementing a second parser of the same source of truth (C-16.5).
5. Run `pnpm test:toolchain` locally before opening the PR.
