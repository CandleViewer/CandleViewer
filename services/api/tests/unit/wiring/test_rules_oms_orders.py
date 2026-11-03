"""E35-T11 slice 3c: the `scale_in` side read and the entry handler's own refusals, at unit level
(24 §11.6 `scale_in`, §11.5, §11.9 `failed`; C-2.12).

`StoredPositionSides` reads the account's stored position in the owner's own scope (every account
for an Owner, the action's account alone for anyone else) and answers the side of the open one-way
position on the instance's symbol, `None` without one. A request whose origin or principal cannot
be established sends nothing. The order port here answers at once; the pipeline's own behaviour is
`tests/rules/executor/test_order_handlers.py`'s."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Coroutine
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

import pytest

from candleviewer.oms.errors import IdempotencyKeyReuse
from candleviewer.oms.idempotency import Fresh, KeyReuse
from candleviewer.oms.submit import OrderRequest, SubmitContext, SubmitOutcome
from candleviewer.rules.executor.handlers import HandlerAnswer
from candleviewer.rules.executor.ports import PrincipalView
from candleviewer.rules.executor.results import BLOCKED_DETAIL, NODE_ID, OMS_DETAIL
from candleviewer.rules_oms_orders import (
    POSITION_READ_TIMEOUT_S,
    PositionSides,
    PreparedEntry,
    RuleEntryHandler,
    RuleOrders,
    StoredPositionSides,
)
from candleviewer.rules_oms_requests import refusal_answer
from candleviewer.storage.repositories.accounts import AccountScope, GrantScope, OwnerScope
from candleviewer.storage.repositories.oms_reads import PositionQuery
from candleviewer.storage.repositories.positions import PositionRow, PositionSide
from tests.rules.executor.request_builders import Principals
from tests.rules.executor.test_order_handlers import OWNER, odd, request
from tests.unit.oms import command_rig as cr

ACCOUNT, OTHER = cr.ACCOUNT, uuid.UUID(int=0xC2)
MANAGER = uuid.UUID(int=0xC3)
T0 = datetime(2026, 11, 2, tzinfo=UTC)
QUERY = PositionQuery(accounts=(ACCOUNT,), symbol="BTCUSDT")
#: Node ids the IR refuses at save that a rule stored before that bound may still hold, and which
#: the OMS's rule origin refuses (built unvalidated, `odd`).
ODD_NODE_IDS: tuple[str, ...] = ("", "a.1", "n" * 65)
ODD_NODE_IDS_NAMED: tuple[str, ...] = ("empty", "dot", "too-long")


def row(
    side: PositionSide | None = "Buy",
    *,
    account: uuid.UUID = ACCOUNT,
    idx: Literal[0, 1, 2] = 0,
    size: str = "0.5",
) -> PositionRow:
    return PositionRow(
        exchange_account_id=account, symbol="BTCUSDT", size=Decimal(size), position_idx=idx,
        side=side, id=uuid.UUID(int=1), recv_ts=T0, updated_at=T0,
    )  # fmt: skip


def view(user: uuid.UUID, *, owner: bool) -> PrincipalView:
    return PrincipalView(
        user_id=user, active=True, role="owner" if owner else "manager", is_owner=owner,
        trade_accounts=frozenset({ACCOUNT}), read_at=0.0,
    )  # fmt: skip


@dataclass
class Reads:
    """`OmsReads.positions` in memory: the rows it holds, and each read's scope and query."""

    rows: tuple[PositionRow, ...] = ()
    asked: list[tuple[AccountScope, PositionQuery]] = field(default_factory=list)

    async def positions(self, scope: AccountScope, query: PositionQuery) -> tuple[PositionRow, ...]:
        self.asked.append((scope, query))
        return self.rows


class Pipeline:
    """The OMS's pipeline, answering at once; `requests` is every request it was handed."""

    def __init__(self) -> None:
        self.requests: list[OrderRequest] = []

    async def submit(self, request: OrderRequest, context: SubmitContext) -> SubmitOutcome:
        self.requests.append(request)
        return SubmitOutcome(
            status=202, anchor_id=uuid.UUID(int=0xA0), order_id=uuid.UUID(int=0xA2),
            trade_group_id=uuid.UUID(int=0xA1), lifecycle="submitted",
            notional_usd=Decimal("600"),
        )  # fmt: skip

    async def answer_replay(self, account_id: Any, replay: Any) -> SubmitOutcome:
        raise AssertionError("no request here repeats a key")


