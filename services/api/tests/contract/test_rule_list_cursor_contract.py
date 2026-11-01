"""#2291 (SR-051), contract first (C-6.1): `listRules` answers a cursor that is not a rule id.

22 states the answer before the code that holds it: `400 invalid_cursor`, the registered code the
other cursor-paged lists answer with, through the shared `BadRequest` response. Each fact is read
from the spec, never a copy (AGENTS.md section 6 rule 12); `listRules`' page-bound sentence, which
`test_rule_authoring_limits_contract.py` reads, stays as it is.
"""

from __future__ import annotations

from typing import Any

from tests.contract._admin_support import SPEC, text

_METHODS = frozenset({"get", "put", "post", "patch", "delete"})
_OPS: dict[str, dict[str, Any]] = {
    op["operationId"]: op
    for item in SPEC["paths"].values()
    for method, op in item.items()
    if method in _METHODS
}
_REGISTRY: dict[str, dict[str, Any]] = {e["code"]: e for e in SPEC["x-error-codes"]}
_BAD_REQUEST = {"$ref": "#/components/responses/BadRequest"}
_PAGE_BOUND = (
    "A page holds at most 200 rules whatever `limit` asks for (`Limit` takes up to 500), and "
    "`meta.next_cursor` carries the rest."
)
_REFUSAL = "A `cursor` that is not a rule id is `400 invalid_cursor`."


def test_list_rules_names_the_malformed_cursor_refusal_as_400_invalid_cursor() -> None:
    listing = _OPS["listRules"]
    prose = text(listing["description"])
    assert _REFUSAL in prose
    assert prose.index(_PAGE_BOUND) < prose.index(_REFUSAL)  # the page bound reads as it did
    assert listing["responses"]["400"] == _BAD_REQUEST
    assert {"$ref": "#/components/parameters/Cursor"} in listing["parameters"]
    registered = _REGISTRY["invalid_cursor"]
    assert (registered["status"], registered["retryable"]) == (400, False)
    # The same answer the other cursor-paged lists declare for a cursor they cannot read.
    assert _OPS["listOrders"]["responses"]["400"] == _BAD_REQUEST
