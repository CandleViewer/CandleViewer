"""The rule entries' handlers and their order port, bound at the composition root (E35-T11 slice
3c; 24 §11.5, §11.9; the rulings of #863 BQ-2 to BQ-5, BQ-9, BQ-17, and of #5003 BQ-4 and BQ-7).

`place_order` and `scale_in` are bound through `RulesService.bind(handlers=...)` (the seam E35-T13
opened, BQ-2 of #5005), each with the `oms_entry` capability its type declares. The executor
calls them per resolved account, after checks 1 to 8 and the records written ahead:

- `prepare` (pure, synchronous) reads the typed parameters (`invalid_params` when they do not
  parse, or when the scope instance names no symbol), the owner's and the armer's roles from the
  same principal views check 5 read (`permission` when either has gone since), and builds the
  request once, fingerprinted once (`request_sha256`), with the owner as the principal and the
  rule as the origin (`rules_oms_requests`); an origin the OMS refuses, a node id that is not a
  short identifier, is `blocked` (`unavailable`) with a detail that never holds the id, never a
  raise (fail closed);
- `send` hands it over under the fire key's `client_ref`, the same request and fingerprint for a
  `retry_once` retry, and maps the answer (`answer_of`, `refusal_answer`). A `scale_in` adds to
  the open position on the instance's symbol, on its side, read from the account's stored
  position (`StoredPositionSides`, bounded): none open is `refused` (`no_position`), nothing sent,
  and a read that fails is `no_answer`, retried at most once as any call that got no answer.

The order port (`RuleOrders`) admits a request as the `placeOrder` route does, and goes no further
than the route: the OMS ready, the anchor's lookup by the owner's key (a decided anchor's answer
replayed, one in flight or another body refused, nothing sent), and `trading.oms_enabled`, the OMS
admissions' own rollout flag, for an entry. The pipeline then runs as a task the OMS runtime
tracks and drains at its stop (`OmsRuntime.run`), on the order lane, its own synchronous checks
last (the clock halt, sizing against the profile, the risk gate, the trading switches, the rate
headroom); the action awaits it shielded, so its bound, above the pipeline's, never cancels it
(BQ-7): a submit still running at that bound is `unknown`, never sent again, and one the
runtime's stop cut short is in flight, never re-sent. Rule actions run on demo and testnet only:
check 4 refuses a live account, and the OMS's own live gate stays the last fence (C-2.11).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field, replace
from decimal import Decimal
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
from candleviewer.rules.executor.results import NODE_ID, OMS_DETAIL, BlockedBy
from candleviewer.rules.scope import ActionRequest
from candleviewer.rules_oms_requests import (
    answer_of,
    canonical_request,
    order_request,
    refusal_answer,
    rule_origin,
    submit_context,
)
from candleviewer.storage.repositories.accounts import AccountScope, GrantScope, OwnerScope
from candleviewer.storage.repositories.oms_reads import PositionQuery

#: The two types this module binds, each `oms_entry` (`handlers.BINDINGS`).
ENTRY_TYPES: Final = ("place_order", "scale_in")
#: The bound on a `scale_in`'s position read, a store read's.
POSITION_READ_TIMEOUT_S: Final = 2.0
_SIDES: Final[dict[str, Side]] = {"Buy": "buy", "Sell": "sell"}


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

    async def submit(self, request: OrderRequest, context: SubmitContext) -> SubmitOutcome:
        """The request's answer, or the OMS's refusal raised as itself; `SubmitCutShort` when the
        runtime's stop cancelled the submit."""
        oms = self._runtime()
        if oms is None or oms.readiness != "ok":
            raise OmsNotReady
        found = await oms.anchors.lookup(
            context.actor.user_id, context.anchored_ref, context.request_sha256
        )
        if isinstance(found, Replay):
            return await oms.submission.answer_replay(request.account_id, found)
        if isinstance(found, InFlight | KeyReuse):
            raise found.refusal()
        if not request.reduce_only and self._oms_enabled() is not True:
            raise TradingDisabled
        task = oms.run(oms.submission.submit(request, context))
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
    refused_by: BlockedBy | None = None
    refused_detail: str | None = None


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
        owner_role, armer_role = _role(owner), _role(armer)
        if owner is None or owner_role is None or (req.armed_by is not None and armer_role is None):
            return replace(built, refused_by="permission")  # a view gone since check 5 read it
        try:
            origin = rule_origin(req, armer_role)
        except ValueError:  # its node id, the one part not minted by the engine (RuleOrigin)
            return replace(built, refused_by="unavailable", refused_detail=OMS_DETAIL[NODE_ID])
        actor = SubmitActor(user_id=req.owner, role=owner_role)
        return replace(built, actor=actor, owner=owner, origin=origin)

    async def send(self, prepared: Prepared, *, client_ref: str) -> HandlerAnswer:
        entry = prepared
        if not isinstance(entry, PreparedEntry) or entry.params is None:
            return HandlerAnswer("refused", error_code="invalid_params")
        if entry.refused_by is not None or entry.actor is None or entry.origin is None:
            blocked_by = entry.refused_by or "permission"
            return HandlerAnswer("refused", blocked_by=blocked_by, detail=entry.refused_detail)
        if entry.account_id is None or entry.owner is None:  # each set with the actor
            return HandlerAnswer("refused", error_code="invalid_params")
        params = entry.params
        side: Side | None = params.side if isinstance(params, PlaceOrderParams) else None
        if side is None:
            try:
                side = await self._position_side(entry.owner, entry.account_id, entry.symbol)
            except Exception:  # never `CancelledError`, which is no `Exception`
                return HandlerAnswer("no_answer", error_code="position_unread")
            if side is None:
                return HandlerAnswer("refused", error_code="no_position")
        request = order_request(
            params, account_id=entry.account_id, symbol=entry.symbol, side=side,
            max_notional_usd=entry.ceiling,
        )  # fmt: skip
        context = submit_context(
            owner=entry.actor.user_id, owner_role=entry.actor.role, origin=entry.origin,
            client_ref=client_ref, request_sha256=prepared.request_sha256,
        )  # fmt: skip
        try:
            outcome = await self._orders.submit(request, context)
        except SubmitCutShort:
            return HandlerAnswer("in_flight", error_code="submit_cut_short")
        except Exception as error:  # never `CancelledError`, which is no `Exception`
            return refusal_answer(error)
        return answer_of(outcome, ceiling=entry.ceiling)

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
