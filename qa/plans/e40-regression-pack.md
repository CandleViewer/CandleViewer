# E40 regression pack (alerts)

Ticket: E40-Q02 (#1203), slice 5 (`Partial:`). Ruling: BQ-10 (the marker, the list in this page, no workflow edit in this slice). Same design as the E08 and E09 packs (`qa/plans/e08-regression-pack.md`, `qa/plans/e09-regression-pack.md`). All paths below are relative to `services/api/` unless they start with `docs/` or `qa/`.

## How to run

```
cd services/api
HYPOTHESIS_PROFILE=ci uv run pytest -p no:randomly --no-cov -m e40_regression
```

`e40_regression` is a pytest marker registered in `services/api/pyproject.toml`. `services/api/tests/conftest.py` applies it at collection to the paths listed under "Marker coverage", so a new test in one of those files joins the pack. A bare `-m` replaces the repo's default `-m` expression, so the marker is never put on `perf`, `fuzz`, `harness` or `flaky` (C-9.3 quarantine) items. The run collects the whole tree first. No docker, no network, no live exchange (C-13.5).

Editing this page? Run its guard first: `cd services/api && uv run pytest -p no:randomly --no-cov tests/qa/test_e40_regression_pack.py`.

### Marker coverage

The marker selects every test in these files except the `perf`, `fuzz`, `harness` and `flaky` items. The list lives in `PACK_PATHS` in `services/api/tests/_e40_regression_pack.py`; `services/api/tests/qa/test_e40_regression_pack.py` compares the two lists in both directions and fails when this page cites a test the marker does not select.

- `tests/alerts/test_alert_compiler.py` an alert carries no action: a root `actions` key, a look-alike key or an action node is refused with `action_node`.
- `tests/alerts/test_alert_compiler_property.py` the same refusal over generated conditions and look-alike keys.
- `tests/alerts/test_alert_gating.py` the gate order, the muted-but-critical override, snooze and cooldown, and the storm window boundary.
- `tests/alerts/test_alert_dispatcher_restart.py` exactly-once delivery across a restart with a pending outbox, disabled channels, one bad row, store outage.
- `tests/alerts/test_alert_evaluator.py` the storm conservation case: 25 firings, all kept in history, the suppressed count exact.

## A. Cases

| Permanent case (BQ-10)                       | Test                                                                                                                                                                                                                                                                       |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| An alert cannot act (E40-TC-E07)             | `tests/alerts/test_alert_compiler.py::test_compile_actions_key_at_root_rejected_as_action_node`, `::test_lookalike_actions_key_inside_operand_rejected`                                                                                                                    |
| An alert cannot act (property, E40-TC-E07)   | `tests/alerts/test_alert_compiler_property.py`                                                                                                                                                                                                                             |
| Critical-override matrix (E40-TC-C01 to C09) | `tests/alerts/test_alert_gating.py::test_gate_muted_but_critical_override_passes`, `::test_gate_muted_follows_critical_override`, `::test_gate_critical_override_does_not_reopen_other_closed_gates`, `::test_gate_order_first_closed_gate_wins_and_later_gates_unchecked` |
| Exactly once under restart (E40-TC-D10)      | `tests/alerts/test_alert_dispatcher_restart.py::test_restart_with_pending_outbox_delivers_exactly_once`                                                                                                                                                                    |
| Storm conservation (E40-TC-B13, B14)         | `tests/alerts/test_alert_evaluator.py::test_evaluator_storm_25_firings_aggregate_without_losing_history`, `tests/alerts/test_alert_gating.py::test_storm_window_boundaries_exactly_n_then_n_plus_1`                                                                        |

### Joins when a PR merges

Not on `main` yet, so not in `PACK_PATHS`; each is added to the list and to "Marker coverage" by the PR that merges it or a follow-up.

| Joins when     | Test                                                                                                               |
| -------------- | ------------------------------------------------------------------------------------------------------------------ |
| PR 5730 merges | `services/api/tests/alerts/test_alert_load_q02.py` (storm conservation at load, 40 conditions to 40 subscriptions) |
| PR 5733 merges | `services/api/tests/chaos/alerts/` scenarios 1 to 6 (row-based exactly-once under kill, failover and relay loss)   |

The rows are removed when the PR merges and its files join the tagger; no guard covers a stale row.

## B. Scope notes

- **Wiring.** No CI job selects `-m e08_regression` or `-m e09_regression` on its own, and no job called "release regression job" exists (BQ-10). This slice adds no workflow edit: the pack tests already run in the `py` lane on every Python change, and its guard runs in the `rest-heavy-1` lane (`tools/ci/py-test-lanes.json`). A nightly or `release.yml` step that runs the command above is a `.github/workflows` edit, so it needs the `security-review` label and goes in one small separate PR.
- **Not in this pack.** Of the plan's 116 `E40-TC-*` cases this pack places 13 by id (the ids in section A); the rest are not placed one by one, and no id-level reason is recorded for them yet: each plan group gets its reason when the pack is next widened. The reasons known today: Performance budgets and the soak (`perf` items), the chaos suite beyond the two PRs above, the axe and screen-reader passes, and the webhook channel (flagged off, descoped to R5). The critical-override row cites gate-level tests only (the gate's own unit tests, not the end-to-end override path); plan group C needs the contract of #5676 before it can join, and the "Joins when" table has no row for it until that merges.
- **Sign-off.** The comment template is `docs/qa/signoff/e40-alerts-signoff-template.md`, in the house form of `docs/qa/e08-signoff.md` and `docs/qa/e09-signoff.md`; the session sheets are in the E40 charters (PR 5731).
