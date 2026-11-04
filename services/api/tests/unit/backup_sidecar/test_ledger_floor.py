"""#3319 B1b (ADR-0041 section 1; AD-SC02, AD-SC07): the sidecar's own run record replays only
whole and chained, fails closed otherwise, and the floor holds against any stream of well-formed
requests: the newest finished artefact of a kind is never removed, and runs never pass the cap
in any window."""

from __future__ import annotations

import asyncio
import os
import threading
import uuid
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from cvbackup import protocol
from cvbackup.floor import FloorRefusal
from cvbackup.ledger import FILE, GENESIS, Ledger, LedgerUnreadable, _write_all
from cvbackup.ops import OpError
from cvbackup.paths import LEDGER_DIR
from tests.unit.backup_sidecar._sidecar import T0, Clock, build, config, mode, read, write


def _record(tmp_path: Path) -> Path:
    return tmp_path / "backups" / LEDGER_DIR / FILE


async def _seeded(tmp_path: Path, sock: str) -> Ledger:
    sidecar = await build(config(tmp_path, sock))
    await sidecar.finished()
    await sidecar.finished("config_bundle")
    sidecar.ledger.close()
    return sidecar.ledger


async def _reloaded(tmp_path: Path, sock: str) -> Ledger:
    sidecar = await build(config(tmp_path, sock))
    sidecar.ledger.close()
    return sidecar.ledger


async def test_ledger_is_private_chained_and_replays(tmp_path: Path, sock: str) -> None:
    await _seeded(tmp_path, sock)
    assert mode(_record(tmp_path)) == 0o600
    lines = read(_record(tmp_path)).splitlines()
    first = protocol.loads(lines[0])
    assert isinstance(first, dict) and (first["seq"], first["prev"]) == (1, GENESIS)
    assert (await _reloaded(tmp_path, sock)).readable


@pytest.mark.parametrize(
    "damage",
    [
        pytest.param(lambda b: b.replace(b'"seq":2', b'"seq":3', 1), id="sequence"),
        pytest.param(
            lambda b: b.replace(b'"kind":"pg_dump"', b'"kind":"pg_dumq"', 1), id="tampered-line"
        ),
        pytest.param(lambda b: b[: b.rindex(b"\n")], id="torn-last-line"),
        pytest.param(lambda b: b + b'{"e":"purged"}\n', id="unknown-shape"),
        pytest.param(lambda b: b"\n".join(b.splitlines()[1:]) + b"\n", id="first-line-gone"),
        pytest.param(lambda b: b.replace(b"}", b" }", 1), id="non-canonical"),
    ],
)
async def test_a_ledger_that_does_not_replay_stays_unreadable(
    tmp_path: Path, sock: str, damage: Callable[[bytes], bytes]
) -> None:
    await _seeded(tmp_path, sock)
    data = read(_record(tmp_path))
    write(_record(tmp_path), damage(data))
    ledger = await _reloaded(tmp_path, sock)
    assert not ledger.readable
    with pytest.raises(LedgerUnreadable):
        ledger.newest("pg_dump")


async def test_a_record_out_of_place_never_replays(tmp_path: Path, sock: str) -> None:
    sidecar = await build(config(tmp_path, sock))
    with pytest.raises(ValueError, match="refuses"):
        await sidecar.ledger.append("quarantined", str(uuid.uuid4()), name="x.age",
                                    purge_after="2026-11-02T12:00:00.000000Z")  # fmt: skip
    assert sidecar.ledger.readable  # a caller's bug, refused before any byte
    sidecar.ledger.close()


