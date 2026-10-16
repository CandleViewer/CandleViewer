"""E42-T03: the shipped flag definitions are `21-database-schema.md` 10.7 row for row, and every
flag's outage value is its default but for the two engaged order-entry switches."""

from __future__ import annotations

from candleviewer.admin.flags import default_registry

_B, _ALL, _OWN = "boolean", "all_roles", "owner_only"
#: 10.7 as `(key, kind, default, is_killswitch, visibility)`. `engine.fallback_lightweight_charts`
#: is the one 10.7 row left out: a third-party production chart library is out of scope (D4, C-1.2).
_SECTION_10_7 = {
    ("trading.live_enabled", _B, False, False, _ALL),
    ("trading.one_click", _B, False, False, _ALL),
    ("engine.webgl_v2", _B, False, False, _ALL),
    ("rules.graph_editor", _B, True, False, _ALL),
    ("rules.form_editor", _B, True, False, _ALL),
    ("algo.twap", _B, False, False, _ALL),
    ("algo.chase", _B, False, False, _ALL),
    ("algo.iceberg", _B, False, False, _ALL),
    ("algo.scaled", _B, False, False, _ALL),
    ("algo.oco", _B, False, False, _ALL),
    ("recorder.auto_record", _B, True, False, _OWN),
    ("storage.cold_tier", _B, True, False, _OWN),
    ("killswitch.ingestion", _B, False, True, _OWN),
    ("killswitch.order_entry", _B, False, True, _ALL),
    ("maintenance.mode", _B, False, True, _ALL),
    ("maintenance.keep_recorder", _B, True, False, _OWN),
}


def test_the_catalogue_is_10_7_row_for_row() -> None:
    r = default_registry()
    rows = {(k, s.kind.value, s.default, s.is_killswitch, s.visibility.value) for k, s in r.items()}
    assert rows == _SECTION_10_7


def test_every_flag_fails_closed_to_its_default_but_two_engaged_switches() -> None:
    """While the store cannot be read every flag takes its default, but the two switches that
    refuse order entry are engaged; only the live gate needs evidence."""
    r = default_registry()
    engaged = {"maintenance.mode": True, "killswitch.order_entry": True}
    fail_closed = {k: s.fail_closed_value for k, s in r.items()}
    assert fail_closed == {k: s.default for k, s in r.items()} | engaged
    assert all(s.overridable != (s.is_killswitch or s.requires_evidence) for s in r.values())
    assert [k for k, s in r.items() if s.requires_evidence] == ["trading.live_enabled"]
