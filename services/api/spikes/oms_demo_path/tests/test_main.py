"""The CLI: what it refuses, what it logs and its exit code. The run itself is stubbed (no
network), but for one test that runs the real `run` against the in-memory venue and sends the
process a real SIGHUP; the environment holds a synthetic pair (the Bybit doc placeholder),
restored after."""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import signal
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.base.errors import AuthError
from spikes.oms_demo_path import __main__ as cli
from spikes.oms_demo_path import runner
from spikes.oms_demo_path.runner import BACKFILL_FAILED, COMPLETED, INTERRUPTED, Config, Harness
from spikes.oms_demo_path.safety import ENV_VAR, PAIR_VARS, EnvCredentials

from .venue import FakeBybit

#: Key-shaped, derived at run time (no secret-shaped literal in the source).
KEY_ID = "k" + hashlib.sha256(b"cli key id").hexdigest()[:19]


class StubRun:
    """Stands in for `runner.run`: records each config, then returns `outcome` or raises."""

    def __init__(self) -> None:
        self.configs: list[Config] = []
        self.outcome = COMPLETED
        self.stop_reason: str | None = None
        self.error: BaseException | None = None

    async def __call__(self, cfg: Config, creds: EnvCredentials) -> dict[str, Any]:
        self.configs.append(cfg)
        if self.error is not None:
            raise self.error
        return {"outcome": self.outcome, "stop_reason": self.stop_reason}


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch) -> StubRun:
    monkeypatch.setenv(ENV_VAR, "demo")
    for name in PAIR_VARS:
        monkeypatch.setenv(name, "XXXXXXXXXX")
    monkeypatch.setattr(cli, "configure_logging", lambda **_: None)
    run = StubRun()
    monkeypatch.setattr(cli, "run", run)
    return run


def _args(tmp_path: Path, *more: str) -> list[str]:
    return ["orders", "--out", str(tmp_path / "runs"), "--staging", str(tmp_path / "s"), *more]


def test_hours_zero_is_refused_not_replaced_by_the_default(stub: StubRun, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exited:
        cli.main(_args(tmp_path, "--hours", "0"))
    assert exited.value.code == 2 and stub.configs == []


def test_hours_default_by_mode_when_not_given(stub: StubRun, tmp_path: Path) -> None:
    assert cli.main(_args(tmp_path)) == 0
    assert stub.configs[0].hours == 4.0


@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        (COMPLETED, 0),
        (INTERRUPTED, 1),
        (f"{COMPLETED}; cleanup INCOMPLETE: cancel and flatten by hand", 1),
        (f"{COMPLETED}; {BACKFILL_FAILED}", 1),
        (f"{INTERRUPTED}; {BACKFILL_FAILED}", 1),
        ("stopped early: SafetyRefusal: cycle failed", 1),
    ],
    ids=[
        "completed",
        "interrupted",
        "cleanup-incomplete",
        "backfill-failed",
        "interrupted-backfill-failed",
        "stopped-early",
    ],
)
def test_only_a_completed_run_exits_zero(
    stub: StubRun, tmp_path: Path, outcome: str, code: int
) -> None:
    stub.outcome = outcome
    assert cli.main(_args(tmp_path)) == code


def test_a_written_run_logs_its_outcome_and_the_first_reason_it_stopped(
    stub: StubRun, tmp_path: Path
) -> None:
    """The owner reads the console first: a stop request that interrupted the cleanup of a run a
    refusal had stopped must not hide the refusal there either."""
    reason = "stopped early: SafetyRefusal: create refused (retCode 10003: AuthError (AUTH_ERROR))"
    stub.outcome, stub.stop_reason = INTERRUPTED, reason
    with capture_logs() as logs:
        assert cli.main(_args(tmp_path)) == 1
    (written,) = [entry for entry in logs if entry["event"] == "run_written"]
    assert (written["outcome"], written["stop_reason"]) == (INTERRUPTED, reason)


