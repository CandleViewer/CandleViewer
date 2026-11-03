"""E35-T09 (#5000): `rules.fired` and `rules.blocked` are registered and keyed (24 §15.5).

Each is keyed by the action's `dedupe_key`, in a namespace of its own (`writer.KEYED_ACTIONS`), so
a retried write of either lands once. Written through the executor's adapter and the real writer,
the record names the rule as its actor, and its `after_state` keeps every id past the redactor."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.writer import KEYED_ACTIONS, AuditWriter, keyed_record_id
from candleviewer.rules.executor.ports import ActionAuditFields, Loosening
from candleviewer.rules_oms_wiring import RuleActionAudit
from tests.unit.audit.audit_fakes import FakeAuditRepository, FakeClock

_DOC = Path(__file__).resolve().parents[5] / "docs" / "plan" / "24-internal-schemas.md"
RULE, OWNER, ARMER = (str(uuid.UUID(int=n)) for n in (7, 0xA1, 0xA2))
FIELDS = ActionAuditFields(
    rule_id=RULE, version=3, ir_hash="ab" * 32, run_id=uuid.UUID(int=8), node_id="a2",
    action_type="place_order", scope_instance="BTCUSDT@*", account_id=uuid.UUID(int=0xB1),
    owner=uuid.UUID(OWNER), armed_by=ARMER, dedupe_key="cd" * 32,
)  # fmt: skip


async def test_rules_fired_and_blocked_are_registered_and_keyed(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    assert {"rules.fired", "rules.blocked"} <= AUDIT_ACTIONS
    assert {"rules.fired", "rules.blocked"} <= set(KEYED_ACTIONS)
    assert KEYED_ACTIONS["rules.fired"] != KEYED_ACTIONS["rules.blocked"]
    section = _DOC.read_text("utf-8").split("\n### 15.5 ", 1)[1].split("\n### 15.6 ", 1)[0]
    vocabulary = " ".join(section.split())
    assert "are registered as `rules.fired` and `rules.blocked` (E35-T09)," in vocabulary
    assert "are not registered yet: E35-T09" not in vocabulary
    writer = AuditWriter(repo, str(tmp_path / "audit.wal"), clock=clock, sleep=repo.retry_sleep)
    await writer.start()
    audit = RuleActionAudit(writer)
    for _ in range(2):  # a retried write of each lands on its first row
        await audit.fired(FIELDS)
        await audit.blocked(replace(FIELDS, blocked_by="kill_switch"))
    await writer.flush(5)
    await writer.stop(1)
    fired, blocked = repo.rows
    assert (fired["action"], blocked["action"]) == ("rules.fired", "rules.blocked")
    assert fired["record_id"] == str(keyed_record_id("rules.fired", FIELDS.dedupe_key))
    assert blocked["record_id"] == str(keyed_record_id("rules.blocked", FIELDS.dedupe_key))
    assert (fired["outcome"], fired["reason"]) == ("success", None)
    assert (blocked["outcome"], blocked["reason"]) == ("denied", "kill_switch")
    for row in (fired, blocked):
        assert (row["actor_label"], row["actor_user_id"]) == (f"rule:{RULE}@v3", None)
        assert (row["object_kind"], row["object_id"], row["request_id"]) == ("rule", RULE, None)
        state = json.loads(row["after_state"])
        assert "<redacted" not in row["after_state"]  # every id survives the writer's redactor
        assert (state["ir_sha256"], state["dedupe_sha256"]) == (FIELDS.ir_hash, FIELDS.dedupe_key)
        assert (state["owner_user_id"], state["armed_by_user_id"]) == (OWNER, ARMER)


async def test_a_rules_loosen_refusal_is_registered_keyed_critical_and_names_the_stops(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    """E35-T12 (24 §15.5, BQ-3): `sl.loosen_refused` is registered and keyed in a namespace of its
    own, so a retried refusal lands once; written through the adapter and the real writer, it is
    the rule's (no `actor_user_id`), `denied` at `critical` with the reason `native_sl`, the order
    its object, and the stop before and after in `after_state` as plain decimal text. Only a
    `native_sl` refusal takes one."""
    assert "sl.loosen_refused" in AUDIT_ACTIONS and "sl.loosen_refused" in KEYED_ACTIONS
    assert KEYED_ACTIONS["sl.loosen_refused"] not in {
        ns for a, ns in KEYED_ACTIONS.items() if a != "sl.loosen_refused"
    }
    order = uuid.UUID(int=0xD1)
    loosening = Loosening(
        order_id=order, symbol="BTCUSDT", before=Decimal("58000"), after=Decimal("57000.50")
    )
    refused = replace(FIELDS, action_type="modify_stop_loss", blocked_by="native_sl")
    writer = AuditWriter(repo, str(tmp_path / "audit.wal"), clock=clock, sleep=repo.retry_sleep)
    await writer.start()
    audit = RuleActionAudit(writer)
    for _ in range(2):
        await audit.loosen_refused(refused, loosening)
    with pytest.raises(ValueError, match="native_sl"):
        await audit.loosen_refused(replace(refused, blocked_by="permission"), loosening)
    await writer.flush(5)
    await writer.stop(1)
    [row] = repo.rows
    assert row["record_id"] == str(keyed_record_id("sl.loosen_refused", FIELDS.dedupe_key))
    assert (row["action"], row["outcome"], row["severity"], row["reason"]) == (
        "sl.loosen_refused", "denied", "critical", "native_sl",
    )  # fmt: skip
    assert (row["actor_label"], row["actor_user_id"]) == (f"rule:{RULE}@v3", None)
    assert (row["object_kind"], row["object_id"]) == ("order", str(order))
    state = json.loads(row["after_state"])
    assert (state["stop_before"], state["stop_after"], state["symbol"]) == (
        "58000", "57000.5", "BTCUSDT",
    )  # fmt: skip
    assert (state["actor_type"], state["blocked_by"], state["order_id"]) == (
        "rule", "native_sl", str(order),
    )  # fmt: skip


async def test_a_loosening_that_names_no_order_keeps_the_rule_as_its_object(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    """`only_tighten: false` names no order (24 §15.5): the record keeps the rule as its object,
    and the order and the stops it names are `None`, none being known."""
    refused = replace(FIELDS, action_type="tighten_stop", blocked_by="native_sl")
    writer = AuditWriter(repo, str(tmp_path / "audit.wal"), clock=clock, sleep=repo.retry_sleep)
    await writer.start()
    await RuleActionAudit(writer).loosen_refused(refused, Loosening(symbol="BTCUSDT"))
    await writer.flush(5)
    await writer.stop(1)
    [row] = repo.rows
    assert (row["action"], row["object_kind"], row["object_id"]) == (
        "sl.loosen_refused", "rule", RULE,
    )  # fmt: skip
    state = json.loads(row["after_state"])
    assert (state["order_id"], state["stop_before"], state["stop_after"], state["symbol"]) == (
        None, None, None, "BTCUSDT",
    )  # fmt: skip
