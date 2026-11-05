"""#3319 B1b ruling 2: `cvbackup/tasks.py` is the package's only task-creation site, the only
`cvbackup` module `cv-bare-create-task` exempts, and it gives what `observability.spawn` gives
the API: a strong reference, a bounded set, a done-callback that logs and records a failure, and
cancellation honoured. One test per guarantee."""

from __future__ import annotations

import ast
import asyncio
import inspect
import logging
from pathlib import Path

import pytest

import cvbackup
from cvbackup import tasks

_CREATORS = {"create_task", "ensure_future", "run_in_executor", "TaskGroup"}
_UNLOGGED = "a-text-that-must-never-be-logged"


async def _wait_all() -> None:
    while tasks.running():
        await asyncio.wait(tasks.running())


def test_tasks_is_the_only_task_creation_site_in_cvbackup() -> None:
    found = []
    for path in sorted(Path(cvbackup.__file__).parent.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            name = getattr(node, "attr", None) or getattr(node, "id", None)
            if isinstance(node, ast.Attribute | ast.Name) and name in _CREATORS:
                found.append(f"{path.name}:{name}")
    assert found == ["tasks.py:create_task"]


def test_tasks_is_the_only_cvbackup_module_the_semgrep_rule_exempts() -> None:
    rule = Path(__file__).resolve().parents[5] / ".semgrep" / "cv-bare-create-task.yml"
    exempt = [line for line in rule.read_text("utf-8").splitlines() if "cvbackup" in line]
    assert len(exempt) == 1 and '"**/cvbackup/tasks.py"' in exempt[0]


async def test_spawn_holds_a_strong_reference_until_the_task_ends() -> None:
    gate = asyncio.Event()

    async def work() -> int:
        await gate.wait()
        return 7

    task = tasks.spawn(work(), name="test.held")
    assert task in tasks.running() and task.get_name() == "test.held"
    gate.set()
    assert await task == 7
    await asyncio.sleep(0)  # the done-callback runs on the next turn
    assert task not in tasks.running()


async def test_spawn_refuses_past_the_bound_and_closes_the_work_unstarted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "MAX_TASKS", 2)
    gate = asyncio.Event()
    held = [tasks.spawn(gate.wait(), name=f"test.bound.{n}") for n in range(2)]
    refused = gate.wait()
    with pytest.raises(tasks.TaskLimit):
        tasks.spawn(refused, name="test.bound.over")
    assert inspect.getcoroutinestate(refused) == inspect.CORO_CLOSED
    assert len(tasks.running()) == 2
    gate.set()
    await asyncio.wait(held)
    tasks.spawn(gate.wait(), name="test.bound.after")  # room again once they end
    await _wait_all()


async def test_spawn_done_callback_logs_and_records_a_failure_by_class_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fails() -> None:
        raise ValueError(_UNLOGGED)

    with caplog.at_level(logging.WARNING, logger="cvbackup"):
        task = tasks.spawn(fails(), name="test.fails")
        await asyncio.wait([task])
        await asyncio.sleep(0)
    assert tasks.failures()[-1] == ("test.fails", "ValueError")
    assert "cvbackup.task_failed name=test.fails error=ValueError" in caplog.text
    assert _UNLOGGED not in caplog.text


async def test_spawn_quiet_failure_is_the_callers_to_read(caplog: pytest.LogCaptureFixture) -> None:
    async def fails() -> None:
        raise ConnectionResetError

    before = tasks.failures()
    with caplog.at_level(logging.WARNING, logger="cvbackup"):
        task = tasks.spawn(fails(), name="test.quiet", quiet=True)
        await asyncio.wait([task])
        await asyncio.sleep(0)
    assert isinstance(task.exception(), ConnectionResetError)
    assert tasks.failures() == before and "task_failed" not in caplog.text


async def test_spawn_honours_cancellation_without_logging_or_recording(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stopped = asyncio.Event()

    async def waits() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    before = tasks.failures()
    with caplog.at_level(logging.WARNING, logger="cvbackup"):
        task = tasks.spawn(waits(), name="test.cancelled")
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.wait([task])
        await asyncio.sleep(0)
    assert task.cancelled() and stopped.is_set() and task not in tasks.running()
    assert tasks.failures() == before and "task_failed" not in caplog.text


async def test_uninterrupted_caller_sees_its_cancel_at_once_while_the_work_lands() -> None:
    gate, landed = asyncio.Event(), asyncio.Event()

    async def step() -> None:
        await gate.wait()
        landed.set()

    caller = asyncio.ensure_future(tasks.uninterrupted(step(), name="test.whole"))
    await asyncio.sleep(0)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert not landed.is_set()
    gate.set()
    await _wait_all()
    assert landed.is_set()
