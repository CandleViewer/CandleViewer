"""`statechart.schema.canonical_json`, the one serializer of `machine_hash`, the snapshot seal's
MAC input and the drain journal's `send_id` (24 §17.6; E50-T62 #3793 adds `allow_nan=False`)."""

from __future__ import annotations

import math

import pytest

from candleviewer.statechart.registry import DEFAULT_MACHINES_DIR, Registry
from candleviewer.statechart.schema import canonical_json


def test_canonical_json_sorts_keys_and_writes_no_whitespace_in_ascii() -> None:
    value = {"b": [1, 0.5, None, True], "a": {"é": "✓", "c": -0.0, "d": 1e16}}
    assert canonical_json(value) == (
        b'{"a":{"c":-0.0,"d":1e+16,"\\u00e9":"\\u2713"},"b":[1,0.5,null,true]}'
    )


def test_canonical_json_serializes_a_list_as_the_send_id_does() -> None:
    assert canonical_json(["order", 1, {"b": 2, "a": 1}]) == b'["order",1,{"a":1,"b":2}]'


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf], ids=["nan", "inf", "-inf"])
def test_canonical_json_refuses_nan_and_infinity(value: float) -> None:
    """E50-T62: NaN and the infinities are not JSON, so they are an error, never `NaN` text."""
    with pytest.raises(ValueError, match="not JSON compliant"):
        canonical_json({"context": {"nested": [value]}})


def test_canonical_json_refuses_a_value_json_cannot_hold() -> None:
    """No `default`: a non-JSON type is an error, never its `str()`."""
    with pytest.raises(TypeError, match="not JSON serializable"):
        canonical_json({"at": object()})


def test_no_committed_chart_holds_a_value_the_strict_serializer_refuses() -> None:
    """`allow_nan=False` changes no `machine_hash`: every committed chart serializes."""
    registry = Registry(machines_dir=DEFAULT_MACHINES_DIR)
    assert registry.keys()
    for key in registry.keys():
        assert canonical_json(registry.get(key)).startswith(b"{")
