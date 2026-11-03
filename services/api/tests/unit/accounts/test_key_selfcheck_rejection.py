"""#4243 (24 §8.4 "A refused credential"): the durable reaction to a credential the venue refused,
through the stored-key self-check's own path. The account is disarmed first, with the refusal as
its code and its owed `account.disabled_by_policy`; then its usable keys are marked failed with the
rule the self-check gives the same refusal (a write-ahead `account.tested`, then the code), and the
failing-key gauge is published. `Store` keeps what it is written, the conditional error writes
included, so a second job and key standing built over it are a restart. A settable clock,
fixture-shaped key facts, no network and no sleep."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.accounts.key_standing import KeyStandings
from candleviewer.accounts.order_gate import DisabledReason, KeyStanding
from candleviewer.accounts.selfcheck import (
    FAILED,
    MAX_PENDING,
    MAX_REJECTIONS,
    REJECTION_TASK,
    KeySelfCheck,
)
from candleviewer.accounts.verification import Refusal, VerificationInconclusive, VerificationPolicy
from candleviewer.audit.actions import validate_action
from candleviewer.audit.models import AuditEmission
from candleviewer.audit.writer import AuditWriter
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.oms_wiring import CredentialRejectionsBinding
from candleviewer.storage.repositories.accounts import (
    InvalidKey,
    PolicyDisarm,
    SelfCheckTargetRow,
    VerifiedKey,
)
from tests.unit.accounts.test_key_selfcheck import (
    ACCT,
    ACCT2,
    EGRESS,
    KEY,
    KEY2,
    NOW,
    facts,
    probed,
    target,
)

TESTED, DISABLED = "account.tested", "account.disabled_by_policy"
JOB = "system:key-selfcheck"
RULES = {
    Refusal.UNKNOWN_KEY: "key_wrong_environment",
    Refusal.KEY_EXPIRED: "key_expired",
    Refusal.PERMISSION_DENIED: "key_missing_scopes",
    Refusal.IP_NOT_ALLOWED: "key_ip_whitelist_mismatch",
}
SECOND = timedelta(seconds=1)


class Store:
    """The self-check's store and audit sink, keeping what is written: rows by key, each key's
    `last_error_at`, the policy-disarm columns by account, and every write in order. An error
    write, and a pass's clearing of it, keep an error stored after the check began
    (`key_selfcheck_sqlalchemy._PASS`, `_ERROR`)."""

    def __init__(self, *rows: SelfCheckTargetRow) -> None:
        self.rows = {row.key_id: row for row in rows}
        self.error_at: dict[UUID, datetime] = {}
        self.disarms: dict[UUID, list[Any]] = {}
        self.events: list[tuple[Any, ...]] = []
        self.refused: set[str] = set()  # audit actions the sink refuses
        self.hang: set[str] = set()  # audit actions whose emit never answers
        #: audit actions whose emit waits until the test opens the event (`entered` set on entry)
        self.gates: dict[str, tuple[asyncio.Event, asyncio.Event]] = {}
        self.hang_targets = self.fail_targets = False

    async def targets(self) -> tuple[SelfCheckTargetRow, ...]:
        if self.hang_targets:
            await asyncio.Event().wait()
        if self.fail_targets:
            raise RuntimeError("the key list is unreadable")
        return tuple(self.rows.values())

    async def record_pass(self, key_id: UUID, verified: VerifiedKey) -> bool:
        self.events.append(("pass", key_id))
        row, newer = self.rows[key_id], self.error_at.get(key_id)
        if newer is not None and newer > verified.at:  # an error stored after the check began
            self.rows[key_id] = replace(row, verified_at=verified.at)
        else:
            self.error_at.pop(key_id, None)
            self.rows[key_id] = replace(row, verified_at=verified.at, last_error_code=None)
        return True

    async def record_error(self, key_id: UUID, *, code: str, at: datetime) -> bool:
        newer = self.error_at.get(key_id)
        if newer is not None and newer > at:
            self.events.append(("error_kept", key_id, code))
            return False
        self.events.append(("error", key_id, code))
        self.rows[key_id] = replace(self.rows[key_id], last_error_code=code)
        self.error_at[key_id] = at
        return True

    async def retire_key(self, key_id: UUID, *, status: str) -> bool:
        self.events.append(("retire", key_id, status))
        return True

    async def invalid_keys(self) -> tuple[InvalidKey, ...]:
        return ()

    async def disable_trading(self, account_id: UUID, *, code: str, at: datetime) -> bool:
        self.events.append(("disable", account_id, code))
        armed = False
        for key_id, row in self.rows.items():
            if row.account.id == account_id and row.account.trading_enabled:
                armed = True
                account = replace(row.account, trading_enabled=False)
                self.rows[key_id] = replace(row, account=account)
        if armed:
            self.disarms[account_id] = [code, at, None]
        return armed

    async def owed_disarms(self) -> tuple[PolicyDisarm, ...]:
        return tuple(
            PolicyDisarm(a, c, at) for a, (c, at, mark) in self.disarms.items() if not mark
        )

    async def mark_disarm_audited(self, disarm: PolicyDisarm, *, at: datetime) -> bool:
        self.events.append(("mark", disarm.account_id))
        row = self.disarms.get(disarm.account_id)
        if row is None or row[2] is not None:
            return False
        row[2] = at
        return True

    async def emit(self, action: str, **fields: Any) -> None:
        validate_action(action)  # what `AuditWriter.emit` refuses, the double refuses
        inspect.signature(AuditWriter.emit).bind(None, action, **fields)
        AuditEmission(record_id=UUID(int=0), action=action, event_ts=NOW, **fields)
        if action in self.hang:
            await asyncio.Event().wait()
        if (gate := self.gates.pop(action, None)) is not None:  # the first emit only
            gate[1].set()
            await gate[0].wait()
        if action in self.refused:
            raise RuntimeError("audit unavailable")
        self.events.append(("audit", action, fields))

    def audits(self, action: str) -> list[dict[str, Any]]:
        return [e[2] for e in self.events if e[0] == "audit" and e[1] == action]

    def kinds(self) -> list[tuple[Any, ...]]:
        return [e[:2] if e[0] == "audit" else e[:3] for e in self.events]


class Calls:
    """One key's signed calls: the fixture's facts, or no verdict; `hold`, when set, keeps the
    key-info call waiting until the test opens it (`entered` set once it waits)."""

    def __init__(self, verdict: bool, hold: asyncio.Event | None, entered: asyncio.Event) -> None:
        self.verdict, self.hold, self.entered = verdict, hold, entered

    async def key_info(self) -> Any:
        if self.hold is not None:
            self.entered.set()
            await self.hold.wait()
        if not self.verdict:
            raise VerificationInconclusive("rate_limited")
        return facts()

    async def probe(self) -> Any:
        return probed()

    async def aclose(self) -> None:
        return None


class Process:
    """One process over `store`: the job, its gate and the key standing that reads it."""

    def __init__(
        self, store: Store, *, verdict: bool = True, timeout_s: float = 1.0,
        key_deadline_s: float = 12.0,
    ) -> None:  # fmt: skip
        self.store, self.gate, self.metrics = store, ReadOnlyGate(), Metrics("demo")
        self.wall, self.entered = NOW, asyncio.Event()
        self.hold: asyncio.Event | None = None
        register_r0(self.metrics)
        self.check = KeySelfCheck(
            store, lambda _key, _uid: Calls(verdict, self.hold, self.entered), gate=self.gate,
            audit=store, policy=VerificationPolicy(egress_ip=EGRESS), env="demo",
            clock=self.now, metrics=self.metrics, timeout_s=timeout_s,
            key_deadline_s=key_deadline_s,
        )  # fmt: skip
        self.standings = KeyStandings(self.check, interval_s=3600.0, stale_after_s=60.0, clock=self)

    def now(self) -> datetime:  # the job's clock and the key standing's wall time
        return self.wall

    def monotonic(self) -> float:  # the key standing's age clock: fixed, so the read never ages
        return 1_000.0

    async def read(self) -> None:
        """The account-health tracking read the key standing observes."""
        self.standings.observe(await self.store.targets())

    async def reject(self, account: UUID, refusal: Refusal, code: int | None = 10003) -> None:
        """A report, then the job's stop, which waits for the reactions in flight."""
        self.check.credential_rejected(account, refusal, exchange_ret_code=code)
        async with asyncio.timeout(5.0):
            await self.check.stop()

    def failing(self, rule: str) -> float | None:
        name = "cv_keys_failing_policy"
        return self.metrics.registry.get_sample_value(name, {"env": "demo", "rule": rule})


