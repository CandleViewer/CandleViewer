"""#5478: 22 `listUsers` (`GET /users`), contract first (C-6.1).

The operation declares every answer its route is to give: `400` (`invalid_cursor`,
`validation_failed`), `401`, `403` and `503` (`store_unavailable`, `audit_unavailable`), each code
one `x-error-codes` registers at that status, beside its unchanged `200` (a `Page` of `User`) and
its `x-rbac`. Its description states the order a keyset cursor needs (`created_at`, then `id`,
resumed strictly after the last row of the page before) and what the cursor is bound to. The route
and its tests follow in the ticket's second PR.
"""

from __future__ import annotations

import re
from typing import Any, Final

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec

_PATH: Final = "/users"
#: Each cited code is `` `<status> <code>` ``, the pattern of `test_openapi_conformance.py`.
_CITED_CODE: Final = re.compile(r"`(\d{3}) ([a-z_]+)`")
_ANSWERS: Final = {
    "400": "BadRequest",
    "401": "Unauthorized",
    "403": "Forbidden",
    "503": "ServiceUnavailable",
}
_ORDER: Final = (
    "The list is ordered by `created_at` ascending, then `id` ascending",
    "a page resumes strictly after the last row of the page before it (`meta.next_cursor`)",
    "a user created while the list is read lands on a later page and no row repeats",
)
_BINDING: Final = (
    "The cursor is bound to the caller and to `status`, `role` and `q` as sent, for one hour",
    "issued to another caller or for other filters is `400 invalid_cursor`",
)


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    loaded: dict[str, Any] = load_openapi_spec()
    return loaded


def _op(spec: dict[str, Any]) -> dict[str, Any]:
    found: dict[str, Any] = spec["paths"][_PATH]["get"]
    return found


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_list_users_declares_its_answers(spec: dict[str, Any]) -> None:
    op = _op(spec)
    assert op["operationId"] == "listUsers"
    assert set(op["responses"]) == {"200", *_ANSWERS}
    for status, name in _ANSWERS.items():
        assert op["responses"][status] == {"$ref": f"#/components/responses/{name}"}, status
    assert "Retry-After" in spec["components"]["responses"]["ServiceUnavailable"]["headers"]


def test_list_users_cites_registered_codes_with_their_status(spec: dict[str, Any]) -> None:
    cited = set(_CITED_CODE.findall(_op(spec)["description"]))
    assert {
        ("400", "invalid_cursor"),
        ("400", "validation_failed"),
        ("503", "store_unavailable"),
        ("503", "audit_unavailable"),
    } <= cited
    registered = {e["code"]: e["status"] for e in spec["x-error-codes"]}
    assert all(registered.get(code) == int(status) for status, code in cited), cited
    assert {status for status, _ in cited} <= set(_op(spec)["responses"])


def test_list_users_states_its_order_and_cursor_binding(spec: dict[str, Any]) -> None:
    text = _flat(_op(spec)["description"])
    for phrase in (*_ORDER, *_BINDING):
        assert phrase in text, phrase
    assert "Authorisation comes first" in text and "never the value" in text


def test_list_users_keeps_its_permission_and_page_shape(spec: dict[str, Any]) -> None:
    op = _op(spec)
    assert op["x-rbac"] == {"permissions": ["users:read"], "scope": "none"}
    page = op["responses"]["200"]["content"]["application/json"]["schema"]["allOf"]
    assert page[0] == {"$ref": "#/components/schemas/Page"}
    items = page[1]["properties"]["items"]
    assert items == {"type": "array", "items": {"$ref": "#/components/schemas/User"}}
    names = {p.get("$ref", "").rsplit("/", 1)[-1] or p.get("name") for p in op["parameters"]}
    assert names == {"Cursor", "Limit", "status", "role", "q"}
