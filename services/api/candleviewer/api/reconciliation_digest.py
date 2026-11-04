"""`getReconciliationDigest` (E29-S07 #1028, BQ-9; 22, 24-internal-schemas.md Sec.8.5 "The
digest"): `GET /exchange-accounts/{accountId}/reconciliation/latest`, the account's latest reported
reconciliation pass as `ReconciliationDigest`.

After the middleware (session state, the view-as guard, deny-by-default) the route checks, each
before the next, as the OMS reads do (`api.oms_reads`):

1. the principal (`resolve_principal`): none composed is 501, none found 401, one whose store does
   not answer 503 `store_unavailable`;
2. `orders:read` and `positions:read` (22 `x-rbac`), each `enforce`d with no account: 403
   `forbidden` without either, audited `rbac.denied`, a 403 even when that record cannot be
   written;
3. the path id: one that is not a UUID is 400 `validation_failed`, unaudited, as nothing in scope
   is named yet;
4. the account in the caller's scope (`auth.scopes.scoped_account_ids`, C-12.4): an account
   outside its grants, one that does not exist, one of another environment (C-2.11) and one with
   no digest are the same 404 `not_found`, byte for byte (SR-E29-13); one outside the grants,
   foreign or absent alike, is counted and audited `rbac.denied`, naming the account asked for,
   best effort (KV-I13), so the records tell the two apart no more than the answers do.

Under a view-as context the principal is the target's, so the read answers in the target's grants,
and a refusal's record names the viewer (`oms_reads.record_actor`). The answer is the digest's JSON
document, as `oms.reconcile_digest.ReconcileDigests` keeps it, with `Cache-Control: no-store`; a
read writes no record of its own. No log line carries a value of the digest (C-12.6).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Final, Protocol

import structlog
from fastapi import APIRouter, Path, Request
from fastapi.responses import Response

from candleviewer.api.csrf import source_ip
from candleviewer.api.oms_reads import record_actor
from candleviewer.api.order_admission import (
    AuditEmitter,
    OrderPrincipals,
    problem,
    resolve_principal,
)
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.api.refusal_session import SessionsLike
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.metrics import count_authz_denial
from candleviewer.auth.scopes import ForbiddenError, enforce, scoped_account_ids
from candleviewer.observability.context import current_request_uuid
from candleviewer.oms.errors import StoreUnavailable

__all__ = ["OPERATION", "PATH", "make_reconciliation_digest_router"]

OPERATION: Final = "getReconciliationDigest"
PATH: Final = "/exchange-accounts/{accountId}/reconciliation/latest"
#: 22 `x-rbac.permissions`, both required; the first names the scope.
PERMISSIONS: Final = (Permission.ORDERS_READ, Permission.POSITIONS_READ)
_NOT_FOUND: Final = "No reconciliation digest for this account."


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class Digests(Protocol):
    """`oms.reconcile_digest.ReconcileDigests.latest`: an account's digest document, or None."""

    def latest(self, account_id: uuid.UUID) -> str | None: ...


def make_reconciliation_digest_router(
    principals: OrderPrincipals | None,
    digests: Digests,
    *,
    audit: AuditEmitter,
    auth: SessionsLike | None = None,
) -> APIRouter:
    """The one read (module docstring)."""
    router = APIRouter()

    async def admit(request: Request) -> TradingPrincipal | Response:
        """Steps 1 and 2 (module docstring)."""
        if principals is None:
            return problem(501, "not_implemented", "No principal source is composed.")
        try:
            principal = await resolve_principal(principals, request, auth)
        except StoreUnavailable:
            return problem(503, "store_unavailable", "The session could not be read.")
        if principal is None:
            return problem(401, "unauthenticated", "No verified session for this request.")
        try:
            for permission in PERMISSIONS:
                await enforce(
                    principal.snapshot, permission, emitter=audit,
                    actor_ip=source_ip(request.scope), session_id=principal.session_id,
                    request_id=current_request_uuid(),
                )  # fmt: skip
        except (ForbiddenError, AuditError, RuntimeError) as exc:
            if not isinstance(exc, ForbiddenError):  # counted by `enforce`; its 403 stands
                _log().warning("reconcile_digest_denial_unaudited", error=type(exc).__name__)
            need = [p.value for p in PERMISSIONS]
            detail = f"Requires {' and '.join(need)}."
            return problem(403, "forbidden", detail, required_permissions=need)
        return principal

    async def foreign(principal: TradingPrincipal, request: Request, account: uuid.UUID) -> None:
        """Step 4's record for an account outside the grants, foreign or absent alike (KV-I13); its
        404 stands."""
        count_authz_denial(PERMISSIONS[0], principal.snapshot.roles, route=OPERATION)
        reason = f"account_not_granted:{PERMISSIONS[0].value}:{Scope.GRANTED_ACCOUNTS.value}"
        try:
            await audit.emit(
                "rbac.denied", **record_actor(principal, request), outcome="denied",
                severity="warning", reason=reason, request_id=current_request_uuid(),
                object_kind="exchange_account", object_id=str(account),
            )  # fmt: skip
        except (AuditError, RuntimeError) as exc:  # RuntimeError: the writer is not started
            _log().warning("reconcile_digest_denial_unaudited", error=type(exc).__name__)

    @router.get(PATH, operation_id=OPERATION)  # nosem: no-raw-account-id reason=orders:read-and-positions:read-enforced-then-the-path-id-checked-in-the-callers-scope-from-auth.scopes.scoped_account_ids-SR-051-one-404-SR-E29-13-#1028 owner=@CandleViewer/security review=2027-04-15  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def get_reconciliation_digest(
        request: Request, account_id: Annotated[str, Path(alias="accountId")]
    ) -> Response:
        admitted = await admit(request)
        if isinstance(admitted, Response):
            return admitted
        try:
            account = uuid.UUID(account_id)
        except ValueError:
            errors = [{"field": "accountId", "rule": "uuid", "message": "Name it by its id."}]
            return problem(
                400, "validation_failed", "1 parameters failed validation.", errors=errors
            )
        snapshot, document = admitted.snapshot, digests.latest(account)
        if not snapshot.is_owner and account not in scoped_account_ids(snapshot):
            await foreign(admitted, request, account)
            document = None
        if document is None:
            return problem(404, "not_found", _NOT_FOUND)
        return Response(
            document, media_type="application/json", headers={"Cache-Control": "no-store"}
        )

    return router
