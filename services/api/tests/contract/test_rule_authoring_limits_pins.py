"""#4834 (E35 authoring limits): each number the code holds is the one `22` states.

`test_rule_authoring_limits_contract.py` pins what `22` says; these tests tie its numbers to the
constants and settings that hold them, so neither moves alone. The condition-node bound and the
validate / compile limit are here; the later changes of #4834 append their own.
"""

from __future__ import annotations

import re
from typing import Any

from candleviewer.api.rules import CHECK_BURST_FACTOR
from candleviewer.rules.compiler.common import MAX_CONDITION_NODES, condition_node_error
from candleviewer.settings import RULES_CHECK_RATE_PER_USER_PER_SECOND, Settings
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from tests.contract._admin_support import SPEC, text

_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_OPS: dict[str, dict[str, Any]] = {
    op["operationId"]: op
    for item in SPEC["paths"].values()
    for method, op in item.items()
    if method in {"get", "put", "post", "patch", "delete"}
}


def _prose(operation_id: str) -> str:
    return text(_OPS[operation_id]["description"])


def _number(pattern: str, prose: str) -> int:
    found = re.search(pattern, prose)
    assert found is not None, pattern
    return int(found.group(1).replace(",", ""))


def test_max_condition_nodes_is_the_bound_22_states() -> None:
    bound = text(_SCHEMAS["RuleIr"]["description"]).split("**Condition-node bound (E35, #4834).**")[
        1
    ]
    assert MAX_CONDITION_NODES == _number(r"`conditions` holds at most ([\d,]+) nodes", bound)
    for operation_id in ("validateRule", "compileRule"):
        assert f"{MAX_CONDITION_NODES:,} condition nodes" in _prose(operation_id)
    invalid = SPEC["components"]["responses"]["RuleIrInvalid"]["content"][
        "application/problem+json"
    ]
    (error,) = invalid["examples"]["conditionNodes"]["value"]["errors"]
    (issue,) = condition_node_error().issues  # the place and the message the code answers with
    assert (error["field"], error["rule"], error["message"]) == (
        issue.path,
        issue.code,
        issue.message,
    )


def test_the_check_limit_default_and_burst_are_the_ones_22_states() -> None:
    prose = _prose("validateRule")
    assert RULES_CHECK_RATE_PER_USER_PER_SECOND == _number(r"\(default (\d+) a second\)", prose)
    assert Settings.model_fields["rules_check_rate_per_user_per_second"].default == (
        RULES_CHECK_RATE_PER_USER_PER_SECOND
    )
    assert "twice the rate" in prose and CHECK_BURST_FACTOR == 2
    burst = RULES_CHECK_RATE_PER_USER_PER_SECOND * CHECK_BURST_FACTOR
    assert burst == _number(r"a burst of twice the rate \((\d+) by default\)", prose)
    assert "`rules_check_rate_per_user_per_second`" in prose
    registered = next(e for e in SPEC["x-error-codes"] if e["code"] == "rate_limited")
    assert ERROR_META[ErrorCode.RATE_LIMITED].title == registered["title"]
