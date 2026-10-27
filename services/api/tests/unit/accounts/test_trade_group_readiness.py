"""E28-T05 S2a (#909): trade-group member readiness, pure and fail closed (US-PROF-005 AC 4,
KV-T12, C-2.21)."""

from __future__ import annotations

import ast
import inspect
from typing import cast, get_args
from uuid import UUID

import pytest
from structlog.testing import capture_logs

import candleviewer.accounts.trade_group_readiness as module
from candleviewer.accounts.trade_group_readiness import (
    MemberReadiness,
    Readiness,
    ReadinessMember,
    ReadinessReason,
    readiness,
)
from candleviewer.domain.primitives import Environment

# E28-A, E28-B and E28-C of the E28 seed: the members of Core3 (tests/fixtures/e28/seed.sql).
A, B, C = (UUID(f"e28f0000-0000-4000-8000-0000000000d{n}") for n in (1, 2, 3))


class _Source:
    """A `ReadinessSource` answering from a table (no entry: ready), counting every ask."""

    def __init__(self, answers: dict[UUID, object] | None = None) -> None:
        self.answers = answers or {}
        self.asked: list[UUID] = []

    def reason(
        self, account_id: UUID, environment: Environment, *, account_enabled: bool
    ) -> ReadinessReason | None:
        self.asked.append(account_id)
        answer = self.answers.get(account_id)
        if isinstance(answer, Exception):
            raise answer
        return cast(ReadinessReason | None, answer)


def _core3(*enabled: bool) -> list[ReadinessMember]:
    return [ReadinessMember(a, on, True) for a, on in zip((A, B, C), enabled, strict=False)]


def test_the_vocabulary_is_the_closed_list_22_serves() -> None:
    assert get_args(ReadinessReason) == (
        "member_disabled", "account_disabled", "key_invalid", "account_unhealthy",
        "account_locked", "kill_switch_engaged", "trading_disabled",
    )  # fmt: skip


def test_two_of_three_ready_when_one_key_self_check_failed() -> None:
    result = readiness(_core3(True, True, True), _Source({B: "key_invalid"}), "demo")
    assert (result.ready, result.total) == (2, 3)
    assert result.members == (
        MemberReadiness(A, True, None),
        MemberReadiness(B, False, "key_invalid"),
        MemberReadiness(C, True, None),
    )


def test_a_disabled_member_is_listed_and_not_counted() -> None:
    source = _Source({B: "account_disabled"})  # the member's own switch comes before the source
    result = readiness(_core3(True, False, True), source, "demo")
    assert (result.ready, result.total) == (2, 2)
    assert result.members[1] == MemberReadiness(B, False, "member_disabled")
    assert source.asked == [A, C]


@pytest.mark.parametrize(
    "answer",
    [RuntimeError("echoed exchange text: invalid key"), "ready", False],
    ids=["raises", "outside the vocabulary", "false"],
)
def test_an_unknown_standing_is_not_ready(answer: object) -> None:
    with capture_logs() as logs:
        result = readiness(_core3(True), _Source({A: answer}), "demo")
    assert (result.ready, result.total) == (0, 1)
    assert result.members == (MemberReadiness(A, False, "trading_disabled"),)
    assert [(e["log_level"], e["account_id"]) for e in logs] == [("error", str(A))]
    assert "invalid key" not in repr(logs)  # the error's class at most, never its text


def test_readiness_is_pure_and_awaits_nothing() -> None:
    source = _Source()
    result = readiness(_core3(True, True, True), source, "demo")
    assert not inspect.iscoroutinefunction(readiness) and not inspect.isawaitable(result)
    assert isinstance(result, Readiness) and source.asked == [A, B, C]  # one ask a member
    tree = ast.parse(inspect.getsource(module))  # `accounts` imports none of the sources (C-3.x)
    names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert [m for m in names if m.startswith("candleviewer")] == ["candleviewer.domain.primitives"]
