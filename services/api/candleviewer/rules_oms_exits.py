"""The rule exits' handlers, bound at the composition root (E35-T12; 24 §11.5 "Exits", §11.6,
§11.9; the rulings of record on #5004, BQ-5 to BQ-10).

`rules` may not import `oms`, `accounts` or `storage` (`forbidden-M15`), so the exits' handlers
live here, beside the entries' (`rules_oms_orders`), and are bound the same way, through
`RulesService.bind(handlers=...)`, each with the capability its type declares. Each builds the
request once at `prepare`, with the owner as the principal and the rule as the origin, through the
entries' own adapter path (`rules_oms_requests.rule_origin`, the armer's role read by
`system_role`) and with the entries' own refusals (`rules_oms_orders`): an origin the OMS
refuses, a node id that is not a short identifier, is `failed` (`invalid_params`), never a raise,
its detail a generic sentence that never holds the id; a principal view gone since check 5 is
`permission`.

- **The reduce-only exits** (`oms_reduce`: `scale_out`, `flatten_position`,
  `flatten_all_positions`; BQ-5, BQ-6): the account's open positions, as the owner may read them
  (`OmsReads.positions`, the private stream's rows the close routes read too), within
  `POSITION_READ_TIMEOUT_S`, a read that fails `failed` (`position_unavailable`), nothing sent;
  then each position to close, in symbol order, as the close routes' own order (`close_request`:
  reduce-only, the closing side, intent `flatten`), through the entries' order port
  (`RuleOrders`, which builds it for a fresh key alone, and `OrderSubmission.submit`) with the
  rule's origin, so on `entry`, and never `protective`, so the OMS's switches judge it as any
  order and the routes' Partial-mode sweep stays theirs: the position's native stop stays in
  place. Each close has an anchor of its own (`uuid5` of the action's `client_ref` and the
  position's key); the first that does not take effect ends the account's action; a flat
  position is `ok` with no order. A symbol outside the rule's `scope.symbols`, when it names
  any, is never closed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from functools import partial
from typing import Any, Final, Protocol
from uuid import UUID, uuid5

from candleviewer.domain.primitives import AccountId
from candleviewer.oms.ports import RuleOrigin, SubmitActor
from candleviewer.oms.position_writes import CloseTerms, close_request
from candleviewer.oms.submit import OrderRequest, SubmitContext
from candleviewer.rules.executor.handlers import Capability, HandlerAnswer, Prepared, prepared
from candleviewer.rules.executor.params import FlattenParams, ReduceParams, reduce_params
from candleviewer.rules.executor.ports import PrincipalReads, PrincipalView
from candleviewer.rules.scope import ActionRequest
from candleviewer.rules_oms_orders import (
    _ORIGIN_REFUSED,
    _PRINCIPAL_GONE,
    POSITION_READ_TIMEOUT_S,
    OrderRuntime,
    RuleOrders,
    SubmitCutShort,
    _role,
)
from candleviewer.rules_oms_requests import answer_of, refusal_answer, rule_origin, system_role
from candleviewer.storage.repositories.accounts import AccountScope, GrantScope, OwnerScope
from candleviewer.storage.repositories.oms_reads import PositionQuery
from candleviewer.storage.repositories.positions import PositionRow

#: The types this module binds, with the capability each declares (`handlers.BINDINGS`).
REDUCE_TYPES: Final = ("scale_out", "flatten_position", "flatten_all_positions")
_HUNDRED: Final = Decimal(100)
#: The failed answers of an exit whose request cannot be built or whose positions are unread.
_INVALID: Final = HandlerAnswer("refused", error_code="invalid_params")
_UNREAD: Final = HandlerAnswer("refused", error_code="position_unavailable")


def owner_scope(owner: PrincipalView, account_id: UUID) -> AccountScope:
    """What the owner may read of the account, as the order route's own reads take it: every
    account for an Owner, the action's account alone for anyone else, which the read re-checks."""
    if owner.is_owner:
        return OwnerScope(owner.user_id)
    return GrantScope(owner.user_id, frozenset({account_id}))


@dataclass(frozen=True, slots=True)
class RulePrincipal:
    """The rule's request as the OMS takes it (24 §11.5 "The principal"): the owner as the
    principal, the owner's snapshot, and the rule as the origin (`RuleOrigin`)."""

    actor: SubmitActor
    owner: PrincipalView
    origin: RuleOrigin


