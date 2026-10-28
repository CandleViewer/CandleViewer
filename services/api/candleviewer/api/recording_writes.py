"""The recorded-set writes (E16-T08, #492): `recording:write`, scope none. Checked in order: session
(401), permission (403, audited), a user actor (403), the body's size (413), the `Idempotency-Key`
and the body (422), a malformed id (404), the per-user write limit (429, #4868), the store (503),
the `recorder` step-up where the write changes retention (403), a replay (409 on another body), the
entry in the settings' env and the caller's view (404), then the write. The pin, always under the
step-up, demands it after the entry's lookup instead, its challenge restating the entry and the pin
(#2304 slice 3c), and looks its key up only behind it (a kept answer, or the 409 for another
request). The policy records each write ahead of the store (503 when it cannot); a pin, an unpin and
a retention change included (#2188 S3c), so the routes record only what they refuse. The caller's
view goes to the port from the principal only (C-12.4): an unpin or a lower retention that a cause
outside it holds is 403, recorded once; on an add the manual reason may already have landed
(recorded by the policy) when a hidden cause took the row between the port's checks. No control
writes until the recorder runtime is bound (#2188 S4b): until then every write is 503."""

from __future__ import annotations

import math
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, replace
from typing import Annotated, Any, Final, NoReturn

from fastapi import APIRouter, Path, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from candleviewer.api import recording_common as common
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.drawings_models import format_errors
from candleviewer.api.idempotency import (
    IdempotencyCache,
    IdempotencyKeyReuse,
    idempotency_key,
    remember,
    replay,
    request_fingerprint,
)
from candleviewer.api.profile_body import BodyTooLarge, read_capped
from candleviewer.api.recording_symbols import _dump
from candleviewer.api.step_up_challenge import ChallengeText, pin_symbol_text
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.writer import AuditUnavailable, AuditWriterStopped
from candleviewer.auth.generated_permissions import Permission
from candleviewer.recorder import control as rc
from candleviewer.recorder.errors import RecorderInvalidUpdateError, RecorderSymbolNotRecordedError
from candleviewer.recorder.errors import RecorderSymbolLimitError as LimitError
from candleviewer.recorder.models import Actor
from candleviewer.ws._generated.error_codes import ErrorCode

BAD, MISSING = ErrorCode.VALIDATION_FAILED, ErrorCode.NOT_FOUND
#: The session's step-up check for `recorder`: `None` when elevated, else the challenge answer,
#: restating the request when the route names it (the pin and the retention set, #2304).
Elevation = Callable[[uuid.UUID | None, ChallengeText | None], Awaitable[JSONResponse | None]]
_RETAINS: Final = frozenset({"pinned", "retention_days"})  # a retention change (04 row 9)
_BASIS: Final = "~0.5-0.75 GB/day/symbol compressed at depth 200"
_DEEP: Final = "Depth 500 records more than the depth-200 planning rate."
_WINDOW_S: Final = 60.0
#: An add is a symbol, at most eight stream names, a depth, `pinned` and `retention_days`: under
#: 1 KiB. Past the cap the body is refused before it is buffered whole or parsed (#4868).
MAX_WRITE_BODY_BYTES: Final = 4_096
_NO_AUDIT: Final = "The audit record could not be written; nothing changed."
_RELAX: Final = "Only the owner can unpin this row or lower its retention."


class WriteLimiter:
    """At most `rate_per_minute` recording writes a minute per user (ruling Q7, on the model of
    `api/audit_limiter.py`): past it, `429` with `Retry-After`. Bounded (C-2.18): at most
    `tracked_users` users, the least recently seen dropped first; the clock is injected."""

    def __init__(self, *, rate_per_minute: int = 30, tracked_users: int = 1024,
                 clock: Callable[[], float] = time.monotonic) -> None:  # fmt: skip
        self._rate, self._cap, self._clock = rate_per_minute, tracked_users, clock
        self._users: OrderedDict[str, deque[float]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._users)

    def admit(self, user: str) -> int | None:
        """`None`, counting the write, when `user` may write now; else the seconds to wait."""
        now = self._clock()
        stamps = self._users.pop(user, None) or deque()
        self._users[user] = stamps  # most recently seen last
        while len(self._users) > self._cap:
            self._users.popitem(last=False)
        while stamps and now - stamps[0] >= _WINDOW_S:
            stamps.popleft()
        if len(stamps) >= self._rate:
            return max(1, math.ceil(_WINDOW_S - (now - stamps[0])))
        stamps.append(now)
        return None