async def test_a_failed_append_leaves_the_record_unreadable(
    tmp_path: Path, sock: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sidecar = await build(config(tmp_path, sock))

    def full(fd: int, data: bytes) -> None:
        raise OSError(28, "no space")

    monkeypatch.setattr("cvbackup.ledger._write_all", full)
    with pytest.raises(LedgerUnreadable):
        await sidecar.ledger.append("started", str(uuid.uuid4()), kind="pg_dump")
    assert not sidecar.ledger.readable
    with pytest.raises(OpError, match="ledger_unreadable"):
        await sidecar.handle("plan", kind="pg_dump")
    sidecar.ledger.close()


async def test_a_read_during_an_append_answers_from_the_durable_record(
    tmp_path: Path, sock: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sidecar = await build(config(tmp_path, sock))
    entered, release = threading.Event(), threading.Event()
    day = T0 - timedelta(days=1)

    def blocked(fd: int, data: bytes) -> None:
        entered.set()
        release.wait(30)
        _write_all(fd, data)

    async def read() -> tuple[int, object]:
        try:
            assert await asyncio.to_thread(entered.wait, 30)
            plan = await sidecar.handle("plan", kind="pg_dump")
            return sidecar.ledger.started_since(day), plan["encrypted"]
        finally:
            release.set()

    monkeypatch.setattr("cvbackup.ledger._write_all", blocked)
    append = sidecar.ledger.append("started", str(uuid.uuid4()), kind="pg_dump")
    assert (await asyncio.gather(append, read()))[1] == (0, True)  # not `ledger_unreadable`
    assert sidecar.ledger.started_since(day) == 1
    sidecar.ledger.close()


async def test_two_concurrent_admissions_at_the_cap_pass_one(tmp_path: Path, sock: str) -> None:
    sidecar = await build(config(tmp_path, sock, run_cap=1))
    admit = [sidecar.floor.admit(str(uuid.uuid4()), "pg_dump", T0) for _ in range(2)]
    outcomes = await asyncio.gather(*admit, return_exceptions=True)
    assert outcomes.count(None) == 1 and sidecar.ledger.started_since(T0 - timedelta(days=1)) == 1
    assert [o.code for o in outcomes if isinstance(o, FloorRefusal)] == ["runs_capped"]
    sidecar.ledger.close()


def _symlinked(record: Path) -> None:
    record.rename(record.with_name("elsewhere"))
    record.symlink_to(record.with_name("elsewhere"))


@pytest.mark.parametrize(
    "replace_record",
    [
        pytest.param(_symlinked, id="symlink"),
        pytest.param(lambda record: os.link(record, record.with_name("second")), id="hard-link"),
        pytest.param(lambda record: (record.unlink(), os.mkfifo(record)), id="fifo"),
    ],
)
async def test_a_ledger_not_one_regular_file_is_unreadable(
    tmp_path: Path, sock: str, replace_record: Callable[[Path], object]
) -> None:
    await _seeded(tmp_path, sock)
    replace_record(_record(tmp_path))
    assert not (await _reloaded(tmp_path, sock)).readable


# -- the floor, against streams of well-formed requests ----------------------------------------


def _scratch(factory: pytest.TempPathFactory) -> tuple[Path, str]:
    """A fresh root per example (hypothesis runs many in one test), in pytest's temp area."""
    path = factory.mktemp("h")
    (path / "s").mkdir()
    return path, str(path / "s" / "c.sock")


_RUNS = st.lists(st.sampled_from(["pg_dump", "config_bundle"]), min_size=1, max_size=6)
_REMOVES = st.lists(st.integers(min_value=0, max_value=5), max_size=12)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(runs=_RUNS, removes=_REMOVES)
def test_floor_stream_of_well_formed_removes_never_takes_newest(
    tmp_path_factory: pytest.TempPathFactory, runs: list[str], removes: list[int]
) -> None:
    async def scenario(tmp: Path, sock: str) -> None:
        sidecar = await build(config(tmp, sock))
        finished = [(kind, *await sidecar.finished(kind)) for kind in runs]
        newest = {kind: backup_id for kind, backup_id, _, _ in finished}
        for index in removes:
            kind, backup_id, location, _ = finished[index % len(finished)]
            try:
                await sidecar.handle("remove", backup_id=backup_id, location=location)
            except OpError as refused:
                assert refused.code == "newest_artefact" and newest[kind] == backup_id
            for kind_, newest_id in newest.items():
                assert sidecar.ledger.get(newest_id).state == "present", kind_
        sidecar.ledger.close()

    asyncio.run(scenario(*_scratch(tmp_path_factory)))


@settings(max_examples=40, deadline=None)
@given(
    cap=st.integers(min_value=1, max_value=4),
    steps=st.lists(st.integers(min_value=0, max_value=3 * 3600), min_size=1, max_size=25),
)
def test_floor_stream_of_well_formed_runs_never_exceeds_cap(
    tmp_path_factory: pytest.TempPathFactory, cap: int, steps: list[int]
) -> None:
    window = timedelta(hours=2)

    async def scenario(tmp: Path, sock: str) -> None:
        clock = Clock()
        sidecar = await build(config(tmp, sock, run_cap=cap, run_window=window), clock)
        admitted = []
        for seconds in steps:
            clock.advance(seconds=seconds)
            try:
                await sidecar.floor.admit(str(uuid.uuid4()), "pg_dump", clock())
                admitted.append(clock())
            except FloorRefusal as refused:
                assert refused.code == "runs_capped"
        for at in admitted:
            assert sum(1 for other in admitted if at - window < other <= at) <= cap
        sidecar.ledger.close()

    asyncio.run(scenario(*_scratch(tmp_path_factory)))