class Pager:
    def __init__(self) -> None:
        self.pages: list[str] = []

    def raise_alert(self, severity: str, summary: str, *, machine_kind: str) -> None:
        self.pages.append(summary)


async def settle() -> None:
    """Every reaction ended, those begun from a pending slot included. A task reads done before
    its done callbacks have run (one of which begins the next pending reaction), so the loop is
    yielded to until it has found none running three turns in a row."""
    quiet = 0
    async with asyncio.timeout(5.0):
        while quiet < 3:
            running = [
                task
                for task in asyncio.all_tasks()
                if task.get_name() == REJECTION_TASK and not task.done()
            ]
            if running:
                quiet = 0
                await asyncio.gather(*running, return_exceptions=True)
            else:
                quiet += 1
                await asyncio.sleep(0)  # a loop turn, no wall time


def two_accounts() -> Store:
    return Store(target(), target(key=KEY2, acct=ACCT2))


@pytest.mark.parametrize("refusal", list(Refusal))
async def test_a_refused_credential_disarms_first_then_marks_the_key_write_ahead(
    refusal: Refusal,
) -> None:
    store = two_accounts()
    p = Process(store)
    await p.reject(ACCT, refusal)
    rule = RULES[refusal]
    assert store.kinds() == [
        ("disable", ACCT, refusal.value), ("audit", DISABLED), ("mark", ACCT),
        ("audit", TESTED), ("error", KEY, rule),
    ]  # fmt: skip
    (tested,) = store.audits(TESTED)
    assert tested["actor_label"] == JOB and "actor_user_id" not in tested  # the job, no user
    assert (tested["object_kind"], tested["object_id"]) == ("api_key", str(KEY))
    assert (tested["outcome"], tested["severity"], tested["reason"]) == (
        "failure", "critical", refusal.value,
    )  # fmt: skip
    assert tested["after_state"] == {
        "failures": [rule], "refusal": refusal.value, "exchange_ret_code": 10003,
        "source": "signed_call",
    }  # fmt: skip
    (disabled,) = store.audits(DISABLED)
    assert disabled["reason"] == refusal.value and disabled["object_id"] == str(ACCT)
    assert store.disarms[ACCT][0] == refusal.value  # the Owner reads the refusal
    assert p.check.results[KEY].outcome == "failed" and p.failing(rule) == 1.0
    # the account's alone: nothing latched system-wide, and the key's status is not moved
    assert p.gate.latched_reason_code is None and not [e for e in store.events if e[0] == "retire"]


