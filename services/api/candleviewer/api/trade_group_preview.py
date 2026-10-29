"""`previewTradeGroup`, `POST /trade-groups/preview` (E28-T05 S3c, #909; 22; SR-E28-22): the
trade-group submit's dry run (24 Sec.9.4 rule 1), which writes nothing but its audit rows. Each
check comes before the next:

1. the principal, as `placeOrder` resolves it (none 401, unread 503, no source composed 501);
2. its user's bucket (`PreviewLimiter`, never the session's): `429 rate_limited`, counted only;
3. `orders:write` (403 `forbidden`, recorded `rbac.denied` by `enforce`);
4. the OMS runtime and the route's reads (none composed 501, not ready 503, as on `placeOrder`);
5. `trading.trade_groups` (`TradeGroupsGate.preview_refusal`: 403 `trading_disabled`, no `reason`);
6. the body: the model, `round_to_lot: false` (ADR-0040) and a repeated account, each 422;
7. each leg's grant, then its row, in the caller's scope: one missing or ungranted refuses the
   whole request alike, `403 account_scope_denied` (SR-E29-13), recorded `rbac.denied` first;
8. each leg's account in this process's environment (400 `environment_mismatch`, counted; C-2.11);
9. each sized leg's bound profile _B_ and its alternate, one of the account's own (else 404);
10. what the planner does not carry, refused as `placeOrder` refuses it (400);
11. an alternate not enabled and trading, or a leverage above `min(B, A)`'s `max_leverage_cap`:
    refused whole (403 `risk_limit_breached`), as a widening;
12. the snapshot (the listing, the market, the legs' cached figures, readiness), then the plan.

No step before 12 reads a figure. Every refusal from step 5 on, and every 200, is written ahead as
one `trade_group.previewed` row (ruling 2), after a scope refusal's `rbac.denied` and a widening's
`trade_group.override_refused` rows; one unwritten is 503 `audit_unavailable`, nothing answered past
it (C-2.9). An outage decides nothing and writes none. No `Idempotency-Key` is read and no arm
token is needed (22). No `detail`, log or label carries a figure, symbol, label or body (C-12.6).

Each answer is one `oms.preview` span, under which the planner starts one `oms.preview_leg` per leg
it plans (`PREVIEW_SPANS`), and is counted once by its outcome (`OUTCOMES`) and, but a 429, timed;
once its record landed, a plan's skipped legs are counted by reason, and a widening's fields once
each (20 Sec.12.1).
"""

from __future__ import annotations

import asyncio
import functools
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Protocol, cast

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from candleviewer.accounts import override_comparator as comparator
from candleviewer.accounts.errors import AccountNotFoundError, AccountsError
from candleviewer.accounts.models import ExchangeAccount
from candleviewer.accounts.profile_cache import EffectiveProfiles
from candleviewer.accounts.sizer import SkipReason
from candleviewer.accounts.sizer_metrics import SizerMetrics
from candleviewer.accounts.trade_group_readiness import ReadinessSource
from candleviewer.api import profile_body as edge
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.order_admission import (
    MAX_ORDER_BODY_BYTES,
    AuditEmitter,
    OrderPrincipals,
    problem,
    rbac_refusal,
    read_capped,
    resolve_principal,
    stop_offset,
    submit_actor,
)
from candleviewer.api.order_problems import order_problem
from candleviewer.api.preview_limiter import PreviewLimiter
from candleviewer.api.profile_projection import plain
from candleviewer.api.profiles import AccountReads
from candleviewer.api.refusal_session import SessionsLike
from candleviewer.api.trade_group_preview_projection import (
    PREVIEWED_ACTION,
    preview_document,
    previewed_entry,
)
from candleviewer.api.trade_groups_gate import TradeGroupsGate
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.metrics import count_authz_denial, normalise_role
from candleviewer.auth.scopes import Deny, ForbiddenError, account_scope, decide, enforce
from candleviewer.domain.primitives import AccountId, Environment, Symbol
from candleviewer.observability.context import current_request_uuid
from candleviewer.observability.metrics import NOOP_CHILD, MetricChild, Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.observability.tracing import span
from candleviewer.oms import ports
from candleviewer.oms.classify import intent_errors
from candleviewer.oms.errors import (
    RULE_INTENT_MISMATCH,
    RULE_NATIVE_STOP_REQUIRED,
    RULE_QTY_ROUNDING,
    RULE_SIZING_MODE_UNSUPPORTED,
    AccountScopeDenied,
    AuditNotDurable,
    FieldError,
    OmsNotReady,
    OrderInvalid,
    ProfileNotFound,
    StoreUnavailable,
)
from candleviewer.oms.fanout import plan as planner
from candleviewer.oms.fanout.guard import LegGuard
from candleviewer.oms.submit import STORE_TIMEOUT_S
from candleviewer.storage.errors import StorageError
from candleviewer.storage.repositories.accounts import AccountScope