def rule_principal(principals: PrincipalReads, req: ActionRequest) -> RulePrincipal | HandlerAnswer:
    """The owner and the armer read again from the views check 5 read, as the entries' handlers
    read them (`rules_oms_orders`): either gone since is `permission`; the origin built through the
    entries' path (`rule_origin`), a refused one `failed` (`invalid_params`), never a raise."""
    owner = principals.principal(req.owner)
    armer = None if req.armed_by is None else _read(principals, req.armed_by)
    owner_role, armer_role = _role(owner), system_role(_role(armer))
    if owner is None or owner_role is None or (req.armed_by is not None and armer_role is None):
        return _PRINCIPAL_GONE  # a view gone since check 5 read it, as the entries refuse
    try:
        origin = rule_origin(req, armer_role)
    except ValueError:  # its node id, the one part the engine does not mint (`RuleOrigin`)
        return _ORIGIN_REFUSED
    return RulePrincipal(SubmitActor(user_id=req.owner, role=owner_role), owner, origin)


def _read(principals: PrincipalReads, user: object) -> PrincipalView | None:
    try:
        return principals.principal(UUID(str(user)))
    except ValueError:
        return None


class OpenPositions(Protocol):
    """The account's open positions, as `owner` may read them."""

    async def open_positions(
        self, owner: PrincipalView, account_id: UUID
    ) -> Sequence[PositionRow]: ...


class _PositionReads(Protocol):
    async def positions(self, scope: AccountScope, query: Any) -> tuple[PositionRow, ...]: ...


class StoredOpenPositions:
    """`OpenPositions` over the OMS's stored positions (`OmsReads.positions`, the private stream's
    rows, bounded by the reads themselves), in the owner's own scope (`owner_scope`)."""

    def __init__(self, reads: _PositionReads) -> None:
        self._reads = reads

    async def open_positions(self, owner: PrincipalView, account_id: UUID) -> Sequence[PositionRow]:
        query = PositionQuery(accounts=(account_id,), open_only=True)
        rows = await self._reads.positions(owner_scope(owner, account_id), query)
        return tuple(row for row in rows if row.exchange_account_id == account_id)


@dataclass(frozen=True, slots=True)
class PreparedExit(Prepared):
    """One exit's request for one account, built once (`prepare`): the fingerprinted canonical
    request and what `send` acts on, unchanged by a retry; or the refusal `prepare` decided. Its
    repr shows none of it (C-12.6)."""

    params: ReduceParams | None = field(default=None, repr=False)
    account_id: UUID | None = field(default=None, repr=False)
    symbol: str | None = field(default=None, repr=False)
    scope_symbols: frozenset[str] = field(default=frozenset(), repr=False)
    principal: RulePrincipal | None = field(default=None, repr=False)
    refused: HandlerAnswer | None = None


def prepare_exit(
    action_type: str,
    params: ReduceParams | None,
    req: ActionRequest,
    account_id: UUID | None,
    principals: PrincipalReads,
    *,
    needs_symbol: bool,
) -> Prepared:
    """An exit's request (module docstring): `invalid_params` for parameters that do not parse or
    a request with no account (or no symbol where it needs one); else the canonical request,
    fingerprinted once, with the principal or the refusal `rule_principal` decided."""
    symbol = req.instance.symbol
    if params is None or account_id is None or (needs_symbol and not symbol):
        return prepared({"invalid": True})
    canonical: Mapping[str, Any] = {
        "action_type": action_type, "account_id": account_id, "symbol": symbol,
        "params": params.model_dump(),
    }  # fmt: skip
    fingerprinted = prepared(canonical)
    built = PreparedExit(
        fingerprinted.request, fingerprinted.request_sha256, params=params,
        account_id=account_id, symbol=symbol, scope_symbols=frozenset(req.rule_scope.symbols),
    )  # fmt: skip
    principal = rule_principal(principals, req)
    if isinstance(principal, HandlerAnswer):
        return replace(built, refused=principal)
    return replace(built, principal=principal)


def admitted_exit(prepared: Prepared) -> PreparedExit | HandlerAnswer:
    """The prepared exit `send` acts on, or the answer that ends it before any read or send."""
    if not isinstance(prepared, PreparedExit) or prepared.params is None:
        return _INVALID
    if prepared.refused is not None:
        return prepared.refused
    if prepared.principal is None or prepared.account_id is None:  # each set with the params
        return _INVALID
    return prepared


async def _close(row: PositionRow, terms: CloseTerms) -> OrderRequest:
    """The close routes' own order for `row` (`close_request`), which `RuleOrders.submit` builds
    for a fresh key alone, as it builds an entry's: a repeat replays its anchor's answer."""
    return close_request(row, terms)


def _position_key(row: PositionRow) -> str:
    return f"{row.symbol}:{row.position_idx}"