async def test_a_stream_status_report_records_no_code_and_names_its_source() -> None:
    store = Store(target())
    await Process(store).reject(ACCT, Refusal.UNKNOWN_KEY, code=None)
    (tested,) = store.audits(TESTED)
    assert tested["after_state"]["exchange_ret_code"] is None
    assert tested["after_state"]["source"] == "stream_status"


async def test_the_records_name_the_refusal_never_a_key_or_a_venue_message() -> None:
    """C-12.6: codes and ids only; the key id is the record's object, never its reason."""
    store = Store(target())
    await Process(store).reject(ACCT, Refusal.IP_NOT_ALLOWED, code=10010)
    for fields in store.audits(TESTED) + store.audits(DISABLED):
        assert fields["reason"] == "ip_not_allowed"
        assert str(KEY) not in str(fields.get("after_state")) and EGRESS not in str(fields)


async def test_another_account_is_untouched_by_the_rejection() -> None:
    """Cross-account: a report for one account marks and disarms that account alone."""
    store = two_accounts()
    p = Process(store)
    await p.reject(ACCT, Refusal.PERMISSION_DENIED)
    assert all(ACCT2 not in e and KEY2 not in e for e in store.events)
    assert store.rows[KEY2].last_error_code is None and store.rows[KEY2].account.trading_enabled
    await p.read()
    assert p.standings.standing(ACCT2) == KeyStanding(True)
    refused = p.standings.standing(ACCT)
    assert refused is not None and refused.disabled_reason is DisabledReason.ACCOUNT_DISABLED


