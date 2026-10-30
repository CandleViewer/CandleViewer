"""`POST /positions/{positionId}/close` (`closePosition`) and `POST /positions/close-all`
(`closeAllPositions`) (E29-T07 #915; 22 as amended by #5013).

**closePosition.** After the middleware (CSRF, the session state, and the view-as guard, which
passes it in a view-as context as the protective write it is, `PROTECTIVE_WRITES`, once the target
holds `positions:write`: a close is protective whole, 22 "View-as session") and the shared
admission (`api.position_admission`, steps 1 to 5: principal, `positions:write`, the caller's rate,
the body, the position in scope with a trade grant; in a live view-as context the scope is also the
target's trade grants, `scope_for_target`, the viewer staying the actor), each step before the
next:

6. the runtime: none composed is 501, one whose readiness is not `ok` 503 `oms_not_ready`;
7. no arm token: a close is never refused for want of it (C-2.6, 22 `ArmToken`);
8. `Idempotency-Key` (400 without one); 9. the 24 h record of first `202` answers (a repeat is the
   stored answer, another body 409 `idempotency_key_reuse`); 10. the in-process guard (a repeat
   while the first runs is 409 `idempotency_in_flight`, `Retry-After: 1`); 11. the anchor
   (`closePosition`, 21 Sec.3.3.10): a decided one answers the rows as read now, or its recorded
   `429`/`502`, nothing sent; an undecided one is 409 in flight within `CV_OMS_INFLIGHT_STUCK_S`,
   then decided `202` (`AnchorService`);
12. the fence only (the environment's lock lost, or the serving loop stalled: 503
    `oms_not_ready`). The C-2.6 carve-out (24 Sec.8.10, 22 `Forbidden`): `trading.oms_enabled`,
    live trading not enabled, the B18 kill switch and the order-entry gate never refuse a close,
    and its `SubmitContext` is `protective`, which this code alone sets, so the pipeline passes
    them too; 13. the position against the body: a flat position, or a `qty` above its size, is
    422 `validation_failed`;
14. the close (`oms.position_writes.close_request`) through the submission pipeline, as a task the
    runtime tracks, shielded from the client's disconnect: its `202` is 22 `OrderAcceptance`
    (`order` set, `trade_group` null), kept 24 h; at 100 % the closed size's Partial-mode
    conditionals are swept once the close fills and the venue reads the position flat; below 100 %
    the position's protective orders are left as they are (C-2.6). One `position.closed` record
    correlates the request with its order before the answer returns.

**closeAllPositions.** A protective write in a view-as context too, on the same terms. The
principal, `positions:write`, the rate, the body (22: the account ids, the symbol,
`cancel_open_orders`), the key and the 24 h record, the guard, the runtime; then the scope
(`scope_for_target`), all or nothing (SR-E29-13: one account outside the caller's trade grants, or
missing, refuses the whole request 403 `account_scope_denied`, audited, nothing sent); then per
account, its open orders cancelled when asked (`CancelAll`, never a recorded stop, C-2.6), each open
position closed whole as above (`protective`, so the kill switch, live enablement and the gate
refuse no leg), and one `position.flattened` record. Its answer is 22 `BulkAccountResult`. It is not
anchored by this amendment (#5013): its repeats are answered from the 24 h record; each
close it sends still carries the pipeline's anchor under `closeAllPositions`, so a later repeat's
persist meets it and sends nothing.

Every refusal from step 8 on is recorded (`position.closed`, outcome `denied`, its code) before it
is answered, else 503 `audit_unavailable`. No log line carries the key, the fingerprint or a value
of the row (C-12.6).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, Final, Protocol

import structlog
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from candleviewer.accounts.trade_groups import ScopedTradeGroup
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.csrf import source_ip
from candleviewer.api.idempotency import IdempotencyCache, StoredResponse, request_fingerprint
from candleviewer.api.order_acceptance import first_acceptance, replayed_acceptance
from candleviewer.api.order_admission import (
    AuditEmitter,
    OrderPrincipals,
    field_errors,
    idempotency_key,
    parse_json_object,
    problem,
    read_capped,
    replay_cached,
    replay_key,
    resolve_principal,
    submit_actor,
)
from candleviewer.api.order_principal import scope_for_target
from candleviewer.api.order_problems import order_problem, outcome_problem
from candleviewer.api.position_admission import (
    POSITIONS_WRITE,
    PositionCaller,
    admit_position_write,
    invalid,
    rate_limited,
)
from candleviewer.api.recording_writes import WriteLimiter
from candleviewer.api.refusal_session import SessionsLike
from candleviewer.api.view_as_policy import ProtectiveWrites
from candleviewer.audit.errors import AuditError
from candleviewer.auth.metrics import count_authz_denial
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.domain.primitives import AccountId, Environment, GroupId
from candleviewer.observability.context import current_request_uuid
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.oms.cancel_all import CancelAllRequest, ScopedAccounts
from candleviewer.oms.errors import (
    PROBLEMS,
    AccountScopeDenied,
    AuditNotDurable,
    FieldError,
    IdempotencyInFlight,
    OmsError,
    OmsNotReady,
    OrderInvalid,
    StoreUnavailable,
    problem_for,
)
from candleviewer.oms.idempotency import InFlight, KeyReuse, Lookup, Replay
from candleviewer.oms.ports import ArmRecords, RequestRecord, SubmitActor, SubmitAudit
from candleviewer.oms.ports import TradingSwitches as Switches
from candleviewer.oms.position_writes import (
    CLOSE_ACTION,
    FLATTEN_ACTION,
    CloseFill,
    CloseTerms,
    VenuePosition,
    close_request,
    is_full_close,
)
from candleviewer.oms.reads import OmsReads
from candleviewer.oms.submit import (
    STORE_TIMEOUT_S,
    OrderRequest,
    SubmitContext,
    SubmitOutcome,
    entry_order_id,
)
from candleviewer.statechart.plugins import LogPager, Pager
from candleviewer.storage.repositories.accounts import AccountScope
from candleviewer.storage.repositories.idempotency_anchors import AnchorOperation
from candleviewer.storage.repositories.oms_reads import PositionQuery
from candleviewer.storage.repositories.orders import OrderRow
from candleviewer.storage.repositories.positions import PositionRow

__all__ = [
    "CLOSE_ALL_PATH",
    "CLOSE_PATH",
    "MAX_CLOSE_BODY_BYTES",
    "MAX_IN_FLIGHT",
    "RATE_PER_MINUTE",
    "CloseAllBody",
    "PositionRuntime",
    "close_all_body",
    "make_position_close_router",
    "position_errors",
    "read_close",
    "replayed_body",
]  # fmt: skip

CLOSE_PATH: Final = "/positions/{positionId}/close"
CLOSE_ALL_PATH: Final = "/positions/close-all"
_OPERATION: Final = "closePosition"
_ALL_OPERATION: Final = "closeAllPositions"
#: 22 `ClosePositionRequest`: five short members, far under 2 KiB.
MAX_CLOSE_BODY_BYTES: Final = 2_048
#: The close-all body: at most `_MAX_ACCOUNTS` ids.
_MAX_ALL_BODY_BYTES: Final = 16_384
_MAX_ACCOUNTS: Final = 200
#: Position writes a user may make a minute (ruling BQ-15); a close is a protective write, so the
#: budget is wide, and the venue's own budget is the adapter's.
RATE_PER_MINUTE: Final = 60
#: Keys the in-process guard holds at once (C-2.18), as the exit routes' guard bounds its own.
MAX_IN_FLIGHT: Final = 1_024
_HUNDRED: Final = Decimal(100)

type Body = dict[str, object]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _OrderRows(Protocol):
    async def get(self, account_id: uuid.UUID, order_id: uuid.UUID) -> OrderRow | None: ...


class _GroupRows(Protocol):
    async def get(self, scope: AccountScope, group_id: GroupId) -> ScopedTradeGroup: ...


class _RouteReads(Protocol):
    @property
    def arm_records(self) -> ArmRecords: ...
    @property
    def switches(self) -> Switches: ...
    @property
    def orders(self) -> _OrderRows: ...
    @property
    def groups(self) -> _GroupRows: ...
    @property
    def environment(self) -> Environment: ...


class _Pipeline(Protocol):
    async def submit(self, request: OrderRequest, context: SubmitContext) -> SubmitOutcome: ...
    async def answer_replay(self, account_id: AccountId, replay: Replay) -> SubmitOutcome: ...


class _Anchors(Protocol):
    async def lookup(
        self, created_by: uuid.UUID, client_ref: uuid.UUID, request_sha256: str, *,
        operation: AnchorOperation = "placeOrder",
    ) -> Lookup: ...  # fmt: skip


class _Positions(Protocol):
    async def entry_stop_ready(self, account_id: AccountId) -> None: ...
    async def await_fill(
        self, account_id: uuid.UUID, order_id: uuid.UUID, *, wait_s: float
    ) -> CloseFill: ...
    async def venue_position(self, row: PositionRow) -> VenuePosition: ...
    async def record(self, record: RequestRecord) -> bool: ...
    async def sweep_after_close(
        self, row: PositionRow, order_id: uuid.UUID, *, actor: SubmitActor,
        request_id: uuid.UUID | None,
    ) -> bool: ...  # fmt: skip


class _CancelAll(Protocol):
    async def scope(self, scope: AccountScope, request: CancelAllRequest) -> ScopedAccounts: ...
    async def run(
        self, accounts: ScopedAccounts, request: CancelAllRequest, *, actor: SubmitActor,
        request_id: uuid.UUID | None,
    ) -> object: ...  # fmt: skip


class PositionRuntime(Protocol):
    """`oms_wiring.OmsRuntime` as the position write routes read it."""

    @property
    def readiness(self) -> str: ...
    @property
    def route(self) -> _RouteReads: ...
    @property
    def submission(self) -> _Pipeline: ...
    @property
    def anchors(self) -> _Anchors: ...
    @property
    def positions(self) -> _Positions: ...
    @property
    def cancel_all(self) -> _CancelAll: ...
    def run(self, coro: Coroutine[Any, Any, Response]) -> asyncio.Task[Response]: ...


def read_close(raw: bytes) -> CloseTerms | tuple[FieldError, ...]:
    """The body (22 `ClosePositionRequest`), read strictly, JSON types only, or each rule it
    breaks: exactly one of `pct` and `qty`, `0 < pct <= 100`, `qty` above zero, a `limit` priced."""
    if parse_json_object(raw) is None:
        return (FieldError("body", "json_object", "Send a JSON object."),)
    try:
        read = api.ClosePositionRequest.model_validate_json(raw, strict=True)
    except ValidationError as exc:
        return tuple(field_errors(exc))
    errors: list[FieldError] = []
    pct = None if read.pct is None else Decimal(read.pct)
    qty = None if read.qty is None else Decimal(read.qty)
    if (pct is None) == (qty is None):
        errors.append(FieldError("pct", "pct_xor_qty", "Send exactly one of pct and qty."))
    if pct is not None and not 0 < pct <= _HUNDRED:
        errors.append(FieldError("pct", "range", "Send a percent above 0 and at most 100."))
    if qty is not None and qty <= 0:
        errors.append(FieldError("qty", "range", "Send a quantity above zero."))
    if read.order_type == "limit" and read.price is None:
        errors.append(FieldError("price", "required", "A limit close needs a price."))
    if errors:
        return tuple(errors)
    price = None if read.price is None else Decimal(read.price)
    tif = read.time_in_force or "GTC"
    return CloseTerms(read.order_type, price, pct, qty, tif)


def position_errors(row: PositionRow, terms: CloseTerms) -> tuple[FieldError, ...]:
    """The body against the position (step 13): an open position, a `qty` within its size."""
    if row.side not in ("Buy", "Sell") or row.size <= 0:
        return (FieldError("positionId", "position_flat", "The position is flat."),)
    if terms.qty is not None and terms.qty > row.size:
        message = "Send at most the position's size: a close never opens the other side."
        return (FieldError("qty", "exceeds_position", message),)
    return ()


async def replayed_body(
    oms: PositionRuntime, outcome: SubmitOutcome, scope: AccountScope, account_id: AccountId
) -> tuple[Body, OrderRow]:
    """A repeat's `OrderAcceptance` from its rows as read now (as `placeOrder`'s is):
    `StoreUnavailable` when they cannot be read, `ValueError` for a group not its outcome's."""
    reads, group_id = oms.route, outcome.trade_group_id
    order_id = outcome.order_id if group_id is None else entry_order_id(group_id)
    found: ScopedTradeGroup | None = None
    try:
        async with asyncio.timeout(STORE_TIMEOUT_S):
            if group_id is not None:
                found = await reads.groups.get(scope, GroupId(group_id))
            row = None if order_id is None else await reads.orders.get(account_id, order_id)
    except OmsNotReady:
        raise
    except Exception as exc:  # any store failure: nothing is sent on a repeat
        _log().warning("oms_position_replay_unread", error=type(exc).__name__)
        raise StoreUnavailable from None
    if row is None:  # an anchor never exists without its order
        _log().error("oms_position_replay_row_missing", anchor_id=str(outcome.anchor_id))
        raise StoreUnavailable
    record = None if found is None else found.record
    return replayed_acceptance(row, record, outcome, reads.environment), row


