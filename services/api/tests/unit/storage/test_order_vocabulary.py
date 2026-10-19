"""The persisted order vocabulary (E29-T03 #847, slice 2; main-orchestrator's ruling 2): the B1
chart's `lifecycle` states, `LifecycleState`, the 24-internal-schemas.md Sec.8.2 mapping onto
`order_state`, and the regenerated REST and WS enums, held to the database types; the contract's
pointers to this slice, which name no revision; and Sec.8.6's exchange-boundary `OmsErrorCode`,
held to the code."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

import pytest
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
_CONTRACTS = (_REPO / "docs/plan/22-api-openapi.yaml", _REPO / "docs/plan/23-ws-protocol.md")


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
    """`list_open` sees every order the chart has not ended, except in three states: `draft`, never
    written, and `untracked` and `held`, which B1 treats as orders the OMS does not own (INV-B1-n;
    SR-E29-03 and SR-E29-12). An untracked order is never managed (S9, `ix_orders_untracked`), and
    only the operator's `OPERATOR_RESOLVED` leaves `held` (INV-B1-m)."""
    chart = _chart()
    ended = {name for name, node in chart.items() if node.get("type") == "final"}
    left_out = {"draft", "untracked", "held"}
    live = [s for s in get_args(LifecycleState) if s not in ended | left_out]
    assert OPEN_STATES == {ORDER_STATE_OF[s] for s in live}


def test_the_regenerated_rest_and_ws_enums_are_the_database_enums() -> None:
    """The contract's vocabulary against the database types. That REST and WS agree, that
    `lifecycle_state` is optional and nullable and that each enum is open-ended for readers is
    the contract test's: tests/contract/test_order_vocabulary_contract.py."""
    frame = json.loads(_WS.read_text(encoding="utf-8"))["schemas"]["cv://ws/v1/orders.schema.json"]
    order = frame["properties"]["orders"]["items"]["properties"]
    states, lifecycle = set(models.ORDER_STATES), set(models.ORDER_LIFECYCLE_STATES)
    assert _values(rest.Order, "state") == states
    assert set(order["state"]["enum"]) == states
    assert _values(rest.Order, "lifecycle_state") == lifecycle
    assert set(order["lifecycle_state"]["enum"]) - {None} == lifecycle
    assert _values(rest.OrderEvent, "kind") == set(models.ORDER_EVENT_KINDS)


@pytest.mark.parametrize("contract", _CONTRACTS, ids=lambda path: path.name)
def test_the_contract_names_no_revision_of_the_implementation(contract: Path) -> None:
    """22 and 23 say 24 Sec.8.2's mapping and the type `order_lifecycle_state` are "added by
    E29-T03's implementation" and leave the revision to 21 Sec.9.4 and 24 Sec.8.2. A migration is
    re-parented onto a newer head when another lands first (C-5.3), which changes its number, so a
    revision named in the contract would then be one that does not exist."""
    assert re.findall(r"\d{4}_order_vocabulary", contract.read_text(encoding="utf-8")) == []


def test_section_8_6_lists_the_exchange_enum_and_keeps_the_oms_codes_apart() -> None:
    """`exchange/base/errors.py` is Sec.8.6's `OmsErrorCode` block verbatim; the five codes the OMS
    raises itself stand beside the block, and none is a member of the exchange-boundary enum."""
    doc = _SCHEMAS.read_text(encoding="utf-8").split("class OmsErrorCode(StrEnum):", 1)[1]
    block, after = doc.split("```", 1)
    assert re.findall(r'^    (\w+) = "\1"', block, re.MULTILINE) == [c.name for c in OmsErrorCode]
    paragraph = after.split("**OMS codes (E29-T03).**", 1)[1].split("\n", 1)[0]
    oms = re.findall(r"`([A-Z_]+)` \(", paragraph)
    assert len(oms) == 5 and not set(oms) & {c.name for c in OmsErrorCode}
