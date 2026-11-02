"""The shared RFC 9457 problem builder (#2828): one `code` from the `x-error-codes` catalogue.

`problem(code, status, detail)` answers `application/problem+json` with
`type == ERRORS_BASE + code`, the catalogue's title and `code`, so no router sends `about:blank`
or a slug the catalogue lacks. `code` must be an `ErrorCode` with the `rest` surface: a WS-only
code raises `ValueError`. `status` is explicit at every call and is never looked up: the
statuses routes answer differ from the catalogue's nominal ones (`validation_failed` is answered
at 422), and a default would change them silently. A specific slug a catalogue code stands for
(a rule-engine refusal, a gateway refusal cause) rides `errors[].rule` via `rule=`, the contract's
`name_taken` precedent; `Problem` has no generic `reason` member.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from fastapi.responses import JSONResponse

from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

#: The `Problem.type` prefix (`22-api-openapi.yaml` `components.schemas.Problem`).
ERRORS_BASE: Final = "https://candleviewer.local/errors/"
PROBLEM_MEDIA_TYPE: Final = "application/problem+json"


def problem_body(
    code: ErrorCode,
    status: int,
    detail: str | None = None,
    *,
    rule: str | None = None,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """The `Problem` body; raises `ValueError` for a code the REST surface does not carry."""
    meta = ERROR_META[ErrorCode(code)]
    if "rest" not in meta.surfaces:
        raise ValueError(f"{code!s} is not a REST error code")
    if not 400 <= status <= 599:
        raise ValueError(f"problem status {status} is not an error status")
    body: dict[str, object] = {
        "type": f"{ERRORS_BASE}{code.value}",
        "title": meta.title,
        "status": status,
        "code": code.value,
    }
    if detail is not None:
        body["detail"] = detail
    if rule is not None:
        body["errors"] = [{"rule": rule}]
    if extra:
        if clash := {"type", "code", "status"} & extra.keys():
            raise ValueError(f"extra may not override {sorted(clash)}")
        body.update(extra)
    return body


def problem(
    code: ErrorCode,
    status: int,
    detail: str | None = None,
    *,
    rule: str | None = None,
    headers: Mapping[str, str] | None = None,
    extra: Mapping[str, object] | None = None,
) -> JSONResponse:
    """`problem_body` as a `JSONResponse` with the problem media type and `headers`."""
    return JSONResponse(
        status_code=status,
        content=problem_body(code, status, detail, rule=rule, extra=extra),
        media_type=PROBLEM_MEDIA_TYPE,
        headers=dict(headers) if headers else None,
    )
