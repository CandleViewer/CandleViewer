"""SR-026 query-parameter allow-list for the self-service routes (#2573, #2632).

A self-service route answers only for the authenticated caller, so it takes only the query
parameters its contract operation declares (22-api-openapi.yaml). A target user under any
spelling, or any other undeclared key, is refused with a 422 `validation_failed` Problem, never
silently ignored (FastAPI drops undeclared query parameters by default). Callers check it after
authentication and the route's permission check, and before any data read or state change.
`DELETE /users/{userId}` (E42-T04 S7, #965), an owner route that names its target in the path,
refuses an undeclared key the same way (`self_service=False`): a target-user key is just one more.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from candleviewer.observability.redaction import redact_text

#: `userId` is the contract's own name for a target user (`components/parameters/UserId`, the
#: owner-only `/users/{userId}` routes).
_TARGET_USER_PARAMS = frozenset({"user_id", "userId"})
#: Echo bounds for client-supplied parameter names, which also pass the shared redaction rules.
_MAX_ECHOED_PARAMS = 8
_MAX_ECHOED_NAME_LEN = 64
_SELF_ONLY = (
    "This route answers only for the authenticated caller and takes no target-user or "
    "undeclared parameter."
)
_DECLARED_ONLY = "This route takes only the query parameters its operation declares."


def _echoed(name: str) -> str:
    """A client-supplied parameter name as echoed. A name over the bound is never echoed, only its
    length: the shared redaction then only ever scans short names (cheap, and a secret shape is
    seen whole), and no prefix of a long token can leak through a cut (#2573 review)."""
    if len(name) > _MAX_ECHOED_NAME_LEN:
        return f"<{len(name)}-character name>"
    return redact_text(name)


def undeclared_query_refusal(
    request: Request, declared: frozenset[str], *, self_service: bool = True
) -> JSONResponse | None:
    """422 `validation_failed` when a self-service route gets an undeclared query key (SR-026).

    Decided on the parameter names alone, so the answer is identical for any value (no existence
    oracle). It echoes at most `_MAX_ECHOED_PARAMS` redacted, bounded names and never a value.
    """
    undeclared = sorted(set(request.query_params) - declared)
    if not undeclared:
        return None
    targets = _TARGET_USER_PARAMS if self_service else frozenset()
    named = undeclared[:_MAX_ECHOED_PARAMS]
    more = len(undeclared) - len(named)
    shown = {p: _echoed(p) for p in named}  # redact each name once, reuse in detail and errors
    listed = ", ".join(shown[p] for p in named) + (f" (+{more} more)" if more else "")
    return JSONResponse(
        status_code=422,
        content={
            "type": "https://candleviewer.local/errors/validation_failed",
            "title": "Request body or parameters failed schema validation",
            "status": 422,
            "code": "validation_failed",
            "detail": f"Query parameter not accepted: {listed}. "
            + (_SELF_ONLY if self_service else _DECLARED_ONLY),
            "errors": [
                (
                    {
                        "field": f"query.{p}",
                        "rule": "target_user_not_accepted",
                        "message": "self-service routes do not accept a target-user parameter",
                    }
                    if p in targets
                    else {
                        "field": f"query.{shown[p]}",
                        "rule": "undeclared_parameter",
                        "message": "not a declared parameter of this route",
                    }
                )
                for p in named
            ],
        },
        media_type="application/problem+json",
    )