async def test_a_repeat_in_the_same_episode_writes_nothing_more() -> None:
    store = Store(target())
    p = Process(store)
    p.check.credential_rejected(ACCT, Refusal.UNKNOWN_KEY, exchange_ret_code=10003)
    await settle()
    written = len(store.events)
    await p.reject(ACCT, Refusal.PERMISSION_DENIED)
    assert store.events[written:] == [("disable", ACCT, "permission_denied")]  # unchanged
    assert len(store.audits(TESTED)) == 1 and len(store.audits(DISABLED)) == 1


async def test_a_report_while_the_accounts_reaction_is_in_flight_waits_in_its_slot() -> None:
    """Code review 4 and security L2: the in-flight log names both refusals (an error when they
    differ), and the latest report begins once the reaction ends; one episode's records stay
    one per key and one disarm."""
    store = Store(target())
    p = Process(store)
    with capture_logs() as logs:
        p.check.credential_rejected(ACCT, Refusal.UNKNOWN_KEY, exchange_ret_code=10003)
        p.check.credential_rejected(ACCT, Refusal.UNKNOWN_KEY, exchange_ret_code=10003)
        p.check.credential_rejected(ACCT, Refusal.IP_NOT_ALLOWED, exchange_ret_code=10010)
        await settle()
    flights = [log for log in logs if log["event"] == "key_selfcheck_rejection_in_flight"]
    assert [(f["log_level"], f["in_flight"], f["refusal"]) for f in flights] == [
        ("warning", "unknown_key", "unknown_key"),
        ("error", "unknown_key", "ip_not_allowed"),
    ]
    assert [e for e in store.events if e[0] == "disable"] == [
        ("disable", ACCT, "unknown_key"), ("disable", ACCT, "ip_not_allowed"),
    ]  # fmt: skip  # the follow-up ran; the disarm keeps the first's code
    assert store.disarms[ACCT][0] == "unknown_key"
    assert len(store.audits(TESTED)) == 1 and len(store.audits(DISABLED)) == 1


async def test_reports_past_the_slots_wait_and_begin_as_reactions_end() -> None:
    """Security L2 (C-2.18): `MAX_REJECTIONS` run at once; the rest wait, one slot an account,
    and each begins when a reaction ends; past `MAX_PENDING` accounts a report is dropped. Each
    is stamped when it arrives (#5559): the wall clock moves on before any reaction runs, and
    every disarm still carries the reports' time."""
    accounts = [UUID(int=1000 + n) for n in range(MAX_REJECTIONS + MAX_PENDING + 1)]
    store = Store(*(target(key=UUID(int=5000 + n), acct=a) for n, a in enumerate(accounts)))
    p = Process(store)
    with capture_logs() as logs:
        for account in accounts:
            p.check.credential_rejected(account, Refusal.UNKNOWN_KEY, exchange_ret_code=None)
        (dropped,) = [log for log in logs if log["event"] == "key_selfcheck_rejection_dropped"]
        p.wall = NOW + SECOND  # every reaction begins after this, the waiting ones later still
        await settle()
    assert dropped["log_level"] == "critical" and dropped["account_id"] == str(accounts[-1])
    assert set(store.disarms) == set(accounts[:-1])  # every one that waited was disarmed
    assert {at for _code, at, _mark in store.disarms.values()} == {NOW}  # stamped on arrival
    assert len(store.audits(DISABLED)) == len(accounts) - 1


async def test_a_report_after_stop_begins_nothing() -> None:
    """Code review 3: a stopped job begins no reaction; a waiting one is dropped, critical."""
    store = Store(target(), target(key=KEY2, acct=ACCT2))
    p = Process(store)
    await p.check.stop()
    with capture_logs() as logs:
        p.check.credential_rejected(ACCT, Refusal.UNKNOWN_KEY, exchange_ret_code=10003)
    await settle()
    assert store.events == [] and [log["log_level"] for log in logs] == ["critical"]


def test_a_report_with_no_running_loop_is_dropped_critical_and_never_raised() -> None:
    p = Process(Store(target()))
    with capture_logs() as logs:
        p.check.credential_rejected(ACCT, Refusal.UNKNOWN_KEY, exchange_ret_code=10003)
    assert [log["event"] for log in logs] == ["key_selfcheck_rejection_dropped"]