class Anchors:
    async def lookup(self, created_by: uuid.UUID, client_ref: uuid.UUID, sha: str) -> Fresh:
        return Fresh()


class Runtime:
    readiness = "ok"

    def __init__(self) -> None:
        self.submission, self.anchors = Pipeline(), Anchors()

    def run(self, coro: Coroutine[Any, Any, SubmitOutcome]) -> asyncio.Task[SubmitOutcome]:
        return asyncio.ensure_future(coro)


def handler(
    runtime: Runtime, action_type: str = "place_order", positions: PositionSides | None = None
) -> RuleEntryHandler:
    orders = RuleOrders(lambda: runtime, lambda: True)
    return RuleEntryHandler(action_type, orders, Principals(frozenset({ACCOUNT})), positions)


async def answer_to(entry: RuleEntryHandler, prepared: Any) -> HandlerAnswer:
    return await entry.send(prepared, client_ref=str(uuid.UUID(int=0xF00)))


@pytest.mark.parametrize(("stored", "side"), [("Buy", "buy"), ("Sell", "sell")])
async def test_the_stored_side_of_an_owners_open_position_is_read_in_the_owner_scope(
    stored: PositionSide, side: str
) -> None:
    reads = Reads((row(stored),))
    sides = StoredPositionSides(reads)
    assert await sides.side(view(OWNER, owner=True), ACCOUNT, "BTCUSDT") == side
    assert reads.asked == [(OwnerScope(OWNER), QUERY)]


async def test_a_non_owner_reads_the_position_in_a_grant_scope_of_its_one_account() -> None:
    """A manager's read names the action's account alone, which the read itself re-checks."""
    reads = Reads((row("Sell"),))
    sides = StoredPositionSides(reads)
    assert await sides.side(view(MANAGER, owner=False), ACCOUNT, "BTCUSDT") == "sell"
    assert reads.asked == [(GrantScope(MANAGER, frozenset({ACCOUNT})), QUERY)]


@pytest.mark.parametrize(
    "rows",
    [
        (),
        (row("Buy", account=OTHER),),  # another account's, which the query names not
        (row("Buy", idx=1), row("Sell", idx=2)),  # hedge-mode legs: no one-way position
        (row("Buy", size="0"),),  # flat
        (row("None"), row(None)),  # no side stored
    ],
    ids=["none", "other-account", "hedge-legs", "flat", "no-side"],
)
async def test_without_an_open_one_way_position_there_is_no_side(rows: tuple[PositionRow]) -> None:
    sides = StoredPositionSides(Reads(rows))
    assert await sides.side(view(OWNER, owner=True), ACCOUNT, "BTCUSDT") is None


async def test_a_scale_in_through_the_stored_read_is_sent_on_the_positions_side() -> None:
    runtime, reads = Runtime(), Reads((row("Sell"),))
    entry = handler(runtime, "scale_in", StoredPositionSides(reads))
    built = entry.prepare(
        request("a1", "scale_in", {"qty": "0.01"}), ACCOUNT, max_notional_usd=None
    )
    answer = await answer_to(entry, built)
    assert (answer.answer, answer.notional_usd) == ("accepted", Decimal("600"))
    [sent] = runtime.submission.requests
    assert (sent.side, sent.intent, sent.symbol) == ("sell", "scale_in", "BTCUSDT")
    assert reads.asked == [(OwnerScope(OWNER), QUERY)]


async def test_an_armer_that_is_no_user_id_is_refused_on_permission() -> None:
    """Fail closed: an armer not read by id is refused before the OMS, as a principal gone since
    check 5 is."""
    runtime = Runtime()
    entry = handler(runtime)
    built = entry.prepare(replace(request(), armed_by="no-user-id"), ACCOUNT, max_notional_usd=None)
    answer = await answer_to(entry, built)
    assert (answer.answer, answer.blocked_by, answer.detail) == ("refused", "permission", None)
    assert runtime.submission.requests == []


@pytest.mark.parametrize("node", ODD_NODE_IDS, ids=ODD_NODE_IDS_NAMED)
async def test_an_origin_the_oms_refuses_fails_with_a_detail_holding_no_id(node: str) -> None:
    """A node id the OMS's rule origin refuses is `invalid_params` (a `failed` action, the
    orchestrator's carry 2), never a raise: the detail is the register's generic sentence, the id
    nowhere in it, and nothing reaches the OMS."""
    runtime = Runtime()
    entry = handler(runtime)
    built = entry.prepare(odd(request(), node), ACCOUNT, max_notional_usd=None)
    answer = await answer_to(entry, built)
    assert (answer.answer, answer.blocked_by, answer.error_code) == (
        "refused", None, "invalid_params",
    )  # fmt: skip
    assert answer.detail == OMS_DETAIL[NODE_ID] and (node == "" or node not in answer.detail)
    assert runtime.submission.requests == []


