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
  position's key). Every position is tried, as an exit only reduces risk: a close that does not
  take effect ends that position alone, and the exit stops early only at a refusal that belongs
  to the account (`ACCOUNT_REFUSALS`) or at a close the OMS runtime's stop cuts short; its answer
  is then the first close that did not take effect, its detail counting the positions not closed.
  A `scale_out` quantity is judged as its close is built, for a fresh key alone (`ExceedsPosition`,
  as K4b's `NoPosition`), so a repeat is answered from its anchor. A flat position is `ok` with no
  order. A symbol outside the rule's `scope.symbols`, when it names any, is never closed.
- **The cancels and the amends** (`oms_cancel`, `oms_amend`; BQ-7 to BQ-9): the rule's own
  resting entries alone (`RuleEntries`: its groups' orders, `placed`, open, neither reduce-only
  nor a recorded stop nor an algo's child), on the action's account, read within
  `ENTRY_READ_TIMEOUT_S`. `cancel_order` takes those on the instance's symbol and
  `cancel_all_orders` those on every symbol, narrowed by `purpose`; each gets one
  `cancel_admitted` with the reason `rule` (`entry`), and a selection past `RULE_ENTRIES_LIMIT`
  is never `ok` (`too_many_orders`). BQ-7's reading of record: never a user's
  manual entry, another rule's order or an algo's child, never a stop, a take-profit or a
  reduce-only exit (C-2.6). The amends move each resting limit entry of the rule on the
  instance's symbol through the exit service's `scope` and `amend`, the rule's request
  (`ExitCaller.origin`), its ratchet last; the level is `stop_level`'s.
- **Check 8** (`RuleStopCheck`; BQ-2): the amend writer's own comparison (`oms/stop_ratchet.py`)
  on the level each target would take, against its own stop and the position's stop at the
  venue on the same side; a loosening is `native_sl` with what `sl.loosen_refused` records; a
  move with no target is the position's, `unavailable`; a cancel naming a stop-loss `native_sl`.
- **The circuit breaker's cancels** (`RuleBreakerCancels`; BQ-10): the tripped rule's resting
  entries on every account of the environment, each `cancel_admitted` with the reason
  `rule_circuit_breaker` (`critical`), as the owner and with no principal check (an exit is
  never gated, 24 §8.10), never a stop, a take-profit or a reduce-only exit whatever the read
  hands it; those not done, and a selection past the cap, are counted in one more `system_events`
  row under the node as the origin names it, and a trip whose cancels cannot start pages.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from functools import partial
from typing import Any, Final, Literal, Protocol
from uuid import UUID, uuid5

import structlog

from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.oms.errors import AccountScopeDenied, OmsNotReady
from candleviewer.oms.exits import AmendTerms, CancelReason, ExitCaller, ExitOutcome
from candleviewer.oms.ports import RuleOrigin, StopOffset, SubmitActor
from candleviewer.oms.position_writes import CloseTerms, close_request
from candleviewer.oms.stop_ratchet import loosens, ratchet_refusal
from candleviewer.oms.submit import OrderRequest, SubmitContext
from candleviewer.rules.executor.handlers import Capability, HandlerAnswer, Prepared, prepared
from candleviewer.rules.executor.params import (
    CancelParams,
    ExitParams,
    FlattenParams,
    ScaleOutParams,
    StopMoveParams,
    exit_params,
    reduce_params,
)
from candleviewer.rules.executor.ports import (
    STOP_ADMITTED,
    Loosening,
    PrincipalReads,
    PrincipalView,
    StopVerdict,
)
from candleviewer.rules.executor.results import BLOCKED_DETAIL, POSITION_STOP
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
from candleviewer.storage.repositories.orders import OrderRow, OrderSide, ScopedOrder
from candleviewer.storage.repositories.positions import PositionRow

#: The types this module binds, with the capability each declares (`handlers.BINDINGS`).
REDUCE_TYPES: Final = ("scale_out", "flatten_position", "flatten_all_positions")
_HUNDRED: Final = Decimal(100)
#: The failed answers of an exit whose request cannot be built or whose positions are unread.
_INVALID: Final = HandlerAnswer("refused", error_code="invalid_params")
_UNREAD: Final = HandlerAnswer("refused", error_code="position_unavailable")
_EXCEEDS: Final = HandlerAnswer("refused", error_code="exceeds_position")
#: The refusals that belong to the account, not to one position (24 §11.5 "Exits"): an exit stops
#: at one, as no later close of the account would pass it; any other refusal ends one position.
ACCOUNT_REFUSALS: Final = frozenset({"rate_limited", "kill_switch", "order_entry"})


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def owner_scope(owner: PrincipalView, account_id: UUID) -> AccountScope:
    """What the owner may read of the account, as the order route's own reads take it: every
    account for an Owner, the action's account alone for anyone else, which the read re-checks."""
    if owner.is_owner:
        return OwnerScope(owner.user_id)
    return GrantScope(owner.user_id, frozenset({account_id}))


@dataclass(frozen=True, slots=True)
class RulePrincipal:
    """The rule's request as the OMS takes it (24 §11.5 "The principal"): the owner as the
    principal, the owner's snapshot, and the rule as the origin (`RuleOrigin`). Its repr shows none
    of them, as `PreparedExit`'s does not (C-12.6)."""

    actor: SubmitActor = field(repr=False)
    owner: PrincipalView = field(repr=False)
    origin: RuleOrigin = field(repr=False)


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

    params: ExitParams | None = field(default=None, repr=False)
    account_id: UUID | None = field(default=None, repr=False)
    symbol: str | None = field(default=None, repr=False)
    scope_symbols: frozenset[str] = field(default=frozenset(), repr=False)
    principal: RulePrincipal | None = field(default=None, repr=False)
    refused: HandlerAnswer | None = None
    #: The rule, whose entries a cancel or an amend reads, and the fire's snapshot an amend's
    #: level reads (slice 3e); the snapshot is never shown (21 §3.4.3).
    rule_id: str = field(default="", repr=False)
    snapshot: Mapping[str, object] = field(default_factory=dict, repr=False)


def prepare_exit(
    action_type: str,
    params: ExitParams | None,
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


class ExceedsPosition(Exception):
    """A `scale_out` quantity above the position it closes (`exceeds_position`, nothing sent),
    judged as the close is built (`_close`), so for a fresh key alone, as K4b's `NoPosition`."""


async def _close(row: PositionRow, terms: CloseTerms) -> OrderRequest:
    """The close routes' own order for `row` (`close_request`), which `RuleOrders.submit` builds
    for a fresh key alone, as it builds an entry's: a repeat replays its anchor's answer whatever
    the position holds now, and only a fresh key's quantity is judged against it."""
    if terms.qty is not None and terms.qty > row.size:
        raise ExceedsPosition
    return close_request(row, terms)


def _not_closed(first: HandlerAnswer, missed: int, of: int) -> HandlerAnswer:
    """The answer of an account whose exit left `missed` of its `of` positions not closed: the
    first close that did not take effect, its detail, when there was more than one position to
    close, counting the ones not closed (a count, never a symbol or an id; C-12.6)."""
    if of < 2:
        return first
    verb = "was" if missed == 1 else "were"
    return replace(first, detail=f"Not done — {missed} of {of} positions {verb} not closed.")


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
        except AccountScopeDenied:  # the owner may no longer read the account: as check 5 refuses
            return _PRINCIPAL_GONE
        except Exception:  # never `CancelledError`, which is no `Exception`
            return _UNREAD
        targets = self._targets(exit_, held)
        if not targets:  # flat: the exit's end state holds (BQ-6)
            return HandlerAnswer("done")
        key = UUID(client_ref)
        taken: list[HandlerAnswer] = []
        missed: list[HandlerAnswer] = []
        for row in targets:  # every position is tried: an exit only reduces risk (24 §11.5)
            answer = await self._close_one(exit_, principal, account, row, key, prepared)
            (taken if answer.answer == "accepted" else missed).append(answer)
            if answer.blocked_by in ACCOUNT_REFUSALS or answer.error_code == "submit_cut_short":
                break  # the account's refusal, or the runtime's stop: no later close is sent
        if not missed:
            return taken[0]
        return _not_closed(missed[0], len(targets) - len(taken), len(targets))

    async def _close_one(
        self,
        exit_: PreparedExit,
        principal: RulePrincipal,
        account: UUID,
        row: PositionRow,
        key: UUID,
        prepared: Prepared,
    ) -> HandlerAnswer:
        """One position's close, under an anchor of its own, as its answer: never a raise."""
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
        except ExceedsPosition:
            return _EXCEEDS
        except SubmitCutShort:
            return HandlerAnswer("in_flight", error_code="submit_cut_short")
        except Exception as error:  # never `CancelledError`, which is no `Exception`
            return refusal_answer(error)
        return answer_of(outcome)

    async def _read(self, owner: PrincipalView, account: UUID) -> Sequence[PositionRow]:
        if self._positions is None:
            raise LookupError("no position read is bound")
        async with asyncio.timeout(POSITION_READ_TIMEOUT_S):
            return await self._positions.open_positions(owner, account)

    def _targets(self, exit_: PreparedExit, held: Sequence[PositionRow]) -> list[PositionRow]:
        """The open positions to close, in symbol order, then position index (module docstring)."""
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
    def _terms(params: ExitParams, row: PositionRow) -> CloseTerms | HandlerAnswer:
        """A flatten's close of the whole position; a `scale_out`'s percent of it, or its
        quantity, which `_close` judges against the position's size for a fresh key alone."""
        if isinstance(params, FlattenParams):
            return CloseTerms("market", pct=_HUNDRED)
        if not isinstance(params, ScaleOutParams):
            return _INVALID
        if params.qty_pct is not None:
            return CloseTerms("market", pct=params.qty_pct)
        if params.qty is None:  # the parameters hold one of the two
            return _INVALID
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


# --- slice 3e: the cancels, the amends, check 8 and the breaker's cancels -------------------------

#: The cancels' and the amends' types (`handlers.BINDINGS`: `oms_cancel`, `oms_amend`).
CANCEL_TYPES: Final = ("cancel_order", "cancel_all_orders")
AMEND_TYPES: Final = ("modify_stop_loss", "modify_take_profit", "tighten_stop")
#: A read of a rule's resting entries: at most this many rows, within this bound, a store read's.
RULE_ENTRIES_LIMIT: Final = 500
ENTRY_READ_TIMEOUT_S: Final = 2.0
#: Each breaker cancel's wait, past which it is counted not done; the exit service, whose task the
#: cancel is, still settles it (`OrderExits._shielded`).
BREAKER_CANCEL_TIMEOUT_S: Final = 15.0
#: The intents a rule's cancel may select (C-2.6: never a stop, a take-profit or a reduce-only
#: exit, which the read leaves out too).
_CANCELLABLE_INTENTS: Final = frozenset({"entry", "scale_in"})
#: The OMS's refusals that sent nothing and may pass later: `retry_once` may retry them (24 §11.9).
_NOT_SENT: Final = frozenset({"oms_not_ready", "store_unavailable", "audit_unavailable"})
#: A cancel whose selection runs past `RULE_ENTRIES_LIMIT` (the read holds one row more): the
#: orders within the cap are tried, and the action is never `ok` (24 §11.5 "Exits").
_TOO_MANY: Final = HandlerAnswer("refused", error_code="too_many_orders")
_NO_TARGET: Final = HandlerAnswer(
    "refused", blocked_by="unavailable", detail=BLOCKED_DETAIL[POSITION_STOP]
)
_ENTRIES_UNREAD: Final = HandlerAnswer("pre_anchor", error_code="store_unavailable")
_OMS_NOT_READY: Final = HandlerAnswer("pre_anchor", error_code="oms_not_ready")


class RuleEntries(Protocol):
    """A rule's resting entries (`SqlAlchemyOrderStore.rule_resting_entries`): its groups' orders
    of `environment`, on the account and the symbol when named."""

    async def rule_resting_entries(
        self,
        rule_id: UUID,
        environment: Environment,
        *,
        account_id: UUID | None = None,
        symbol: str | None = None,
        limit: int,
    ) -> tuple[OrderRow, ...]: ...


class _Exits(Protocol):
    """`OnLaneExits` as the rule's cancels and amends drive it."""

    async def scope(self, caller: ExitCaller, order_id: UUID) -> ScopedOrder | ExitOutcome: ...

    async def cancel_admitted(
        self,
        row: OrderRow,
        *,
        actor: SubmitActor,
        reason: CancelReason,
        request_id: UUID | None,
        origin: RuleOrigin | None = None,
    ) -> ExitOutcome: ...

    async def amend(
        self,
        scoped: ScopedOrder,
        terms: AmendTerms,
        *,
        caller: ExitCaller,
        expected_seq: int | None,
    ) -> ExitOutcome: ...


class ExitRuntime(Protocol):
    """`oms_wiring.OmsRuntime` as the exits read it: its exit service, `OmsNotReady` before it is
    composed."""

    @property
    def exits(self) -> _Exits: ...


def _decimal(value: object) -> Decimal | None:
    return value if isinstance(value, Decimal) and value.is_finite() else None


def stop_level(
    params: StopMoveParams,
    *,
    kind: Literal["stop_loss", "take_profit"],
    side: OrderSide,
    price: Decimal | None,
    snapshot: Mapping[str, object],
) -> Decimal | None:
    """The level an amend sets on a `side` entry priced at `price` (24 §11.5 "Exits"; BQ-9), or
    `None` when the snapshot cannot give it (`metric_unavailable`): `absolute` the `value`;
    `offset_from_entry` `value` from the order's price; `offset_from_price` `value` from the
    snapshot's `price`; `atr` `value` times the snapshot's `atr` from the order's price;
    `structure` `value` beyond the snapshot's `swing_low` (a long's stop, a short's take-profit)
    or `swing_high` (a short's stop, a long's take-profit), a stop on the far side and a
    take-profit on the near side. Each offset goes away from its base, on the protective side for
    a stop (below a long's) and the profitable side for a take-profit (above a long's)."""
    value, long = params.value, side == "Buy"
    away = Decimal(-1) if (kind == "stop_loss") == long else Decimal(1)
    if params.mode == "absolute":
        return value
    if params.mode == "structure":
        low = (kind == "stop_loss") == long
        held = _decimal(snapshot.get("swing_low" if low else "swing_high"))
        if held is None:
            return None
        return held + away * value if kind == "stop_loss" else held - away * value
    if params.mode == "offset_from_price":
        base = _decimal(snapshot.get("price"))
        return None if base is None else base + away * value
    if price is None:
        return None
    if params.mode == "atr":
        atr = _decimal(snapshot.get("atr"))
        return None if atr is None else price + away * value * atr
    return price + away * value  # `offset_from_entry`


async def read_entries(
    entries: RuleEntries | None,
    rule_id: str,
    environment: Environment,
    *,
    account_id: UUID | None,
    symbol: str | None,
) -> tuple[OrderRow, ...]:
    """The rule's resting entries, within `ENTRY_READ_TIMEOUT_S`, up to one row past
    `RULE_ENTRIES_LIMIT`, so a selection the cap stops is seen as such (`capped`); a raise (an
    unbound read, a rule id that is no UUID, a store that does not answer) for the caller to
    refuse on."""
    if entries is None:
        raise LookupError("no read of the rule's entries is bound")
    async with asyncio.timeout(ENTRY_READ_TIMEOUT_S):
        return await entries.rule_resting_entries(
            UUID(rule_id), environment, account_id=account_id, symbol=symbol,
            limit=RULE_ENTRIES_LIMIT + 1,
        )  # fmt: skip


def capped(rows: Sequence[OrderRow]) -> tuple[Sequence[OrderRow], bool]:
    """The rows within `RULE_ENTRIES_LIMIT`, and whether the selection ran past it."""
    return rows[:RULE_ENTRIES_LIMIT], len(rows) > RULE_ENTRIES_LIMIT


def amend_targets(rows: Sequence[OrderRow]) -> list[OrderRow]:
    """The entries an amend moves: the rule's resting limit entries, `submitted`."""
    resting = ("entry", "Limit", "submitted")
    return [row for row in rows if (row.intent, row.order_type, row.lifecycle_state) == resting]


def exit_answer(outcome: ExitOutcome, order_id: UUID) -> HandlerAnswer:
    """The exit service's answer as a `HandlerAnswer` (24 §11.5, §11.9): taken is `accepted`
    with its order; not known is `in_flight`, never sent again; a refusal that sent nothing and
    may pass later is `pre_anchor`; a rate limit `rate_limited`; the amend ratchet's
    `risk_limit_breached` (a looser stop, the writer's own refusal) `native_sl`; any other refusal
    `refused` with its code, never its text."""
    ids: dict[str, Any] = {"order_id": order_id}
    if outcome.kind == "accepted":
        return HandlerAnswer("accepted", **ids)
    if outcome.kind == "unknown":
        return HandlerAnswer("in_flight", error_code=outcome.unknown_reason, **ids)
    code = outcome.code or "refused"
    if code in _NOT_SENT:
        return HandlerAnswer("pre_anchor", error_code=code, **ids)
    if outcome.status == 429:
        return HandlerAnswer("refused", error_code=code, blocked_by="rate_limited", **ids)
    if code == "risk_limit_breached":
        return HandlerAnswer("refused", error_code=code, blocked_by="native_sl", **ids)
    return HandlerAnswer("refused", error_code=code, **ids)


def _exits_of(runtime: Callable[[], ExitRuntime | None]) -> _Exits | None:
    oms = runtime()
    if oms is None:
        return None
    try:
        return oms.exits
    except OmsNotReady:
        return None


class _ExitBase:
    """What the cancels' and the amends' handlers share: the request built once
    (`prepare_exit`), the rule's resting entries read, the exit service."""

    capability: Capability

    def __init__(
        self,
        action_type: str,
        runtime: Callable[[], ExitRuntime | None],
        principals: PrincipalReads,
        entries: RuleEntries | None,
        environment: Environment,
    ) -> None:
        self._type, self._runtime, self._principals = action_type, runtime, principals
        self._entries, self._environment = entries, environment

    def prepare(
        self, req: ActionRequest, account_id: UUID | None, *, max_notional_usd: Decimal | None
    ) -> Prepared:
        params = exit_params(self._type, req.payload.params)
        needs_symbol = self._type != "cancel_all_orders"
        built = prepare_exit(
            self._type, params, req, account_id, self._principals, needs_symbol=needs_symbol
        )
        if isinstance(built, PreparedExit):  # the rule and the fire's snapshot, for `send`
            return replace(built, rule_id=req.rule_id, snapshot=req.metric_values)
        return built

    async def _rows(self, exit_: PreparedExit, *, symbol: str | None) -> tuple[OrderRow, ...]:
        return await read_entries(
            self._entries, exit_.rule_id, self._environment, account_id=exit_.account_id,
            symbol=symbol,
        )  # fmt: skip


class RuleCancelHandler(_ExitBase):
    """A rule's cancel (module docstring), capability `oms_cancel`."""

    capability: Capability = "oms_cancel"

    def __init__(
        self,
        action_type: str,
        runtime: Callable[[], ExitRuntime | None],
        principals: PrincipalReads,
        entries: RuleEntries | None,
        environment: Environment,
    ) -> None:
        if action_type not in CANCEL_TYPES:
            raise ValueError(f"{action_type} is not a rule's cancel")
        super().__init__(action_type, runtime, principals, entries, environment)

    async def send(self, prepared: Prepared, *, client_ref: str) -> HandlerAnswer:
        exit_ = admitted_exit(prepared)
        if isinstance(exit_, HandlerAnswer):
            return exit_
        principal, params = exit_.principal, exit_.params
        if principal is None or not isinstance(params, CancelParams):
            return _INVALID
        symbol = exit_.symbol if self._type == "cancel_order" else None
        try:
            rows, overflow = capped(await self._rows(exit_, symbol=symbol))
        except Exception:  # never `CancelledError`, which is no `Exception`
            return _ENTRIES_UNREAD
        wanted = _CANCELLABLE_INTENTS if params.purpose is None else {params.purpose}
        chosen = [r for r in rows if r.intent in wanted and r.intent in _CANCELLABLE_INTENTS]
        if not chosen:
            return _TOO_MANY if overflow else HandlerAnswer("done")
        exits = _exits_of(self._runtime)
        if exits is None:
            return _OMS_NOT_READY
        first: HandlerAnswer | None = None
        worst: HandlerAnswer | None = None
        for row in chosen:  # every selected order is tried; the first not taken is the answer
            try:
                outcome = await exits.cancel_admitted(
                    row, actor=principal.actor, reason="rule", request_id=None,
                    origin=principal.origin,
                )  # fmt: skip
            except OmsNotReady:
                answer = _OMS_NOT_READY
            except Exception as error:  # never `CancelledError`, which is no `Exception`
                answer = refusal_answer(error)
            else:
                answer = exit_answer(outcome, row.id)
            if answer.answer == "accepted":
                first = first or answer
            else:
                worst = worst or answer
        if worst is None and overflow:  # the orders past the cap stay: never `ok`
            worst = _TOO_MANY
        return worst or first or HandlerAnswer("done")


class RuleAmendHandler(_ExitBase):
    """A rule's amend of its resting entries' stop or take-profit (module docstring), capability
    `oms_amend`; `tighten_stop` is `modify_stop_loss`, judged by check 8 first and by the
    exit service's ratchet last."""

    capability: Capability = "oms_amend"

    def __init__(
        self,
        action_type: str,
        runtime: Callable[[], ExitRuntime | None],
        principals: PrincipalReads,
        entries: RuleEntries | None,
        environment: Environment,
    ) -> None:
        if action_type not in AMEND_TYPES:
            raise ValueError(f"{action_type} is not a rule's amend")
        super().__init__(action_type, runtime, principals, entries, environment)
        self._kind: Literal["stop_loss", "take_profit"] = (
            "take_profit" if action_type == "modify_take_profit" else "stop_loss"
        )

    async def send(self, prepared: Prepared, *, client_ref: str) -> HandlerAnswer:
        exit_ = admitted_exit(prepared)
        if isinstance(exit_, HandlerAnswer):
            return exit_
        principal, params, account = exit_.principal, exit_.params, exit_.account_id
        if principal is None or account is None or not isinstance(params, StopMoveParams):
            return _INVALID
        try:
            targets = amend_targets(await self._rows(exit_, symbol=exit_.symbol))
        except Exception:  # never `CancelledError`, which is no `Exception`
            return _ENTRIES_UNREAD
        if not targets:  # check 8 refuses it first: a move of the position's stop
            return _NO_TARGET
        levels = [
            stop_level(params, kind=self._kind, side=r.side, price=r.price, snapshot=exit_.snapshot)
            for r in targets
        ]  # fmt: skip
        if any(level is None for level in levels):  # every level known before any send
            return HandlerAnswer("refused", error_code="metric_unavailable")
        exits = _exits_of(self._runtime)
        if exits is None:
            return _OMS_NOT_READY
        caller = ExitCaller(
            owner_scope(principal.owner, account), principal.actor, None, principal.origin
        )
        first: HandlerAnswer | None = None
        for row, level in zip(targets, levels, strict=True):
            if level is None:  # held above
                return _INVALID
            answer = await self._amend(exits, caller, row, level)
            if answer.answer != "accepted":
                return answer
            first = first or answer
        return first or HandlerAnswer("done")

    async def _amend(
        self, exits: _Exits, caller: ExitCaller, row: OrderRow, level: Decimal
    ) -> HandlerAnswer:
        terms = AmendTerms(sides={self._kind: StopOffset(unit="price", value=level)})
        try:
            scoped = await exits.scope(caller, row.id)
            if isinstance(scoped, ExitOutcome):
                return exit_answer(scoped, row.id)
            outcome = await exits.amend(scoped, terms, caller=caller, expected_seq=None)
        except OmsNotReady:
            return _OMS_NOT_READY
        except Exception as error:  # never `CancelledError`, which is no `Exception`
            return refusal_answer(error)
        return exit_answer(outcome, row.id)


class RuleStopCheck:
    """Check 8's port (`StopCheck`; module docstring), over the rule's resting entries and the
    account's positions as the owner reads them. A read that raises reaches the executor's bound,
    which refuses (`native_sl`, fail closed)."""

    def __init__(
        self,
        principals: PrincipalReads,
        entries: RuleEntries | None,
        positions: OpenPositions | None,
        environment: Environment,
    ) -> None:
        self._principals, self._entries = principals, entries
        self._positions, self._environment = positions, environment

    async def judge(self, req: ActionRequest, account_id: UUID | None) -> StopVerdict:
        params = exit_params(req.action_type, req.payload.params)
        if req.action_type in CANCEL_TYPES:
            purpose = params.purpose if isinstance(params, CancelParams) else None
            return StopVerdict(refused="native_sl") if purpose == "stop_loss" else STOP_ADMITTED
        if req.action_type not in AMEND_TYPES:  # a type no port judges: fail closed
            return StopVerdict(refused="native_sl")
        if not isinstance(params, StopMoveParams) or account_id is None:
            return STOP_ADMITTED  # no request: the handler answers `invalid_params`, nothing sent
        stop = req.action_type != "modify_take_profit"
        symbol = req.instance.symbol
        if stop and not params.only_tighten:  # asks for a loosening: refused as one
            return StopVerdict(refused="native_sl", loosening=Loosening(symbol=symbol))
        targets = amend_targets(
            await read_entries(
                self._entries, req.rule_id, self._environment, account_id=account_id,
                symbol=symbol,
            )
        )  # fmt: skip
        if not targets:
            return StopVerdict(refused="unavailable", detail=POSITION_STOP)
        if not stop:
            return STOP_ADMITTED
        held = await self._stops_in_force(req, account_id)
        for row in targets:
            level = stop_level(
                params, kind="stop_loss", side=row.side, price=row.price,
                snapshot=req.metric_values,
            )  # fmt: skip
            if level is None:  # the handler answers `metric_unavailable`, nothing sent
                continue
            loose = self._looser(row, level, held)
            if loose is not None:
                return StopVerdict(refused="native_sl", loosening=loose)
        return STOP_ADMITTED

    async def _stops_in_force(
        self, req: ActionRequest, account_id: UUID
    ) -> Mapping[tuple[str, int, str], Decimal]:
        """The account's positions' Full-mode stops at the venue, by symbol, index and side."""
        owner = self._principals.principal(req.owner)
        if self._positions is None or owner is None:
            raise LookupError("the positions' stops cannot be read")
        rows = await self._positions.open_positions(owner, account_id)
        return {
            (row.symbol, row.position_idx, row.side): row.stop_loss
            for row in rows
            if row.stop_loss is not None and row.tpsl_mode == "Full" and row.side is not None
        }

    @staticmethod
    def _looser(
        row: OrderRow, level: Decimal, held: Mapping[tuple[str, int, str], Decimal]
    ) -> Loosening | None:
        """The amend writer's own comparison (`stop_ratchet`): `level` against the order's own
        stop, then against its position's stop at the venue on the same side."""
        found = Loosening(order_id=row.id, symbol=row.symbol, after=level)
        if ratchet_refusal(side=row.side, requested=level, current=row.stop_loss, in_force=()):
            return replace(found, before=row.stop_loss)
        position_stop = held.get((row.symbol, row.position_idx, row.side))
        if position_stop is not None and loosens(row.side, position_stop, level):
            return replace(found, before=position_stop)
        return None


class BreakerAlerts(Protocol):
    """`RuleAlerts.breaker_cancels`: the count of the breaker's cancels not done."""

    async def breaker_cancels(
        self, rule_id: str, run_id: UUID, node_id: str, *, sent: int, not_done: int | None
    ) -> None: ...


class RuleBreakerCancels:
    """`BreakerCancels` (module docstring): the tripped rule's resting entries on every account of
    the environment, cancelled with the reason `rule_circuit_breaker` as the rule's owner, with no
    principal check; each cancel bounded by `BREAKER_CANCEL_TIMEOUT_S`, those not done counted."""

    def __init__(
        self,
        runtime: Callable[[], ExitRuntime | None],
        principals: PrincipalReads,
        entries: RuleEntries | None,
        environment: Environment,
        alerts: BreakerAlerts | None,
    ) -> None:
        self._runtime, self._principals = runtime, principals
        self._entries, self._environment, self._alerts = entries, environment, alerts

    async def cancel_resting(self, req: ActionRequest) -> None:
        try:
            origin = self._origin(req)
        except ValueError:  # a rule id or a version the origin refuses: no cancel can start
            _log().critical(
                "rules.breaker_cancels_not_started", cv_page=True, rule_id=req.rule_id,
                reason="origin_refused",
            )  # fmt: skip
            return
        node = origin.node_id  # the tripping node, as the cancels' records name it
        try:
            read = await read_entries(
                self._entries, req.rule_id, self._environment, account_id=None, symbol=None
            )
        except Exception as exc:  # never `CancelledError`, which is no `Exception`
            _log().error(
                "rules.breaker_entries_unread", rule_id=req.rule_id, kind=type(exc).__name__
            )
            await self._report(req, node, sent=0, not_done=None)
            return
        within, overflow = capped(read)
        rows = [r for r in within if not r.reduce_only and r.intent in _CANCELLABLE_INTENTS]
        exits = _exits_of(self._runtime) if rows else None
        actor = self._actor(req)
        sent = not_done = 0
        for row in rows:
            sent += 1
            if exits is None or not await self._cancelled(exits, row, actor, origin):
                not_done += 1
        if overflow:  # entries past the cap stay resting: one more not done, at least
            not_done += 1
        await self._report(req, node, sent=sent, not_done=not_done)

    async def _cancelled(
        self, exits: _Exits, row: OrderRow, actor: SubmitActor, origin: RuleOrigin
    ) -> bool:
        try:
            async with asyncio.timeout(BREAKER_CANCEL_TIMEOUT_S):
                outcome = await exits.cancel_admitted(
                    row, actor=actor, reason="rule_circuit_breaker", request_id=None, origin=origin
                )
        except Exception as exc:  # never `CancelledError`, which is no `Exception`
            _log().warning(
                "rules.breaker_cancel_not_done", order_id=str(row.id), kind=type(exc).__name__
            )
            return False
        if outcome.kind != "accepted":
            _log().warning(
                "rules.breaker_cancel_not_done", order_id=str(row.id), code=outcome.code,
                outcome=outcome.kind,
            )  # fmt: skip
        return outcome.kind == "accepted"

    def _actor(self, req: ActionRequest) -> SubmitActor:
        """The owner as the principal, the role its last snapshot read (`unknown` with none read:
        the breaker's cancels are never gated on it, 24 §8.10)."""
        view = self._principals.principal(req.owner)
        role = view.role if view is not None and view.role else "unknown"
        return SubmitActor(user_id=req.owner, role=role)

    def _origin(self, req: ActionRequest) -> RuleOrigin:
        """The tripped rule its cancels' records name: its id and version, the tripping fire and
        action, and its armer with the armer's last read role, one of the closed role set
        (neither, with none read). A node id the origin refuses stands as `circuit_breaker`: the
        records name the rule, not the node."""
        armer = _read(self._principals, req.armed_by) if req.armed_by is not None else None
        role = None if armer is None else system_role(armer.role)
        armed_by = None if armer is None or role is None else armer.user_id
        for node in (req.payload.node_id, "circuit_breaker"):
            try:
                return RuleOrigin(
                    rule_id=UUID(req.rule_id), version=req.version, run_id=req.run_id,
                    node_id=node, armed_by=armed_by, armed_by_role=role if armed_by else None,
                )  # fmt: skip
            except ValueError:
                continue
        raise ValueError("the tripped rule names no origin")  # a rule id or a version refused

    async def _report(
        self, req: ActionRequest, node: str, *, sent: int, not_done: int | None
    ) -> None:
        if self._alerts is not None:
            await self._alerts.breaker_cancels(
                req.rule_id, req.run_id, node, sent=sent, not_done=not_done
            )


def rule_exit_handlers(
    runtime: Callable[[], ExitRuntime | None],
    *,
    principals: PrincipalReads,
    entries: RuleEntries | None,
    environment: Environment,
) -> dict[str, RuleCancelHandler | RuleAmendHandler]:
    """The cancels' and the amends' handlers over the exit service, for
    `RulesService.bind(handlers=...)`."""
    bound: dict[str, RuleCancelHandler | RuleAmendHandler] = {
        t: RuleCancelHandler(t, runtime, principals, entries, environment) for t in CANCEL_TYPES
    }
    for t in AMEND_TYPES:
        bound[t] = RuleAmendHandler(t, runtime, principals, entries, environment)
    return bound
