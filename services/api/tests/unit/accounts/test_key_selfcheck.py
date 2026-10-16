"""E27-T03 slice 2a1 (#836): the stored-key self-check's verdicts and what each one writes.

Facts come from the documented-shape replies in `tests/fixtures/key_verification/` (its README
names source, date, env and redaction), parsed by the adapter parsers. `World` is the store, audit
sink and calls at once, around the real `ReadOnlyGate`: one event log keeps the order (latch,
audit, write), and the audit sink refuses what `AuditWriter.emit` refuses (#2144). The clock is
fixed and a hang is cut by a zero timeout, so nothing waits on wall time or the network.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.accounts.selfcheck import FAILED, KEY_DEADLINE_S, KeySelfCheck
from candleviewer.accounts.verification import KeyRefused, Refusal, VerificationPolicy
from candleviewer.audit.actions import validate_action
from candleviewer.audit.models import AuditEmission
from candleviewer.audit.writer import AuditWriter
from candleviewer.exchange.bybit.key_info import (
    ApiKeyFacts,
    ProbeFacts,
    parse_key_info,
    parse_probe,
)
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.storage.repositories.accounts import (
    ExchangeAccountRow,
    SelfCheckTargetRow,
    VerifiedKey,
)
from tests.unit.accounts._permission_cases import BASE

FIXTURES = Path(__file__).parents[2] / "fixtures" / "key_verification"
NOW = datetime(2026, 10, 15, 9, tzinfo=UTC)
T = 1792054800000  # the fixtures' exchange clock, NOW in epoch ms
EGRESS = "203.0.113.7"
WITHDRAW = {**BASE, "Wallet": ["Withdraw"]}
KEY, ACCT, KEY2, ACCT2 = UUID(int=11), UUID(int=1), UUID(int=12), UUID(int=2)
HOUR = timedelta(hours=1)
KEK = "secrets.kek_unavailable"
TESTED = "account.tested"
RECORD = {"actor_label", "object_kind", "object_id", "env", "after_state"}
FAILURE = {"outcome", "severity", "reason"}
FACTS = {"fetched_at", "uid", "readOnly", "permissions", "expiredAt", "uta", "withdraw_enabled"}
CODES = {"warnings", "failures"}
WITHDRAW_FAILURE = [("latch", FAILED), ("audit", TESTED), ("error", KEY)]


def load(name: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return body


def facts(**result: Any) -> ApiKeyFacts:
    body = copy.deepcopy(load("key_info_trade.json"))
    body["result"].update(result)
    return parse_key_info(body)


def probed() -> ProbeFacts:
    return parse_probe(load("wallet_balance.json"), sent_at_ms=T - 50, received_at_ms=T + 50)


def target(
    env: str = "demo", *, key: UUID = KEY, acct: UUID = ACCT, read_only: bool = False
) -> SelfCheckTargetRow:
    account = ExchangeAccountRow(
        acct, "bybit", env, "main", "1000001", None, "fx", "accent.neutral", True, True,
        "one_way", "cross", "UNIFIED", "USDT", None, None, 5, None, NOW, NOW, None,
    )  # fmt: skip
    return SelfCheckTargetRow(key, read_only, NOW - HOUR / 2, account)


class World:
    def __init__(
        self, *rows: SelfCheckTargetRow, info: object = None, timeout_s: float = 10.0,
        key_deadline_s: float = KEY_DEADLINE_S,
    ) -> None:  # fmt: skip
        self.rows, self.now, self.fail_audit, self.written = list(rows), NOW, False, True
        self.close_error: Exception | None = None
        self.hang: set[str] = set()
        self.info = facts() if info is None else info
        self.infos: dict[UUID, object] = {}
        self.seen = probed()
        self.events: list[tuple[Any, ...]] = []
        self.built: list[tuple[UUID, str]] = []
        self.gate = ReadOnlyGate()
        self.gate.subscribe(lambda _on, code, _text: self.events.append(("latch", code)))
        self.check = KeySelfCheck(
            self, self.calls, gate=self.gate, audit=self, env="demo", clock=lambda: self.now,
            policy=VerificationPolicy(egress_ip=EGRESS), timeout_s=timeout_s,
            key_deadline_s=key_deadline_s,
        )  # fmt: skip

    async def _io(self, name: str) -> None:
        if name in self.hang:
            await asyncio.Event().wait()

    async def run(self) -> None:
        """One pass. The outer bound makes a lost inner one fail the test, not hang the suite."""
        async with asyncio.timeout(1.0):
            await self.check.run_once()

    async def targets(self) -> tuple[SelfCheckTargetRow, ...]:
        await self._io("targets")
        return tuple(self.rows)

    async def record_pass(self, key_id: UUID, verified: VerifiedKey) -> bool:
        await self._io("record_pass")
        self.events.append(("pass", key_id, verified))
        return self.written

    async def record_error(self, key_id: UUID, *, code: str, at: datetime) -> bool:
        await self._io("record_error")
        self.events.append(("error", key_id, code))
        return True

    async def emit(self, action: str, **fields: Any) -> None:
        validate_action(action)  # what `AuditWriter.emit` refuses, the double refuses
        inspect.signature(AuditWriter.emit).bind(None, action, **fields)
        AuditEmission(record_id=UUID(int=0), action=action, event_ts=NOW, **fields)
        await self._io("emit")
        if self.fail_audit:
            raise RuntimeError("audit unavailable")
        self.events.append(("audit", action, fields))

    def calls(self, key_id: UUID, uid: str) -> World:
        self.built.append((key_id, uid))
        return self

    async def _answer(self, name: str, outcome: object) -> Any:
        self.events.append((name,))
        await self._io(name)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def key_info(self) -> Any:
        return await self._answer("key_info", self.infos.get(self.built[-1][0], self.info))

    async def probe(self) -> Any:
        return await self._answer("probe", self.seen)

    async def aclose(self) -> None:
        self.events.append(("aclose",))
        await self._io("aclose")
        if self.close_error is not None:
            raise self.close_error

    def kinds(self) -> list[tuple[Any, ...]]:
        return [e[:2] for e in self.events if e[0] not in ("key_info", "probe", "aclose")]

    def of(self, kind: str) -> list[tuple[Any, ...]]:
        return [e for e in self.events if e[0] == kind]

    def audit(self, action: str) -> dict[str, Any]:
        (fields,) = [e[2] for e in self.of("audit") if e[1] == action]
        return cast(dict[str, Any], fields)


async def test_pass_audits_then_refreshes_the_verified_columns() -> None:
    w = World(target())
    await w.run()
    assert w.kinds() == [("audit", TESTED), ("pass", KEY)]
    audit = w.audit(TESTED)
    assert (audit["actor_label"], audit["object_kind"], audit["object_id"], audit["env"]) == (
        "system:key-selfcheck", "api_key", str(KEY), "demo",
    )  # fmt: skip
    snapshot = {
        "fetched_at": NOW.isoformat(),
        "uid": "1000001",
        "readOnly": 0,
        "permissions": dict(facts().permissions),
        "ips": [EGRESS],
        "expiredAt": "2027-04-13T00:00:00+00:00",
    }
    shown = {k: v for k, v in snapshot.items() if k != "ips"}  # the whitelist stays in api_keys
    assert "outcome" not in audit and audit["after_state"] == {
        **shown, "uta": True, "withdraw_enabled": False, "warnings": [], "failures": [],
    }  # fmt: skip
    assert w.of("pass") == [
        ("pass", KEY, VerifiedKey(snapshot, True, False, (EGRESS,), facts().expires_at, NOW))
    ]
    check = w.check.results[KEY]
    assert (check.outcome, check.code, check.last_pass_at, w.built) == (
        "passed", None, NOW, [(KEY, "1000001")],
    )  # fmt: skip


async def test_a_read_only_stored_key_passes_as_read_only() -> None:
    w = World(target(read_only=True), info=facts(readOnly=1))
    await w.run()
    ((_, _, written),) = w.of("pass")
    assert (written.can_trade, written.read_only) == (False, True)


async def test_stored_key_with_withdraw_latches_first_and_records_the_rule() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    await w.run()
    assert ("probe",) not in w.events  # the fund-right gate runs before any second signed call
    assert w.kinds() == WITHDRAW_FAILURE
    tested = w.audit(TESTED)
    assert (tested["outcome"], tested["severity"], tested["reason"]) == (
        "failure", "critical", "key_withdraw_permission",
    )  # fmt: skip
    assert tested["after_state"]["withdraw_enabled"] is True
    assert w.of("error") == [("error", KEY, "key_withdraw_permission")]


@pytest.mark.parametrize(
    ("info", "rule"),
    [
        (facts(ips=["198.51.100.9"]), "key_ip_whitelist_mismatch"),
        (facts(ips=[]), "key_ip_whitelist_missing"),
        (KeyRefused(Refusal.UNKNOWN_KEY, 10003), "key_wrong_environment"),
    ],
    ids=["ip-mismatch", "no-whitelist", "wrong-environment-10003"],
)
async def test_verdict_failure_latches_and_records_the_rule(info: object, rule: str) -> None:
    w = World(target(), info=info)
    await w.run()
    assert [k for k in w.kinds() if k[0] != "audit"] == [("latch", FAILED), ("error", KEY)]
    check = w.check.results[KEY]
    assert (check.outcome, check.code, check.egress_ip) == ("failed", rule, EGRESS)


@pytest.mark.parametrize(
    ("info", "fields", "state"),
    [
        (None, RECORD, FACTS | CODES),
        (facts(ips=["198.51.100.9"]), RECORD | FAILURE, FACTS | CODES),
        (KeyRefused(Refusal.UNKNOWN_KEY, 10003), RECORD | FAILURE, CODES),
    ],
    ids=["pass", "ip-mismatch", "refusal"],
)
async def test_an_audit_record_holds_codes_and_permissions_never_an_ip(
    info: object, fields: set[str], state: set[str]
) -> None:
    w = World(target(), info=info)
    await w.run()
    record = w.audit(TESTED)
    assert (set(record), set(record["after_state"])) == (fields, state)
    text = json.dumps(w.of("audit"))  # the whitelist and egress IP stay in api_keys and the result
    assert EGRESS not in text and "198.51.100.9" not in text


async def test_ip_mismatch_keeps_the_egress_ip_for_copying_into_the_whitelist() -> None:
    w = World(target(), info=facts(ips=["198.51.100.9"]))
    await w.run()
    assert EGRESS in w.check.results[KEY].result.failures[0].message


async def test_every_key_of_a_pass_is_judged_and_recorded_on_its_own() -> None:
    w = World(target(), target(key=KEY2, acct=ACCT2))
    w.infos[KEY2] = facts(permissions=WITHDRAW)
    await w.run()
    outcomes = {key: check.outcome for key, check in w.check.results.items()}
    assert (outcomes, w.of("pass")[0][1]) == ({KEY: "passed", KEY2: "failed"}, KEY)
    assert w.of("error") == [("error", KEY2, "key_withdraw_permission")]


async def test_a_key_that_leaves_the_list_leaves_the_results() -> None:
    w = World(target(), target(key=KEY2, acct=ACCT2))
    await w.run()
    del w.rows[1]
    await w.run()
    assert set(w.check.results) == {KEY}


async def test_a_pass_clears_a_standing_failure() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    await w.run()
    w.info = facts()
    await w.run()
    assert (w.check.results[KEY].outcome, w.check.results[KEY].code) == ("passed", None)


async def test_a_refused_audit_refuses_the_pass_write_and_keeps_the_last_pass() -> None:
    w = World(target())
    w.fail_audit = True
    await w.run()
    assert (w.kinds(), w.check.results[KEY].last_pass_at) == ([], NOW - HOUR / 2)


async def test_a_pass_that_changes_no_row_is_logged_and_keeps_the_last_pass() -> None:
    w = World(target())
    w.written = False
    with capture_logs() as logs:
        await w.run()
    assert w.check.results[KEY].last_pass_at == NOW - HOUR / 2
    assert [log["event"] for log in logs if log["log_level"] == "warning"] == [
        "key_selfcheck_record_unchanged"
    ]


async def test_a_kek_latch_is_never_replaced_by_a_failing_key() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    w.gate.latch(reason_code=KEK, reason_text="kek")
    await w.run()
    assert (w.gate.reason_code, w.of("latch")) == (KEK, [("latch", KEK)])


async def test_a_repeated_failure_notifies_the_gate_listeners_once() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    await w.run()
    await w.run()
    assert w.of("latch") == [("latch", FAILED)]


@pytest.mark.parametrize(
    ("info", "expected"),
    [(None, [("audit", TESTED), ("pass", KEY)]), (facts(permissions=WITHDRAW), WITHDRAW_FAILURE)],
    ids=["pass", "withdraw"],
)
@pytest.mark.parametrize(
    ("hang", "error"),
    [(set(), RuntimeError("close failed")), ({"aclose"}, None)],
    ids=["raises", "hangs"],
)
async def test_a_failing_close_never_changes_the_verdict(
    info: object, expected: list[tuple[Any, ...]], hang: set[str], error: Exception | None
) -> None:
    w = World(target(), info=info, timeout_s=0.0)
    w.hang, w.close_error = hang, error
    await w.run()
    assert (w.kinds(), w.of("aclose")) == (expected, [("aclose",)])


@pytest.mark.parametrize("step", ["emit", "record_pass"])
async def test_a_hanging_pass_write_is_cut_and_keeps_the_last_pass(step: str) -> None:
    w = World(target(), timeout_s=0.0)
    w.hang.add(step)
    await w.run()
    assert (w.of("pass"), w.check.results[KEY].last_pass_at) == ([], NOW - HOUR / 2)


@pytest.mark.parametrize("step", ["emit", "record_error"])
async def test_a_hanging_write_never_undoes_the_failure_latch(step: str) -> None:
    w = World(target(), info=facts(permissions=WITHDRAW), timeout_s=0.0)
    w.hang.add(step)
    await w.run()
    assert (w.gate.reason_code, w.check.results[KEY].outcome) == (FAILED, "failed")


async def test_a_key_of_another_environment_is_never_checked() -> None:
    w = World(target(env="live"))
    await w.run()
    assert (w.built, w.events, w.check.results) == ([], [], {})


async def test_a_hanging_key_list_is_cut_by_its_timeout() -> None:
    w = World(target(), timeout_s=0.0)
    w.hang.add("targets")
    async with asyncio.timeout(1.0):  # a lost bound fails here instead of hanging the suite
        with pytest.raises(TimeoutError):
            await w.check.run_once()


@pytest.mark.parametrize("call", ["key_info", "probe"])
async def test_a_hanging_signed_call_is_cut_by_the_key_deadline(call: str) -> None:
    w = World(target(), key_deadline_s=0.0)
    w.hang.add(call)
    async with asyncio.timeout(1.0):  # a lost bound fails here instead of hanging the suite
        with pytest.raises(TimeoutError):
            await w.check.run_once()
    assert (w.events[-1], w.of("pass")) == (("aclose",), [])
