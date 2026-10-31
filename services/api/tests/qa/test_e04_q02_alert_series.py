"""Every series an alert reads is emitted, recorded or scraped (E04-Q02, #257).

BQ-08: an alert whose series nothing produces can never fire, and reads as "healthy" (RSK-047,
observability gaps); this is how `PostgresDown` (`pg_up`) slipped through, since the dashboard
lint checks panels, not rules. `PostgresDown`, `ClockDriftBlockingTrading` and the unemitted class
behind them are #5174 (P1). Each series in each alert expression, guards included, must be
(1) a catalogue series that is emitted: `status="live"` or `exported=True` (a `planned` entry
records an owner epic, not an emitter; `register_r0` registers live ones only), histogram
families by name, (2) a recorded
rule, or (3) an external name whose producing job is a scrape target in `prometheus.yml`. The
lookup is `infra/grafana/lint_dashboards.py`'s, loaded by path, plus the scrape-job condition.
Today's violations are listed with reasons in `e04_q02_alert_series_baseline.json`; the check
fails on a new violation and on a stale entry, so the list only shrinks. Static: no network, no
docker, and no claim about a running stack.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final

import pytest

from candleviewer.observability.metrics_catalogue import CATALOGUE
from tests._alert_rules import (
    Rule,
    base_name,
    lint_module,
    load_rules,
    recorded_names,
    scrape_jobs,
    series_in,
)

BASELINE: Final = Path(__file__).with_name("e04_q02_alert_series_baseline.json")
Pair = tuple[str, str]  # (alert, series)
# The scrape job that produces each external name the dashboard lint lists. `process_*` rides on
# the API's own scrape (any `process_*` name, e.g. `process_start_time_seconds`, which the lint's
# list omits); the push-model names reach Prometheus through the pushgateway; Alertmanager
# and Prometheus self-metrics have no job here, which is what the check reports for them.
_PUSHED_PREFIXES: Final = ("ga_defect", "design_qa_", "push_time_seconds")
# `alert_drill.py` pushes this gauge to the pushgateway on demand (infra/alertmanager/).
_PUSHED_EXTRA: Final = frozenset({"cv_synthetic_alert"})


def producer_job(name: str) -> str | None:
    """The job that would supply an external series, or None if it is not a known external name."""
    if name.startswith("process_"):
        return "candleviewer-api"
    if name.startswith(_PUSHED_PREFIXES) or name in _PUSHED_EXTRA:
        return "pushgateway"
    if name.startswith("alertmanager_"):
        return "alertmanager"
    if name.startswith("prometheus_") or name == "ALERTS":
        return "prometheus"
    return None


# Catalogue entries still marked `planned` whose owner module already creates the series from its
# catalogue spec (the status is stale, or the module registers it when wired). Each is a cite the
# test below re-checks, so a name leaves this table when its emitter does.
_PLANNED_BUT_EMITTED: Final = {
    "cv_outbox_dead_total": "app.py",  # bound at start by the alert.deliver dispatcher
    "cv_outbox_depth": "app.py",
    "oms_position_reading_owed_age_seconds": "oms_stream_wiring.py",
    "oms_unknown_orders": "oms/order_machine.py",
}


def planned_names() -> frozenset[str]:
    """Catalogue entries nothing emits yet: `planned`, not `exported`, no emitter module."""
    return frozenset(
        s.name
        for s in CATALOGUE
        if s.status == "planned" and not s.exported and s.name not in _PLANNED_BUT_EMITTED
    )


def emitted_names() -> frozenset[str]:
    """Catalogue names the dashboard lint finds, minus the planned ones."""
    return frozenset(lint_module().catalogue_names()) - planned_names()


def violations(rules: list[Rule]) -> set[Pair]:
    lint = lint_module()
    known, recorded, jobs = emitted_names(), recorded_names(), scrape_jobs()
    bad: set[Pair] = set()
    for r in rules:
        for s in series_in(r.expr, with_process=True):
            if s in recorded or base_name(s) in known:
                continue
            external = s in lint.EXTERNAL or s in _PUSHED_EXTRA or s.startswith("process_")
            if external and producer_job(s) in jobs:
                continue
            bad.add((r.alert, s))
    return bad


def baseline_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = json.loads(BASELINE.read_text("utf-8"))["entries"]
    return entries


def diff(rules: list[Rule], entries: Iterable[dict[str, Any]]) -> tuple[set[Pair], set[Pair]]:
    """(new violations, stale baseline pairs)."""
    listed = {(e["alert"], e["series"]) for e in entries}
    now = violations(rules)
    return now - listed, listed - now


def test_alert_series_all_emitted_recorded_or_scraped() -> None:
    new, _ = diff(load_rules(), baseline_entries())
    assert not new, (
        f"alert expressions read series nothing emits, records or scrapes: {sorted(new)}; "
        f"fix the expression, or list the pair in {BASELINE.name} with a reason"
    )


def test_alert_series_baseline_has_no_stale_entries() -> None:
    _, stale = diff(load_rules(), baseline_entries())
    assert not stale, (
        f"{BASELINE.name} lists pairs that now resolve or are gone: {sorted(stale)}; "
        "delete them so the baseline shrinks"
    )


def test_alert_series_baseline_entries_carry_a_reason() -> None:
    entries = baseline_entries()
    keys = [(e["alert"], e["series"]) for e in entries]
    assert len(keys) == len(set(keys)), "duplicate baseline entry"
    assert keys == sorted(keys)
    for e in entries:
        assert set(e) == {"alert", "series", "reason"}, e
        assert e["reason"].strip(), e


def test_alert_series_external_names_in_use_are_all_scraped_or_baselined() -> None:
    # The lint's EXTERNAL list is not proof of existence: every external name an alert reads has
    # a producer job, and one with no scrape target must be in the baseline.
    jobs = scrape_jobs()
    listed = {(e["alert"], e["series"]) for e in baseline_entries()}
    lint = lint_module()
    for r in load_rules():
        for s in series_in(r.expr, with_process=True):
            if s in lint.EXTERNAL and producer_job(s) not in jobs:
                assert (r.alert, s) in listed, (r.alert, s)


# --- BQ-09 (b): the check itself fails when its input is broken --------------------------------


def test_self_test_rule_reading_a_fake_series_is_reported() -> None:
    mutated = [*load_rules(), Rule("x.yml", "FakeHigh", "cv_no_such_series_total > 1")]
    new, _ = diff(mutated, baseline_entries())
    assert new == {("FakeHigh", "cv_no_such_series_total")}


def test_self_test_external_name_without_a_scrape_job_is_reported() -> None:
    mutated = [Rule("x.yml", "AmDown", "increase(alertmanager_alerts_invalid_total[5m]) > 0")]
    assert violations(mutated) == {("AmDown", "alertmanager_alerts_invalid_total")}


def test_self_test_catalogue_recorded_and_pushed_names_resolve() -> None:
    lint = lint_module()
    some_catalogue = sorted(lint.catalogue_names())[0]
    mutated = [
        Rule("x.yml", "A", f"{some_catalogue} > 1"),
        Rule("x.yml", "B", "cv:e2e_tick_to_paint_seconds:p95_1m > 1"),
        Rule("x.yml", "C", "ga_defects_open > 1"),
        Rule("x.yml", "D", "process_start_time_seconds > 1"),
    ]
    assert violations(mutated) == set()


def test_self_test_planned_catalogue_name_does_not_count_as_emitted() -> None:
    planned = sorted(planned_names())
    assert planned, "the catalogue lists planned series"
    mutated = [Rule("x.yml", "P", f"{planned[0]} > 1")]
    assert violations(mutated) == {("P", planned[0])}
    assert planned[0] in lint_module().catalogue_names()


def test_planned_but_emitted_names_still_have_an_emitter_outside_the_catalogue() -> None:
    root = Path(__file__).resolve().parents[2] / "candleviewer"
    planned = {s.name for s in CATALOGUE if s.status == "planned"}
    for name, module in _PLANNED_BUT_EMITTED.items():
        assert name in planned, f"{name} is no longer planned: drop it from the table"
        assert name in (root / module).read_text("utf-8"), (name, module)


def test_self_test_fixed_expression_makes_its_baseline_entry_stale() -> None:
    entries = [*baseline_entries(), {"alert": "Gone", "series": "gone_total", "reason": "x"}]
    _, stale = diff(load_rules(), entries)
    assert stale == {("Gone", "gone_total")}


@pytest.mark.parametrize("name", ["pg_up", "credential_expiry_days", "env_mismatch_attempts_total"])
def test_alert_series_named_by_the_draft_stay_listed_until_they_resolve(name: str) -> None:
    # Dropping one of these from the baseline without fixing the rule must fail the first test.
    assert any(e["series"] == name for e in baseline_entries())