class RuleReduceHandler:
    """The handler of one reduce-only exit (module docstring), capability `oms_reduce`."""

    capability: Capability = "oms_reduce"

    def __init__(
        self,
        action_type: str,
        orders: RuleOrders,
        principals: PrincipalReads,
        positions: OpenPositions | None,
    ) -> None:
        if action_type not in REDUCE_TYPES:
            raise ValueError(f"{action_type} is not a reduce-only exit")
        self._type, self._orders = action_type, orders
        self._principals, self._positions = principals, positions

    def prepare(
        self, req: ActionRequest, account_id: UUID | None, *, max_notional_usd: Decimal | None
    ) -> Prepared:
        params = reduce_params(self._type, req.payload.params)
        needs_symbol = self._type == "scale_out" or (
            self._type == "flatten_position"
            and not (isinstance(params, FlattenParams) and params.symbols)
        )
        return prepare_exit(
            self._type, params, req, account_id, self._principals, needs_symbol=needs_symbol
        )

    async def send(self, prepared: Prepared, *, client_ref: str) -> HandlerAnswer:
        exit_ = admitted_exit(prepared)
        if isinstance(exit_, HandlerAnswer):
            return exit_
        principal, account = exit_.principal, exit_.account_id
        if principal is None or account is None:  # `admitted_exit` holds both
            return _INVALID
        try:
            held = await self._read(principal.owner, account)
        except Exception:  # never `CancelledError`, which is no `Exception`
            return _UNREAD
        targets = self._targets(exit_, held)
        if not targets:  # flat: the exit's end state holds (BQ-6)
            return HandlerAnswer("done")
        key, first = UUID(client_ref), None
        for row in targets:
            terms = self._terms(exit_.params, row) if exit_.params is not None else _INVALID
            if isinstance(terms, HandlerAnswer):
                return terms
            context = SubmitContext(
                actor=principal.actor, client_ref=key, request_sha256=prepared.request_sha256,
                anchor_ref=uuid5(key, _position_key(row)), origin=principal.origin,
            )  # fmt: skip
            try:
                outcome = await self._orders.submit(
                    AccountId(account), context, partial(_close, row, terms)
                )
            except SubmitCutShort:
                return HandlerAnswer("in_flight", error_code="submit_cut_short")
            except Exception as error:  # never `CancelledError`, which is no `Exception`
                return refusal_answer(error)
            answer = answer_of(outcome)
            if answer.answer != "accepted":
                return answer
            first = first or answer
        return first or HandlerAnswer("done")

    async def _read(self, owner: PrincipalView, account: UUID) -> Sequence[PositionRow]:
        if self._positions is None:
            raise LookupError("no position read is bound")
        async with asyncio.timeout(POSITION_READ_TIMEOUT_S):
            return await self._positions.open_positions(owner, account)

    def _targets(self, exit_: PreparedExit, held: Sequence[PositionRow]) -> list[PositionRow]:
        """The open positions to close, in symbol order (module docstring)."""
        params = exit_.params
        named = params.symbols if isinstance(params, FlattenParams) else None
        wanted: set[str | None] | None = None if named is None else set(named)
        if wanted is None and self._type != "flatten_all_positions":
            wanted = {exit_.symbol}
        rows = [
            row for row in held
            if row.side in ("Buy", "Sell") and row.size > 0
            and (wanted is None or row.symbol in wanted)
            and (not exit_.scope_symbols or row.symbol in exit_.scope_symbols)
        ]  # fmt: skip
        return sorted(rows, key=lambda row: (row.symbol, row.position_idx))

    @staticmethod
    def _terms(params: ReduceParams, row: PositionRow) -> CloseTerms | HandlerAnswer:
        """A flatten's close of the whole position; a `scale_out`'s percent of it, or its
        quantity, never above the position's size (`exceeds_position`, nothing sent)."""
        if isinstance(params, FlattenParams):
            return CloseTerms("market", pct=_HUNDRED)
        if params.qty_pct is not None:
            return CloseTerms("market", pct=params.qty_pct)
        if params.qty is None or params.qty > row.size:
            return HandlerAnswer("refused", error_code="exceeds_position")
        return CloseTerms("market", qty=params.qty)


def rule_reduce_handlers(
    runtime: Callable[[], OrderRuntime | None],
    *,
    oms_enabled: Callable[[], bool],
    principals: PrincipalReads,
    positions: OpenPositions | None,
) -> dict[str, RuleReduceHandler]:
    """The three reduce-only exits' handlers over one order port, for
    `RulesService.bind(handlers=...)`."""
    orders = RuleOrders(runtime, oms_enabled)
    return {t: RuleReduceHandler(t, orders, principals, positions) for t in REDUCE_TYPES}