async def test_the_disarm_lands_however_long_marking_several_keys_takes() -> None:
    """Code review 2: the disarm runs first, each step under its own bound, so an audit sink
    that never answers for the keys' records cuts the marking alone."""
    keys = [UUID(int=40 + n) for n in range(4)]
    store = Store(*(target(key=key) for key in keys))
    store.hang.add(TESTED)
    p = Process(store, timeout_s=0.05, key_deadline_s=0.0)
    p.check.credential_rejected(ACCT, Refusal.UNKNOWN_KEY, exchange_ret_code=10003)
    await settle()
    assert store.kinds()[:3] == [
        ("disable", ACCT, "unknown_key"),
        ("audit", DISABLED),
        ("mark", ACCT),
    ]
    assert store.disarms[ACCT][2] is not None  # its record written and marked
    assert not [e for e in store.events if e[0] == "error"]  # no code without its record
    assert all(p.check.results[key].outcome == "failed" for key in keys)  # held in memory


async def test_a_refused_record_withholds_the_code_while_the_disarm_holds() -> None:
    """C-2.9: no code without its write-ahead record; enforcement runs whatever the sink does."""
    store = Store(target())
    store.refused.add(TESTED)
    p = Process(store)
    with capture_logs() as logs:
        await p.reject(ACCT, Refusal.UNKNOWN_KEY)
    assert not [e for e in store.events if e[0] == "error"]
    assert ("disable", ACCT, "unknown_key") in store.events and store.disarms[ACCT][2] is not None
    assert p.check.results[KEY].outcome == "failed"  # refused in memory all the same
    unmarked = [log for log in logs if log["event"] == "key_selfcheck_rejection_unmarked"]
    assert [log["log_level"] for log in unmarked] == ["critical"]


async def test_an_unreadable_key_list_still_disarms_the_account() -> None:
    store = Store(target())
    store.fail_targets = True
    with capture_logs() as logs:
        await Process(store).reject(ACCT, Refusal.UNKNOWN_KEY)
    assert store.disarms[ACCT][0] == "unknown_key" and not store.audits(TESTED)
    unread = [log for log in logs if log["event"] == "key_selfcheck_rejection_unread"]
    assert [log["log_level"] for log in unread] == ["critical"]


async def test_a_pass_whose_check_began_before_the_rejection_leaves_the_mark() -> None:
    """Security L1: a pass in flight when the rejection lands keeps neither its stored clear nor
    its result: the code stays and the account stays refused."""
    store = Store(target())
    p = Process(store)
    await p.read()
    p.hold = asyncio.Event()
    run = asyncio.create_task(p.check.run_once())
    async with asyncio.timeout(5.0):
        await p.entered.wait()  # the check began at NOW
    p.wall = NOW + SECOND
    p.check.credential_rejected(ACCT, Refusal.UNKNOWN_KEY, exchange_ret_code=10003)
    await settle()
    p.hold.set()
    async with asyncio.timeout(5.0):
        await run
    assert ("pass", KEY) in store.events  # the pass's facts were written
    assert store.rows[KEY].last_error_code == "key_wrong_environment"  # its clear was not
    assert p.check.results[KEY].outcome == "failed"
    await p.read()
    refused = p.standings.standing(ACCT)
    assert refused is not None and refused.disabled_reason is DisabledReason.ACCOUNT_DISABLED


async def test_an_error_whose_check_began_before_the_rejection_keeps_the_mark() -> None:
    """Security L1: an older check's code never overwrites the newer mark."""
    store = Store(target())
    p = Process(store)
    p.wall = NOW + SECOND
    await p.reject(ACCT, Refusal.PERMISSION_DENIED)
    assert await store.record_error(KEY, code="rate_limited", at=NOW) is False
    assert store.rows[KEY].last_error_code == "key_missing_scopes"


async def test_a_code_outside_the_verdict_table_is_held_and_paged_never_durable() -> None:
    """Delta review 1: a refused signature (`10004`) is no verdict on the key (the self-check
    holds it inconclusive, SR-E27-18): held in memory and paged, with no record, disarm or code,
    so a later inconclusive check latches nothing; a mapped code (`10003`) is durable."""
    store = two_accounts()
    p = Process(store)
    pager = Pager()
    binding = CredentialRejectionsBinding(
        p.standings, key_refusal=ExchangeBybitService.key_refusal, pager=pager, marks=p.check
    )
    await p.read()
    await binding.refused(
        AccountId(ACCT), error_code="AUTH_ERROR", exchange_ret_code=10004, verdict=True
    )
    await settle()
    assert store.events == [] and store.rows[KEY].last_error_code is None and len(pager.pages) == 1
    held = p.standings.standing(ACCT)
    assert held is not None and not held.has_active_key  # refused in memory: `unknown_key`
    await binding.refused(
        AccountId(ACCT2), error_code="AUTH_ERROR", exchange_ret_code=10003, verdict=True
    )
    await settle()
    assert store.disarms[ACCT2][0] == "unknown_key" and len(store.audits(TESTED)) == 1


