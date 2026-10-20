"""Unit tests for `candleviewer.statechart.config` (E50-T59)."""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.statechart import config
from candleviewer.statechart.config import (
    CV_INBOX_BOUND,
    CV_SERVICE_POOL,
    CV_START_TIMEOUT,
    LANES,
    register_event_schemas,
)

Schemas = dict[str, dict[str, dict[str, Any]]]


@pytest.fixture()
def schemas(monkeypatch: pytest.MonkeyPatch) -> Schemas:
    """A throwaway `CV_EVENT_SCHEMAS` for one test: `register_event_schemas` reads the module
    global when called, so a test machine registered here never reaches the process-wide map
    the factory and the contract suite read (C-13.7: no shared state, no order dependence)."""
    isolated: Schemas = {}
    monkeypatch.setattr(config, "CV_EVENT_SCHEMAS", isolated)
    return isolated


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


def test_register_event_schemas_merges_new_entries_per_machine(schemas: Schemas) -> None:
    register_event_schemas("test.config_a", {"TEST_EVENT_A": {"type": "object"}})

    assert schemas["test.config_a"]["TEST_EVENT_A"] == {"type": "object"}
    assert "TEST_EVENT_A" not in schemas.get("test.config_b", {})


def test_register_event_schemas_rejects_conflicting_redefinition(schemas: Schemas) -> None:
    register_event_schemas("test.config_a", {"TEST_EVENT_B": {"type": "object"}})
    with pytest.raises(ValueError, match="collision"):
        register_event_schemas("test.config_a", {"TEST_EVENT_B": {"type": "string"}})
    assert schemas["test.config_a"]["TEST_EVENT_B"] == {"type": "object"}


def test_two_machines_may_give_one_event_name_different_schemas(schemas: Schemas) -> None:
    """#847: B1 closes `EXEC`, `CANCEL`, `KILL`, `SL_DEADLINE` and `SL_OBSERVED`, which other
    charts keep permissive, so the map is keyed by machine."""
    register_event_schemas("test.config_a", {"TEST_SHARED": {"type": "object"}})
    register_event_schemas("test.config_b", {"TEST_SHARED": {"type": "string"}})
    assert schemas["test.config_a"]["TEST_SHARED"] != schemas["test.config_b"]["TEST_SHARED"]


def test_a_test_registration_never_reaches_the_process_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The contract suite sweeps the real machines' schemas (`test_factory.py`); a machine a unit
    test registers into the `schemas` fixture's map must stay out of the process-wide one."""
    process_map = config.CV_EVENT_SCHEMAS
    isolated: Schemas = {}
    monkeypatch.setattr(config, "CV_EVENT_SCHEMAS", isolated)
    register_event_schemas("test.config_c", {"TEST_EVENT_C": {"type": "string"}})
    assert "test.config_c" in isolated
    assert "test.config_c" not in process_map
