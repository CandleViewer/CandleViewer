"""#2893 S14: the switch CLI over `control` (`cvdev.account_fixture.cli`).

`main` runs in process on settings built here, with the checkout's pack and the state directory
under `tmp_path`. Real time is not faked: the clock assertions read the offset file, and a switch's
start is checked against the fixture clock around the call. No socket opens and nothing sleeps.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

from candleviewer.settings import Environment, FeedMode, Settings
from cvdev.account_fixture import cli
from cvdev.account_fixture.control import CLOCK_FILE, KEYS_DIR, FixtureClock, KeyStates
from cvdev.account_fixture.requestlog import FILE_NAME
from tests._account_fixtures import PACK

STORED: Final = "fixture-stored_key_rejected-0046"
COMPLIANT: Final = "fixture-compliant-0001"
#: A refusal never echoes a credential; the word itself must not appear.
CREDENTIAL_WORD: Final = "".join(("sec", "ret"))


def _armed(directory: Path) -> Settings:
    return Settings(
        environment=Environment.DEMO,
        feed=FeedMode.SYNTHETIC,
        account_fixture="compliant",
        account_fixture_dir=str(directory),
    )


def _run(
    argv: list[str], settings: Settings, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str]:
    status = cli.main(argv, settings=settings, pack=PACK)
    out, err = capsys.readouterr()
    return status, out + err


def test_clock_set_and_advance_move_the_fixture_clock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _armed(tmp_path)
    moment = datetime(2026, 10, 5, 12, tzinfo=UTC)

    status, out = _run(["clock", "set", moment.isoformat()], settings, capsys)
    assert status == 0
    assert out.startswith("account-fixture: fixture clock now reads 2026-10-05T12:00")
    before = FixtureClock(tmp_path)()
    assert _run(["clock", "advance", "-90.5"], settings, capsys)[0] == 0
    after = FixtureClock(tmp_path)()
    assert timedelta(seconds=-91) < after - before < timedelta(seconds=-90)
    assert (tmp_path / CLOCK_FILE).is_file()


def test_switch_defaults_to_the_stored_scenarios_switch_to(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = FixtureClock(tmp_path)()
    status, out = _run(["switch", STORED], _armed(tmp_path), capsys)

    body = json.loads((tmp_path / KEYS_DIR / f"{STORED}.json").read_text())
    assert (status, body["scenario"], body["overlays"]) == (0, "live_key_on_demo", [])
    assert datetime.fromisoformat(body["started"]) >= before  # scenario time restarts at the switch
    assert f"{STORED} answers as live_key_on_demo (overlays: none)" in out
    (line,) = [json.loads(x) for x in (tmp_path / FILE_NAME).read_text().splitlines()]
    assert (line["outcome"], line["signing_key_id"]) == ("switch", STORED)


def test_switch_seeds_named_overlays(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["switch", COMPLIANT, "--to", "compliant", "--overlay", "open_position_btcusdt_5x_sl"]
    status, out = _run(argv, _armed(tmp_path), capsys)

    body = json.loads((tmp_path / KEYS_DIR / f"{COMPLIANT}.json").read_text())
    assert (status, body["overlays"]) == (0, ["open_position_btcusdt_5x_sl"])
    assert "overlays: open_position_btcusdt_5x_sl" in out


def test_unarmed_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    status, out = _run(["clock", "advance", "1"], Settings(), capsys)
    assert (status, out) == (2, f"account-fixture: refused: {cli.NOT_ARMED}\n")
    assert not list(tmp_path.iterdir())


def test_live_is_refused_even_on_settings_that_skipped_validation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings.model_construct(
        environment=Environment.LIVE,
        feed=FeedMode.SYNTHETIC,
        account_fixture="compliant",
        account_fixture_dir=str(tmp_path),
    )
    assert _run(["switch", STORED], settings, capsys) == (
        2,
        f"account-fixture: refused: {cli.LIVE}\n",
    )
    assert not list(tmp_path.iterdir())


def test_a_settings_gate_refusal_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings.model_construct(
        environment=Environment.TESTNET,
        feed=FeedMode.SYNTHETIC,
        account_fixture="compliant",
        account_fixture_dir=str(tmp_path),
        test_clock=False,
    )
    status, out = _run(["clock", "advance", "1"], settings, capsys)
    assert (status, "CV_ENVIRONMENT=demo" in out) == (2, True)
    assert not list(tmp_path.iterdir())


def test_armed_without_a_state_directory_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings(
        environment=Environment.DEMO, feed=FeedMode.SYNTHETIC, account_fixture="compliant"
    )
    assert _run(["clock", "advance", "1"], settings, capsys) == (
        2,
        f"account-fixture: refused: {cli.NO_DIR}\n",
    )


def test_invalid_settings_print_no_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Live with the fixture on fails Settings' own gate at load; the input is never echoed."""
    monkeypatch.setenv("CV_ENVIRONMENT", "live")
    monkeypatch.setenv("CV_ACCOUNT_FIXTURE", "compliant")
    monkeypatch.setenv("CV_ACCOUNT_FIXTURE_DIR", str(tmp_path))
    status = cli.main(["clock", "advance", "1"], pack=PACK)
    out, err = capsys.readouterr()
    assert (status, out, err) == (
        2,
        "",
        "account-fixture: refused: invalid settings; nothing changed\n",
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["switch", "fixture-nope-9999"],
        ["switch", COMPLIANT],  # compliant names no switch_to
        ["switch", COMPLIANT, "--to", "no_such_scenario"],
        ["clock", "set", "2026-10-05T12:00:00"],  # naive
        ["clock", "advance", "1.1e9"],  # past the offset file's bound
        ["clock", "advance", "1e12"],  # past datetime's range
    ],
    ids=["foreign-key", "no-switch-to", "unknown-target", "naive-moment", "huge", "overflow"],
)
def test_a_refusal_is_one_clean_line(
    argv: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, out = _run(argv, _armed(tmp_path), capsys)
    assert status == 2
    assert out.startswith("account-fixture: refused: ") and out.count("\n") == 1
    assert "Traceback" not in out and str(tmp_path) not in out and CREDENTIAL_WORD not in out


def test_a_state_failure_names_no_path_and_chains_nothing(tmp_path: Path) -> None:
    """A missing state directory is an `OSError` naming its path: the refusal is a fixed line,
    raised `from None`, with no cause or context left to print."""
    args = cli._parser().parse_args(["clock", "advance", "1"])
    with pytest.raises(cli.CliRefused) as refused:
        cli.run(args, _armed(tmp_path / "gone"), PACK)

    assert str(refused.value) == cli.STATE_FAILED
    assert refused.value.__cause__ is None and refused.value.__suppress_context__


@pytest.mark.parametrize("seconds", ["soon", "nan", "1e20"])
def test_a_bad_seconds_argument_is_a_usage_error(
    seconds: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as usage:
        cli.main(["clock", "advance", seconds], settings=_armed(tmp_path), pack=PACK)
    assert usage.value.code == 2
    assert "seconds must be a signed decimal" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_a_bad_moment_is_a_usage_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as usage:
        cli.main(["clock", "set", "tomorrow"], settings=_armed(tmp_path), pack=PACK)
    assert usage.value.code == 2
    assert "the moment must be ISO 8601 with an offset" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_a_value_error_off_the_control_surface_is_the_fixed_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pack or request-log `ValueError` may name a path: the refusal replaces it, unchained."""

    def broken(*_args: object, **_kwargs: object) -> None:
        raise ValueError(f"cannot read {tmp_path}")

    monkeypatch.setattr(KeyStates, "switch", broken)
    args = cli._parser().parse_args(["switch", STORED])
    with pytest.raises(cli.CliRefused) as refused:
        cli.run(args, _armed(tmp_path), PACK)

    assert str(refused.value) == cli.STATE_FAILED
    assert refused.value.__cause__ is None and refused.value.__suppress_context__


def test_an_unknown_overlay_is_refused_with_the_fixed_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["switch", STORED, "--overlay", "no-such-overlay"]
    status, out = _run(argv, _armed(tmp_path), capsys)
    assert status == 2
    assert out.count("\n") == 1 and out.startswith("account-fixture: refused: ")
    assert "no-such-overlay" not in out and "Traceback" not in out

    args = cli._parser().parse_args(argv)
    with pytest.raises(cli.CliRefused) as refused:
        cli.run(args, _armed(tmp_path), PACK)
    assert refused.value.__cause__ is None and refused.value.__suppress_context__


@pytest.mark.parametrize("error", [KeyError("secret-name"), RuntimeError("at /some/path")])
def test_a_key_or_runtime_error_is_the_fixed_state_failed_refusal(
    error: Exception, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(KeyStates, "switch", broken)
    args = cli._parser().parse_args(["switch", STORED])
    with pytest.raises(cli.CliRefused) as refused:
        cli.run(args, _armed(tmp_path), PACK)

    assert str(refused.value) == cli.STATE_FAILED
    assert refused.value.__cause__ is None and refused.value.__suppress_context__


def test_an_unexpected_exception_is_the_fixed_line_with_no_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(*_args: object, **_kwargs: object) -> str:
        raise TypeError(f"bad value at {tmp_path}")

    monkeypatch.setattr(cli, "run", broken)
    status, out = _run(["switch", STORED], _armed(tmp_path), capsys)

    assert status == 2
    assert out == f"account-fixture: refused: {cli.STATE_FAILED}\n"
