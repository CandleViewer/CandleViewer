"""B12 `replay` bindings: guards pure and total, actions total, services idempotent (E26-T01)."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

import candleviewer.statechart.bindings.b12_replay as b12

SEEDED = {"session_id": "s1", "range_start": 10, "range_end": 20, "cursor": 12, "loop": True}


class _Interp:
    pass


class _Ev:
    def __init__(self, data: object = None, error: object = None) -> None:
        self.data, self.error = data, error


def _ctx() -> dict[str, Any]:
    return {"session_id": None, "cursor": 0, "speed": 1.0, "error": None, "input": dict(SEEDED)}


class _Hostile(dict[str, Any]):
    def get(self, *_args: object, **_kwargs: object) -> Any:
        raise RuntimeError("boom")


def test_loop_enabled_is_pure_and_total() -> None:
    ctx = _ctx()
    before = copy.deepcopy(ctx)
    assert b12.loop_enabled(ctx, None) is True and ctx == before
    assert b12.loop_enabled({"loop": False, "session_id": "s"}, None) is False
    assert b12.loop_enabled({"input": 7}, object()) is False
    assert b12.loop_enabled(_Hostile(), None) is False


async def test_actions_are_total_on_hostile_events_and_keep_rps_bounds() -> None:
    hostile: list[object] = [
        None, {}, _Ev(), _Ev(data={"cursor": "x", "speed": True, "coverage_gaps": [[1]]}),
        _Ev(data={"cursor": 10**12, "speed": 1e9, "coverage_gaps": "nope", "error": object()}),
        _Ev(error=ValueError("/etc/passwd")),
    ]  # fmt: skip
    ctx = _ctx()
    for name, action in b12.ACTIONS.items():
        for event in hostile:
            await action(_Interp(), ctx, event, None)  # never raises (no hook: logged only)
        assert 10 <= ctx["cursor"] <= 20 and b12.SPEED_MIN <= ctx["speed"] <= b12.SPEED_MAX, name
    assert ctx["session_id"] == "s1" and ctx["error"] in {"ValueError", "killed"}


async def test_actions_publish_plain_facts_through_the_attached_hook() -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    async def hook(name: str, facts: Mapping[str, object]) -> None:
        seen.append((name, dict(facts)))

    interp, ctx = _Interp(), _ctx()
    b12.attach_hook(interp, hook)
    await b12.set_cursor(interp, ctx, _Ev(data={"cursor": 15}), None)
    await b12.set_speed(interp, ctx, _Ev(data={"speed": 2.5}), None)
    await b12.record_coverage(interp, ctx, _Ev(data={"coverage_gaps": [[11, 12]]}), None)
    await b12.record_error(interp, ctx, _Ev(data={"error": "SourceGone: /data/x"}), None)
    await b12.audit_kill(interp, ctx, None, None)
    assert [n for n, _ in seen] == ["cursor", "speed", "coverage", "error", "killed"]
    assert seen[0][1]["cursor"] == 15 and seen[1][1]["speed"] == 2.5
    assert seen[2][1]["coverage_gaps"] == [[11, 12]] and seen[3][1]["error"] == "SourceGone"


async def test_cursor_actions_leave_the_cursor_alone_without_range_facts() -> None:
    ctx: dict[str, Any] = {"session_id": "s1", "cursor": 7}
    await b12.set_cursor(_Interp(), ctx, _Ev(data={"cursor": 99}), None)
    await b12.reset_cursor_to_start(_Interp(), ctx, None, None)
    assert ctx["cursor"] == 7


async def test_data_services_are_idempotent_no_ops_until_e36() -> None:
    for service in b12.SERVICES.values():
        ctx = _ctx()
        assert await service(_Interp(), ctx, None) is None
        assert await service(_Interp(), ctx, None) is None and ctx == _ctx()
