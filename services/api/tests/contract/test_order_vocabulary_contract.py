"""Contract (E29-T03 #847, slice 2): the order vocabulary on REST and WS, with no database types.

`docs/plan/22-api-openapi.yaml` grows `OrderState` and `OrderEventKind`, adds `OrderLifecycleState`
and gives `Order` the optional, nullable `lifecycle_state`; `23-ws-protocol.md` section 15.1's
`orders` frame carries the same values and field. The REST side is read from the regenerated
models and the spec, the WS side from the `packages/protocol` bundle, never from a copy of either
(AGENTS.md section 6 rule 12), so the two surfaces cannot drift apart, nor lose the wording that
makes the added values additive (C-6.3). The tests that hold the same enums to the database types
come with the migration that adds those types.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel

from candleviewer.api._generated import openapi_models as rest
from candleviewer.api.contract_conformance import load_openapi_spec

_BUNDLE = Path(__file__).resolve().parents[4] / "packages" / "protocol" / "ws-schemas.json"
_FRAME: dict[str, Any] = json.loads(_BUNDLE.read_text(encoding="utf-8"))["schemas"][
    "cv://ws/v1/orders.schema.json"
]
#: One order of the WS `orders` frame (23 section 15.1), as the protocol package bundles it.
_WS_ORDER: dict[str, Any] = _FRAME["properties"]["orders"]["items"]
_WS_FIELDS: dict[str, Any] = _WS_ORDER["properties"]
_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
#: The spec schemas that carry the vocabulary; each says it is open-ended for readers (C-6.3).
_ENUM_SCHEMAS = ("OrderState", "OrderLifecycleState", "OrderEventKind")
#: What slice 2 adds to the persisted `order_state` and `order_event_kind` vocabularies.
_ADDED_STATES = frozenset({"triggered", "unknown", "quarantined", "killed", "held"})
_ADDED_KINDS = frozenset({"kill", "adopt"})


def _values(model: type[BaseModel], field: str) -> set[str]:
    """The `Literal` values of a generated field, through `| None`."""
    annotation = model.model_fields[field].annotation
    literal = next(a for a in (annotation, *get_args(annotation)) if get_origin(a) is Literal)
    return set(get_args(literal))


def _words(description: str) -> str:
    """A description on one line: a YAML block keeps its line breaks, a phrase may span two."""
    return " ".join(description.split())


def test_the_rest_and_ws_order_states_are_the_same_values() -> None:
    assert _values(rest.Order, "state") == set(_WS_FIELDS["state"]["enum"])


def test_the_rest_and_ws_lifecycle_states_are_the_same_values() -> None:
    ws_states = set(_WS_FIELDS["lifecycle_state"]["enum"]) - {None}  # the null is no state
    assert _values(rest.Order, "lifecycle_state") == ws_states


def test_the_added_order_states_are_on_rest_and_ws() -> None:
    assert _ADDED_STATES <= _values(rest.Order, "state")
    assert _ADDED_STATES <= set(_WS_FIELDS["state"]["enum"])


def test_the_added_order_event_kinds_are_on_rest() -> None:
    assert _ADDED_KINDS <= _values(rest.OrderEvent, "kind")


def test_lifecycle_state_is_optional_and_nullable_on_rest() -> None:
    field = rest.Order.model_fields["lifecycle_state"]
    assert field.is_required() is False
    assert type(None) in get_args(field.annotation)


def test_lifecycle_state_is_optional_and_nullable_on_ws() -> None:
    assert "lifecycle_state" not in _WS_ORDER["required"]
    assert None in _WS_FIELDS["lifecycle_state"]["enum"]


def test_every_order_enum_is_open_ended_for_readers() -> None:
    """C-6.3: a new value is additive only where the field says it is open-ended."""
    described = [_SCHEMAS[name]["description"] for name in _ENUM_SCHEMAS]
    described += [_WS_FIELDS[name]["description"] for name in ("state", "lifecycle_state")]
    assert [text for text in described if "Open-ended for readers" not in _words(text)] == []


def test_a_client_keeps_an_order_in_an_unknown_state_live_until_removed_lists_it() -> None:
    """23 section 15.1: the frame's `removed` is how an order the client cannot place leaves."""
    described = [_SCHEMAS["OrderState"]["description"], _WS_FIELDS["state"]["description"]]
    assert [text for text in described if not re.search(r"\blive\b.*`removed`", _words(text))] == []