class Limited(common.Problem):
    def __init__(self, wait: int) -> None:
        # one sentence: the countdown rides `Retry-After` and the extension, never the detail,
        # so two refusals a second apart answer one body (#4868)
        super().__init__(429, ErrorCode.RATE_LIMITED, "Too many recording writes; retry after "
                         "Retry-After.", retry_after_seconds=wait)  # fmt: skip

    def response(self) -> JSONResponse:
        out = super().response()
        out.headers["Retry-After"] = str(self.extra["retry_after_seconds"])
        return out


class _Answered(common.Problem):
    """An answer another gate built (the step-up challenge), returned as it is."""

    def __init__(self, out: JSONResponse) -> None:
        super().__init__(out.status_code, ErrorCode.STEP_UP_REQUIRED, "")
        self.out = out

    def response(self) -> JSONResponse:
        return self.out


class _Pin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    pinned: bool
    retention_days: Annotated[int, Field(ge=1, le=3650)] | None = None


class _Stop(BaseModel):  # unknown parameters are ignored, as FastAPI's own are
    model_config = ConfigDict(frozen=True, extra="ignore")
    purge_data: bool = False
    force: bool = False


@dataclass(frozen=True, slots=True)
class _Call:  # an admitted write: who, as which actor, against which control, under which key
    p: AuditPrincipal
    actor: Actor
    control: rc.RecordingControl
    key: str | None
    digest: str
    replayed: Response | None


def _json[B: BaseModel](model: type[B]) -> Callable[[Request, bytes], B]:
    def parse(_request: Request, raw: bytes) -> B:
        try:
            return model.model_validate_json(raw)
        except ValidationError as exc:  # bounded, input-free field errors
            raise common.Problem(422, BAD, "Invalid body.", errors=format_errors(exc)) from None

    return parse


def _update(request: Request, raw: bytes) -> api.UpdateRecordedSymbolRequest:
    """`retention_days: null` restores the default only with `pinned: false` (22)."""
    body = _json(api.UpdateRecordedSymbolRequest)(request, raw)
    if not body.model_fields_set:
        raise common.Problem(422, BAD, "The body names nothing to change.")
    if "retention_days" in body.model_fields_set and body.retention_days is None:
        if body.pinned is not False:
            rule = {"field": "retention_days", "rule": "retention_days_null_needs_unpin",
                    "message": "Null restores the default only with pinned: false."}  # fmt: skip
            raise common.Problem(422, BAD, "Invalid body.", errors=[rule])
    return body


def _stop(request: Request, _raw: bytes) -> bool:
    """`force`; `purge_data=true` is refused (ruling Q3): only `purgeRecordedData` deletes data."""
    try:
        query = _Stop.model_validate(dict(request.query_params))
    except ValidationError as exc:
        raise common.Problem(422, BAD, "Invalid query.", errors=format_errors(exc)) from None
    if query.purge_data:
        rule = {"field": "purge_data", "rule": "use_purge_route", "message": "Deprecated."}
        raise common.Problem(
            422, BAD, "A stop deletes no data; use the purge route.", errors=[rule]
        )
    return query.force


def _missing() -> common.Problem:
    return common.Problem(404, MISSING, "No such recorded symbol.")


def _spec(body: BaseModel) -> rc.EntrySpec:
    """The fields the body names; the rest keep their setting (or take the default)."""
    named = {k: getattr(body, k) for k in body.model_fields_set}
    streams, days = named.get("streams"), named.get("retention_days")
    return rc.EntrySpec(None if streams is None else tuple(streams), named.get("depth"),
                        named.get("pinned"), days,
                        "retention_days" in named and days is None)  # fmt: skip


def _invalid(rule: str, field: str | None) -> common.Problem:
    """`422` for a change the policy's own check refuses, naming its field and rule."""
    named = {"field": field, "rule": rule, "message": "Refused by the recorder."}
    return common.Problem(422, BAD, "Invalid body.", errors=[named])


async def _stored[T](write: Coroutine[Any, Any, T]) -> T:
    """A port write, which the policy records ahead of the store: a refused record is `503`."""
    try:
        return await write
    except (AuditUnavailable, AuditWriterStopped):
        raise common.Problem(503, ErrorCode.AUDIT_UNAVAILABLE, _NO_AUDIT) from None