__all__ = [
    "OUTCOMES", "PREVIEW_PATH", "SKIP_REASONS", "PreviewOms", "PreviewReads",
    "make_trade_group_preview_router",
]  # fmt: skip

PREVIEW_PATH: Final = "/trade-groups/preview"
_WRITE: Final = Permission.ORDERS_WRITE
#: `rbac.denied`'s reason for a missing account, as `placeOrder` writes it (step 7).
_NOT_GRANTED: Final = f"account_not_granted:{_WRITE.value}:{Scope.GRANTED_ACCOUNTS.value}"
_UNREAD: Final = (AccountsError, StorageError, TimeoutError)
type Figures = Mapping[uuid.UUID, comparator.AccountFigures | None]
#: What a `trade_group.previewed` row answers: a plan, a whole refusal, or a refusal's rule or code.
type Answer = planner.GroupPlan | planner.GroupRefused | str
type _Handler = Callable[[Request], Awaitable[Response]]
#: `cv_tradegroup_preview_total`'s outcomes: each answer's by its status (`_outcome`), and a leg
#: in another environment its own, not `invalid` (SR-E28-16, C-2.11).
OUTCOMES: Final = ("ok", "refused", "rate_limited", "invalid", "environment_mismatch", "error")
#: `cv_tradegroup_legs_skipped_total`'s reasons, 22's codes of a skipped leg: the request's own
#: skip, and the sizer's (`SkipReason`), which `rejection_code` keeps.
SKIP_REASONS: Final = ("skipped", *(reason.value for reason in SkipReason))


def _outcome(status: int) -> str:
    """An answer's outcome by its status: a refusal (401, 403, 404) `refused`, a body or leg the
    preview cannot take (400, 422) `invalid`, and a 5xx `error`."""
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "error"
    return "ok" if status < 300 else "invalid" if status in (400, 422) else "refused"


@dataclass(frozen=True, slots=True)
class PreviewMeasures:
    """The preview's series (20 Sec.12.1), every child bound once: each label set is closed, and
    no value outside it is counted (`NOOP_CHILD`), so nothing on the answer's path can raise;
    `clock` times an answer from its handler's entry, as a profile save's (`SaveMeasures`)."""

    outcomes: Mapping[str, MetricChild]
    seconds: MetricChild
    skipped: Mapping[str, MetricChild]
    refused: Mapping[str, MetricChild]
    clock: Callable[[], float] = time.perf_counter

    @classmethod
    def bound(
        cls, metrics: Metrics, *, clock: Callable[[], float] = time.perf_counter
    ) -> PreviewMeasures:
        """Registered through the facade as catalogued (idempotent)."""
        spec = {s.name: s for s in CATALOGUE}

        def children(name: str, values: Iterable[str]) -> dict[str, MetricChild]:
            s = spec[name]
            metric = metrics.counter(s.name, s.help, s.labels, max_series=s.max_series)
            return {value: metric.labels(value) for value in values}

        timed = spec["cv_tradegroup_preview_seconds"]
        seconds = metrics.histogram(timed.name, timed.help, buckets=timed.buckets or (),
                                    max_series=timed.max_series)  # fmt: skip
        return cls(
            children("cv_tradegroup_preview_total", OUTCOMES), seconds.child(),
            children("cv_tradegroup_legs_skipped_total", SKIP_REASONS),
            children("cv_override_refused_total", sorted(comparator.OVERRIDE_CLASS)), clock,
        )  # fmt: skip

    def answered(self, outcome: str, elapsed_s: float) -> None:
        """One answer by its outcome, timed unless the bucket refused it."""
        self.outcomes.get(outcome, NOOP_CHILD).inc()
        if outcome != "rate_limited":
            self.seconds.observe(elapsed_s)

    def planned(self, plan: planner.GroupPlan) -> None:
        """Each leg the plan skipped, by its code."""
        for leg in plan.legs:
            if leg.status == "skipped":
                self.skipped.get(str(leg.reason), NOOP_CHILD).inc()

    def widening(self, refused: planner.GroupRefused) -> None:
        """Each distinct field of the override table the request was refused on (ADR-0040)."""
        violations = (v for leg in refused.legs for v in leg.violations)
        for cap in comparator.refused_fields(violations):
            self.refused.get(cap, NOOP_CHILD).inc()


