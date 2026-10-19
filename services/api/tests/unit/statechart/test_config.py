"""Unit tests for `candleviewer.statechart.config` (E50-T59)."""

from __future__ import annotations

import pytest

from candleviewer.statechart.config import (
    CV_INBOX_BOUND,
    CV_SERVICE_POOL,
    CV_START_TIMEOUT,
    LANES,
    register_event_schemas,
)


def test_all_lanes_have_inbox_and_pool_entries() -> None:
    for lane in LANES:
        assert lane in CV_INBOX_BOUND
        assert lane in CV_SERVICE_POOL
        assert CV_INBOX_BOUND[lane] > 0
        assert CV_SERVICE_POOL[lane] > 0


def test_service_pool_total_within_mustnot_08_ceiling() -> None:
    assert sum(CV_SERVICE_POOL.values()) <= 200


def test_start_timeout_is_positive() -> None:
    assert CV_START_TIMEOUT > 0


def test_register_event_schemas_merges_new_entries_per_machine() -> None:
    register_event_schemas("test.config_a", {"TEST_EVENT_A": {"type": "object"}})
    from candleviewer.statechart.config import CV_EVENT_SCHEMAS

    assert CV_EVENT_SCHEMAS["test.config_a"]["TEST_EVENT_A"] == {"type": "object"}
    assert "TEST_EVENT_A" not in CV_EVENT_SCHEMAS.get("test.config_b", {})


def test_register_event_schemas_rejects_conflicting_redefinition() -> None:
    register_event_schemas("test.config_a", {"TEST_EVENT_B": {"type": "object"}})
    with pytest.raises(ValueError, match="collision"):
        register_event_schemas("test.config_a", {"TEST_EVENT_B": {"type": "string"}})


def test_two_machines_may_give_one_event_name_different_schemas() -> None:
    """#847: B1 closes `EXEC`, `CANCEL`, `KILL`, `SL_DEADLINE` and `SL_OBSERVED`, which other
    charts keep permissive, so the map is keyed by machine."""
    from candleviewer.statechart.config import CV_EVENT_SCHEMAS

    register_event_schemas("test.config_a", {"TEST_SHARED": {"type": "object"}})
    register_event_schemas("test.config_b", {"TEST_SHARED": {"type": "string"}})
    assert (
        CV_EVENT_SCHEMAS["test.config_a"]["TEST_SHARED"]
        != CV_EVENT_SCHEMAS["test.config_b"]["TEST_SHARED"]
    )
