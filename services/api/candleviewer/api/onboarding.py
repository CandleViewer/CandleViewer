"""`GET /onboarding/checklist`, `POST /onboarding/checklist/dismiss` (E09-S06).

Scope `self`: the caller's own identity is the only input; nothing about other
users, accounts or key material is ever returned. Dismissal is a per-user row
(server-side) accepted only while every step is `ok`.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Mapping
from typing import Any, Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from candleviewer.api.onboarding_checklist import Probe, assemble
from candleviewer.api.users import SnapshotResolver
from candleviewer.audit.models import AuditOutcome, Severity


class DismissalStore(Protocol):
    async def is_dismissed(self, user_id: Any) -> bool: ...

    async def dismiss(self, user_id: Any) -> None: ...


class _Metrics(Protocol):
    def inc(self, name: str, **labels: str) -> None: ...


def _problem(status: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"type": "about:blank", "title": title, "status": status, "detail": detail},
        media_type="application/problem+json",
    )


def make_onboarding_router(
    store: DismissalStore | None,
    principal_resolver: SnapshotResolver | None,
    probes: Mapping[str, Probe],
    flags: Mapping[str, bool],
    metrics: _Metrics | None = None,
    emitter: Any = None,
) -> APIRouter:
    router = APIRouter(tags=["settings"])

    def _count(name: str, **labels: str) -> None:
        if metrics is not None:
            metrics.inc(name, **labels)

    @router.get("/onboarding/checklist")
    async def get_checklist(request: Request) -> Response:
        if principal_resolver is None or store is None:
            return _problem(501, "Not implemented", "onboarding not wired")
        got = principal_resolver.resolve(request)
        principal = await got if inspect.isawaitable(got) else got
        if principal is None:
            return _problem(401, "Unauthorized", "no verified session for this request")
        started = time.monotonic()
        try:
            dismissed = await store.is_dismissed(principal.user_id)
        except Exception:
            dismissed = False
        items, complete, raw = await assemble(principal.user_id, probes, flags, dismissed=dismissed)
        _count("onboarding_checklist_views_total")
        for key, res, timed_out in raw:
            _count("onboarding_step_state_total", step=key, state=res.state)
            if timed_out:
                _count("onboarding_probe_timeouts_total", step=key)
        observe = getattr(metrics, "observe_latency", None)
        if observe is not None:
            observe(time.monotonic() - started)
        return JSONResponse(
            {"complete": complete, "dismissed": dismissed and complete, "items": items}
        )

    @router.post("/onboarding/checklist/dismiss")
    async def dismiss(request: Request) -> Response:
        if principal_resolver is None or store is None:
            return _problem(501, "Not implemented", "onboarding not wired")
        got = principal_resolver.resolve(request)
        principal = await got if inspect.isawaitable(got) else got
        if principal is None:
            return _problem(401, "Unauthorized", "no verified session for this request")
        raw_body = await request.body()
        if raw_body.strip():
            # Self-scope only: any client-supplied target/step state is tampering.
            if emitter is not None:
                await emitter.emit(
                    "onboarding.checklist_tamper_rejected",
                    actor_label=str(principal.user_id),
                    actor_user_id=principal.user_id,
                    outcome=AuditOutcome.DENIED,
                    severity=Severity.WARNING,
                    reason="client_supplied_state",
                )
            return _problem(403, "Forbidden", "the checklist accepts no client-supplied state")
        _, complete, _raw = await assemble(principal.user_id, probes, flags, dismissed=False)
        if not complete:
            return _problem(409, "Conflict", "the checklist is not complete")
        await store.dismiss(principal.user_id)
        _count("onboarding_checklist_dismissed_total")
        return Response(status_code=204)

    return router
