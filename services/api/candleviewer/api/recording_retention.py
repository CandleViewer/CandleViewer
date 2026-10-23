"""`listRetentionPolicies` and `setRetentionPolicies` (E16-T08, #492): read with `recording:read`;
replace with `recording:write` behind the path-gated `recorder` step-up (`api.step_up`, 04 row 9).

The PUT is checked in order: session (401), permission (403, audited), `Idempotency-Key` (a
replay, or 409 for another body), body (422 `validation_failed`, unknown fields too), the Q5
mapping and the validator (422 `retention_invalid_policy`), store (503), `apply_now` (409 with
retention off, 409 `job_running`). Then `retention.change` is written with the set before and
after, BEFORE the set is replaced in one transaction (C-2.9): if it cannot be written the answer
is 503 `audit_unavailable` and nothing changes. `apply_now` reserves its one `retention_sweep`
job first and lets it run only once the new set is stored; a refused request cancels it.

Q5: `retain_days` is the hot window for `archive_parquet` (the stream's total horizon stays its
default) and the total horizon for `drop`. The store holds no field for `downsample`, `pin` or
`applies_to_pinned`, so those are refused until it does."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from candleviewer.api import recording_common as common
from candleviewer.api.drawings_models import format_errors
from candleviewer.api.idempotency import (
    IdempotencyCache,
    IdempotencyKeyReuse,
    idempotency_key,
    remember,
    replay,
    request_fingerprint,
)
from candleviewer.api.recorder_admin import JOB_KIND, AdminJobStore, Job, JobConflict, logger
from candleviewer.audit.models import Severity
from candleviewer.auth.generated_permissions import Permission
from candleviewer.recorder.retention import (
    DERIVED_FROM_TRADES,
    InvalidRetentionPolicy,
    PolicyRow,
    RunReport,
    validate_policies,
)
from candleviewer.recorder.retention_defaults import STREAM_DEFAULTS, canonical_stream
from candleviewer.ws._generated.error_codes import ErrorCode

_PATH = "/recording/retention-policies"
_MAX_BODY = 256 * 1024
_UNHELD = "The store holds no field for this yet."
Stream = Literal["trades", "orderbook_delta", "orderbook_snapshot", "tickers", "klines",
                 "liquidations", "open_interest", "funding"]  # fmt: skip


class PolicyStore(Protocol):  # `SqlAlchemyRetentionPolicies`
    async def list_policies(self) -> list[dict[str, Any]]: ...
    async def replace(self, rows: Sequence[Mapping[str, Any]], *,
                      actor: str | None) -> list[dict[str, Any]]: ...  # fmt: skip


class Sweeper(Protocol):  # `RetentionManager`
    async def run_nightly(self) -> RunReport: ...


class _PolicyIn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    stream: Stream
    retain_days: Annotated[int, Field(ge=1, le=3650)]
    action: Literal["drop", "archive_parquet", "downsample", "pin"]
    symbol: Annotated[str, Field(pattern=r"^[A-Z0-9]{2,20}USDT$")] | None = None
    applies_to_pinned: bool = False


class _SetIn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    items: Annotated[list[_PolicyIn], Field(max_length=1000)]


def _invalid(detail: str) -> common.Problem:
    return common.Problem(422, ErrorCode.RETENTION_INVALID_POLICY, detail)


def _checked(items: Sequence[_PolicyIn]) -> None:
    """Q5's refusals, one row per scope and stream, and no derived stream outliving `trades`."""
    rows: dict[tuple[str | None, str], PolicyRow] = {}
    for i in items:
        if i.action in ("downsample", "pin") or i.applies_to_pinned:
            raise _invalid(_UNHELD)
        stream = canonical_stream(i.stream)
        if (i.symbol, stream) in rows:
            raise _invalid("One policy per symbol and stream.")
        hot, total = STREAM_DEFAULTS[stream]
        if i.action == "drop":
            rows[(i.symbol, stream)] = PolicyRow(i.symbol, stream, min(hot, i.retain_days),
                                                 i.retain_days)  # fmt: skip
        else:
            horizon = None if total is None else max(total, i.retain_days)
            rows[(i.symbol, stream)] = PolicyRow(i.symbol, stream, i.retain_days, horizon)
    for scope in {None} | {s for s, _ in rows}:
        for derived in DERIVED_FROM_TRADES:  # the API cannot set them: their defaults hold
            rows.setdefault((scope, derived), PolicyRow(scope, derived, *STREAM_DEFAULTS[derived]))
    try:
        validate_policies(rows)
    except InvalidRetentionPolicy:
        raise _invalid("A stream derived from trades would outlive it.") from None


