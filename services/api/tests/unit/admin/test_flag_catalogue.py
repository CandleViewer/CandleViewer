"""E42-T03: the shipped flag definitions build into a registry, gate no security control, and
fail closed to the restrictive value where they are safety-relevant."""

from __future__ import annotations

from structlog.testing import capture_logs

from candleviewer.admin.flags import (
    DENIED,
    FLAGS,
    LIVE_ENABLED,
    MAINTENANCE_KEEP_RECORDER,
    MAINTENANCE_MODE,
    Audience,
    default_registry,
)


def test_catalogue_builds_and_gates_no_security_control() -> None:
    registry = default_registry()
    assert len(registry) == len(FLAGS)
    assert all(not (spec.gates & DENIED) for spec in registry.values())
    assert "engine.fallback_lightweight_charts" not in registry  # C-1.2


def test_safety_relevant_flags_fail_closed() -> None:
    registry = default_registry()
    live = registry[LIVE_ENABLED]
    assert (live.default, live.fail_closed_value, live.requires_evidence) == (False, False, True)
    for key in (MAINTENANCE_MODE, "killswitch.order_entry"):
        spec = registry[key]
        assert (spec.is_killswitch, spec.default, spec.fail_closed_value) == (True, False, True)
    assert registry["killswitch.ingestion"].fail_closed_value is False
    assert registry[MAINTENANCE_KEEP_RECORDER].audience is Audience.OWNER
    assert registry[MAINTENANCE_MODE].audience is Audience.ALL


def test_startup_log_names_the_gates_of_every_shipped_flag() -> None:
    registry = default_registry()
    with capture_logs() as logs:
        registry.log_startup()
    by_key = {f["key"]: f for f in logs[0]["flags"]}
    assert set(by_key) == set(registry)
    assert by_key[MAINTENANCE_MODE]["gates"] == ["kill_switch"]
    assert by_key[LIVE_ENABLED]["gates"] == ["live_gate"]
