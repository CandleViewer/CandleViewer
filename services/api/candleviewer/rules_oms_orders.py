"""The rule entries' handlers and their order port, bound at the composition root (E35-T11 slice
3c; 24 §11.5, §11.9; the rulings of #863 BQ-2 to BQ-5, BQ-9, BQ-17, and of #5003 BQ-4 and BQ-7).

`place_order` and `scale_in` are bound through `RulesService.bind(handlers=...)` (the seam E35-T13
opened, BQ-2 of #5005), each with the `oms_entry` capability its type declares. The executor
calls them per resolved account, after checks 1 to 8 and the records written ahead:

- `prepare` (pure, synchronous) reads the typed parameters (`invalid_params` when they do not
  parse, or when the scope instance names no symbol), the owner's and the armer's roles from the
  same principal views check 5 read, and builds the request once, fingerprinted once
  (`request_sha256`), with the owner as the principal and the rule as the origin
  (`rules_oms_requests`). Two refusals are decided here and answered by `send`, nothing sent, each
  after the hand-over's records as the OMS's own refusals are (24 §11.5): a principal gone since
  check 5 (`permission`), and an origin the OMS refuses, a node id that is not a short identifier
  (`failed`, `invalid_params`, with a sentence that never names the id), never a raise;
- `send` hands it over under the fire key's `client_ref`, the same request and fingerprint for a
  `retry_once` retry, and maps the answer (`answer_of`, `refusal_answer`). A `scale_in` adds to
  the open position on the instance's symbol, on its side, read from the account's stored
  position (`StoredPositionSides`, bounded) for a fresh key only, after the anchor's lookup: a
  repeat is answered from its anchor whatever the position is now. None open is `failed`
  (`no_position`), nothing sent, and a read that fails is `no_answer` (`position_unread`), retried
  at most once as any call that got no answer.

The order port (`RuleOrders`) admits a request as the `placeOrder` route does, and goes no further
than the route: the OMS ready, the anchor's lookup by the owner's key (a decided anchor's answer
replayed, one in flight or another body refused, nothing sent), then, for a fresh key, the request
(the `scale_in` side read), and `trading.oms_enabled`, the OMS admissions' own rollout flag, for an
entry. The pipeline then runs as a task the OMS runtime tracks and drains at its stop
(`OmsRuntime.run`), on the order lane, its own synchronous checks last (the clock halt, sizing
against the profile, the risk gate, the trading switches, the rate headroom); the action awaits it
shielded, so its bound, above the pipeline's, never cancels it (BQ-7): a submit still running at
that bound is `unknown`, never sent again, and one the runtime's stop cut short is in flight
(`submit_cut_short`), never re-sent. Rule actions run on demo and testnet only: check 4 refuses a
live account, and the OMS's own live gate stays the last fence (C-2.11).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field, replace
from decimal import Decimal
from functools import partial
from typing import Any, Final, Protocol
from uuid import UUID

from candleviewer.domain.primitives import AccountId, Side
from candleviewer.oms.errors import OmsNotReady, TradingDisabled
from candleviewer.oms.idempotency import InFlight, KeyReuse, Lookup, Replay
from candleviewer.oms.ports import RuleOrigin, SubmitActor
from candleviewer.oms.submit import OrderRequest, SubmitContext, SubmitOutcome
from candleviewer.rules.executor.handlers import (
    Capability,
    HandlerAnswer,
    Prepared,
    prepared,
)
from candleviewer.rules.executor.params import EntryParams, PlaceOrderParams, entry_params
from candleviewer.rules.executor.ports import PrincipalReads, PrincipalView
from candleviewer.rules.executor.results import NODE_ID, OMS_DETAIL
from candleviewer.rules.scope import ActionRequest
from candleviewer.rules_oms_requests import (
    answer_of,
    canonical_request,
    order_request,
    refusal_answer,
    rule_origin,
    submit_context,
    system_role,
)
from candleviewer.storage.repositories.accounts import AccountScope, GrantScope, OwnerScope
from candleviewer.storage.repositories.oms_reads import PositionQuery

#: The two types this module binds, each `oms_entry` (`handlers.BINDINGS`).
ENTRY_TYPES: Final = ("place_order", "scale_in")
#: The bound on a `scale_in`'s position read, a store read's.
POSITION_READ_TIMEOUT_S: Final = 2.0
_SIDES: Final[dict[str, Side]] = {"Buy": "buy", "Sell": "sell"}
#: `prepare`'s two refusals, which `send` answers with nothing sent (module docstring).
_PRINCIPAL_GONE: Final = HandlerAnswer("refused", blocked_by="permission")
_ORIGIN_REFUSED: Final = HandlerAnswer(
    "refused", error_code="invalid_params", detail=OMS_DETAIL[NODE_ID]
)
#: A fresh key's request, built only once the anchor's lookup has found none (`RuleOrders.submit`).
RequestBuilder = Callable[[], Awaitable[OrderRequest]]


class _Pipeline(Protocol):
    async def submit(self, request: OrderRequest, context: SubmitContext) -> SubmitOutcome: ...

    async def answer_replay(self, account_id: AccountId, replay: Replay) -> SubmitOutcome: ...


class _Anchors(Protocol):
    async def lookup(self, created_by: UUID, client_ref: UUID, request_sha256: str) -> Lookup: ...


class OrderRuntime(Protocol):
    """`oms_wiring.OmsRuntime` as the order port reads it, as the `placeOrder` route does."""

    @property
    def readiness(self) -> str: ...

    @property
    def submission(self) -> _Pipeline: ...

    @property
    def anchors(self) -> _Anchors: ...

    def run(self, coro: Coroutine[Any, Any, SubmitOutcome]) -> asyncio.Task[SubmitOutcome]: ...


class SubmitCutShort(Exception):
    """The OMS runtime's stop cancelled a submit it was draining: its outcome is not known."""