def _logical(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("stream", "retain_days", "action", "symbol")
    return {k: row[k] for k in keys}


def _dump(row: Mapping[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], **_logical(row), "applies_to_pinned": False,
            "updated_at": common.iso_z(row["updated_at"])}  # fmt: skip


def make_recording_retention_router(
    policies: Callable[[], PolicyStore | None],
    jobs: AdminJobStore,
    sweeper: Callable[[], Sweeper | None],
    retention_enabled: bool,
    principal_resolver: common.Resolver | None,
    audit: common.Emitter,
    *,
    idempotency: IdempotencyCache | None = None,
) -> APIRouter:
    """`policies` is `None` until its store exists (503); `sweeper` runs an `apply_now` pass."""
    router = APIRouter(tags=["recording"], route_class=common.ProblemRoute)
    cache = IdempotencyCache() if idempotency is None else idempotency

    def bound() -> PolicyStore:
        if (found := policies()) is None:
            raise common.unavailable()
        return found

    def bad(detail: str, **extra: Any) -> common.Problem:
        return common.Problem(422, ErrorCode.VALIDATION_FAILED, detail, **extra)

    @router.get(_PATH)
    async def list_retention_policies(request: Request) -> JSONResponse:
        await common.caller(principal_resolver, audit, request, Permission.RECORDING_READ)
        return JSONResponse({"items": [_dump(r) for r in await bound().list_policies()]})

    @router.put(_PATH)
    async def set_retention_policies(request: Request) -> Response:
        p = await common.caller(principal_resolver, audit, request, Permission.RECORDING_WRITE)
        try:
            key = idempotency_key(request, "setRetentionPolicies")
        except ValueError:
            raise bad("Idempotency-Key must be a UUID.") from None
        apply_now = request.query_params.get("apply_now", "false")
        raw = await request.body()
        if apply_now not in ("true", "false") or len(raw) > _MAX_BODY:
            raise bad("Invalid apply_now or body size.")
        owner, now = str(p.user_id), apply_now == "true"
        digest = request_fingerprint("PUT", f"{_PATH}?apply_now={apply_now}", raw)
        try:
            if (hit := replay(cache, owner, key, digest)) is not None:
                return hit
        except IdempotencyKeyReuse:
            code = ErrorCode.IDEMPOTENCY_KEY_REUSE
            raise common.Problem(409, code, "The key was first used with another body.") from None
        try:
            body = _SetIn.model_validate_json(raw or b"{}")
        except ValidationError as exc:  # bounded, input-free field errors
            raise bad("Invalid policy set.", errors=format_errors(exc)) from None
        _checked(body.items)
        store, run = bound(), sweeper()
        if now and not retention_enabled:
            raise common.Problem(409, ErrorCode.CONFLICT, "The retention scheduler is off.")
        if now and run is None:
            raise common.unavailable()
        before = await store.list_policies()
        gate: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        try:
            if now and run is not None:
                _reserve(jobs, run, gate, (owner, key or "", digest))
            after = [_logical(i.model_dump()) for i in body.items]
            try:  # write-ahead (C-2.9): the change lands BEFORE the new set does
                await audit.emit(
                    "retention.change", actor_label=p.username, actor_user_id=p.user_id,
                    actor_ip=p.ip, session_id=p.session_id, request_id=p.request_id,
                    object_kind="retention_policies", severity=Severity.WARNING,
                    before_state={"items": [_logical(r) for r in before]},
                    after_state={"items": after, "apply_now": now},
                )  # fmt: skip
            except Exception as exc:
                logger().error("retention_change_audit_failed", error=type(exc).__name__)
                code = ErrorCode.AUDIT_UNAVAILABLE
                raise common.Problem(503, code, "The audit record could not be written.") from None
            stored = await store.replace(after, actor=owner)
            gate.set_result(True)
        finally:
            if not gate.done():
                gate.set_result(False)  # refused: the reserved sweep never runs
        out = JSONResponse({"items": [_dump(r) for r in stored]})
        return remember(cache, owner, key, digest, out)

    return router


def _reserve(
    jobs: AdminJobStore, run: Sweeper, gate: asyncio.Future[bool], key: tuple[str, str, str]
) -> Job:
    """The one `retention_sweep` job, held until `gate` says the new set is stored."""

    async def work(progress: Callable[[float], None]) -> dict[str, object]:
        if not await gate:
            raise asyncio.CancelledError
        report = await run.run_nightly()
        progress(100.0)
        return {"deleted": len(report.deleted), "freed_bytes": report.freed_bytes,
                "skipped": len(report.skipped), "failed": len(report.failed)}  # fmt: skip

    async def done(job: Job) -> None:
        logger().info("retention_apply_now_done", job_id=job.id, status=job.status)

    try:
        return jobs.submit(JOB_KIND, key, work, done)
    except JobConflict:
        raise common.Problem(409, ErrorCode.JOB_RUNNING, "A sweep is already running.") from None
