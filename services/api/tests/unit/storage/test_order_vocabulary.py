"""The persisted order vocabulary (E29-T03 #847, slice 2; main-orchestrator's ruling 2): the B1
chart's `lifecycle` states, `LifecycleState`, the 24-internal-schemas.md Sec.8.2 mapping onto
`order_state`, and the regenerated REST and WS enums, held to the database types; and Sec.8.6's
exchange-boundary `OmsErrorCode`, held to the code."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel

from candleviewer.api._generated import openapi_models as rest
from candleviewer.db import models
from candleviewer.exchange.base.errors import OmsErrorCode
from candleviewer.storage.repositories.orders import (
    OPEN_STATES,
    ORDER_STATE_OF,
    LifecycleState,
    OrderState,
)

_REPO = Path(__file__).resolve().parents[5]
_CHART = _REPO / "services/api/candleviewer/statechart/machines/B01.order.machine.json"
_WS = _REPO / "packages/protocol/ws-schemas.json"
_SCHEMAS = _REPO / "docs/plan/24-internal-schemas.md"
_SECTION = "### 8.2 Order state machine"  # of 24-internal-schemas.md


def _chart() -> dict[str, Any]:
    machine = json.loads(_CHART.read_text(encoding="utf-8"))
    lifecycle: dict[str, Any] = machine["states"]["lifecycle"]["states"]
    return lifecycle


def _doc_table() -> list[tuple[str, str]]:
    """The rows of the "Persisted state" table of 24 Sec.8.2, in order."""
    doc = _SCHEMAS.read_text(encoding="utf-8")
    section = doc.split(_SECTION, 1)[1].split("**Persisted state", 1)[1].split("\n### ", 1)[0]
    return re.findall(r"^\| `(\w+)` +\| `(\w+)` +\|$", section, re.MULTILINE)


def _values(model: type[BaseModel], field: str) -> set[str]:
    """The `Literal` values of a generated field, through `| None`."""
    annotation = model.model_fields[field].annotation
    literal = next(a for a in (annotation, *get_args(annotation)) if get_origin(a) is Literal)
    return set(get_args(literal))


def test_lifecycle_state_is_the_charts_lifecycle_region_verbatim() -> None:
    assert get_args(LifecycleState) == tuple(_chart()) == models.ORDER_LIFECYCLE_STATES


def test_every_chart_state_maps_to_one_order_state_as_24_section_8_2_lists() -> None:
    assert list(ORDER_STATE_OF) == list(get_args(LifecycleState))  # total, in chart order
    assert list(ORDER_STATE_OF.items()) == _doc_table()
    assert set(ORDER_STATE_OF.values()) == set(get_args(OrderState))  # and onto


def test_the_mapping_has_no_many_to_one_case_and_six_names_differ() -> None:
    """24 Sec.8.2 lists no many-to-one case; a second chart state on one value must be listed
    there first. The renamed six are the `submitted` trap `lifecycle_state` closes."""
    values = list(ORDER_STATE_OF.values())
    assert sorted(v for v in set(values) if values.count(v) > 1) == []
    assert {chart: db for chart, db in ORDER_STATE_OF.items() if chart != db} == {
        "draft": "new", "validated": "pending_submit", "submitting": "submitted",
        "submitted": "accepted", "cancel_pending": "pending_cancel",
        "amend_pending": "pending_amend",
    }  # fmt: skip


def test_the_open_states_are_every_live_chart_state() -> None:
    """`list_open` sees every order the chart has not ended, but a draft (never written) and an
    untracked order (`ix_orders_untracked`; never managed, S9)."""
    chart = _chart()
    ended = {name for name, node in chart.items() if node.get("type") == "final"}
    live = [s for s in get_args(LifecycleState) if s not in {*ended, "draft", "untracked"}]
    assert OPEN_STATES == {ORDER_STATE_OF[s] for s in live}


def test_the_regenerated_rest_and_ws_enums_are_the_database_enums() -> None:
    frame = json.loads(_WS.read_text(encoding="utf-8"))["schemas"]["cv://ws/v1/orders.schema.json"]
    order = frame["properties"]["orders"]["items"]["properties"]
    assert _values(rest.Order, "state") == set(order["state"]["enum"]) == set(models.ORDER_STATES)
    ws_lifecycle = set(order["lifecycle_state"]["enum"]) - {None}
    lifecycle = set(models.ORDER_LIFECYCLE_STATES)
    assert _values(rest.Order, "lifecycle_state") == lifecycle == ws_lifecycle
    assert None in order["lifecycle_state"]["enum"]  # nullable on both, never required
    assert rest.Order.model_fields["lifecycle_state"].is_required() is False
    assert _values(rest.OrderEvent, "kind") == set(models.ORDER_EVENT_KINDS)


def test_the_order_enums_are_open_ended_for_readers() -> None:
    """C-6.3: a new value is additive only where the field says it is open-ended, and a client
    keeps an order whose state it does not know live until `removed` lists it (23 Sec.15.1)."""
    frame = json.loads(_WS.read_text(encoding="utf-8"))["schemas"]["cv://ws/v1/orders.schema.json"]
    order = frame["properties"]["orders"]["items"]["properties"]
    rest_state = rest.Order.model_fields["state"].description
    described = [rest_state, rest.OrderEvent.model_fields["kind"].description]
    described += [order["state"]["description"], order["lifecycle_state"]["description"]]
    assert all("Open-ended for readers" in str(text) for text in described)
    assert all("live" in str(text) and "`removed`" in str(text) for text in described[::2])


def test_section_8_6_lists_the_exchange_enum_and_keeps_the_oms_codes_apart() -> None:
    """`exchange/base/errors.py` is Sec.8.6's `OmsErrorCode` block verbatim; the five codes the OMS
    raises itself stand beside the block, and none is a member of the exchange-boundary enum."""
    doc = _SCHEMAS.read_text(encoding="utf-8").split("class OmsErrorCode(StrEnum):", 1)[1]
    block, after = doc.split("```", 1)
    assert re.findall(r'^    (\w+) = "\1"', block, re.MULTILINE) == [c.name for c in OmsErrorCode]
    paragraph = after.split("**OMS codes (E29-T03).**", 1)[1].split("\n", 1)[0]
    oms = re.findall(r"`([A-Z_]+)` \(", paragraph)
    assert len(oms) == 5 and not set(oms) & {c.name for c in OmsErrorCode}