async def test_a_pass_reading_the_reactions_disarm_as_owed_sends_no_second_record() -> None:
    """Delta review 3: one sender per account's record. A pass's `_settle_owed` that reads the
    disarm owed while the reaction is still sending its record skips it: one record."""
    store = Store(target())
    opened, entered = asyncio.Event(), asyncio.Event()
    store.gates[DISABLED] = (opened, entered)
    p = Process(store)
    p.check.credential_rejected(ACCT, Refusal.UNKNOWN_KEY, exchange_ret_code=10003)
    async with asyncio.timeout(5.0):
        await entered.wait()  # the reaction's record is in flight, its disarm owed in the store
    async with asyncio.timeout(5.0):
        await p.check.run_once()  # reads the disarm owed and skips it: it waits on nothing
    opened.set()
    await settle()
    assert len(store.audits(DISABLED)) == 1 and store.disarms[ACCT][2] is not None


async def test_a_key_unusable_report_is_never_durable_and_an_auth_refusal_is() -> None:
    """Security M1, through the binding into the job: a stream's `key_unusable` (a local secrets
    fault, `verdict=False`) writes no record, disarm or code; its `auth_refused` does."""
    store = two_accounts()
    p = Process(store)
    pager = Pager()
    binding = CredentialRejectionsBinding(
        p.standings, key_refusal=ExchangeBybitService.key_refusal, pager=pager, marks=p.check
    )
    await binding.refused(
        AccountId(ACCT), error_code="AUTH_ERROR", exchange_ret_code=None, verdict=False
    )
    await settle()
    assert store.events == [] and store.rows[KEY].last_error_code is None and len(pager.pages) == 1
    await binding.refused(
        AccountId(ACCT2), error_code="AUTH_ERROR", exchange_ret_code=None, verdict=True
    )
    await settle()
    assert store.disarms[ACCT2][0] == "unknown_key" and len(store.audits(TESTED)) == 1
    assert store.rows[KEY2].last_error_code == "key_wrong_environment" and len(pager.pages) == 2


async def test_admission_stays_refused_across_a_restart_until_a_pass_and_the_owner() -> None:
    """The stored code and disarm outlive the process: the next one's key standing refuses the
    account before any check, and its boot pass with no verdict keeps the failure in force. A
    pass begun after the mark clears it; the account stays disarmed, as only the Owner re-arms."""
    store = Store(target())
    first = Process(store)
    first.wall = NOW - SECOND  # the rejection lands before the passing check begins
    await first.read()
    assert first.standings.standing(ACCT) == KeyStanding(True)
    await first.reject(ACCT, Refusal.UNKNOWN_KEY)

    restarted = Process(store, verdict=False)
    await restarted.read()
    standing = restarted.standings.standing(ACCT)
    assert standing is not None and standing.disabled_reason is DisabledReason.ACCOUNT_DISABLED
    async with asyncio.timeout(5.0):
        await restarted.check.run_once()
    assert restarted.check.results[KEY].outcome == "failed"
    assert restarted.gate.latched_reason_code == FAILED  # a standing failure, as for any
    assert store.rows[KEY].last_error_code == "key_wrong_environment"

    passed = Process(store, verdict=True)
    async with asyncio.timeout(5.0):
        await passed.check.run_once()
    assert store.rows[KEY].last_error_code is None  # the pass cleared the mark
    await passed.read()
    standing = passed.standings.standing(ACCT)
    assert standing is not None and standing.disabled_reason is DisabledReason.ACCOUNT_DISABLED


