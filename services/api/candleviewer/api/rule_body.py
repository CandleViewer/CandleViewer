"""The body reader of the rule routers, extracted unchanged from `api/rules_crud.py` so that
`api/rules.py` (validate, compile) reads its bodies the same way, as `api/drawings.py` reads one:
under `MAX_RULE_BODY_BYTES` before the body is buffered whole (413 `payload_too_large`), then
strict UTF-8 nested no deeper than a rule needs. Each router answers a bad body in its own shape.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, Final

from fastapi import Request
from fastapi.responses import JSONResponse

from candleviewer.rules.compiler.common import MAX_DEPTH, MAX_ITEMS
from candleviewer.ws.limits import json_depth_exceeds

#: The body ceiling of the rule routes, from the document bounds every save applies
#: (`check_bounds`): `MAX_ITEMS` values at 100 bytes each. The densest corpus rule takes a fifth
#: of that per value as compact JSON and under a third indented, so a rule at the bounds fits.
MAX_RULE_BODY_BYTES: Final = MAX_ITEMS * 100
#: The deepest body a rule within the bounds needs: `MAX_DEPTH + 1` nested objects and arrays (a
#: value at depth `MAX_DEPTH` may be one) inside the body's own object.
MAX_JSON_DEPTH: Final = MAX_DEPTH + 2
_LENGTH: Final = re.compile(r"[0-9]{1,19}")  # a usable `Content-Length`, as `api/drawings.py`
_TOO_LARGE: Final = "Request body or batch exceeds the operation's size ceiling"


def _declared_length(raw: str) -> int | None:
    """`Content-Length` when it is 1..19 ASCII digits, else None (only the streamed count then)."""
    return int(raw) if _LENGTH.fullmatch(raw) else None


async def _read_capped(request: Request, cap: int) -> bytes | None:
    """The raw body, or None past `cap` bytes, before it is buffered whole: a declared length over
    `cap` is refused unread and a stream stops one chunk past it, as in `api/drawings.py`."""
    declared = _declared_length(request.headers.get("content-length", ""))
    if declared is not None and declared > cap:
        return None
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > cap:
            return None
    # Starlette's own body cache: `Request.body()` fills it, and `body()`, `json()` and `stream()`
    # reuse it, so a later reader of this request (live arming's step-up) sees these bytes.
    request._body = data = bytes(raw)
    return data


async def read_object(
    request: Request, bad: Callable[[str], JSONResponse]
) -> dict[str, Any] | JSONResponse | None:
    """The JSON object sent (else None), the 413 past the ceiling, or the router's `bad(detail)`
    for a body nested deeper than a rule needs, checked before anything decodes it."""
    raw = await _read_capped(request, MAX_RULE_BODY_BYTES)
    if raw is None:
        detail = f"The request body exceeds {MAX_RULE_BODY_BYTES} bytes."
        problem = {"type": "https://candleviewer.local/errors/payload_too_large",
                   "title": _TOO_LARGE, "status": 413, "code": "payload_too_large",
                   "detail": detail}  # fmt: skip
        return JSONResponse(problem, 413, media_type="application/problem+json")
    try:
        text = raw.decode("utf-8")
        if json_depth_exceeds(text, MAX_JSON_DEPTH):  # as `api/drawings.py`
            return bad(f"JSON nesting is deeper than {MAX_JSON_DEPTH} levels.")
        body = json.loads(text)
    except ValueError:  # not UTF-8 JSON
        return None
    return body if isinstance(body, dict) else None


__all__ = ["MAX_JSON_DEPTH", "MAX_RULE_BODY_BYTES", "read_object"]
