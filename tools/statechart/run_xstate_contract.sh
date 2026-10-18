#!/usr/bin/env bash
# The BLOCKING statechart contract gate (E50-T31; docs/plan/29-statechart-adoption-plan.md §1.7),
# defined once (#3104): the `xstate-contract` step of pr.yml's `gates` job and the `xstate-contract`
# job of _job-xstate-contract.yml (the nightly's callee) both run this file after checkout and
# astral-sh/setup-uv with python-version 3.12. It runs from the repository root whatever the
# caller's directory, and stops at the first failing command, as the job's separate steps did.
#
# Event-name coverage also runs as the `gates` step `event-coverage`; it stays here so the nightly
# keeps it. No tracing (SR-146), no secrets, no network beyond `uv sync`.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

cd services/api
uv sync --frozen --all-groups
# The -m keeps every marker addopts deselects (scripts/tests/test_workflow_pytest_markers.py reads
# this call): a quarantined `flaky` test runs in no lane (C-9.3, #3091).
uv run pytest tests/xstate_contract tests/xstate_upstream -q --no-cov \
  -m "not sync_parity and not fuzz and not perf and not harness and not flaky" \
  -W error::RuntimeWarning --durations=10 --junitxml=xstate-contract-junit.xml

# Event-name coverage over every Gateway.send site (E50-T05, MUST-10). Two commands, not `a && b`:
# under `set -e` a failing left side of a non-final `&&` would not stop the script.
uv run python ../../tools/statechart/event_coverage.py
uv run pytest ../../scripts/tests/test_event_coverage.py -q --no-cov -W error::RuntimeWarning

# Suite budget < 60 s + per-machine throughput (E50-T06), from the JUnit report above.
cd ../..
python tools/statechart/suite_budget.py services/api/xstate-contract-junit.xml
