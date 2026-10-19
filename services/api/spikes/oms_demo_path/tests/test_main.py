"""The CLI: what it refuses, what it logs and its exit code. The run itself is stubbed (no
network); the environment holds a synthetic pair (the Bybit doc placeholder), restored after."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.base.errors import AuthError
from spikes.oms_demo_path import __main__ as cli
from spikes.oms_demo_path.runner import COMPLETED, INTERRUPTED, Config
from spikes.oms_demo_path.safety import ENV_VAR, PAIR_VARS, EnvCredentials

#: Key-shaped, derived at run time (no secret-shaped literal in the source).
KEY_ID = "k" + hashlib.sha256(b"cli key id").hexdigest()[:19]


class StubRun:
    """Stands in for `runner.run`: records each config, then returns `outcome` or raises."""

    def __init__(self) -> None:
        self.configs: list[Config] = []
        self.outcome = COMPLETED
        self.error: Exception | None = None

    async def __call__(self, cfg: Config, creds: EnvCredentials) -> dict[str, Any]:
        self.configs.append(cfg)
        if self.error is not None:
            raise self.error
        return {"outcome": self.outcome}


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
        (f"{COMPLETED}; cleanup INCOMPLETE: flatten in the demo UI", 1),
        ("stopped early: SafetyRefusal: cycle failed", 1),
    ],
    ids=["completed", "interrupted", "cleanup-incomplete", "stopped-early"],
)
def test_only_a_completed_run_exits_zero(
    stub: StubRun, tmp_path: Path, outcome: str, code: int
) -> None:
    stub.outcome = outcome
    assert cli.main(_args(tmp_path)) == code


def test_a_failed_run_logs_the_error_class_only(stub: StubRun, tmp_path: Path) -> None:
    """A 10004 retMsg echoes the signed string, key id included (C-12.2)."""
    echo = f'error sign! origin_string[1760630400000{KEY_ID}5000{{"category":"linear"}}]'
    stub.error = AuthError(echo, exchange_ret_code=10004, exchange_ret_msg=echo)
    with capture_logs() as logs:
        assert cli.main(_args(tmp_path)) == 1
    assert {"event": "run_failed", "error": "AuthError", "log_level": "error"} in logs
    assert KEY_ID not in repr(logs)