@dataclass(slots=True)
class _Seen:
    """What one answer does not say of itself: its symbol once read (its span's), and whether a
    leg was in another environment (its `400`'s outcome)."""

    symbol: str | None = None
    mismatch: bool = False


def _leg_span(account_id: AccountId) -> AbstractContextManager[object]:
    """One planned leg, an `oms.preview_leg` span under the preview's, by its account id."""
    return span("oms.preview_leg", {"exchange_account_id": str(account_id)})


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class MarketPrices(Protocol):
    async def market(self, symbol: Symbol) -> ports.MarketReading: ...


class PeekedFigures(Protocol):
    async def peeked(
        self, symbol: Symbol, fallbacks: Mapping[uuid.UUID, Decimal | None]
    ) -> Figures: ...


class PreviewOms(Protocol):
    """`oms_wiring.PreviewParts` as the route reads it: the order path's own reads, no write."""

    @property
    def guard(self) -> LegGuard: ...
    @property
    def stops(self) -> ports.StopResolver: ...
    @property
    def instruments(self) -> ports.Instruments: ...
    @property
    def prices(self) -> MarketPrices: ...
    @property
    def figures(self) -> PeekedFigures: ...


class PreviewRuntime(Protocol):
    """`oms_wiring.OmsRuntime` as the route reads it: its readiness and the preview's reads."""

    @property
    def readiness(self) -> str: ...
    @property
    def preview(self) -> PreviewOms: ...


@dataclass(frozen=True, slots=True)
class PreviewReads:
    """The route's reads beside the OMS: the legs' accounts in the caller's scope, the profile
    cache (_B_ and any alternate), readiness and this process's environment (C-2.11)."""

    accounts: AccountReads
    profiles: EffectiveProfiles
    readiness: ReadinessSource
    environment: Environment