async def test_a_stop_drops_the_reports_still_waiting_critical() -> None:
    """Orchestrator read 5: a report waiting in its slot when the job stops never begins."""
    store = Store(target())
    p = Process(store)
    with capture_logs() as logs:
        p.check.credential_rejected(ACCT, Refusal.UNKNOWN_KEY, exchange_ret_code=10003)
        p.check.credential_rejected(ACCT, Refusal.IP_NOT_ALLOWED, exchange_ret_code=10010)
        async with asyncio.timeout(5.0):
            await p.check.stop()
    await settle()
    unbegun = [log for log in logs if log["event"] == "key_selfcheck_rejections_unbegun"]
    assert [(log["log_level"], log["accounts"]) for log in unbegun] == [("critical", 1)]
    assert [e for e in store.events if e[0] == "disable"] == [("disable", ACCT, "unknown_key")]


async def test_a_stop_cancels_a_reaction_still_marking_past_the_disarms_bounds() -> None:
    """Orchestrator read 5: the stop waits the disarm's three bounds, then cancels: the disarm
    and its record are behind it, only the marking is cut."""
    keys = [UUID(int=60 + n) for n in range(6)]
    store = Store(*(target(key=key) for key in keys))
    store.hang.add(TESTED)
    p = Process(store, timeout_s=0.02)
    before = asyncio.all_tasks()
    p.check.credential_rejected(ACCT, Refusal.UNKNOWN_KEY, exchange_ret_code=10003)
    (reaction,) = asyncio.all_tasks() - before
    async with asyncio.timeout(5.0):
        await p.check.stop()  # six hung records outlast the disarm's three bounds
    assert reaction.cancelled()
    assert store.disarms[ACCT][2] is not None  # the disarm's record written and marked
    assert not [e for e in store.events if e[0] == "error"]


async def test_a_reaction_cut_by_its_deadline_is_logged_critical_by_class() -> None:
    """Orchestrator read 5: a reaction that raises is logged by its class, never its text."""
    keys = [UUID(int=80 + n) for n in range(12)]
    store = Store(*(target(key=key) for key in keys))
    store.hang.add(TESTED)
    p = Process(store, timeout_s=0.01, key_deadline_s=0.0)  # deadline 9 bounds; 12 records hang
    with capture_logs() as logs:
        p.check.credential_rejected(ACCT, Refusal.UNKNOWN_KEY, exchange_ret_code=10003)
        await settle()
    (failed,) = [log for log in logs if log["event"] == "key_selfcheck_rejection_failed"]
    assert (failed["log_level"], failed["error"]) == ("critical", "TimeoutError")
    assert store.disarms[ACCT][0] == "unknown_key"  # the disarm came first


async def test_a_waiting_report_whose_account_is_running_waits_for_its_own_end() -> None:
    """Orchestrator read 5: a slot freed by another account's end skips an account whose own
    reaction still runs; that account's report begins when its reaction ends."""
    store = two_accounts()
    opened, entered = asyncio.Event(), asyncio.Event()
    store.gates[DISABLED] = (opened, entered)  # the first record: ACCT2's, sent first
    p = Process(store)
    p.check.credential_rejected(ACCT2, Refusal.UNKNOWN_KEY, exchange_ret_code=10003)
    before = asyncio.all_tasks()
    p.check.credential_rejected(ACCT, Refusal.UNKNOWN_KEY, exchange_ret_code=10003)
    (acct_reaction,) = asyncio.all_tasks() - before
    p.check.credential_rejected(ACCT2, Refusal.IP_NOT_ALLOWED, exchange_ret_code=10010)
    async with asyncio.timeout(5.0):
        await entered.wait()
        await acct_reaction  # ACCT's reaction ends while ACCT2's is held; its drain has run
    assert store.disarms[ACCT][2] is not None
    assert [e for e in store.events if e[0] == "disable" and e[1] == ACCT2] == [
        ("disable", ACCT2, "unknown_key")
    ]  # its waiting report did not begin beside it
    opened.set()
    await settle()
    assert [e[2] for e in store.events if e[0] == "disable" and e[1] == ACCT2] == [
        "unknown_key", "ip_not_allowed",
    ]  # fmt: skip


async def test_a_key_whose_failure_is_already_stored_keeps_it_and_writes_nothing() -> None:
    """Orchestrator read 5: one mark an episode, the stored standing failure included."""
    store = Store(target(last_error="key_ip_whitelist_mismatch"))
    p = Process(store)
    await p.reject(ACCT, Refusal.UNKNOWN_KEY)
    assert p.check.results[KEY].outcome == "failed"
    assert p.check.results[KEY].code == "key_ip_whitelist_mismatch"
    assert not store.audits(TESTED) and not [e for e in store.events if e[0] == "error"]
