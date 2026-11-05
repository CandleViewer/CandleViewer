"""#3319 B1b (ADR-0041 section 4): the sidecar's process is hardened (no core file, not dumpable,
private umask) before it serves, refuses a bad configuration by name, and serves its socket with
the quarantine sweeper until stopped."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

import cvbackup
from cvbackup import __main__ as entry
from cvbackup import tasks
from cvbackup.ledger import FILE
from cvbackup.ops import Ops
from cvbackup.paths import LEDGER_DIR
from tests.unit.backup_sidecar._sidecar import (
    Clock,
    build,
    config,
    exchange,
    read,
    request_frame,
    write,
)

_API = str(Path(cvbackup.__file__).resolve().parents[1])
_PROBE = """
import ctypes, os, resource, sys
sys.path.insert(0, sys.argv[1])
from cvbackup.__main__ import harden
harden()
libc = ctypes.CDLL(None)
print(resource.getrlimit(resource.RLIMIT_CORE), libc.prctl(3, 0, 0, 0, 0), oct(os.umask(0)))
"""


def test_process_is_not_dumpable_and_core_limit_zero() -> None:
    probe = subprocess.run(  # noqa: S603 - this interpreter, a fixed script, no input
        [sys.executable, "-I", "-c", _PROBE, _API], capture_output=True, text=True, check=True
    )
    assert probe.stdout.split() == ["(0,", "0)", "0", "0o77"]


def test_main_refuses_a_bad_configuration_by_name(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(logging.getLogger("cvbackup"), "filters", [])
    assert entry.main({"CVB_SOCKET": "relative", "CVB_BACKUP_ROOT": "/srv/cvb"}) == 2
    assert logging.getLogger("cvbackup").filters == [entry.STRUCTURAL]  # before anything logs
    assert capsys.readouterr().err.strip() == (
        "cvbackup: CVB_SOCKET must be an absolute path in canonical form, not /"
    )


async def test_serve_answers_on_its_socket_and_sweeps_until_stopped(
    tmp_path: Path, sock: str
) -> None:
    stop, ready, clock = asyncio.Event(), asyncio.Event(), Clock()
    cfg = config(tmp_path, sock, grace=timedelta(hours=1))
    serving = asyncio.ensure_future(entry.serve(cfg, stop, clock=clock, ready=ready))
    async with asyncio.timeout(5):
        await ready.wait()
        frames = await exchange(sock, request_frame("plan", {"kind": "config_bundle"}))
        stop.set()
        await serving
    assert frames[-1]["t"] == "ok"
    assert set(os.listdir(tmp_path / "backups")) == {
        ".cvb",
        ".quarantine",
        "config_bundle",
        "pg_dump",
    }


async def test_sweep_at_the_task_bound_is_deferred_to_the_next_sweep(
    tmp_path: Path, sock: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sidecar, stop, sweeps = await build(config(tmp_path, sock)), asyncio.Event(), []

    async def bound() -> int:
        sweeps.append(stop.set() if sweeps else None)  # the second sweep: then stop
        raise tasks.TaskLimit

    monkeypatch.setattr(sidecar.ops, "sweep", bound)
    monkeypatch.setattr(entry, "SWEEP_S", 0.0)
    await entry._sweep(sidecar.ops, stop)
    assert len(sweeps) == 2 and "cvbackup.sweep_deferred reason=task_limit" in caplog.messages


async def test_serve_stops_on_sigterm_while_an_op_hangs_on_an_open_connection(
    tmp_path: Path, sock: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def hangs(self: Ops, request: Any, progress: Any) -> dict[str, object]:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return {}

    monkeypatch.setattr(Ops, "handle", hangs)
    stop, ready = asyncio.Event(), asyncio.Event()
    serving = asyncio.ensure_future(entry.serve(config(tmp_path, sock), stop, ready=ready))
    async with asyncio.timeout(5):
        await ready.wait()
        reader, writer = await asyncio.open_unix_connection(sock)
        writer.write(request_frame("plan", {"kind": "pg_dump"}))
        await started.wait()
        stop.set()  # the connection still open, its op still running
        await serving
        assert await reader.read() == b""  # closed unanswered
    writer.close()
    assert cancelled.is_set()


async def _record_of_two_runs(tmp_path: Path, sock: str) -> Path:
    sidecar = await build(config(tmp_path, sock))
    await sidecar.finished()
    await sidecar.finished("config_bundle")
    sidecar.ledger.close()
    return tmp_path / "backups" / LEDGER_DIR / FILE


async def test_check_ledger_reports_a_record_that_replays(
    tmp_path: Path, sock: str, capsys: pytest.CaptureFixture[str]
) -> None:
    await _record_of_two_runs(tmp_path, sock)
    assert entry.check_ledger(str(tmp_path / "backups")) == 0
    assert capsys.readouterr().out == "cvbackup: the run record replays, 4 entries\n"


@pytest.mark.parametrize(
    ("damage", "line"),
    [
        pytest.param(lambda b: b[:-1], 4, id="torn"),
        pytest.param(
            lambda b: b.replace(b'"kind":"pg_dump"', b'"kind":"config_bundle"', 1),
            2,
            id="tampered-caught-by-the-chain",
        ),
    ],
)
async def test_check_ledger_names_the_line_a_record_stops_replaying_and_never_repairs_it(
    tmp_path: Path, sock: str, capsys: pytest.CaptureFixture[str],
    damage: Callable[[bytes], bytes], line: int,
) -> None:  # fmt: skip
    record = await _record_of_two_runs(tmp_path, sock)
    damaged = damage(read(record))
    write(record, damaged)
    assert entry.check_ledger(str(tmp_path / "backups")) == 1
    assert capsys.readouterr().out == f"cvbackup: the run record does not replay from line {line}\n"
    assert read(record) == damaged


def test_check_ledger_without_a_record_or_through_a_link(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "backups"
    (root / LEDGER_DIR).mkdir(parents=True)
    assert entry.check_ledger(str(root)) == 0
    (root / LEDGER_DIR / FILE).symlink_to(tmp_path / "elsewhere")
    assert entry.check_ledger(str(root)) == 1
    assert capsys.readouterr().out.splitlines() == [
        "cvbackup: no run record yet",
        "cvbackup: the run record cannot be read (OSError)",
    ]


def test_main_check_ledger_reads_the_configured_root_and_refuses_other_arguments(
    tmp_path: Path, sock: str, capsys: pytest.CaptureFixture[str]
) -> None:
    env = {"CVB_BACKUP_ROOT": config(tmp_path, sock).root}  # it needs no other variable
    assert entry.main(env, ["check-ledger"]) == 0
    assert entry.main({"CVB_BACKUP_ROOT": "relative"}, ["check-ledger"]) == 2
    assert entry.main(env, ["serve", "--now"]) == 2
    out = capsys.readouterr()
    assert out.out == "cvbackup: no run record yet\n"
    assert out.err.splitlines() == [
        "cvbackup: CVB_BACKUP_ROOT must be an absolute path in canonical form, not /",
        "usage: python -I -m cvbackup [check-ledger]",
    ]


async def test_run_record_bytes_per_run_stay_small(tmp_path: Path, sock: str) -> None:
    """The record grows by one run's `started` and `finished` entries (pruning is out of v1):
    about 600 bytes besides the root's path, which the location repeats."""
    record = await _record_of_two_runs(tmp_path, sock)
    per_run = [len(line) + 1 for line in read(record).splitlines()]
    root = len(str(tmp_path / "backups"))
    assert sum(per_run[:2]) - root <= 620 and sum(per_run[2:]) - root <= 620