class NoPosition(Exception):
    """A `scale_in` found no open position to add to: nothing is sent (`no_position`)."""


class PositionUnread(Exception):
    """A `scale_in`'s position read failed or ran past its bound: no answer (`position_unread`)."""


def _cancelling() -> bool:
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


class RuleOrders:
    """The order port (module docstring): `runtime()` is the process's OMS, `None` while none is
    composed; `oms_enabled` is the `trading.oms_enabled` view (off while unread)."""

    def __init__(
        self, runtime: Callable[[], OrderRuntime | None], oms_enabled: Callable[[], bool]
    ) -> None:
        self._runtime, self._oms_enabled = runtime, oms_enabled

    async def submit(
        self, account_id: AccountId, context: SubmitContext, request: RequestBuilder
    ) -> SubmitOutcome:
        """The fire key's answer: a decided anchor's replay, whatever `request` would build now;
        for a fresh key, `request()` and its submit. The OMS's refusal is raised as itself,
        `SubmitCutShort` when the runtime's stop cancelled the submit, and what `request()` raises
        (`NoPosition`, `PositionUnread`) with nothing sent."""
        oms = self._runtime()
        if oms is None or oms.readiness != "ok":
            raise OmsNotReady
        found = await oms.anchors.lookup(
            context.actor.user_id, context.anchored_ref, context.request_sha256
        )
        if isinstance(found, Replay):
            return await oms.submission.answer_replay(account_id, found)
        if isinstance(found, InFlight | KeyReuse):
            raise found.refusal()
        built = await request()  # a fresh key only: a repeat never reads the position again
        if not built.reduce_only and self._oms_enabled() is not True:
            raise TradingDisabled
        task = oms.run(oms.submission.submit(built, context))
        try:
            return await asyncio.shield(task)  # the action's bound never cancels the submit
        except asyncio.CancelledError:
            if task.cancelled() and not _cancelling():  # the runtime's, not this call's
                raise SubmitCutShort from None
            raise


class PositionSides(Protocol):
    """The side of the open position a `scale_in` adds to, read as `owner` may read it; `None`
    when the account holds none on the symbol."""

    async def side(self, owner: PrincipalView, account_id: UUID, symbol: str) -> Side | None: ...


class _PositionReads(Protocol):
    async def positions(self, scope: AccountScope, query: Any) -> tuple[Any, ...]: ...


class StoredPositionSides:
    """`PositionSides` over the OMS's stored positions (`OmsReads.positions`, the private
    stream's rows, bounded by the reads themselves), in the owner's own scope: every account for
    an Owner, the action's account alone for anyone else, which the read re-checks."""

    def __init__(self, reads: _PositionReads) -> None:
        self._reads = reads

    async def side(self, owner: PrincipalView, account_id: UUID, symbol: str) -> Side | None:
        scope: AccountScope = (
            OwnerScope(owner.user_id)
            if owner.is_owner
            else GrantScope(owner.user_id, frozenset({account_id}))
        )
        query = PositionQuery(accounts=(account_id,), symbol=symbol)
        rows = await self._reads.positions(scope, query)
        for row in rows:
            side = _SIDES.get(str(row.side))
            if row.exchange_account_id == account_id and row.position_idx == 0 and row.size > 0:
                if side is not None:
                    return side
        return None


@dataclass(frozen=True, slots=True)
class PreparedEntry(Prepared):
    """One entry's request for one account, built once (`RuleEntryHandler.prepare`): the
    fingerprinted canonical request, and what `send` builds the OMS's request and context from,
    unchanged by a retry. Its repr shows none of it (C-12.6)."""

    params: EntryParams | None = field(default=None, repr=False)
    account_id: UUID | None = field(default=None, repr=False)
    symbol: str = field(default="", repr=False)
    ceiling: Decimal | None = field(default=None, repr=False)
    actor: SubmitActor | None = field(default=None, repr=False)
    owner: PrincipalView | None = field(default=None, repr=False)
    origin: RuleOrigin | None = field(default=None, repr=False)
    #: `prepare`'s refusal, which `send` answers with nothing sent (module docstring).
    refusal: HandlerAnswer | None = None


