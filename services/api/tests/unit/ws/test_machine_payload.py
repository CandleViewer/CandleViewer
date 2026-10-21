"""E17-T08 (`23-ws-protocol.md` §6.4, §15.10): the registry's hand-written payload check agrees with
the bundled schema on a valid and an invalid corpus for every `machine_kind`, and is stricter only
where its docstring says. Its chart table matches the schema, the kind set and the admin API."""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator

from candleviewer.api.admin_statecharts import entity_kind
from candleviewer.ws.machine_payload import check_machine_payload
from candleviewer.ws.topics import MACHINE_ENTITY_KIND, MACHINE_KINDS
from tests.unit.ws._seq_support import _REGISTRY, _SCHEMAS
from tests.unit.ws.test_machines import _payload

_MACHINES: dict[str, Any] = _SCHEMAS["cv://ws/v1/machines.schema.json"]
_BUNDLE = Draft202012Validator(_MACHINES, registry=_REGISTRY)
#: Each `context_summary` key with a value of its §15.10 type, and one outside it.
_SUMMARY = {
    "symbol": ("BTCUSDT", "btcusdt"),
    "halted_by_kill": (False, 0),
    "recon_misses": (0, -1),
    "severity": ("info", "fatal"),
    "delivery_attempts": (2, True),
    "storm_count": (1, "1"),
    "gap_count_24h": (3, None),
    "resync_count": (4, 1.5),
    "mfa_satisfied": (True, "yes"),
    "step_up_failures": (0, []),
    "scope": ("global", "all"),
    "cancel_working": (True, None),
    "flatten": (False, 1),
}
#: Changes to a minimal payload: each field at and past its §15.10 edges.
_CHANGES: list[dict[str, Any]] = [
    {},
    *({"state": v} for v in ("a" * 64, "a" * 65, "Working", "", "lifecycle.submitted", 7)),
    {"regions": {"lifecycle": "submitted", "protection": "sl_pending"}},
    *({"regions": {f"r{i}": "s" for i in range(n)}} for n in (1, 4, 5)),
    *({"regions": r} for r in ({"Auth": "a", "b": "c"}, {"a": "B", "b": "c"}, ["a", "b"])),
    {"tags": ["critical", "terminal"]},
    *({"tags": [f"t{i:02}" for i in range(n)]} for n in (32, 33)),
    *({"tags": t} for t in (["a", "a"], ["Protected"], [1], "terminal")),
    *({"degraded": v} for v in (True, 0, None)),
    *({"machine_hash": v} for v in ("f" * 64, "0" * 63, "A" * 64, 0)),
    *({"environment": v} for v in ("testnet", "paper", None)),
    *({"updated_at_ms": v} for v in (0, 2**53 - 1, 2**53, -1, True, "1", 1.5)),
    *({"machine_kind": v} for v in ("position_protection", None, ["order"])),
    {"entity_id": "0a000000-0000-4000-8000-0000000000aa"},
    *({"context_summary": v} for v in ({}, [], {"reason": "manual halt"})),
    *({"context_summary": {key: v}} for key, pair in _SUMMARY.items() for v in pair),
]


@pytest.mark.parametrize("machine_kind", sorted(MACHINE_ENTITY_KIND))
def test_the_check_agrees_with_the_bundled_schema(machine_kind: str) -> None:
    base, kind = _payload(machine_kind), MACHINE_ENTITY_KIND[machine_kind]
    corpus = [{**base, **change} for change in _CHANGES]
    corpus += [{k: v for k, v in base.items() if k != gone} for gone in base]
    for payload in corpus:
        assert (check_machine_payload(kind, payload) is None) is _BUNDLE.is_valid(payload), payload
    assert {_BUNDLE.is_valid(p) for p in corpus} == {True, False}  # both corpora are there


def test_a_payload_is_refused_to_every_other_kind() -> None:
    """`machine_kind` names the entity's own chart (`algo`: B4-B7), which §15.10 cannot check."""
    for machine_kind, kind in MACHINE_ENTITY_KIND.items():
        for other in set(MACHINE_KINDS) - {kind}:
            assert check_machine_payload(other, _payload(machine_kind)) == "machine_kind"


@pytest.mark.parametrize(
    "change", [{"tags": ["terminal", "critical"]}, {"updated_at_ms": 1.0}, {"state": "working\n"}]
)
def test_the_check_is_stricter_than_the_bundle_only_where_it_says(change: dict[str, Any]) -> None:
    """Sorted `tags` (§6.4), no float for an integer, and an ECMA-262 `$` (no trailing newline)."""
    payload = {**_payload("order"), **change}
    assert _BUNDLE.is_valid(payload) and check_machine_payload("order", payload) is not None


def test_the_chart_table_is_the_schemas_the_kind_sets_and_the_admin_apis() -> None:
    assert sorted(MACHINE_ENTITY_KIND) == sorted(_MACHINES["properties"]["machine_kind"]["enum"])
    assert set(MACHINE_ENTITY_KIND.values()) == set(MACHINE_KINDS)
    assert all(entity_kind(chart) == kind for chart, kind in MACHINE_ENTITY_KIND.items())
    assert set(_SUMMARY) == set(_MACHINES["properties"]["context_summary"]["properties"])