def _decimal(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _sizing(sizing: api.Sizing | None) -> ports.SizingRequest | None:
    if sizing is None:
        return None
    return ports.SizingRequest(
        sizing.mode, _decimal(sizing.qty), sizing.round_to_lot,
        notional_usd=_decimal(sizing.notional_usd), pct=_decimal(sizing.pct),
        risk_per_trade_usd=_decimal(sizing.risk_per_trade_usd),
        risk_per_trade_pct=_decimal(sizing.risk_per_trade_pct),
        max_notional_usd=_decimal(sizing.max_notional_usd),
    )  # fmt: skip


def _terms(layer: api.Defaults | api.Overrides | None) -> planner.LegTerms:
    """One layer of the body, `defaults` or a leg's `overrides`, as the planner takes it."""
    if layer is None:
        return planner.LegTerms()
    leg = layer if isinstance(layer, api.Overrides) else None
    return planner.LegTerms(
        sizing=_sizing(layer.sizing), price=_decimal(layer.price),
        leverage=None if leg is None else _decimal(leg.leverage),
        stop_loss=stop_offset(layer.stop_loss), take_profit=stop_offset(layer.take_profit),
        time_in_force=layer.time_in_force, tpsl_mode=layer.tpsl_mode,
        position_idx=None if leg is None else leg.position_idx,
    )  # fmt: skip


def _group(body: api.CreateTradeGroupRequest) -> planner.GroupRequest:
    legs = tuple(
        planner.LegRequest(AccountId(leg.exchange_account_id), _terms(leg.overrides),
                           skip=leg.overrides is not None and leg.overrides.skip)
        for leg in body.legs
    )  # fmt: skip
    defaults = _terms(body.defaults)
    return planner.GroupRequest(body.symbol, body.side, body.order_type, legs, defaults)


def _layers(body: api.CreateTradeGroupRequest) -> list[tuple[str, api.Defaults | api.Overrides]]:
    """Each layer the body names, with its path."""
    named: list[tuple[str, api.Defaults | api.Overrides]] = []
    if body.defaults is not None:
        named.append(("defaults", body.defaults))
    return named + [(f"legs[{i}].overrides", leg.overrides) for i, leg in enumerate(body.legs)
                    if leg.overrides is not None]  # fmt: skip


def _unsound(body: api.CreateTradeGroupRequest) -> list[FieldError]:
    """Step 6 past the model: `round_to_lot: false` (the quantity is always floored, ADR-0040 row
    16) and each repeat of an account (SR-E28-17), at its own index."""
    floored, once = "The quantity is always floored to the lot step.", "One leg per account."
    errors = [FieldError(f"{path}.sizing.round_to_lot", RULE_QTY_ROUNDING, floored)
              for path, layer in _layers(body)
              if layer.sizing is not None and layer.sizing.round_to_lot is False]  # fmt: skip
    seen: set[uuid.UUID] = set()
    for index, leg in enumerate(body.legs):
        if leg.exchange_account_id in seen:
            field = f"legs[{index}].exchange_account_id"
            errors.append(FieldError(field, "duplicate_account", once))
        seen.add(leg.exchange_account_id)
    return errors


def _uncarried(body: api.CreateTradeGroupRequest) -> list[FieldError]:
    """Step 10: what the planner does not carry, as `placeOrder` refuses it."""
    errors = intent_errors(effect=ports.OrderEffect.ENTRY, intent=body.intent)
    later = "is not available yet."
    asked = [("reduce_only", body.reduce_only, RULE_INTENT_MISMATCH, "A group never reduces."),
             ("algo.kind", body.algo is not None and body.algo.kind != "none", "algo_unsupported",
              f"Emulated algos {later}"),
             ("defaults.trigger", body.defaults is not None and body.defaults.trigger is not None,
              "trigger_unsupported", f"A conditional entry {later}")]  # fmt: skip
    for path, layer in _layers(body):
        stop = layer.stop_loss
        asked += [(f"{path}.trailing_stop", layer.trailing_stop is not None,
                   "trailing_stop_unsupported", f"A trailing stop {later}"),
                  (f"{path}.sizing.mode", layer.sizing is not None
                   and layer.sizing.mode == "pct_position", RULE_SIZING_MODE_UNSUPPORTED,
                   f"pct_position sizing {later}"),
                  (f"{path}.stop_loss", stop is not None and Decimal(stop.value) <= 0,
                   RULE_NATIVE_STOP_REQUIRED, "The stop must be above zero.")]  # fmt: skip
    return errors + [FieldError(field, rule, text) for field, met, rule, text in asked if met]


def _prejudged(
    leg: planner.LegRequest, chosen: planner.LegProfiles
) -> tuple[comparator.Violation, ...]:
    """Step 11 (R1S-03): an alternate that is not enabled and trading (ADR-0040 rows 5 and 6), and
    a leverage above the tighter `max_leverage_cap` of _B_ and _A_ (R3), each the violation the
    comparator names, where the profile model would answer them 400 and unrecorded."""
    alternate = chosen.alternate
    found = [comparator.Violation(field=flag, rule="never", reason="profile_disabled")
             for flag in ("enabled", "trading_enabled")
             if alternate is not None and getattr(alternate, flag) is not True]  # fmt: skip
    caps = [p.max_leverage_cap for p in (chosen.bound, alternate) if p is not None]
    cap, asked = min((c for c in caps if c is not None), default=None), leg.overrides.leverage
    if asked is not None and cap is not None and asked > cap:
        violation = comparator.Violation(
            field="max_leverage_cap", rule="R3", reason="above_limit", limit=cap, requested=asked
        )
        found.append(violation)
    return tuple(found)


def _widening(refused: planner.GroupRefused) -> JSONResponse:
    """`403 risk_limit_breached`, one `errors[]` entry per offending leg (22 `tradeGroupWidening`):
    the leg, its first violated field and that field's limit; the requested value stays in the
    leg's `trade_group.override_refused` row (C-12.6)."""
    errors = []
    for leg in refused.legs:
        first, text = leg.violations[0], "This leg would go past its bound profile's caps."
        entry = {"field": f"legs[{leg.index}]", "rule": first.field, "message": text}
        errors.append(entry | ({} if first.limit is None else {"limit": plain(first.limit)}))
    detail = "A leg would go past its bound profile's caps."
    return problem(403, "risk_limit_breached", detail, errors=errors)


def _parsed(raw: bytes | None) -> api.CreateTradeGroupRequest | list[FieldError]:
    """The body as 22 declares it (step 6), or why it is not: past the cap, or not the model, its
    entries as the profile writes render them (no input, an unknown member at its parent)."""
    if raw is None:
        text = f"Send a body of at most {MAX_ORDER_BODY_BYTES} bytes."
        return [FieldError("body", "body_too_large", text)]
    try:
        return api.CreateTradeGroupRequest.model_validate_json(raw, strict=True)
    except ValidationError as exc:
        return [FieldError(e.field or "body", e.rule, e.message) for e in edge.model_errors(exc)]


def _invalid(errors: Sequence[FieldError], status: int = 400) -> JSONResponse:
    """`validation_failed`: a 400 as `placeOrder` renders it, or the body's 422."""
    if status == 400:
        return order_problem(OrderInvalid(errors=errors))
    entries = [{"field": e.field, "rule": e.rule, "message": e.message} for e in errors]
    return problem(422, "validation_failed", "The request failed validation.", errors=entries)


async def _rows(
    reads: PreviewReads, scope: AccountScope, group: planner.GroupRequest
) -> tuple[list[ExchangeAccount], uuid.UUID | None]:
    """Each leg's account row in `scope`, or the first leg's account with none: missing, deleted
    or outside the scope alike (M13's one `AccountNotFoundError`)."""
    rows: list[ExchangeAccount] = []
    async with asyncio.timeout(STORE_TIMEOUT_S):
        for leg in group.legs:
            try:
                rows.append(await reads.accounts.get_account(scope, leg.account_id))
            except AccountNotFoundError:
                return rows, leg.account_id
    return rows, None


async def _profiles(
    reads: PreviewReads, group: planner.GroupRequest, named: Sequence[uuid.UUID | None]
) -> dict[AccountId, planner.LegProfiles]:
    """Step 9: each sized leg's _B_, the account's default, and the alternate it names."""
    chosen: dict[AccountId, planner.LegProfiles] = {}
    read = reads.profiles.get_effective_profile
    async with asyncio.timeout(STORE_TIMEOUT_S):
        for leg, alternate in zip(group.legs, named, strict=True):
            if not leg.skip:
                bound = await read(leg.account_id)
                other = None if alternate is None else await read(leg.account_id, alternate)
                chosen[leg.account_id] = planner.LegProfiles(bound, other)
    return chosen


def make_trade_group_preview_router(
    principals: OrderPrincipals | None, runtime: Callable[[], PreviewRuntime | None], *,
    reads: PreviewReads | None, gate: TradeGroupsGate, audit: AuditEmitter,
    limiter: PreviewLimiter, metrics: Metrics, auth: SessionsLike | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> APIRouter:  # fmt: skip
    """`POST /trade-groups/preview` (module docstring): no principal source or no OMS runtime
    composed, 501; no `reads`, 503. `clock` times each answer (`PreviewMeasures`)."""
    router = APIRouter(tags=["trading"])
    measures = PreviewMeasures.bound(metrics, clock=clock)
    observer = SizerMetrics.register(metrics)
    traced = {} if reads is None else {"env": reads.environment}

    def unread(what: str, exc: BaseException | None = None) -> JSONResponse:
        if exc is not None:
            _log().warning("trade_group_preview_unread", read=what, error=type(exc).__name__)
        return problem(503, "store_unavailable", "The preview's reads are unavailable.")

    async def audit_answer(
        who: comparator.RefusalActor, group: planner.GroupRequest | None, answer: Answer,
        response: Response, *ahead: tuple[str, Mapping[str, Any]],
    ) -> Response:  # fmt: skip
        """`response` once each row `ahead`, then `answer`'s `trade_group.previewed` row, is
        written; one unwritten is 503, and nothing past it is answered (C-2.9)."""
        rows = (*ahead, (PREVIEWED_ACTION, previewed_entry(group, answer, actor=who)))
        try:
            async with asyncio.timeout(STORE_TIMEOUT_S):
                for action, row in rows:
                    await audit.emit(action, **row)
        except Exception as exc:  # whatever stopped it, nothing is answered unrecorded
            _log().error("trade_group_preview_unrecorded", error=type(exc).__name__)
            return order_problem(AuditNotDurable("a preview's record did not land"))
        return response

    async def widened(
        who: comparator.RefusalActor, group: planner.GroupRequest, refused: planner.GroupRefused
    ) -> Response:
        """A whole refusal: each offending leg's `trade_group.override_refused` row first; its
        fields counted once the record landed, so a 503 counts none and its retry once."""
        made = [comparator.refusal_record(
            leg.violations, actor=who, bound=leg.bound, leg_index=leg.index,
            alternate_id=None if leg.alternate is None else leg.alternate.profile_id,
        ) for leg in refused.legs]  # fmt: skip
        ahead = [(record.action, record.emit_kwargs()) for record in made]
        refusal = _widening(refused)
        answered = await audit_answer(who, group, refused, refusal, *ahead)
        if answered is refusal:
            measures.widening(refused)
        return answered

    async def scope_denied(
        who: comparator.RefusalActor, session: uuid.UUID | None, group: planner.GroupRequest,
        account: uuid.UUID, reason: str, roles: frozenset[str],
    ) -> Response:  # fmt: skip
        """Step 7's one refusal for a missing and an ungranted account: counted, recorded
        `rbac.denied` naming the account as `placeOrder` records it, then the previewed row."""
        count_authz_denial(_WRITE, roles)
        denial = {
            "actor_label": str(who.user_id), "actor_user_id": who.user_id, "actor_ip": who.ip,
            "session_id": session, "object_kind": "exchange_account", "object_id": str(account),
            "outcome": "denied", "severity": "warning", "reason": reason,
            "request_id": who.request_id,
        }  # fmt: skip
        denied = order_problem(AccountScopeDenied())
        return await audit_answer(
            who, group, "account_scope_denied", denied, ("rbac.denied", denial)
        )

    def measured(handler: _Handler) -> _Handler:
        """`handler` as one `oms.preview` span: the environment, the symbol once read and the
        outcome; that outcome counted, and the answer timed but a 429's (20 Sec.12.1). What the
        answer does not say of itself, the handler notes on the request's `_Seen`."""

        def ended(request: Request, outcome: str, started: float) -> dict[str, str]:
            """The answer's outcome, counted and timed, and its span's attributes."""
            seen = cast(_Seen, request.state.preview)
            if outcome == "invalid" and seen.mismatch:
                outcome = "environment_mismatch"
            measures.answered(outcome, measures.clock() - started)
            return ({} if seen.symbol is None else {"symbol": seen.symbol}) | {"result": outcome}

        @functools.wraps(handler)  # FastAPI reads the handler's own signature
        async def timed(request: Request) -> Response:
            started, request.state.preview = measures.clock(), _Seen()
            with span("oms.preview", traced) as current:
                try:
                    response = await handler(request)
                except Exception:  # an answer FastAPI turns into a 500: an `error`, then raised
                    current.set_attributes(ended(request, "error", started))
                    raise
                current.set_attributes(ended(request, _outcome(response.status_code), started))
            return response

        return timed

    @router.post(PREVIEW_PATH)
    @measured
    async def preview_trade_group(request: Request) -> Response:
        seen = cast(_Seen, request.state.preview)
        if principals is None:
            return problem(501, "not_implemented", "No principal source is composed.")
        try:
            principal = await resolve_principal(principals, request, auth)
        except StoreUnavailable as exc:
            return order_problem(exc)
        if principal is None:
            return problem(401, "unauthenticated", "No verified session for this request.")
        caller, actor = principal.snapshot, submit_actor(principal, request)
        if (wait := limiter.try_take(caller.user_id)) is not None:  # the user's, not the session's
            detail = "Too many previews; retry after the delay given."
            limited = problem(429, "rate_limited", detail, retry_after_seconds=wait)
            limited.headers["Retry-After"] = str(wait)
            return limited
        request_id = current_request_uuid()
        try:
            await enforce(
                caller, _WRITE, emitter=audit, actor_ip=actor.ip, session_id=actor.session_id,
                request_id=request_id,
            )  # fmt: skip
        except ForbiddenError as exc:
            return rbac_refusal(exc.deny)
        except (AuditError, RuntimeError, TimeoutError):  # counted by `enforce`, not recorded
            return order_problem(AuditNotDurable("a refusal's record did not land"))
        if (oms := runtime()) is None:
            return problem(501, "not_implemented", "No OMS is composed on this backend.")
        if reads is None:
            return unread("composition")
        if oms.readiness != "ok":
            return order_problem(OmsNotReady())
        role = cast(comparator.Role, normalise_role(caller.roles))  # the highest it holds
        who = comparator.RefusalActor(caller.user_id, role, reads.environment, request_id, actor.ip)
        if (off := gate.preview_refusal()) is not None:  # step 5
            return await audit_answer(who, None, "trading_disabled", off)
        body = _parsed(await read_capped(request))
        if isinstance(body, list):
            return await audit_answer(who, None, body[0].rule, _invalid(body, 422))
        group = _group(body)
        seen.symbol = group.symbol
        if unsound := _unsound(body):
            return await audit_answer(who, group, unsound[0].rule, _invalid(unsound, 422))
        for leg in group.legs:  # step 7: every grant first, from memory, then the rows
            decision = decide(caller, _WRITE, scope=Scope.GRANTED_ACCOUNTS,
                              exchange_account_id=leg.account_id, requires_trade=True)  # fmt: skip
            if isinstance(decision, Deny):
                reason = f"{decision.reason.value}:{_WRITE.value}:{Scope.GRANTED_ACCOUNTS.value}"
                session, roles = actor.session_id, caller.roles
                return await scope_denied(who, session, group, leg.account_id, reason, roles)
        try:
            rows, missing = await _rows(reads, account_scope(caller), group)
        except _UNREAD as exc:
            return unread("accounts", exc)
        if missing is not None:
            session, roles = actor.session_id, caller.roles
            return await scope_denied(who, session, group, missing, _NOT_GRANTED, roles)
        outside = [FieldError(f"legs[{i}].exchange_account_id", "environment_mismatch",
                              "This account is not in this server's environment.")
                   for i, row in enumerate(rows) if row.env.value != reads.environment]  # fmt: skip
        if outside:  # step 8, counted and recorded (SR-E28-16); no such leg reaches the figures
            seen.mismatch = True
            return await audit_answer(who, group, "environment_mismatch", _invalid(outside))
        named = [None if leg.overrides is None else leg.overrides.profile_id for leg in body.legs]
        try:
            chosen = await _profiles(reads, group, named)
        except AccountNotFoundError:  # not one of the account's own profiles, or none bound
            return await audit_answer(who, group, "not_found", order_problem(ProfileNotFound()))
        except _UNREAD as exc:
            return unread("profiles", exc)
        if uncarried := _uncarried(body):  # step 10
            return await audit_answer(who, group, uncarried[0].rule, _invalid(uncarried))
        refused = tuple(
            planner.RefusedLeg(index, profiles.bound, profiles.alternate, found)
            for index, leg in enumerate(group.legs)
            if (profiles := chosen.get(leg.account_id)) is not None
            and (found := _prejudged(leg, profiles))
        )  # fmt: skip
        if refused:  # step 11, before anything is sized or any figure read
            return await widened(who, group, planner.GroupRefused(refused))
        fallbacks: dict[uuid.UUID, Decimal | None] = {
            account: profiles.bound.fallback_sl_offset_pct for account, profiles in chosen.items()
        }
        try:  # step 12
            preview = oms.preview
            instrument = await preview.instruments.instrument(group.symbol)
            if instrument is None:
                text = "No instrument is listed under this symbol."
                unlisted = _invalid((FieldError("symbol", "listed", text),))
                return await audit_answer(who, group, "listed", unlisted)
            market = await preview.prices.market(group.symbol)
            known = await preview.figures.peeked(group.symbol, fallbacks)
        except OmsNotReady:
            return order_problem(OmsNotReady())
        snapshot = planner.take_snapshot(
            [(row.id, row.is_enabled) for row in rows], environment=reads.environment,
            instrument=instrument, mid=market.mid, last=market.last, figures=known.get,
            readiness=reads.readiness,
        )  # fmt: skip
        try:
            plan = planner.plan_group(
                group, profiles=chosen, snapshot=snapshot, guard=preview.guard,
                stops=preview.stops, observer=observer, leg_span=_leg_span,
            )  # fmt: skip
        except OrderInvalid as exc:  # the planner's own refusals, each naming its rule
            return await audit_answer(who, group, exc.errors[0].rule, order_problem(exc))
        if isinstance(plan, planner.GroupRefused):
            return await widened(who, group, plan)
        labels = {row.id: row.label for row in rows}
        document = JSONResponse(preview_document(plan, labels))
        answered = await audit_answer(who, group, plan, document)
        if answered is document:  # its skipped legs counted once its record landed, as a widening
            measures.planned(plan)
        return answered

    return router