class RuleEntryHandler:
    """The handler of one entry type (module docstring), capability `oms_entry`."""

    capability: Capability = "oms_entry"

    def __init__(
        self,
        action_type: str,
        orders: RuleOrders,
        principals: PrincipalReads,
        positions: PositionSides | None = None,
    ) -> None:
        if action_type not in ENTRY_TYPES:
            raise ValueError(f"{action_type} is not an entry this handler places")
        self._type, self._orders = action_type, orders
        self._principals, self._positions = principals, positions

    def prepare(
        self, req: ActionRequest, account_id: UUID | None, *, max_notional_usd: Decimal | None
    ) -> Prepared:
        params = entry_params(self._type, req.payload.params)
        symbol = req.instance.symbol
        if params is None or account_id is None or not symbol:
            return prepared({"invalid": True})
        canonical = canonical_request(
            self._type, params, account_id=account_id, symbol=symbol,
            max_notional_usd=max_notional_usd,
        )  # fmt: skip
        fingerprinted = prepared(canonical)
        built = PreparedEntry(
            fingerprinted.request, fingerprinted.request_sha256, params=params,
            account_id=account_id, symbol=symbol, ceiling=max_notional_usd,
        )  # fmt: skip
        owner = self._principals.principal(req.owner)
        armer = None if req.armed_by is None else self._read(req.armed_by)
        owner_role, armer_role = _role(owner), system_role(_role(armer))
        if owner is None or owner_role is None or (req.armed_by is not None and armer_role is None):
            return replace(built, refusal=_PRINCIPAL_GONE)  # a view gone since check 5 read it
        try:
            origin = rule_origin(req, armer_role)
        except ValueError:  # its node id, the one part not minted by the engine (RuleOrigin)
            return replace(built, refusal=_ORIGIN_REFUSED)
        actor = SubmitActor(user_id=req.owner, role=owner_role)
        return replace(built, actor=actor, owner=owner, origin=origin)

    async def send(self, prepared: Prepared, *, client_ref: str) -> HandlerAnswer:
        entry = prepared
        if not isinstance(entry, PreparedEntry) or entry.params is None:
            return HandlerAnswer("refused", error_code="invalid_params")
        if entry.refusal is not None:  # decided at `prepare`: nothing is sent
            return entry.refusal
        if entry.actor is None or entry.origin is None:  # each set unless `prepare` refused
            return _PRINCIPAL_GONE
        if entry.account_id is None or entry.owner is None:  # each set with the actor
            return HandlerAnswer("refused", error_code="invalid_params")
        context = submit_context(
            owner=entry.actor.user_id, owner_role=entry.actor.role, origin=entry.origin,
            client_ref=client_ref, request_sha256=prepared.request_sha256,
        )  # fmt: skip
        build = partial(
            self._request, entry.params, entry.account_id, entry.owner, entry.symbol, entry.ceiling
        )
        try:
            outcome = await self._orders.submit(AccountId(entry.account_id), context, build)
        except NoPosition:
            return HandlerAnswer("refused", error_code="no_position")
        except PositionUnread:
            return HandlerAnswer("no_answer", error_code="position_unread")
        except SubmitCutShort:
            return HandlerAnswer("in_flight", error_code="submit_cut_short")
        except Exception as error:  # never `CancelledError`, which is no `Exception`
            return refusal_answer(error)
        return answer_of(outcome, ceiling=entry.ceiling)

    async def _request(
        self,
        params: EntryParams,
        account: UUID,
        owner: PrincipalView,
        symbol: str,
        ceiling: Decimal | None,
    ) -> OrderRequest:
        """A fresh key's request: a `place_order` on its own side, a `scale_in` on the side of
        the open position, read now, bounded (`NoPosition` with none open, `PositionUnread` when
        the read fails)."""
        side: Side | None = params.side if isinstance(params, PlaceOrderParams) else None
        if side is None:
            try:
                side = await self._position_side(owner, account, symbol)
            except Exception as lost:  # never `CancelledError`, which is no `Exception`
                raise PositionUnread from lost
            if side is None:
                raise NoPosition
        return order_request(
            params, account_id=account, symbol=symbol, side=side, max_notional_usd=ceiling
        )

    def _read(self, user: object) -> PrincipalView | None:
        try:
            return self._principals.principal(UUID(str(user)))
        except ValueError:
            return None

    async def _position_side(self, owner: PrincipalView, account: UUID, symbol: str) -> Side | None:
        if self._positions is None:
            raise LookupError("no position read is bound")
        async with asyncio.timeout(POSITION_READ_TIMEOUT_S):
            return await self._positions.side(owner, account, symbol)


def _role(view: PrincipalView | None) -> str | None:
    """The role a request names for a user: its view's while the view is active, else none."""
    return view.role if view is not None and view.active else None


def rule_order_handlers(
    runtime: Callable[[], OrderRuntime | None],
    *,
    oms_enabled: Callable[[], bool],
    principals: PrincipalReads,
    positions: PositionSides | None,
) -> dict[str, RuleEntryHandler]:
    """`place_order`'s and `scale_in`'s handlers over one order port, for
    `RulesService.bind(handlers=...)`."""
    orders = RuleOrders(runtime, oms_enabled)
    return {t: RuleEntryHandler(t, orders, principals, positions) for t in ENTRY_TYPES}
