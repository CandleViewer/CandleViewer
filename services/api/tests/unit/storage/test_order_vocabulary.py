"""The persisted order vocabulary (E29-T03 #847, slice 2; main-orchestrator's ruling 2): the B1
chart's `lifecycle` states, `LifecycleState` and the 24-internal-schemas.md Sec.8.2 mapping onto
`order_state`, held to the chart, the doc and the database types."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, get_args

from candleviewer.db import models
from candleviewer.storage.repositories.orders import (
    OPEN_STATES,
    ORDER_STATE_OF,
    LifecycleState,
    OrderState,
)

_REPO = Path(__file__).resolve().parents[5]
_CHART = _REPO / "services/api/candleviewer/statechart/machines/B01.order.machine.json"
_SECTION = "### 8.2 Order state machine"  # of 24-internal-schemas.md


def _chart() -> dict[str, Any]:
    machine = json.loads(_CHART.read_text(encoding="utf-8"))
    lifecycle: dict[str, Any] = machine["states"]["lifecycle"]["states"]
    return lifecycle


def _doc_table() -> list[tuple[str, str]]:
    """The rows of the "Persisted state" table of 24 Sec.8.2, in order."""
    doc = (_REPO / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8")
    section = doc.split(_SECTION, 1)[1].split("**Persisted state", 1)[1].split("\n### ", 1)[0]
    return re.findall(r"^\| `(\w+)` +\| `(\w+)` +\|$", section, re.MULTILINE)


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
