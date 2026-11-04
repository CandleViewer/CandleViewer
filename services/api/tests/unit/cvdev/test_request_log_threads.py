"""#977: the account fixture's request log is safe from two threads, each on its own event loop.

The order lane runs the OMS on its own thread and loop, beside the serving loop (20 Sec.6.2), so
once the lane is served from the fixture's pack both write to the one request log. Each write's
stamp, size check, rotation and append, and a close, are taken under one lock. Every file lives
under `tmp_path`; the clock is a counter the log reads under its lock.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from cvdev.account_fixture import requestlog
from cvdev.account_fixture.requestlog import FILE_NAME, MAX_LINE_BYTES, RequestLog
from tests.unit.cvdev.test_request_log import KEY_IDS, NOW, SERVED, _open

LINES = 200
KEY = KEY_IDS["compliant"]


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    (tmp_path / "fixture").mkdir()
    return tmp_path / "fixture"


def _counting() -> Callable[[], Any]:
    """A clock one millisecond on at each read: the log reads it under its lock."""
    ticks = iter(range(1_000_000))
    return lambda: NOW + timedelta(milliseconds=next(ticks))


def _two_loops(log: RequestLog, lines: int = LINES) -> list[BaseException]:
    """Two threads, each running its own event loop that writes `lines` lines, started together."""
    start, errors = threading.Barrier(2), list[BaseException]()

    async def writes() -> None:
        for _ in range(lines):
            log.write(**SERVED, signing_key_id=KEY)
            await asyncio.sleep(0)

    def run() -> None:
        start.wait()
        try:
            asyncio.run(writes())
        except BaseException as exc:  # reported to the test, which asserts there is none
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return errors


def _lines(log_dir: Path) -> list[dict[str, Any]]:
    files = sorted(log_dir.glob(f"{FILE_NAME}*"), reverse=True)  # oldest backup first
    texts = [f.read_text() for f in files]
    assert all(text.endswith("\n") for text in texts if text)
    return [json.loads(line) for text in texts for line in text.splitlines()]


def test_two_loops_write_every_line_whole_in_stamp_order(log_dir: Path) -> None:
    with _open(log_dir, clock=_counting()) as log:
        assert _two_loops(log) == []
    lines = _lines(log_dir)
    assert len(lines) == 2 * LINES
    stamps = [line["ts"] for line in lines]
    assert stamps == sorted(stamps) and len(set(stamps)) == len(stamps)


def test_two_loops_rotating_the_log_never_meet_a_released_descriptor(log_dir: Path) -> None:
    with _open(log_dir, clock=_counting(), max_bytes=MAX_LINE_BYTES, backups=9) as log:
        assert _two_loops(log) == []
    assert (log_dir / f"{FILE_NAME}.9").exists()  # it rotated, many times
    stamps = [line["ts"] for line in _lines(log_dir)]
    assert stamps == sorted(stamps)


def test_a_rotation_holds_out_the_other_threads_write_and_close(
    log_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deterministic: thread A's write stops inside its rotation; thread B's write and the close
    wait for the lock, then B's line lands in the new file and the close follows."""
    log = _open(log_dir, max_bytes=MAX_LINE_BYTES)
    log.write(**SERVED, signing_key_id=KEY)
    size = length = (log_dir / FILE_NAME).stat().st_size  # every line is as long
    while size + length <= MAX_LINE_BYTES:
        log.write(**SERVED, signing_key_id=KEY)
        size += length  # so the next line rotates
    inside, release = threading.Event(), threading.Event()
    real_rotate = RequestLog._rotate

    def held(self: RequestLog) -> None:
        if not inside.is_set():
            inside.set()
            assert release.wait(5)
        real_rotate(self)

    monkeypatch.setattr(RequestLog, "_rotate", held)
    done: dict[str, threading.Event] = {name: threading.Event() for name in ("a", "b", "close")}

    def write(name: str) -> None:
        log.write(**SERVED, signing_key_id=KEY)
        done[name].set()

    a = threading.Thread(target=write, args=("a",))
    a.start()
    assert inside.wait(5)
    b = threading.Thread(target=write, args=("b",))

    def close_after_b() -> None:
        b.join()
        log.close()
        done["close"].set()

    closer = threading.Thread(target=close_after_b)
    b.start()
    closer.start()
    assert not done["b"].wait(0.2)  # held at the lock, not writing to a released descriptor
    release.set()
    for thread in (a, b, closer):
        thread.join(5)
    assert all(event.is_set() for event in done.values())
    assert len((log_dir / FILE_NAME).read_text().splitlines()) == 2
    with pytest.raises(requestlog.RequestLogFileError, match="closed"):
        log.write(**SERVED, signing_key_id=KEY)