@dataclass(frozen=True, slots=True)
class _Admitted:
    caller: PositionCaller[CloseTerms]
    oms: PositionRuntime
    key: uuid.UUID
    digest: str
    held: tuple[str, str]


def make_position_close_router(
    principals: OrderPrincipals | None, runtime: Callable[[], PositionRuntime | None],
    reads: OmsReads | None, *, audit: AuditEmitter, records: SubmitAudit, metrics: Metrics,
    auth: SessionsLike | None = None, replays: IdempotencyCache | None = None,
    limiter: WriteLimiter | None = None, pager: Pager | None = None,
    protective: ProtectiveWrites | None = None,
) -> APIRouter:  # fmt: skip
    """`closePosition` and `closeAllPositions` (module docstring). `audit` takes `rbac.denied`,
    `records` the refusals; `replays` is the 24 h record of first `2xx` answers; `protective`, the
    view-as guard's registry, learns that these handlers decide a viewer's close themselves."""
    if protective is not None:
        protective.register(_OPERATION)
        protective.register(_ALL_OPERATION)
    router = APIRouter(tags=["positions"])
    kept = replays if replays is not None else IdempotencyCache()
    rate = limiter if limiter is not None else WriteLimiter(rate_per_minute=RATE_PER_MINUTE)
    paging: Pager = LogPager() if pager is None else pager
    running: set[tuple[str, str]] = set()
    spec = next(spec for spec in CATALOGUE if spec.name == "oms_submit_rejected_total")
    rejected = metrics.counter(spec.name, spec.help, spec.labels, max_series=spec.max_series)

    def not_ready() -> Response:
        rejected.labels(PROBLEMS[OmsNotReady].code).inc()
        return order_problem(OmsNotReady(), pager=paging)

    async def refused(error: OmsError, caller: PositionCaller[CloseTerms], step: str) -> Response:
        """A refusal from step 8 on: recorded before it is answered (C-2.9), else 503."""
        if isinstance(error, OmsNotReady):
            return not_ready()
        row, code = caller.row, problem_for(error).code
        record = RequestRecord(
            CLOSE_ACTION, row.exchange_account_id, "position", row.id, "denied",
            "error" if problem_for(error).status >= 500 else "warning", code, caller.actor,
            {"step": step, "code": code, "symbol": row.symbol}, caller.request_id,
        )  # fmt: skip
        try:
            async with asyncio.timeout(STORE_TIMEOUT_S):
                await records.write(record)
        except Exception as exc:  # no refusal is answered unrecorded; the key stays unbound
            rejected.labels(PROBLEMS[AuditNotDurable].code).inc()
            _log().error("oms_close_refusal_unrecorded", step=step, error=type(exc).__name__)
            return order_problem(AuditNotDurable("the refusal's record did not land"))
        rejected.labels(code).inc()
        if isinstance(error, OrderInvalid) and step == "position":
            return invalid(*error.errors)
        return order_problem(error, pager=paging)

    async def replayed(adm: _Admitted, outcome: SubmitOutcome) -> Response:
        """A decided anchor's answer: its recorded `429`/`502`, or its rows as read now."""
        if outcome.status != 202:
            return outcome_problem(outcome)
        snapshot = adm.caller.principal.snapshot
        account = AccountId(adm.caller.row.exchange_account_id)
        try:
            scope = scope_for_target(snapshot, adm.caller.principal.target)
            body, _row = await replayed_body(adm.oms, outcome, scope, account)
        except ValueError:
            return order_problem(OmsError("a replay read a group other than its outcome's"))
        return JSONResponse(body, 202, {"Idempotency-Replayed": "true"})

    async def answer(adm: _Admitted, order: OrderRequest, context: SubmitContext,
                     full: bool) -> Response:  # fmt: skip
        """Step 14's task: the close's answer, its record, the sweep, and a first `202` kept."""
        caller, oms = adm.caller, adm.oms
        try:
            outcome = await oms.submission.submit(order, context)
        except OmsError as exc:  # recorded by the pipeline before it was raised
            return order_problem(exc, pager=paging)
        if outcome.status != 202:
            return outcome_problem(outcome)
        if outcome.replayed or outcome.written is None:
            try:
                return await replayed(adm, outcome)
            except OmsError as exc:
                return order_problem(exc, pager=paging)
        body = first_acceptance(outcome, oms.route.environment)
        order_id, row = outcome.written.order.id, caller.row
        detail: Mapping[str, str | None] = {
            "position_id": str(row.id), "order_id": str(order_id), "symbol": row.symbol,
            "full": str(full).lower(), "environment": oms.route.environment,
        }  # fmt: skip
        await oms.positions.record(RequestRecord(
            CLOSE_ACTION, row.exchange_account_id, "position", row.id, "success", "info",
            "requested", caller.actor, detail, caller.request_id,
        ))  # fmt: skip
        if full:
            await oms.positions.sweep_after_close(
                row, order_id, actor=caller.actor, request_id=caller.request_id
            )
        out = JSONResponse(body, 202)
        kept.put(*adm.held, StoredResponse(context.request_sha256, 202, bytes(out.body), None))
        return out

    @router.post(CLOSE_PATH, status_code=202)
    async def close_position(
        request: Request, position_ref: Annotated[str, Path(alias="positionId")]
    ) -> Response:
        admitted = await admit_position_write(
            request, position_ref, operation=_OPERATION, principals=principals, auth=auth,
            audit=audit, reads=reads, limiter=rate, max_body=MAX_CLOSE_BODY_BYTES,
            parse=read_close,
        )  # fmt: skip
        if not isinstance(admitted, PositionCaller):
            return admitted
        caller, row, terms = admitted, admitted.row, admitted.body
        oms = runtime()  # step 6
        if oms is None:
            return problem(501, "not_implemented", "No OMS is composed on this backend.")
        if oms.readiness != "ok":
            return not_ready()
        step = "key"
        try:
            key = idempotency_key(request)
            path = CLOSE_PATH.replace("{positionId}", str(row.id))
            digest = request_fingerprint("POST", path, caller.raw)
            held = replay_key(caller.principal.snapshot.user_id, _OPERATION, key)
            step = "replay"
            cached = replay_cached(kept, held, digest)
            if cached is not None:
                return cached
            step = "guard"
            if held in running:
                raise IdempotencyInFlight(retry_after_s=1)
            if len(running) >= MAX_IN_FLIGHT:
                return rate_limited(1, "closes in flight")
            adm = _Admitted(caller, oms, key, digest, held)
            step = "anchor"
            found = await oms.anchors.lookup(
                caller.principal.snapshot.user_id, key, digest, operation=_OPERATION
            )
            if isinstance(found, Replay):
                account = AccountId(row.exchange_account_id)
                return await replayed(adm, await oms.submission.answer_replay(account, found))
            if isinstance(found, InFlight | KeyReuse):
                raise found.refusal()
            step = "fence"  # C-2.6: only the fence; live, the kill switch and the gate never refuse
            fenced = oms.route.switches.refusal(AccountId(row.exchange_account_id),
                                                oms.route.environment)  # fmt: skip
            if isinstance(fenced, OmsNotReady):
                raise fenced
            step = "position"
            errors = position_errors(row, terms)
            if errors:
                raise OrderInvalid(errors[0].message, errors=errors)
        except OmsError as exc:
            if step == "key":
                return order_problem(exc)  # 400: no key to bind, unaudited as the body is
            return await refused(exc, caller, step)
        context = SubmitContext(caller.actor, key, digest, caller.request_id,
                                operation=_OPERATION, protective=True)  # fmt: skip
        order, full = close_request(row, terms), is_full_close(row, terms)
        running.add(held)
        try:
            task = oms.run(answer(adm, order, context, full))
        except OmsNotReady:
            running.discard(held)
            return not_ready()
        task.add_done_callback(lambda _done: running.discard(held))
        return await asyncio.shield(task)

    # --- closeAllPositions ----------------------------------------------------------------------

    async def scope_denied(snapshot: PrincipalSnapshot, actor: SubmitActor,
                           named: tuple[uuid.UUID, ...]) -> Response:  # fmt: skip
        """SR-E29-13's refusal: counted and audited `rbac.denied`, a 403 even unrecorded."""
        count_authz_denial(POSITIONS_WRITE, snapshot.roles, route=_ALL_OPERATION)
        reason = f"account_not_granted:{POSITIONS_WRITE.value}:granted_accounts"
        listed = [str(account) for account in named]
        try:  # one record naming the ids it listed, as cancel-all's (no account is in scope)
            await audit.emit(
                "rbac.denied", actor_label=str(actor.user_id), actor_user_id=actor.user_id,
                actor_ip=actor.ip, session_id=actor.session_id, outcome="denied",
                severity="warning", reason=reason, request_id=current_request_uuid(),
                after_state={"operation": _ALL_OPERATION, "exchange_account_ids": listed},
            )  # fmt: skip
        except (AuditError, RuntimeError) as exc:  # RuntimeError: the writer is not started
            _log().warning("oms_close_all_denial_unaudited", error=type(exc).__name__)
        return order_problem(AccountScopeDenied())

    async def flatten(
        oms: PositionRuntime, accounts: ScopedAccounts, rows: tuple[PositionRow, ...],
        request: CancelAllRequest, cancel: bool, actor: SubmitActor, key: uuid.UUID,
        digest: str, held: tuple[str, str],
    ) -> Response:  # fmt: skip
        """Each account's open orders cancelled when asked, then each position closed whole."""
        request_id = current_request_uuid()
        if cancel and accounts.ids:
            try:
                await oms.cancel_all.run(accounts, request, actor=actor, request_id=request_id)
            except OmsError as exc:  # the closes still go: flattening never waits on a cancel
                _log().warning("oms_close_all_cancel_failed", error=type(exc).__name__)
        results: list[Body] = []
        for account in accounts.ids:
            affected, error = 0, None
            for row in (r for r in rows if r.exchange_account_id == account):
                ref = uuid.uuid5(key, str(row.id))
                context = SubmitContext(actor, key, digest, request_id, operation=_ALL_OPERATION,
                                        anchor_ref=ref, protective=True)  # fmt: skip
                order = close_request(row, CloseTerms("market", pct=_HUNDRED))
                try:
                    outcome = await oms.submission.submit(order, context)
                except OmsError as exc:
                    error = error or _leg_error(problem_for(exc).code, exc)
                    continue
                if outcome.status != 202:
                    error = error or {"code": outcome.code or "exchange_error",
                                      "message": "The close was not accepted.",
                                      "retryable": outcome.status == 429}  # fmt: skip
                    continue
                affected += 1
                if outcome.written is not None:
                    await oms.positions.sweep_after_close(
                        row, outcome.written.order.id, actor=actor, request_id=request_id
                    )
            await oms.positions.record(RequestRecord(
                FLATTEN_ACTION, account, "exchange_account", account,
                "success" if error is None else "failure", "info" if error is None else "warning",
                "flattened" if error is None else str(error["code"]), actor,
                {"affected": str(affected), "symbol": request.symbol,
                 "environment": oms.route.environment}, request_id,
            ))  # fmt: skip
            results.append({"exchange_account_id": str(account), "ok": error is None,
                            "affected": affected, "error": error})  # fmt: skip
        succeeded = sum(1 for r in results if r["ok"])
        body: Body = {"results": results, "requested": len(results), "succeeded": succeeded}
        out = JSONResponse(body, 200)
        kept.put(*held, StoredResponse(digest, 200, bytes(out.body), None))
        return out

    @router.post(CLOSE_ALL_PATH)
    async def close_all_positions(request: Request) -> Response:
        if principals is None:
            return problem(501, "not_implemented", "No principal source is composed.")
        try:
            principal = await resolve_principal(principals, request, auth)
        except StoreUnavailable:
            return problem(503, "store_unavailable", "The session could not be read.")
        if principal is None:
            return problem(401, "unauthenticated", "No verified session for this request.")
        snapshot, actor = principal.snapshot, submit_actor(principal, request)
        try:
            await enforce(
                snapshot, POSITIONS_WRITE, emitter=audit, actor_ip=source_ip(request.scope),
                session_id=principal.session_id, request_id=current_request_uuid(),
            )  # fmt: skip
        except (ForbiddenError, AuditError, RuntimeError) as exc:
            if not isinstance(exc, ForbiddenError):
                _log().warning("oms_close_all_denial_unaudited", error=type(exc).__name__)
            need = [POSITIONS_WRITE.value]
            return problem(403, "forbidden", "Requires positions:write.", required_permissions=need)
        wait = rate.admit(str(snapshot.user_id))
        if wait is not None:
            return rate_limited(wait, "position writes")
        raw = await read_capped(request, _MAX_ALL_BODY_BYTES)
        if raw is None:
            message = f"Send at most {_MAX_ALL_BODY_BYTES} bytes."
            return invalid(FieldError("body", "body_too_large", message))
        parsed = close_all_body(raw)
        if not isinstance(parsed, CloseAllBody):
            return invalid(*parsed)
        try:
            key = idempotency_key(request)
        except OmsError as exc:
            return order_problem(exc)
        digest = request_fingerprint("POST", CLOSE_ALL_PATH, raw)
        held = replay_key(snapshot.user_id, _ALL_OPERATION, key)
        cached = replay_cached(kept, held, digest)
        if cached is not None:
            return cached
        if held in running:
            return order_problem(IdempotencyInFlight(retry_after_s=1))
        if len(running) >= MAX_IN_FLIGHT:
            return rate_limited(1, "requests in flight")
        oms = runtime()
        if oms is None:
            return problem(501, "not_implemented", "No OMS is composed on this backend.")
        if oms.readiness != "ok":
            return not_ready()
        named, symbol, cancel = (
            parsed.exchange_account_ids,
            parsed.symbol,
            parsed.cancel_open_orders,
        )
        selection = CancelAllRequest(named, symbol, frozenset(), exclude_reduce_only=True)
        scope = scope_for_target(snapshot, principal.target)
        try:
            accounts = await oms.cancel_all.scope(scope, selection)
            if reads is None:
                raise StoreUnavailable
            query = PositionQuery(accounts=accounts.ids, symbol=symbol, open_only=True)
            rows = await reads.positions(scope, query) if accounts.ids else ()
        except AccountScopeDenied:
            return await scope_denied(snapshot, actor, named)
        except OmsNotReady:
            return not_ready()
        except OmsError as exc:
            return order_problem(exc, pager=paging)
        settled = CancelAllRequest(accounts.ids, symbol, frozenset(), exclude_reduce_only=True)
        running.add(held)
        try:
            task = oms.run(flatten(oms, accounts, rows, settled, cancel, actor, key, digest, held))
        except OmsNotReady:
            running.discard(held)
            return not_ready()
        task.add_done_callback(lambda _done: running.discard(held))
        return await asyncio.shield(task)

    return router


