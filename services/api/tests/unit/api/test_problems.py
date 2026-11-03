"""`problem_body` refuses an `extra` that would overwrite the catalogued members (#2828)."""

from __future__ import annotations

import pytest

from candleviewer.api.problems import problem_body
from candleviewer.ws._generated.error_codes import ErrorCode


@pytest.mark.parametrize("member", ["type", "code", "status"])
def test_problem_body_extra_cannot_override_a_catalogued_member(member: str) -> None:
    with pytest.raises(ValueError, match=member):
        problem_body(ErrorCode.NOT_FOUND, 404, extra={member: "x"})


def test_problem_body_extra_may_override_the_title_and_add_members() -> None:
    body = problem_body(ErrorCode.NOT_FOUND, 404, extra={"title": "Custom", "retry_after": 3})
    assert body["title"] == "Custom" and body["retry_after"] == 3
    assert body["code"] == "not_found" and body["status"] == 404
