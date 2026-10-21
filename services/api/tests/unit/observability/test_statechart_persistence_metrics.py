"""E50-T63: the two statechart persistence metric families. Each is catalogued `planned` under E50
like the other `cv_machine_*` rows (registered by their owner, here the persistence bundle, on the
app's one facade), bounded by its closed label sets; the label is `operation`, an allow-listed
name, with the bound stated here (`.semgrep/cv-obs-metric-label-allowlist.yml`)."""

from __future__ import annotations

from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.statechart_wiring import PERSIST_OPERATIONS, PERSIST_OUTCOMES

SPECS = {spec.name: spec for spec in CATALOGUE}


def test_the_persist_ops_counter_is_catalogued_with_its_closed_label_sets() -> None:
    spec = SPECS["cv_machine_persist_ops_total"]
    assert (spec.kind, spec.labels, spec.status, spec.owner_epic) == (
        "counter",
        ("operation", "outcome"),
        "planned",
        "E50",
    )
    assert PERSIST_OPERATIONS == ("persist", "restore", "quarantine", "event_flush")
    assert PERSIST_OUTCOMES == ("ok", "refused", "degraded", "error")
    assert spec.max_series == len(PERSIST_OPERATIONS) * len(PERSIST_OUTCOMES) == 16
    assert "page" in spec.alert and "error" in spec.alert


def test_the_wal_pending_gauge_is_catalogued_with_no_label() -> None:
    spec = SPECS["cv_machine_event_wal_pending"]
    assert (spec.kind, spec.unit, spec.labels, spec.status, spec.owner_epic, spec.max_series) == (
        "gauge",
        "rows",
        (),
        "planned",
        "E50",
        1,
    )