def make_recording_writes_router(
    control: Callable[[], rc.RecordingControl | None],
    principal_resolver: common.Resolver | None,
    audit: common.Emitter,
    elevation: Elevation | None,
    listed: Callable[[str], bool],
    *,
    limiter: WriteLimiter | None = None,
    cache: IdempotencyCache | None = None,
) -> APIRouter:
    """`control` writes the recorded set (`None`: 503); `elevation` checks the `recorder`
    step-up; `listed` is the instrument catalogue's check of a symbol to add."""
    router = APIRouter(tags=["recording"], route_class=common.ProblemRoute)
    limits = WriteLimiter() if limiter is None else limiter  # both are falsy while empty
    replays = IdempotencyCache() if cache is None else cache

    async def begin[M](request: Request, operation: str, parse: Callable[[Request, bytes], M],
                       retains: Callable[[M], bool], *, entry_id: str | None = None,
                       looked_up: bool = True) -> tuple[M, _Call]:  # fmt: skip
        """The admission; `looked_up=False` leaves the key's lookup to `kept`, for a route that
        demands its step-up after this (the pin, #2304). The write limit is admitted once the
        key, the body or query and the path id parse, before any store or audit effect: a
        request that is no write answers its 422 or 404, touches nothing and spends no budget
        (#4868); every well-formed write is counted."""
        p = await common.caller(principal_resolver, audit, request, Permission.RECORDING_WRITE)
        try:  # `added_by` and the audit name a user, so the actor must be one
            actor = Actor(kind="user", id=str(uuid.UUID(str(p.actor_id))))
        except ValueError:
            raise common.Problem(403, ErrorCode.FORBIDDEN, "Only a user may write.") from None
        try:
            raw = await read_capped(request, MAX_WRITE_BODY_BYTES)
        except BodyTooLarge:
            msg = f"The body exceeds {MAX_WRITE_BODY_BYTES} bytes."
            raise common.Problem(413, ErrorCode.PAYLOAD_TOO_LARGE, msg) from None
        try:
            key = idempotency_key(request, operation)
        except ValueError:
            raise common.Problem(422, BAD, "Idempotency-Key must be a UUID.") from None
        body = parse(request, raw)
        if entry_id is not None:
            try:  # the id's own parse; `visible` looks it up, after the admission
                uuid.UUID(entry_id)
            except ValueError:
                raise _missing() from None
        if (wait := limits.admit(actor.id)) is not None:
            raise Limited(wait)
        if (found := control()) is None:
            raise common.unavailable()
        if retains(body):
            await gate(p, None)
        where = f"{request.url.path}?{request.url.query}"
        call = _Call(p, actor, found, key, request_fingerprint(request.method, where, raw), None)
        return body, kept(call) if looked_up else call

    def kept(call: _Call) -> _Call:
        """`call` with the key's kept answer, if any; the key with another request is 409."""
        try:
            hit = replay(replays, call.actor.id, call.key, call.digest)
        except IdempotencyKeyReuse:
            msg = "The Idempotency-Key was first used with another request."
            raise common.Problem(409, ErrorCode.IDEMPOTENCY_KEY_REUSE, msg) from None
        return replace(call, replayed=hit)

    async def gate(p: AuditPrincipal, text: ChallengeText | None) -> None:
        """The `recorder` step-up (unwired: 503); a refusal is raised as its answer."""
        if elevation is None:
            raise common.unavailable()
        if (refused := await elevation(p.session_id, text)) is not None:
            raise _Answered(refused)

    def done(call: _Call, out: Response) -> Response:
        return remember(replays, call.actor.id, call.key, call.digest, out)

    def view(call: _Call, entry: rc.RecordedEntry) -> rc.RecordedEntry | None:
        """`entry` as the caller sees it: a restricted view (R-I2, Q6) for all but the Owner."""
        return entry if call.p.is_owner else rc.restricted_view(entry)

    def shown(call: _Call, entry: rc.RecordedEntry | None) -> rc.RecordedEntry:
        if entry is None or (seen := view(call, entry)) is None:
            raise _missing()
        return seen

    async def visible(call: _Call, entry_id: str) -> rc.RecordedEntry:
        """The entry by id, looked up in the settings' env (C-2.11) before any write; another
        env's, a malformed or a restricted-away id is the same 404."""
        try:
            uid = str(uuid.UUID(entry_id))
        except ValueError:
            raise _missing() from None
        if (entry := await call.control.get(uid)) is None or view(call, entry) is None:
            raise _missing()
        return entry

    async def _audit(call: _Call, action: str, symbol: str, entry_id: str | None,
                      refused: str | None = None, **fields: Any) -> None:  # fmt: skip
        """A record the route writes (C-2.9); `refused`: a refused write's cause. Unwritten: 503."""
        p, out = call.p, {"outcome": AuditOutcome.DENIED, "reason": refused}
        await _stored(audit.emit(
            action, actor_label=p.actor_name, actor_user_id=p.actor_id, actor_ip=p.ip,
            session_id=p.session_id, request_id=p.request_id, object_kind="recorded_symbol",
            object_id=entry_id, object_label=symbol, **(out if refused is not None else {}),
            **fields, severity=Severity.INFO if refused is None else Severity.WARNING,
        ))  # fmt: skip

    async def relax_refused(call: _Call, refused: rc.RelaxRefused, symbol: str,
                            entry_id: str | None) -> NoReturn:  # fmt: skip
        """`403` for an unpin or a lower retention the caller's view does not cover (ruled
        05:10Z), nothing changed: one denied `retention.change`, the policy's or this one."""
        if not refused.recorded:
            await _audit(call, "retention.change", symbol, entry_id, "relax_refused")
        raise common.Problem(403, ErrorCode.FORBIDDEN, _RELAX)

    async def audit_refusal(
        call: _Call, entry: rc.RecordedEntry, causes: tuple[rc.Refusal, ...]
    ) -> NoReturn:
        """`409` for a refused stop. The audit names the real cause; the body names it to the
        Owner, and to anyone else only a cause their view shows (restricted refusal parity)."""
        held = replace(entry, refusals=causes)
        cause = rc.stop_refusal(held) or "conflict"
        await _audit(call, "recorder.stop", entry.symbol, entry.id, cause)
        named = rc.stop_refusal(held, restricted=not call.p.is_owner)
        extra = {} if named is None else {"refusal": named}
        raise common.Problem(409, ErrorCode.CONFLICT, "An auto-record trigger holds the symbol.",
                             **extra)  # fmt: skip

    @router.post("/recording/symbols")
    async def add_recorded_symbol(request: Request) -> Response:
        body, call = await begin(request, "addRecordedSymbol", _json(api.AddRecordedSymbolRequest),
                                 lambda b: bool(b.model_fields_set & _RETAINS))  # fmt: skip
        if call.replayed is not None:
            return call.replayed
        if not listed(body.symbol):
            rule = {"field": "symbol", "rule": "listed_instrument", "message": "Not listed."}
            raise common.Problem(422, BAD, "The symbol is not a listed instrument.", errors=[rule])
        spec, status = _spec(body), await call.control.status()
        entries = (e for e in status.entries if e.symbol == body.symbol and e.id)  # rows: an id
        held = next(entries, None)
        held_id = None if held is None else held.id
        if held is not None and view(call, held) is None:  # held only by a cause outside the view
            if not held.streams:  # no stored streams to keep: the policy would name its default
                raise common.unavailable()
            if body.model_fields_set & _RETAINS:  # a join honours neither: the request's record
                await _audit(call, "retention.change", body.symbol, held.id, "joined")
            spec = rc.EntrySpec(held.streams, held.depth)  # a join adds a cause, changes no setting
        try:  # the policy writes `recorder.start` ahead of the row (add_manual)
            restricted = not call.p.is_owner  # the principal's view, never the request's
            entry, prior = await _stored(
                call.control.add(body.symbol, spec, call.actor, restricted=restricted)
            )
        except rc.RelaxRefused as refused:
            await relax_refused(call, refused, body.symbol, held_id)
        except RecorderSymbolNotRecordedError:  # a racing stop took the row after the add; the
            # record's `object_id` is null when this add created the row (no id was read before)
            await _audit(call, "recorder.start", body.symbol, held_id, "not_recorded")
            raise _missing() from None
        except (LimitError, RecorderInvalidUpdateError) as exc:  # before its record
            capped, (setting, field) = isinstance(exc, LimitError), rc.setting_rule(spec.depth)
            cause = ErrorCode.RECORDER_SYMBOL_LIMIT.value if capped else setting
            if not capped:
                raise _invalid(setting, field) from None
            await _audit(call, "recorder.start", body.symbol, None, cause)
            raise common.Problem(422, ErrorCode.RECORDER_SYMBOL_LIMIT,
                                 "The recorder's symbol cap is reached.") from None  # fmt: skip
        seen = shown(call, entry)
        out = _dump(seen)
        if prior is None:
            out["estimate"] = {"basis": _BASIS, "warning": _DEEP if seen.depth == 500 else None}
        return done(call, JSONResponse(out, 201 if prior is None else 200))

    @router.put("/recording/symbols/{recordedSymbolId}/pin")
    async def pin_recorded_symbol(
        request: Request, entry_id: Annotated[str, Path(alias="recordedSymbolId")]
    ) -> Response:
        """Always under the `recorder` step-up (04 row 9), demanded once the body is valid and
        the entry is found (#2304 slice 3c), so a refused or missing one is never challenged;
        a kept answer is read back only behind it."""
        body, call = await begin(request, "pinRecordedSymbol", _json(_Pin), lambda _b: False,
                                 entry_id=entry_id, looked_up=False)  # fmt: skip
        entry = await visible(call, entry_id)
        days = None if body.pinned else body.retention_days
        await gate(call.p, pin_symbol_text(entry.symbol, entry.id, pinned=body.pinned,
                                           retention_days=days))  # fmt: skip
        if (call := kept(call)).replayed is not None:  # the key, only behind the step-up
            return call.replayed
        try:  # the policy records the pin or the unpin, its retention too, ahead of the row
            pinned = await _stored(call.control.pin(
                entry.id, body.pinned, call.actor, restricted=not call.p.is_owner,
                retention_days=body.retention_days))  # fmt: skip
        except rc.RelaxRefused as refused:
            await relax_refused(call, refused, entry.symbol, entry.id)
        if pinned is None:  # the row went after the lookup: no active row to pin
            await _audit(call, "retention.change", entry.symbol, entry.id, "not_recorded")
            raise _missing()
        return done(call, JSONResponse(_dump(shown(call, pinned))))

    @router.patch("/recording/symbols/{recordedSymbolId}")
    async def update_recorded_symbol(
        request: Request, entry_id: Annotated[str, Path(alias="recordedSymbolId")]
    ) -> Response:
        """`pinned` or `retention_days` under the `recorder` step-up (04 row 9); `streams` and
        `depth` alone without (row 8). The policy records `recorder.update` (update_manual) and
        `retention.change` (set_pin, set_retention) ahead of its store. `retention_days` on a
        row that stays pinned is ignored: a pin keeps forever (22 nulls the days). The answer
        reports the stored values; it promises no change to a running session."""
        body, call = await begin(request, "updateRecordedSymbol", _update,
                                 lambda b: bool(b.model_fields_set & _RETAINS),
                                 entry_id=entry_id)  # fmt: skip
        if call.replayed is not None:
            return call.replayed
        entry, spec = await visible(call, entry_id), _spec(body)
        try:
            restricted = not call.p.is_owner  # the principal's view, never the request's
            updated = await _stored(
                call.control.update(entry.id, spec, call.actor, restricted=restricted)
            )
        except rc.RelaxRefused as refused:
            await relax_refused(call, refused, entry.symbol, entry.id)
        except rc.ChangeRefused as refused:
            if refused.rule != "not_manual":  # the policy's own check of the change
                raise _invalid(refused.rule, refused.field) from None
            await _audit(call, "recorder.update", entry.symbol, entry.id, refused.rule)
            msg = "Streams and depth change only on a manually recorded symbol."
            raise common.Problem(409, ErrorCode.CONFLICT, msg) from None
        return done(call, JSONResponse(_dump(shown(call, updated))))

    @router.delete("/recording/symbols/{recordedSymbolId}")
    async def remove_recorded_symbol(
        request: Request, entry_id: Annotated[str, Path(alias="recordedSymbolId")]
    ) -> Response:
        """Ends the manual reason: `204`, the row then lingers until the grace window ends (Q1);
        a pin stays (Q4). Refused while a trigger holds, unless `force`. No step-up: it changes
        no retention and deletes nothing."""
        force, call = await begin(request, "removeRecordedSymbol", _stop, lambda _f: False,
                                  entry_id=entry_id)  # fmt: skip
        if call.replayed is not None:
            return call.replayed
        entry = await visible(call, entry_id)
        if not force and rc.stop_refusal(entry) is not None:  # refused before remove_manual
            await audit_refusal(call, entry, entry.refusals)
        try:  # the policy writes `recorder.stop` ahead of the row (remove_manual)
            await _stored(call.control.remove(entry.id, call.actor, force=force))
        except rc.StopRefused as refused:  # a trigger came after the lookup
            await audit_refusal(call, entry, refused.causes)
        return done(call, Response(status_code=204))

    return router
