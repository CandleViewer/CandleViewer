"""E35-T09 (#5000): `rules.fired` and `rules.blocked` are registered and keyed (24 §15.5).

Each is keyed by the action's `dedupe_key`, in a namespace of its own (`writer.KEYED_ACTIONS`), so
a retried write of either lands once. Written through the executor's adapter and the real writer,
the record names the rule as its actor, and its `after_state` keeps every id past the redactor."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from pathlib import Path

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.writer import KEYED_ACTIONS, AuditWriter, keyed_record_id
from candleviewer.rules.executor.ports import ActionAuditFields
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
    assert "and are registered (E35-T09):" in vocabulary
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