def test_a_failed_run_logs_the_error_class_only(stub: StubRun, tmp_path: Path) -> None:
    """A 10004 retMsg echoes the signed string, key id included (C-12.2)."""
    echo = f'error sign! origin_string[1760630400000{KEY_ID}5000{{"category":"linear"}}]'
    stub.error = AuthError(echo, exchange_ret_code=10004, exchange_ret_msg=echo)
    with capture_logs() as logs:
        assert cli.main(_args(tmp_path)) == 1
    assert {"event": "run_failed", "error": "AuthError", "log_level": "error"} in logs
    assert KEY_ID not in repr(logs)


def test_an_aborting_stop_request_logs_its_class_only_and_exits_one(
    stub: StubRun, tmp_path: Path
) -> None:
    """A further Ctrl-C or SIGTERM cancels what the run was doing, here the handling of a 10004
    whose retMsg echoes the key id. Nothing escapes `main` to print that error's traceback: the
    class is logged and the exit code is 1 (C-12.2)."""
    echo = f'error sign! origin_string[1760630400000{KEY_ID}5000{{"category":"linear"}}]'
    cancelled = asyncio.CancelledError()
    cancelled.__context__ = AuthError(echo, exchange_ret_code=10004, exchange_ret_msg=echo)
    stub.error = cancelled
    with capture_logs() as logs:
        assert cli.main(_args(tmp_path)) == 1
    assert {"event": "run_interrupted", "error": "CancelledError", "log_level": "error"} in logs
    assert KEY_ID not in repr(logs)


def test_the_10018_burst_is_refused_in_a_soak(
    stub: StubRun, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["soak", "--capture-10018", "--out", str(tmp_path / "runs")]
    with pytest.raises(SystemExit) as exited:
        cli.main([*argv, "--staging", str(tmp_path / "s")])
    assert exited.value.code == 2 and stub.configs == []
    assert "refused: the 10018 burst runs in orders mode only" in capsys.readouterr().err


def test_the_10002_capture_is_refused_in_a_soak(
    stub: StubRun, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["soak", "--capture-10002", "--out", str(tmp_path / "runs")]
    with pytest.raises(SystemExit) as exited:
        cli.main([*argv, "--staging", str(tmp_path / "s")])
    assert exited.value.code == 2 and stub.configs == []
    assert "refused: the 10002 capture runs in orders mode only" in capsys.readouterr().err


async def _no_sleep(_: float) -> None:
    return None


def test_a_hangup_during_the_wrap_up_ends_the_run_interrupted_and_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real `run`, on the in-memory venue, through `main`: SIGHUP (the terminal closing) comes
    while the backfill reads, after the run completed its cycle. The handler `run` installed turns
    it into a stop request: the outputs are written, the outcome reads `interrupted` and the exit
    code is 1, not the 0 of the `completed` the run had reached. The signal is delivered by running
    the callback the loop was given, as the loop does."""
    monkeypatch.setenv(ENV_VAR, "demo")
    for name in PAIR_VARS:
        monkeypatch.setenv(name, "XXXXXXXXXX")
    monkeypatch.setattr(cli, "configure_logging", lambda **_: None)
    registered: dict[int, Callable[[], None]] = {}
    install = runner._on_signals

    def on_signals(h: Harness) -> None:
        def add(sig: int, callback: Callable[..., None], *args: Any) -> None:
            registered[sig] = functools.partial(callback, *args)

        monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", add)
        install(h)

    venue = FakeBybit()
    venue.on_get = lambda path: (
        registered[signal.SIGHUP]() if path == "/v5/execution/list" else None
    )
    offline = functools.partial(
        Harness, transport_factory=venue.transport, dial_fn=venue.dial, sleep=_no_sleep
    )
    monkeypatch.setattr(runner, "_on_signals", on_signals)
    monkeypatch.setattr(runner, "Harness", offline)

    argv = ["--orders", "1", "--hours", "0.000001", "--fill-wait-s", "0"]
    with capture_logs() as logs:
        code = cli.main(_args(tmp_path, *argv))
    assert code == 1 and signal.SIGHUP in registered
    (run_dir,) = (tmp_path / "runs").iterdir()
    saved = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert (saved["outcome"], saved["stop_reason"]) == (INTERRUPTED, "stop request (SIGHUP)")
    (written,) = [entry for entry in logs if entry["event"] == "run_written"]
    assert written["stop_reason"] == "stop request (SIGHUP)"
