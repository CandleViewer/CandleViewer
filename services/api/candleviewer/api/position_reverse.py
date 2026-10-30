"""`POST /positions/{positionId}/reverse`, `reversePosition` (E29-T07 #915; 22 as amended by
#5013; 21 Sec.3.3.10, 24 Sec.8.3 rule 1).

After the middleware and the shared admission (`api.position_admission`, steps 1 to 5), each step
before the next:

6. the runtime: none composed is 501, one whose readiness is not `ok` 503 `oms_not_ready`;
7. the arm token on a live account (22 `ArmToken`; a repeat passes it too, before any lookup):
   403 `session_not_armed`;
8. `Idempotency-Key` (400 without one); 9. the 24 h record: every `202` is stored and replayed
   verbatim; 10. the in-process guard: a repeat while the first request runs is 409
   `idempotency_in_flight` with `Retry-After: 1`;
11. the anchors, `uuid5(key, "close")` then `uuid5(key, "open")` (`reversePosition`): a reversal
    is undecided while either is, and a repeat decides it, the close's first, never resumes it and
    never sends: with the entry's anchor present the answer is `reversed` with the entry as it
    stands; without it, the close's reconciled state decides (`close_unfilled`, with
    `close.reconciling` while unresolved; `close_partially_filled`; `entry_refused` with reason
    `timeout` once the close filled). A recorded `429` or `502` on the close is replayed;
12. the refusals knowable before any send: `trading.oms_enabled` (the entry is no reduce-only
    order), then live trading, the kill switch and the order-entry gate (403 `trading_disabled`);
    an open position; the native-stop pre-check (`PositionWrites.entry_stop_ready`, C-2.6): an
    account whose profile cannot give the entry a stop is 422 `validation_failed`
    (`native_stop_required`), nothing sent;
13. the reversal, as a task the runtime tracks, shielded from the client's disconnect: the
    reduce-only market close of the whole position; then the wait, on the injected clock, for B1 to
    confirm it filled, at most `REVERSE_WAIT_S` from the request's arrival; then the venue's own
    read of the position's key (`venue_position`): any size left is `entry_refused` with reason
    `open_exposure`, a failed read `exchange_unavailable`, no entry sent; then, only once it filled
    and the venue reads it flat, the profile-sized entry with its native stop. A close the exchange
    rejects is its `502`, no entry sent; one not filled, or partly, at the deadline ends the
    reversal with no entry; an entry refused by a check or the exchange is `entry_refused` with its
    code.

Each order keeps its own write-ahead submit record (the pipeline's, C-2.9); one
`position.reversed` record correlates the pair and the outcome before the answer returns. Every
refusal from step 7 on is recorded (`position.reversed`, outcome `denied`, its code) before it is
answered, else 503 `audit_unavailable`. No log line carries the key, the fingerprint or a value of
the row (C-12.6).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Annotated, Any, Final, Literal

import structlog
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.idempotency import IdempotencyCache, StoredResponse, request_fingerprint
from candleviewer.api.order_acceptance import first_acceptance
from candleviewer.api.order_admission import (
    AuditEmitter,
    OrderPrincipals,
    arm_token,
    field_errors,
    idempotency_key,
    parse_json_object,
    problem,
    replay_cached,
    replay_key,
)
from candleviewer.api.order_problems import order_problem, outcome_problem
from candleviewer.api.position_admission import (
    PositionCaller,
    admit_position_write,
    invalid,
    rate_limited,
)
from candleviewer.api.position_close import (
    MAX_IN_FLIGHT,
    RATE_PER_MINUTE,
    PositionRuntime,
    position_errors,
    replayed_body,
)
from candleviewer.api.recording_writes import WriteLimiter
from candleviewer.api.refusal_session import SessionsLike
from candleviewer.auth.scopes import account_scope
from candleviewer.domain.primitives import AccountId
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.oms.errors import (
    PROBLEMS,
    AuditNotDurable,
    FieldError,
    IdempotencyInFlight,
    OmsError,
    OmsNotReady,
    OrderInvalid,
    SessionNotArmed,
    TradingDisabled,
    problem_for,
)
from candleviewer.oms.idempotency import InFlight, KeyReuse, Replay
from candleviewer.oms.ports import FAILED, OrderType, RequestRecord, SubmitAudit
from candleviewer.oms.position_writes import (
    REVERSE_ACTION,
    REVERSE_WAIT_S,
    CloseTerms,
    close_request,
    entry_request,
    reversal_refs,
)
from candleviewer.oms.reads import OmsReads
from candleviewer.oms.submit import RECONCILING, STORE_TIMEOUT_S, SubmitContext, SubmitOutcome
from candleviewer.statechart.plugins import LogPager, Pager

__all__ = [
    "MAX_REVERSE_BODY_BYTES", "REVERSE_PATH", "decided_outcome", "make_position_reverse_router",
    "read_reverse",
]  # fmt: skip

REVERSE_PATH: Final = "/positions/{positionId}/reverse"
_OPERATION: Final = "reversePosition"
#: 22 `ReversePositionRequest`: three short members.
MAX_REVERSE_BODY_BYTES: Final = 1_024
_HUNDRED: Final = Decimal(100)

type Body = dict[str, object]
Outcome = Literal["reversed", "close_unfilled", "close_partially_filled", "entry_refused"]
#: `entry_refused`'s `reason` when the venue does not read the position flat after its close
#: filled, each an `x-error-codes` code (22 `ReverseAcceptance.reason`): size left on the key is
#: `open_exposure` (the account holds an open position the request does not resolve); a read
#: that fails is `exchange_unavailable`.
_VENUE_REFUSAL: Final[Mapping[str, str]] = {
    "open": "open_exposure",
    "unread": "exchange_unavailable",
}


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EntryTerms:
    """22 `ReversePositionRequest` once read: the entry's type and price (`size_mode` is
    `profile`, the only value 22 admits)."""

    order_type: OrderType = "market"
    price: Decimal | None = None


def read_reverse(raw: bytes) -> EntryTerms | tuple[FieldError, ...]:
    """The body, optional (22: `requestBody.required: false`), read strictly."""
    if not raw.strip():
        return EntryTerms()
    if parse_json_object(raw) is None:
        return (FieldError("body", "json_object", "Send a JSON object."),)
    try:
        read = api.ReversePositionRequest.model_validate_json(raw, strict=True)
    except ValidationError as exc:
        return tuple(field_errors(exc))
    if read.order_type == "limit" and read.price is None:
        return (FieldError("price", "required", "A limit entry needs a price."),)
    return EntryTerms(read.order_type, None if read.price is None else Decimal(read.price))


def decided_outcome(
    close: SubmitOutcome, chart: str | None, filled: Decimal
) -> tuple[Outcome, str | None]:
    """A reversal without its entry's anchor, from its close's reconciled state (22): unresolved
    is `close_unfilled`; filled, `entry_refused` (`timeout`: no entry is sent this late); partly
    filled, `close_partially_filled`; otherwise `close_unfilled`."""
    if close.lifecycle == RECONCILING:
        return "close_unfilled", None
    if chart == "filled":
        return "entry_refused", "timeout"
    if filled > 0:
        return "close_partially_filled", None
    return "close_unfilled", None


@dataclass(frozen=True, slots=True)
class _Admitted:
    caller: PositionCaller[EntryTerms]
    oms: PositionRuntime
    key: uuid.UUID
    digest: str
    held: tuple[str, str]
    started: float


def make_position_reverse_router(
    principals: OrderPrincipals | None, runtime: Callable[[], PositionRuntime | None],
    reads: OmsReads | None, *, audit: AuditEmitter, records: SubmitAudit,
    oms_enabled: Callable[[], bool], metrics: Metrics, auth: SessionsLike | None = None,
    replays: IdempotencyCache | None = None, limiter: WriteLimiter | None = None,
    pager: Pager | None = None, wait_s: float = REVERSE_WAIT_S,
) -> APIRouter:  # fmt: skip
    """`reversePosition` (module docstring). The wait is at most `wait_s` from the request's
    arrival, measured on the runtime's own clock (`PositionRuntime.monotonic`), the one the fill
    wait's deadline is read on, so the deadline uses one clock."""
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

    async def refused(error: OmsError, caller: PositionCaller[EntryTerms], step: str) -> Response:
        """A refusal from step 7 on: recorded before it is answered (C-2.9), else 503."""
        if isinstance(error, OmsNotReady):
            return not_ready()
        row, code = caller.row, problem_for(error).code
        record = RequestRecord(
            REVERSE_ACTION, row.exchange_account_id, "position", row.id, "denied",
            "error" if problem_for(error).status >= 500 else "warning", code, caller.actor,
            {"step": step, "code": code, "symbol": row.symbol}, caller.request_id,
        )  # fmt: skip
        try:
            async with asyncio.timeout(STORE_TIMEOUT_S):
                await records.write(record)
        except Exception as exc:  # no refusal is answered unrecorded; the key stays unbound
            rejected.labels(PROBLEMS[AuditNotDurable].code).inc()
            _log().error("oms_reverse_refusal_unrecorded", step=step, error=type(exc).__name__)
            return order_problem(AuditNotDurable("the refusal's record did not land"))
        rejected.labels(code).inc()
        if isinstance(error, OrderInvalid) and step in ("position", "stop"):
            return invalid(*error.errors)
        return order_problem(error, pager=paging)

    def answered(adm: _Admitted, body: Body, *, replayed: bool) -> Response:
        """A `202`: every one is stored and replayed verbatim (22)."""
        headers = {"Idempotency-Replayed": "true"} if replayed else {}
        out = JSONResponse(body, 202, headers)
        kept.put(*adm.held, StoredResponse(adm.digest, 202, bytes(out.body), None))
        return out

    async def correlate(
        adm: _Admitted, outcome: Outcome, reason: str | None, close_id: object, open_id: object
    ) -> None:
        """The one `position.reversed` record of the pair and its outcome, before the answer."""
        row = adm.caller.row
        detail: Mapping[str, str | None] = {
            "position_id": str(row.id), "symbol": row.symbol, "outcome": outcome,
            "reason": reason, "close_order_id": None if close_id is None else str(close_id),
            "open_order_id": None if open_id is None else str(open_id),
            "environment": adm.oms.route.environment,
        }  # fmt: skip
        await adm.oms.positions.record(RequestRecord(
            REVERSE_ACTION, row.exchange_account_id, "position", row.id, "success", "info",
            outcome, adm.caller.actor, detail, adm.caller.request_id,
        ))  # fmt: skip

    async def decide(adm: _Admitted, found: Replay, open_ref: uuid.UUID) -> Response:
        """Step 11's repeat (module docstring): decided from the anchors, nothing sent."""
        oms, caller = adm.oms, adm.caller
        account = AccountId(caller.row.exchange_account_id)
        scope = account_scope(caller.principal.snapshot)
        closed = await oms.submission.answer_replay(account, found)
        if closed.status != 202:
            return outcome_problem(closed)
        close_body, close_row = await replayed_body(oms, closed, scope, account)
        user = caller.principal.snapshot.user_id
        opened = await oms.anchors.lookup(user, open_ref, adm.digest, operation=_OPERATION)
        if isinstance(opened, InFlight | KeyReuse):
            raise opened.refusal()
        if isinstance(opened, Replay):
            entry = await oms.submission.answer_replay(account, opened)
            # its rows, whatever its first answer was: an entry's end is in `open` (22)
            shown = replace(entry, status=202, code=None, ret_code=None, retry_after_s=None)
            open_body, open_row = await replayed_body(oms, shown, scope, account)
            body: Body = {
                "close": close_body,
                "open": open_body,
                "outcome": "reversed",
                "reason": None,
            }
            await correlate(adm, "reversed", None, close_row.id, open_row.id)
            return answered(adm, body, replayed=True)
        outcome, reason = decided_outcome(closed, close_row.lifecycle_state, close_row.cum_exec_qty)
        decided: Body = {"close": close_body, "open": None, "outcome": outcome, "reason": reason}
        await correlate(adm, outcome, reason, close_row.id, None)
        return answered(adm, decided, replayed=True)

    async def reverse(
        adm: _Admitted, entry: EntryTerms, refs: tuple[uuid.UUID, uuid.UUID]
    ) -> Response:
        """Step 13's task (module docstring): the close, the wait, then the entry."""
        oms, caller, row = adm.oms, adm.caller, adm.caller.row
        close_ref, open_ref = refs
        account = AccountId(row.exchange_account_id)
        env, scope = oms.route.environment, account_scope(caller.principal.snapshot)
        context = SubmitContext(caller.actor, adm.key, adm.digest, caller.request_id,
                                operation=_OPERATION, anchor_ref=close_ref)  # fmt: skip
        try:
            closed = await oms.submission.submit(
                close_request(row, CloseTerms("market", pct=_HUNDRED)), context
            )
        except OmsError as exc:  # refused and recorded by the pipeline: nothing sent
            return order_problem(exc, pager=paging)
        if closed.status != 202:  # the close rejected, or refused at the send: no entry
            return outcome_problem(closed)
        if closed.replayed or closed.written is None:  # the key's earlier request answers
            replay = await oms.anchors.lookup(caller.principal.snapshot.user_id, close_ref,
                                              adm.digest, operation=_OPERATION)  # fmt: skip
            if not isinstance(replay, Replay):
                return order_problem(IdempotencyInFlight(retry_after_s=1))
            return await decide(adm, replay, open_ref)
        close_id = closed.written.order.id
        deadline = adm.started + wait_s  # on the runtime's clock, from the request's arrival
        fill = await oms.positions.await_fill(account, close_id, deadline=deadline)
        try:  # the close as it stands after the wait, else as its first answer wrote it
            close_body, _ = await replayed_body(oms, closed, scope, account)
        except (OmsError, ValueError):
            close_body = first_acceptance(closed, env)
        if fill != "filled":  # never an entry against a position still open (22)
            outcome: Outcome = "close_unfilled" if fill == "unfilled" else "close_partially_filled"
            await correlate(adm, outcome, None, close_id, None)
            return answered(adm, {"close": close_body, "open": None, "outcome": outcome,
                                  "reason": None}, replayed=False)  # fmt: skip
        # B1 says filled; the venue must say flat too before the entry goes (22, C-2.6): size left
        # on the key, or a read that fails, sends no entry.
        venue = await oms.positions.venue_position(row)
        if venue != "flat":
            reason = _VENUE_REFUSAL[venue]
            await correlate(adm, "entry_refused", reason, close_id, None)
            return answered(adm, {"close": close_body, "open": None,
                                  "outcome": "entry_refused", "reason": reason},
                            replayed=False)  # fmt: skip
        entry_context = replace(context, anchor_ref=open_ref)
        try:
            opened = await oms.submission.submit(
                entry_request(row, entry.order_type, entry.price), entry_context
            )
        except OmsError as exc:  # recorded by the pipeline: the account is flat on the symbol
            reason = problem_for(exc).code
            await correlate(adm, "entry_refused", reason, close_id, None)
            return answered(adm, {"close": close_body, "open": None,
                                  "outcome": "entry_refused", "reason": reason},
                            replayed=False)  # fmt: skip
        if opened.status != 202:  # the exchange's rejection, or its rate at the send
            reason = opened.code or "exchange_error"
            await correlate(adm, "entry_refused", reason, close_id, opened.order_id)
            return answered(adm, {"close": close_body, "open": None,
                                  "outcome": "entry_refused", "reason": reason},
                            replayed=False)  # fmt: skip
        if opened.written is None:  # a held key met at the persist: its rows as they stand
            open_body, open_row = await replayed_body(oms, opened, scope, account)
            open_id: uuid.UUID = open_row.id
        else:
            open_body, open_id = first_acceptance(opened, env), opened.written.order.id
        await correlate(adm, "reversed", None, close_id, open_id)
        return answered(adm, {"close": close_body, "open": open_body, "outcome": "reversed",
                              "reason": None}, replayed=False)  # fmt: skip

    async def guarded(
        adm: _Admitted, entry: EntryTerms, refs: tuple[uuid.UUID, uuid.UUID]
    ) -> Response:
        try:
            return await reverse(adm, entry, refs)
        except OmsError as exc:  # a read on the way failed: the orders sent stand, B1 owns them
            return order_problem(exc, pager=paging)
        except ValueError:  # SEC-S3F2-03: a group other than its outcome's, so fail closed
            return order_problem(OmsError("a replay read a group other than its outcome's"))

    @router.post(REVERSE_PATH, status_code=202)
    async def reverse_position(
        request: Request, position_ref: Annotated[str, Path(alias="positionId")]
    ) -> Response:
        arrived = runtime()  # its clock read at arrival; step 6 judges whether it is composed
        started = None if arrived is None else arrived.monotonic()
        admitted = await admit_position_write(
            request, position_ref, operation=_OPERATION, principals=principals, auth=auth,
            audit=audit, reads=reads, limiter=rate, max_body=MAX_REVERSE_BODY_BYTES,
            parse=read_reverse,
        )  # fmt: skip
        if not isinstance(admitted, PositionCaller):
            return admitted
        caller, row, entry = admitted, admitted.row, admitted.body
        oms = runtime()  # step 6
        if oms is None:
            return problem(501, "not_implemented", "No OMS is composed on this backend.")
        if oms.readiness != "ok":
            return not_ready()
        if started is None:  # composed since the request arrived: measured from now
            started = oms.monotonic()
        account, step = AccountId(row.exchange_account_id), "arm"
        try:
            armed = oms.route.arm_records.check(
                session_id=caller.principal.session_id, environment=oms.route.environment,
                token=arm_token(request),
            )  # fmt: skip
            if armed == FAILED:
                raise SessionNotArmed
            step = "key"
            try:
                key = idempotency_key(request)
            except OmsError as exc:
                return order_problem(exc)  # 400: no key to bind, unaudited as the body is
            path = REVERSE_PATH.replace("{positionId}", str(row.id))
            digest = request_fingerprint("POST", path, caller.raw)
            user = caller.principal.snapshot.user_id
            held = replay_key(user, _OPERATION, key)
            step = "replay"
            cached = replay_cached(kept, held, digest)
            if cached is not None:
                return cached
            step = "guard"
            if held in running:
                raise IdempotencyInFlight(retry_after_s=1)
            if len(running) >= MAX_IN_FLIGHT:
                return rate_limited(1, "reversals in flight")
            adm = _Admitted(caller, oms, key, digest, held, started)
            refs = reversal_refs(key)
            step = "anchor"
            found = await oms.anchors.lookup(user, refs[0], digest, operation=_OPERATION)
            if isinstance(found, InFlight | KeyReuse):
                raise found.refusal()
            if isinstance(found, Replay):
                return await decide(adm, found, refs[1])
            step = "flag"
            if not oms_enabled():
                raise TradingDisabled
            step = "switches"
            switched = oms.route.switches.refusal(account, oms.route.environment)
            if switched is not None:
                raise switched
            step = "position"
            errors = position_errors(row, CloseTerms("market", pct=_HUNDRED))
            if errors:
                raise OrderInvalid(errors[0].message, errors=errors)
            step = "stop"
            await oms.positions.entry_stop_ready(account)
        except OmsError as exc:
            return await refused(exc, caller, step)
        except ValueError:  # SEC-S3F2-03: a group other than its outcome's, so fail closed
            return order_problem(OmsError("a replay read a group other than its outcome's"))
        running.add(held)
        try:
            task = oms.run(guarded(adm, entry, refs))
        except OmsNotReady:
            running.discard(held)
            return not_ready()
        task.add_done_callback(lambda _done: running.discard(held))
        return await asyncio.shield(task)

    return router
