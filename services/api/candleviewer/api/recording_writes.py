"""The recorded-set writes (E16-T08, #492): `recording:write`, scope none. Checked in order:
session (401), permission (403, audited), a user actor (403), the per-user write limit (429), the
`Idempotency-Key` and the body (422), the store (503), the `recorder` step-up where the write
changes retention (403), a replay (409 on another body), the entry in the settings' env and the
caller's view (404), then the write, audited ahead of the store (503 when it cannot be). No
control has writes until the recorder runtime is bound (#2188): until then every write is 503."""

from __future__ import annotations

import math
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any, Final

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
from candleviewer.api.recording_symbols import _dump
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.writer import AuditUnavailable, AuditWriterStopped
from candleviewer.auth.generated_permissions import Permission
from candleviewer.recorder import control as rc
from candleviewer.recorder.errors import RecorderError, RecorderSymbolLimitError
from candleviewer.recorder.models import Actor
from candleviewer.ws._generated.error_codes import ErrorCode

BAD, MISSING = ErrorCode.VALIDATION_FAILED, ErrorCode.NOT_FOUND
#: The session's step-up check for `recorder`: `None` when elevated, else the challenge answer.
Elevation = Callable[[uuid.UUID | None], Awaitable[JSONResponse | None]]
_RETAINS: Final = frozenset({"pinned", "retention_days"})  # a retention change (04 row 9)
_BASIS: Final = "~0.5-0.75 GB/day/symbol compressed at depth 200"
_DEEP: Final = "Depth 500 records more than the depth-200 planning rate."
_WINDOW_S: Final = 60.0


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
        super().__init__(429, ErrorCode.RATE_LIMITED, f"Too many recording writes; retry in "
                         f"{wait} s.", retry_after_seconds=wait)  # fmt: skip

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


def _missing() -> common.Problem:
    return common.Problem(404, MISSING, "No such recorded symbol.")


def _spec(body: BaseModel) -> rc.EntrySpec:
    """The fields the body names; the rest keep their setting (or take the default)."""
    named = {k: getattr(body, k) for k in body.model_fields_set}
    streams = named.get("streams")
    return rc.EntrySpec(None if streams is None else tuple(streams), named.get("depth"),
                        named.get("pinned"), named.get("retention_days"))  # fmt: skip


def _state(e: rc.RecordedEntry | rc.EntrySpec) -> dict[str, Any]:
    streams = None if e.streams is None else list(e.streams)
    return {"streams": streams, "depth": e.depth, "pinned": e.pinned,
            "retention_days": e.retention_days}  # fmt: skip


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
                       retains: Callable[[M], bool]) -> tuple[M, _Call]:  # fmt: skip
        p = await common.caller(principal_resolver, audit, request, Permission.RECORDING_WRITE)
        try:  # `added_by` and the audit name a user, so the actor must be one
            actor = Actor(kind="user", id=str(uuid.UUID(str(p.actor_id))))
        except ValueError:
            raise common.Problem(403, ErrorCode.FORBIDDEN, "Only a user may write.") from None
        if (wait := limits.admit(actor.id)) is not None:
            raise Limited(wait)
        raw = await request.body()
        try:
            key = idempotency_key(request, operation)
        except ValueError:
            raise common.Problem(422, BAD, "Idempotency-Key must be a UUID.") from None
        body = parse(request, raw)
        if (found := control()) is None:
            raise common.unavailable()
        if retains(body):
            if elevation is None:
                raise common.unavailable()
            if (refused := await elevation(p.session_id)) is not None:
                raise _Answered(refused)
        where = f"{request.url.path}?{request.url.query}"
        digest = request_fingerprint(request.method, where, raw)
        try:
            hit = replay(replays, actor.id, key, digest)
        except IdempotencyKeyReuse:
            msg = "The Idempotency-Key was first used with another request."
            raise common.Problem(409, ErrorCode.IDEMPOTENCY_KEY_REUSE, msg) from None
        return body, _Call(p, actor, found, key, digest, hit)

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

    async def _audit(call: _Call, action: str, symbol: str, entry_id: str | None = None,
                     **fields: Any) -> None:  # fmt: skip
        """One audit record, written before the store changes (C-2.9); none, no write (503)."""
        p, denied = call.p, fields.get("outcome") == AuditOutcome.DENIED
        try:
            await audit.emit(
                action, actor_label=p.actor_name, actor_user_id=p.actor_id, actor_ip=p.ip,
                session_id=p.session_id, request_id=p.request_id, object_kind="recorded_symbol",
                object_id=entry_id, object_label=symbol,
                severity=Severity.WARNING if denied else Severity.INFO, **fields,
            )  # fmt: skip
        except (AuditUnavailable, AuditWriterStopped):
            msg = "The audit record could not be written; nothing changed."
            raise common.Problem(503, ErrorCode.AUDIT_UNAVAILABLE, msg) from None

    @router.post("/recording/symbols")
    async def add_recorded_symbol(request: Request) -> Response:
        body, call = await begin(request, "addRecordedSymbol", _json(api.AddRecordedSymbolRequest),
                                 lambda b: bool(b.model_fields_set & _RETAINS))  # fmt: skip
        if call.replayed is not None:
            return call.replayed
        if not listed(body.symbol):
            rule = {"field": "symbol", "rule": "listed_instrument", "message": "Not listed."}
            raise common.Problem(422, BAD, "The symbol is not a listed instrument.", errors=[rule])
        spec = _spec(body)
        await _audit(call, "recorder.start", body.symbol, after_state=_state(spec))
        try:
            entry, created = await call.control.add(body.symbol, spec, call.actor)
        except RecorderSymbolLimitError:
            code = ErrorCode.RECORDER_SYMBOL_LIMIT
            await _audit(call, "recorder.start", body.symbol, outcome=AuditOutcome.DENIED,
                         reason=code.value)  # fmt: skip
            raise common.Problem(422, code, "The recorder's symbol cap is reached.") from None
        out = _dump(shown(call, entry))
        if created:
            out["estimate"] = {"basis": _BASIS, "warning": _DEEP if entry.depth == 500 else None}
        return done(call, JSONResponse(out, 201 if created else 200))

    @router.put("/recording/symbols/{recordedSymbolId}/pin")
    async def pin_recorded_symbol(
        request: Request, entry_id: Annotated[str, Path(alias="recordedSymbolId")]
    ) -> Response:
        """Always under the `recorder` step-up (04 row 9; the guard gates the path as well)."""
        body, call = await begin(request, "pinRecordedSymbol", _json(_Pin), lambda _b: True)
        if call.replayed is not None:
            return call.replayed
        entry = await visible(call, entry_id)
        after = {"pinned": body.pinned, "retention_days": body.retention_days}
        await _audit(call, "retention.change", entry.symbol, entry.id,
                     before_state=_state(entry), after_state=after)  # fmt: skip
        try:
            pinned = await call.control.pin(entry.id, body.pinned, call.actor,
                                            retention_days=body.retention_days)  # fmt: skip
        except RecorderError as exc:  # the row went after the lookup: no active row to pin
            await _audit(call, "retention.change", entry.symbol, entry.id,
                         outcome=AuditOutcome.DENIED, reason=type(exc).__name__)  # fmt: skip
            raise _missing() from None
        return done(call, JSONResponse(_dump(shown(call, pinned))))

    return router