def _leg_error(code: str, error: OmsError) -> Body:
    """22 `LegError`: the code, a fixed message, and whether a retry may succeed."""
    status = problem_for(error).status
    return {"code": code, "message": "The close was refused.", "retryable": status in (429, 503)}


@dataclass(frozen=True, slots=True)
class CloseAllBody:
    """22 `closeAllPositions`' body once read."""

    exchange_account_ids: tuple[uuid.UUID, ...]
    symbol: str | None
    cancel_open_orders: bool


def close_all_body(raw: bytes) -> CloseAllBody | tuple[FieldError, ...]:
    """22 `closeAllPositions`' body: the account ids (each a UUID, at most `_MAX_ACCOUNTS`), the
    symbol, `cancel_open_orders` (default true); nothing else."""
    body = parse_json_object(raw)
    if body is None:
        return (FieldError("body", "json_object", "Send a JSON object."),)
    errors = [FieldError(k, "extra_forbidden", "Unknown member.")
              for k in sorted(set(body) - {"exchange_account_ids", "symbol",
                                           "cancel_open_orders"})]  # fmt: skip
    ids: list[uuid.UUID] = []
    listed = body.get("exchange_account_ids", [])
    if not isinstance(listed, list) or len(listed) > _MAX_ACCOUNTS:
        errors.append(FieldError("exchange_account_ids", "array", "Send a list of account ids."))
    else:
        for value in listed:
            try:
                ids.append(uuid.UUID(value))
            except (TypeError, ValueError, AttributeError):  # not text, or not a UUID
                errors.append(FieldError("exchange_account_ids", "uuid", "Send each id as a UUID."))
                break
    symbol = body.get("symbol")
    if symbol is not None:
        try:
            api.Symbol.model_validate_json(json.dumps(symbol), strict=True)
        except ValidationError:
            errors.append(FieldError("symbol", "symbol", "Send a symbol such as BTCUSDT."))
    cancel = body.get("cancel_open_orders", True)
    if not isinstance(cancel, bool):
        errors.append(FieldError("cancel_open_orders", "boolean", "Send true or false."))
    if errors:
        return tuple(errors)
    named = tuple(dict.fromkeys(ids))
    return CloseAllBody(named, symbol if isinstance(symbol, str) else None, bool(cancel))
