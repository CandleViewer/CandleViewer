"""E35-T09 (#5000) slice 2c: the executor's result types against their contract (24 §11.9).

`ActionResult` and `SimulatedAction` field for field as §11.9 writes them; `blocked_by` one closed
set, equal to §11.9's list, to `20-architecture.md` §12.1's `reason` values and to the metric's
`max_series` (BQ-5 of #863); one plain `blocked_detail` sentence per value (BQ-12); and every IR
trigger type mapped into the run row's `rr_trigger` CHECK (`0013_rules`, BQ-3).
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

import candleviewer
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.rules.executor.ports import TRIGGER_REASON, trigger_reason
from candleviewer.rules.executor.results import (
    BLOCKED_BY,
    BLOCKED_DETAIL,
    OUTCOMES,
    ROW_UNREAD,
    RULE_LIMITS,
    ActionResult,
    BlockedBy,
    Outcome,
    SimulatedAction,
    blocked_result,
    skipped_result,
)
from candleviewer.rules.ir.models import TriggerType

_PLAN = Path(__file__).resolve().parents[4] / "docs" / "plan"
_SECTION = (_PLAN / "24-internal-schemas.md").read_text(encoding="utf-8")
_SECTION = _SECTION.split("\n### 11.9 ", 1)[1].split("\n## 12. ", 1)[0]
_MIGRATION = Path(candleviewer.__file__).parent / "migrations" / "versions" / "0013_rules.py"
#: Words `blocked_detail` never uses (E35-D03's register; public-safe copy).
_BANNED = ("previously", "leak", "could", "bypass", "exposed", "allowed")


def _class_fields(name: str) -> list[str]:
    body = _SECTION.split(f"class {name}(BaseModel):", 1)[1].split("\n\n", 1)[0]
    return re.findall(r"^    (\w+):", body, flags=re.MULTILINE)


def _ids(**over: Any) -> dict[str, Any]:
    base = {"node_id": "a1", "action_type": "place_order", "account_id": None}
    return base | {"resolved_accounts": (), "dedupe_key": "0" * 64} | over


def test_action_result_and_simulated_action_match_24_11_9() -> None:
    assert list(ActionResult.model_fields) == _class_fields("ActionResult")
    assert list(SimulatedAction.model_fields) == _class_fields("SimulatedAction")
    declared = re.search(r"outcome: Literal\[([^\]]*)\]", _SECTION)
    assert declared is not None and tuple(re.findall(r'"(\w+)"', declared[1])) == OUTCOMES
    account = uuid.UUID(int=3)
    ok = ActionResult(**_ids(account_id=account, resolved_accounts=(account,)), outcome="ok",
                      order_id=uuid.UUID(int=4), duration_us=0)  # fmt: skip
    assert ok.model_dump(mode="json")["order_id"] == str(uuid.UUID(int=4))
    named: tuple[tuple[Outcome, BlockedBy | None], ...] = (
        ("blocked", "cap"), ("skipped", "mode_changed"), ("skipped", None),
    )  # fmt: skip
    for outcome, reason in named:
        ActionResult(**_ids(), outcome=outcome, blocked_by=reason, duration_us=1)
    refused: tuple[tuple[Outcome, BlockedBy | None], ...] = (
        ("blocked", None), ("blocked", "mode_changed"), ("skipped", "cap"), ("ok", "cap"),
        ("failed", "scope"), ("unknown", "backpressure"), ("simulated", "unavailable"),
    )  # fmt: skip
    for outcome, reason in refused:
        with pytest.raises(ValidationError, match="blocked_by"):
            ActionResult(**_ids(), outcome=outcome, blocked_by=reason, duration_us=1)
    for bad in ({"duration_us": -1}, {"dedupe_key": "A" * 64}, {"extra": 1}, {"outcome": "done"}):
        with pytest.raises(ValidationError):
            ActionResult(**(_ids(outcome="ok", duration_us=0) | bad))
    assert (ActionResult.model_config["frozen"], ActionResult.model_config["extra"]) == (
        True, "forbid",
    )  # fmt: skip
    simulated = SimulatedAction(action_type="place_order", params={}, would_target_accounts=())
    assert simulated.blocked_by is None and simulated.estimated_qty is None


def test_blocked_by_set_equals_the_metric_reason_labels() -> None:
    literal = re.search(r"BlockedBy = Literal\[([^\]]*)\]", _SECTION)
    assert literal is not None and tuple(re.findall(r'"(\w+)"', literal[1])) == BLOCKED_BY
    listed = _SECTION.split("`blocked_by` is one closed set", 1)[1].split("\n\n", 2)[1]
    assert tuple(re.findall(r"^- `(\w+)`:", listed, flags=re.MULTILINE)) == BLOCKED_BY
    doc_20 = (_PLAN / "20-architecture.md").read_text(encoding="utf-8")
    row = next(r for r in doc_20.splitlines() if "`rule_actions_blocked_total{reason}`" in r)
    words = row.split("word for word (", 1)[1].split(")", 1)[0]
    assert tuple(re.findall(r"`(\w+)`", words)) == BLOCKED_BY
    (spec,) = (s for s in CATALOGUE if s.name == "rule_actions_blocked_total")
    assert spec.labels == ("reason",) and spec.max_series == len(BLOCKED_BY) == 16


def test_blocked_detail_is_one_plain_sentence_per_reason() -> None:
    """BQ-12: E35-D03's register, at most 80 characters, one sentence ending in a full stop,
    naming the condition and never data (no digit, id, account or figure; C-12.6). E35-T10: `cap`
    has one more per rule limit it names, each PROPOSED as the others are."""
    assert set(BLOCKED_DETAIL) == {*BLOCKED_BY, ROW_UNREAD, *RULE_LIMITS}
    for reason, sentence in BLOCKED_DETAIL.items():
        assert sentence.startswith("Not done — ") and len(sentence) <= 80, reason
        assert sentence.endswith(".") and sentence.count(".") == 1, reason
        assert not re.search(r"[0-9!?;]|\. ", sentence), reason
        assert not any(word in sentence.lower() for word in _BANNED), reason
    assert len(set(BLOCKED_DETAIL.values())) == len(BLOCKED_DETAIL)
    refusal = blocked_result(**_ids(), reason="native_sl")
    assert (refusal.outcome, refusal.blocked_detail) == ("blocked", BLOCKED_DETAIL["native_sl"])
    unread = skipped_result(**_ids(), reason="mode_changed", unread=True)
    assert (unread.blocked_by, unread.blocked_detail) == (
        "mode_changed",
        BLOCKED_DETAIL[ROW_UNREAD],
    )
    after_a_stop = skipped_result(**_ids())
    assert (after_a_stop.blocked_by, after_a_stop.blocked_detail) == (None, None)
    with pytest.raises(ValueError):
        skipped_result(**_ids(), unread=True)  # an unread row is a `mode_changed` skip only


def test_trigger_reasons_map_every_trigger_type_into_the_runs_check() -> None:
    check = re.search(
        r"rr_trigger\s+CHECK \(trigger_reason IN\s*\(([^)]*)\)", _MIGRATION.read_text()
    )
    assert check is not None
    allowed = set(re.findall(r"'(\w+)'", check[1]))
    assert set(TRIGGER_REASON) == set(get_args(TriggerType)) and len(TRIGGER_REASON) == 13
    assert set(TRIGGER_REASON.values()) <= allowed
    assert TRIGGER_REASON == {
        "on_bar_close": "bar_close", "on_order_fill": "fill",
        "on_position_open": "position_change", "on_position_close": "position_change",
        "on_position_update": "position_change", "on_timer": "schedule",
        "on_schedule": "schedule", "on_price_update": "tick", "on_metric_change": "tick",
        "on_signal": "tick", "pre_trade_check": "tick", "on_book_update": "tick",
        "on_liquidation": "tick",
    }  # fmt: skip
    assert trigger_reason("on_order_fill") == "fill" and trigger_reason("not_a_trigger") == "tick"
