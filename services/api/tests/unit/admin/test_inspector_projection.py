"""E42-T07: the inspector's runtime-free projections. The export round-trips every registered
chart through the authoring schema; nothing here constructs or queries an interpreter."""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import UUID

import pytest

from candleviewer.admin.errors import AdminError
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
_ACCOUNT = UUID("a1000000-0000-4000-8000-000000000001")
_ORDER = "order:0a000000-0000-4000-8000-000000000001"
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
_FORBIDDEN_MODULES = (
    "xstate_statemachine",
    "candleviewer.statechart.factory",
    "candleviewer.statechart.persistence",
    "candleviewer.statechart.gateway",
)


def test_the_registry_holds_all_twenty_catalogue_charts() -> None:
    assert len(_REGISTRY.keys()) == 20


@pytest.mark.parametrize("kind", _REGISTRY.keys())
def test_export_round_trips_every_registered_chart_through_the_authoring_schema(kind: str) -> None:
    exported = export_chart(_REGISTRY, kind)
    chart = _REGISTRY.get(kind)
    assert (exported["machine_kind"], exported["machine_hash"]) == (kind, _REGISTRY.hash(kind))
    assert not set(_POLICY) & set(exported["stately"])
    restored = {**exported["stately"], **{k: chart[k] for k in _POLICY if k in chart}}
    assert restored == chart
    validate(restored)


def test_export_answers_the_same_for_any_id_of_a_kind() -> None:
    assert export_chart(_REGISTRY, _ORDER) == export_chart(_REGISTRY, "order")


@pytest.mark.parametrize(
    "key",
    ["algo:0a000000-0000-4000-8000-000000000001", "kill_switch:x", "order:", "nonsense"],
)
def test_export_refuses_algo_keys_bad_grammar_and_unregistered_kinds(key: str) -> None:
    with pytest.raises(UnknownMachineKeyError):
        export_chart(_REGISTRY, key)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("kill_switch", ("kill_switch", None)),
        (_ORDER, ("order", "0a000000-0000-4000-8000-000000000001")),
        ("book:BTCUSDT", ("book", "BTCUSDT")),
    ],
)
def test_machine_keys_follow_the_entity_grammar(key: str, expected: tuple[str, str | None]) -> None:
    assert parse_machine_key(key) == expected


@pytest.mark.parametrize(
    "key",
    [
        "order",
        "kill_switch:x",
        "order:",
        "order:a:b",
        "order:0A000000-0000-4000-8000-000000000001",
        "position_protection:1",
        "Order:1",
    ],
)
def test_malformed_or_unexposed_keys_are_unknown(key: str) -> None:
    with pytest.raises(UnknownMachineKeyError):
        parse_machine_key(key)


def test_unknown_key_errors_are_admin_errors() -> None:
    assert issubclass(UnknownMachineKeyError, AdminError)


def test_entity_kinds_are_read_only() -> None:
    with pytest.raises(TypeError):
        ENTITY_KINDS["order"] = ENTITY_KINDS["leg"]  # type: ignore[index]  # proves immutability


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
    ("kind", "scope_user", "scope_account", "expected"),
    [
        ("order", None, _ACCOUNT, True),
        ("order", None, None, False),
        ("risk_lockout", None, None, False),
        ("kill_switch", None, None, True),
        ("book", None, None, True),
        ("session", _ME, None, True),
        ("session", _OTHER, None, False),
        ("alert", None, None, False),
        ("replay", _OTHER, None, False),
        ("unknown_kind", _ME, _ACCOUNT, False),
    ],
)
def test_visibility_fails_closed(
    kind: str, scope_user: UUID | None, scope_account: UUID | None, expected: bool
) -> None:
    assert visible(kind, scope_user=scope_user, scope_account=scope_account, caller=_ME) is expected


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


def test_context_summary_drops_non_scalars_and_kinds_without_keys() -> None:
    assert context_summary("kill_switch", {"scope": {"nested": 1}, "flatten": True}) == {
        "flatten": True
    }
    assert context_summary("leg", {"leg_id": "x", "account_id": "a"}) == {}
    assert context_summary("unknown_kind", {"symbol": "x"}) == {}


def test_published_state_of_a_compound_chart_is_the_roots_active_child() -> None:
    chart = _REGISTRY.get("kill_switch")
    assert "engaged" in chart["states"]
    assert published_state(chart, ["kill_switch", "kill_switch.engaged"]) == "engaged"


def test_published_state_of_a_parallel_chart_is_the_first_regions_child() -> None:
    chart = _REGISTRY.get("order")
    assert "submitted" in chart["states"]["lifecycle"]["states"]
    configuration = ["order", "order.lifecycle", "order.lifecycle.submitted", "order.protection"]
    assert published_state(chart, configuration) == "submitted"


def test_published_state_is_none_without_an_active_child() -> None:
    assert published_state(_REGISTRY.get("kill_switch"), []) is None


def _imports(path: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(str(node.module))
            names |= {alias.name for alias in node.names}
    return modules, names


@pytest.mark.parametrize("path", sorted(_PACKAGE.glob("*.py")), ids=lambda p: p.name)
def test_inspector_never_imports_the_runtime_or_an_interpreter(path: Path) -> None:
    modules, names = _imports(path)
    assert not {m for m in modules for f in _FORBIDDEN_MODULES if m == f or m.startswith(f + ".")}
    assert not {"Interpreter", "SyncInterpreter", "build", "restore"} & names


def test_the_import_guard_sees_a_plain_import(tmp_path: Path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text("import xstate_statemachine\n", encoding="utf-8")
    assert _imports(probe)[0] == {"xstate_statemachine"}
