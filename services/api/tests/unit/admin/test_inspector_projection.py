"""E42-T07: the inspector's runtime-free projections. The export round-trips every registered
chart through the authoring schema; no test (and no code under test) builds an interpreter."""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import UUID

import pytest

from candleviewer.admin.inspector import (
    ENTITY_KINDS,
    UnknownMachineKeyError,
    context_summary,
    export_chart,
    parse_machine_key,
    published_state,
    visible,
)
from candleviewer.statechart import Registry, validate

_REGISTRY = Registry()
_ME = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001")
_OTHER = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002")
#: The CV policy keys `export_stately` removes; they sit at the chart root only.
_POLICY = (
    "strictConfig",
    "strict",
    "strictTargets",
    "actionErrorPolicy",
    "guardErrorPolicy",
    "spawnBlockingTimeout",
)
_PACKAGE = Path(__file__).resolve().parents[3] / "candleviewer/admin/inspector"


@pytest.mark.parametrize("kind", _REGISTRY.keys())
def test_export_round_trips_every_registered_chart_through_the_authoring_schema(kind: str) -> None:
    exported = export_chart(_REGISTRY, kind)
    chart = _REGISTRY.get(kind)
    assert (exported["machine_kind"], exported["machine_hash"]) == (kind, _REGISTRY.hash(kind))
    assert not set(_POLICY) & set(exported["stately"])
    restored = {**exported["stately"], **{k: chart[k] for k in _POLICY if k in chart}}
    assert restored == chart
    validate(restored)


def test_export_answers_the_same_for_any_id_and_refuses_unregistered_kinds() -> None:
    by_kind = export_chart(_REGISTRY, "order")
    assert export_chart(_REGISTRY, "order:0a000000-0000-4000-8000-000000000001") == by_kind
    for key in ("algo:0a000000-0000-4000-8000-000000000001", "nonsense"):
        with pytest.raises(UnknownMachineKeyError):
            export_chart(_REGISTRY, key)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("kill_switch", ("kill_switch", None)),
        (
            "order:0a000000-0000-4000-8000-000000000001",
            ("order", "0a000000-0000-4000-8000-000000000001"),
        ),
        ("book:BTCUSDT", ("book", "BTCUSDT")),
    ],
)
def test_machine_keys_follow_the_entity_grammar(key: str, expected: tuple[str, str | None]) -> None:
    assert parse_machine_key(key) == expected


@pytest.mark.parametrize(
    "key", ["order", "kill_switch:x", "order:", "position_protection:1", "Order:1"]
)
def test_malformed_or_unexposed_keys_are_unknown(key: str) -> None:
    with pytest.raises(UnknownMachineKeyError):
        parse_machine_key(key)


def test_entity_kinds_cover_every_exposed_chart_and_only_registered_ones() -> None:
    covered = {mk for rule in ENTITY_KINDS.values() for mk in rule.machine_kinds}
    assert covered <= set(_REGISTRY.keys())
    assert set(_REGISTRY.keys()) - covered == {
        "position_protection",
        "rule_instance",
        "ws_conn",
        "paper_account",
    }


@pytest.mark.parametrize(
    ("kind", "scope_user", "expected"),
    [
        ("order", None, True),
        ("kill_switch", None, True),
        ("session", _ME, True),
        ("session", _OTHER, False),
        ("alert", None, False),
        ("replay", _OTHER, False),
        ("unknown_kind", _ME, False),
    ],
)
def test_user_scoped_kinds_stay_self_scoped_for_the_owner(
    kind: str, scope_user: UUID | None, expected: bool
) -> None:
    assert visible(kind, scope_user=scope_user, caller=_ME) is expected


def test_context_summary_keeps_only_allowed_scalar_keys() -> None:
    context = {
        "symbol": "BTCUSDT",
        "halted_by_kill": False,
        "recon_misses": 2,
        "order_link_id": "cv-1",
        "qty": "0.5",
        "account_id": "a1",
    }
    assert context_summary("order", context) == {
        "symbol": "BTCUSDT",
        "halted_by_kill": False,
        "recon_misses": 2,
    }
    assert context_summary("kill_switch", {"scope": {"nested": 1}, "flatten": True}) == {
        "flatten": True
    }
    assert context_summary("leg", {"leg_id": "x", "account_id": "a"}) == {}
    assert context_summary("unknown_kind", {"symbol": "x"}) == {}


@pytest.mark.parametrize(
    ("kind", "configuration", "expected"),
    [
        ("kill_switch", ["kill_switch", "kill_switch.engaged"], "engaged"),
        (
            "order",
            ["order", "order.lifecycle", "order.lifecycle.submitted", "order.protection"],
            "submitted",
        ),
        ("kill_switch", [], None),
    ],
)
def test_published_state_is_the_roots_active_child(
    kind: str, configuration: list[str], expected: str | None
) -> None:
    chart = _REGISTRY.get(kind)
    if expected is not None:
        root_states = chart["states"] if kind != "order" else chart["states"]["lifecycle"]["states"]
        assert expected in root_states
    assert published_state(chart, configuration) == expected


def test_inspector_never_imports_the_runtime_or_an_interpreter() -> None:
    for path in _PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import | ast.ImportFrom)
            for alias in node.names
        }
        modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        assert not any(str(m).startswith("xstate_statemachine") for m in modules), path
        assert not {"Interpreter", "SyncInterpreter", "build", "restore"} & names, path
