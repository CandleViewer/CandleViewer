"""#2386: a `.env` file holding an exchange key fails startup and never echoes its value.

`Settings` declares no exchange key field (C-2.7, C-12.2), so `CV_BYBIT_API_KEY` in the `.env`
file is an unknown name and refuses the load. The sentinel below is an inert fixture string,
never a credential; it must reach none of the surfaces a boot site prints or raises.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from pydantic import ValidationError

from candleviewer import audit_ack_break, bootstrap_owner, breakglass
from candleviewer.settings import (
    Settings,
    SettingsRefusedError,
    load_settings,
    refusal_messages,
)

_SENTINEL = "SENT2386Kq7ZxW9vB3"
_VARIABLE = "CV_BYBIT_API_KEY"


@pytest.fixture
def env_file_with_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # `Settings` reads `.env` from the working directory
    for name in [n for n in os.environ if n.upper().startswith("CV_")]:
        monkeypatch.delenv(name)
    (tmp_path / ".env").write_text(f"{_VARIABLE}={_SENTINEL}\n", encoding="utf-8")


def test_load_settings_env_file_exchange_key_names_variable_never_value(
    env_file_with_key: None,
) -> None:
    with pytest.raises(SettingsRefusedError) as refused:
        load_settings()

    error = refused.value
    assert _VARIABLE.lower() in str(error).lower()
    assert _SENTINEL not in str(error) + repr(error) + repr(error.args)
    assert error.__context__ is None and error.__cause__ is None


@pytest.mark.parametrize(
    ("main", "argv"),
    [
        pytest.param(breakglass.main, ["--owner", "alice"], id="breakglass"),
        pytest.param(bootstrap_owner.main, ["--owner", "owner@example.test"], id="bootstrap-owner"),
        pytest.param(
            audit_ack_break.main,
            [
                "--owner", "alice", "--first-bad-id", "1", "--kind", audit_ack_break.KINDS[0],
                "--reason", "sentinel check",
            ],
            id="audit-ack-break",
        ),
    ],
)  # fmt: skip
def test_cli_env_file_exchange_key_fails_startup_without_its_value(
    capsys: pytest.CaptureFixture[str],
    env_file_with_key: None,
    main: Callable[[Sequence[str] | None], int],
    argv: list[str],
) -> None:
    assert main(argv) == breakglass.EXIT_INVALID

    captured = capsys.readouterr()
    assert "invalid settings" in captured.err
    assert _SENTINEL not in captured.err + captured.out


def test_settings_env_file_exchange_key_refuses_with_the_value_hidden_from_messages(
    env_file_with_key: None,
) -> None:
    with pytest.raises(ValidationError) as refused:
        Settings()

    messages = refusal_messages(refused.value)
    assert any(_VARIABLE.lower() in line.lower() for line in messages)
    assert _SENTINEL not in "\n".join(messages)