def test_a_prepared_entrys_repr_shows_none_of_its_request() -> None:
    """C-12.6 (R1C2-04): a built entry's repr names no parameter, account, symbol, ceiling,
    owner or origin."""
    entry = handler(Runtime())
    built = entry.prepare(request(), ACCOUNT, max_notional_usd=Decimal("1234.5"))
    assert isinstance(built, PreparedEntry) and built.origin is not None
    text = repr(built)
    for held in (
        "PlaceOrderParams", "market", str(ACCOUNT), "BTCUSDT", "1234.5", str(OWNER),
        str(built.origin.rule_id), "RuleOrigin", "PrincipalView",
    ):  # fmt: skip
        assert held not in text, held


class KeyUsedElsewhere(Anchors):
    async def lookup(self, created_by: uuid.UUID, client_ref: uuid.UUID, sha: str) -> Any:
        return KeyReuse()


async def test_a_key_first_used_for_another_request_is_refused_and_nothing_submitted() -> None:
    """R1C2-04: the anchor's lookup finds the fire key used with another body: the OMS's
    key-reuse refusal, as the `placeOrder` route answers it, and no submit."""
    runtime = Runtime()
    runtime.anchors = KeyUsedElsewhere()
    entry = handler(runtime)
    answer = await answer_to(entry, entry.prepare(request(), ACCOUNT, max_notional_usd=None))
    assert answer == refusal_answer(IdempotencyKeyReuse())
    assert runtime.submission.requests == []


class Hung:
    """A position read that never answers."""

    async def side(self, owner: PrincipalView, account_id: uuid.UUID, symbol: str) -> Any:
        await asyncio.Event().wait()


async def test_a_position_read_that_never_answers_is_no_answer_within_its_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R1C2-04: a `scale_in`'s position read is bounded (`POSITION_READ_TIMEOUT_S`, a store
    read's 2 s; 0 here): one that never answers is `no_answer` (`position_unread`), nothing sent."""
    assert POSITION_READ_TIMEOUT_S == 2.0
    monkeypatch.setattr("candleviewer.rules_oms_orders.POSITION_READ_TIMEOUT_S", 0.0)
    runtime = Runtime()
    entry = handler(runtime, "scale_in", Hung())
    built = entry.prepare(
        request("a1", "scale_in", {"qty": "0.01"}), ACCOUNT, max_notional_usd=None
    )
    async with asyncio.timeout(5):
        answer = await answer_to(entry, built)
    assert (answer.answer, answer.error_code) == ("no_answer", "position_unread")
    assert runtime.submission.requests == []


async def test_a_scale_in_with_no_position_read_bound_gets_no_answer() -> None:
    """No position read bound at the composition root (the OMS reads not composed): a `scale_in`
    for a fresh key is `no_answer` (`position_unread`), nothing sent."""
    runtime = Runtime()
    entry = handler(runtime, "scale_in", None)
    built = entry.prepare(
        request("a1", "scale_in", {"qty": "0.01"}), ACCOUNT, max_notional_usd=None
    )
    answer = await answer_to(entry, built)
    assert (answer.answer, answer.error_code) == ("no_answer", "position_unread")
    assert runtime.submission.requests == []


@pytest.mark.parametrize("missing", ["account_id", "owner"])
async def test_a_prepared_entry_missing_its_account_or_owner_sends_nothing(missing: str) -> None:
    runtime = Runtime()
    entry = handler(runtime)
    built = entry.prepare(request(), ACCOUNT, max_notional_usd=None)
    assert isinstance(built, PreparedEntry) and built.actor is not None
    broken = (
        replace(built, account_id=None) if missing == "account_id" else replace(built, owner=None)
    )
    answer = await answer_to(entry, broken)
    assert (answer.answer, answer.error_code) == ("refused", "invalid_params")
    assert runtime.submission.requests == []


def test_the_oms_details_keep_the_registers_form() -> None:
    """One plain sentence each, at most 80 characters, none a `blocked_by`'s own sentence."""
    for sentence in OMS_DETAIL.values():
        assert sentence.startswith("Not done — ") and sentence.endswith(".")
        assert len(sentence) <= 80 and sentence.count(".") == 1
    assert not set(OMS_DETAIL.values()) & set(BLOCKED_DETAIL.values())
