"""`expose_csrf_token` and `set_csrf_cookie` (ADR-0038 3b and F8, #3519 S4.2). No I/O.

The CORS gate keeps the flag in the request's scope state under `FLAG_STATE_KEY`, as `True` only
for a request whose one `Origin` is listed while `desktop.backend_connection` is on (`cors_on`).
"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.requests import Request
from starlette.responses import Response

from candleviewer.api.cors import FLAG_STATE_KEY
from candleviewer.api.csrf import expose_csrf_token, set_csrf_cookie
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER

_VALUE = "n0nce.m4c"  # an inert SR-041 value in the `<nonce>.<mac>` shape
#: Every scope state but exactly `True`: the gate stored "off", or nothing (no listed `Origin`),
#: or a truthy value no gate stores.
_NOT_ON: dict[str, dict[str, Any]] = {
    "flag_off": {"state": {FLAG_STATE_KEY: False}},
    "key_absent": {"state": {}},
    "no_state": {},
    "string_true": {"state": {FLAG_STATE_KEY: "true"}},
    "one": {"state": {FLAG_STATE_KEY: 1}},
}


def _request(scope: dict[str, Any]) -> Request:
    return Request({"type": "http", "headers": [], **scope})


def test_expose_csrf_token_flag_state_true_sets_the_header_and_no_store() -> None:
    response = Response()

    expose_csrf_token(_request({"state": {FLAG_STATE_KEY: True}}), response, _VALUE)

    assert response.headers[CSRF_HEADER] == _VALUE
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("scope", _NOT_ON.values(), ids=list(_NOT_ON))
def test_expose_csrf_token_any_other_flag_state_adds_nothing(scope: dict[str, Any]) -> None:
    response = Response()
    before = list(response.headers.raw)

    expose_csrf_token(_request(scope), response, _VALUE)

    assert response.headers.raw == before


@pytest.mark.parametrize(
    ("scope", "header"),
    [({"state": {FLAG_STATE_KEY: True}}, _VALUE), *((s, None) for s in _NOT_ON.values())],
    ids=["flag_on", *_NOT_ON],
)
def test_set_csrf_cookie_is_no_store_whatever_the_flag_and_has_the_header_only_when_on(
    scope: dict[str, Any], header: str | None
) -> None:
    response = Response()

    set_csrf_cookie(_request(scope), response, _VALUE, max_age=60)

    assert response.headers["set-cookie"].startswith(f"{CSRF_COOKIE}={_VALUE}; ")
    assert response.headers["cache-control"] == "no-store"  # F8: the body holds the access token
    assert response.headers.get(CSRF_HEADER) == header
