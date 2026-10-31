"""Every alert on a series is guarded by an ``absent()`` rule or accounted for (E04-Q02, #257).

BQ-07 (Reading A): a threshold rule on a series that is not exported reads as "healthy" (RSK-047,
observability gaps: the metric is silent, the alert never fires). A guard (`absent(...)` or
`absent_over_time(...)` in any rule file, matched by metric family name) makes the silence
visible. 58 rules had a series with no guard when the check was written (56 when counted as
"no guard on any series it reads"); a guard for a series created lazily or behind a default-off
flag would fire for good on a healthy system, so those are listed with a reason class in
`e04_q02_alert_guard_baseline.json` instead. The check fails on a new unguarded series and on a
stale baseline entry (a series now guarded, or a rule gone), so the list only shrinks. The match
is by name: label scope is not checked. Pure parsing of
`infra/prometheus/alerts/`; no network, no docker.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final

import pytest

from tests._alert_rules import (
    DRILL_RULE,
    Rule,
    base_name,
    guarded_names,
    is_guard,
    is_threshold,
    load_rules,
    series_in,
)

BASELINE: Final = Path(__file__).with_name("e04_q02_alert_guard_baseline.json")
CLASSES: Final = frozenset({"lazy-series", "module-guard", "flag-gated", "routed"})
Pair = tuple[str, str]  # (alert, series)


def unguarded(rules: list[Rule]) -> set[Pair]:
    """(alert, series) for every series a threshold rule reads that no `absent()` covers."""
    covered = guarded_names(rules)
    return {
        (r.alert, s)
        for r in rules
        if r.alert != DRILL_RULE and is_threshold(r.expr)
        for s in series_in(r.expr)
        if base_name(s) not in covered
    }


def baseline_entries() -> list[dict[str, Any]]:
    doc = json.loads(BASELINE.read_text("utf-8"))
    entries: list[dict[str, Any]] = doc["entries"]
    return entries


def diff(rules: list[Rule], entries: Iterable[dict[str, Any]]) -> tuple[set[Pair], set[Pair]]:
    """(new unguarded pairs, stale baseline pairs)."""
    listed = {(e["alert"], e["series"]) for e in entries}
    now = unguarded(rules)
    return now - listed, listed - now


def test_alert_rules_unguarded_series_all_in_baseline() -> None:
    new, _ = diff(load_rules(), baseline_entries())
    assert not new, (
        "threshold rules read series with no absent() guard and no baseline entry: "
        f"{sorted(new)}; add `absent(<series>)` to metric_guards.yml, or list the pair in "
        f"{BASELINE.name} with its reason class"
    )


def test_alert_guard_baseline_has_no_stale_entries() -> None:
    _, stale = diff(load_rules(), baseline_entries())
    assert not stale, (
        f"{BASELINE.name} lists pairs that are now guarded or gone: {sorted(stale)}; "
        "delete them so the baseline shrinks"
    )


def test_alert_guard_baseline_entries_carry_class_and_reason() -> None:
    entries = baseline_entries()
    keys = [(e["alert"], e["series"]) for e in entries]
    assert len(keys) == len(set(keys)), "duplicate baseline entry"
    for e in entries:
        assert set(e) == {"alert", "series", "class", "reason"}, e
        assert e["class"] in CLASSES, e
        assert e["reason"].strip(), e


def test_alert_guard_baseline_is_sorted_for_review() -> None:
    entries = baseline_entries()
    assert entries == sorted(entries, key=lambda e: (e["alert"], e["series"]))


# --- BQ-09 (b): the check itself fails when its input is broken --------------------------------

_BASE: Final = [
    Rule("a.yml", "FooHigh", "foo_depth > 10"),
    Rule("a.yml", "FooAbsent", "absent(foo_depth)"),
    Rule("a.yml", "BarHigh", 'sum by (env) (increase(bar_total{kind!="x"}[5m])) > 0'),
]


def test_self_test_guarded_rule_is_not_reported() -> None:
    assert unguarded(_BASE) == {("BarHigh", "bar_total")}


def test_self_test_new_unguarded_rule_is_reported() -> None:
    mutated = [*_BASE, Rule("a.yml", "BazHigh", "baz_seconds > 5")]
    new, stale = diff(mutated, [{"alert": "BarHigh", "series": "bar_total"}])
    assert new == {("BazHigh", "baz_seconds")}
    assert not stale


def test_self_test_new_guard_makes_a_baseline_entry_stale() -> None:
    mutated = [*_BASE, Rule("a.yml", "BarAbsent", "absent_over_time(bar_total[10m])")]
    new, stale = diff(mutated, [{"alert": "BarHigh", "series": "bar_total"}])
    assert not new
    assert stale == {("BarHigh", "bar_total")}


def test_self_test_removed_rule_makes_a_baseline_entry_stale() -> None:
    _, stale = diff(_BASE[:2], [{"alert": "BarHigh", "series": "bar_total"}])
    assert stale == {("BarHigh", "bar_total")}


def test_self_test_histogram_buckets_share_the_guard_of_the_family() -> None:
    rules = [
        Rule("a.yml", "LatSlow", "histogram_quantile(0.95, rate(lat_seconds_bucket[5m])) > 1"),
        Rule("a.yml", "LatAbsent", "absent(lat_seconds_count)"),
    ]
    assert unguarded(rules) == set()


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("foo > 1", True),
        ('foo{a!="b"} == 0', True),
        ('foo{a=~"b.*"}', False),
        ("absent(foo)", False),
        ("vector(1)", False),
    ],
)
def test_self_test_threshold_detection(expr: str, expected: bool) -> None:
    assert is_threshold(expr) is expected


@pytest.mark.parametrize(
    "word", ["count", "count_values", "group", "stddev", "stdvar", "bottomk", "quantile"]
)
def test_self_test_aggregation_word_before_by_is_not_read_as_a_series(word: str) -> None:
    assert series_in(f"{word} by (env) (foo_total) > 1") == {"foo_total"}


def test_alert_rules_scan_finds_the_known_rule_population() -> None:
    # Guards against the scan going blind (a path or parse change that returns no rules).
    rules = load_rules()
    assert sum(is_guard(r.expr) for r in rules) >= 40
    assert sum(is_threshold(r.expr) for r in rules) >= 100
