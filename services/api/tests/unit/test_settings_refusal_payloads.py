"""#5303: a `Settings` refusal reports only the offending field.

Every other setting that can hold text carries `_MARKER` (inert fixture strings, never a
credential). Each refusal is triggered in turn; the marker must appear in none of the error's
renderings, while the refusal message stays as it was. The boot sites report messages only.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from candleviewer import bootstrap_owner, breakglass
from candleviewer.settings import (
    UNKNOWN_HOME_REFUSAL,
    Settings,
    SettingsRefusedError,
    load_settings,
    refusal_messages,
)

#: An inert marker standing in for every other setting's value; never a credential.
_MARKER = "MK5303ZQ"

#: Settings that hold text whose own checks refuse any marker-bearing value: left at default.
_UNMARKABLE = frozenset({
    "mesh_trusted_proxy_header",  # an HTTP field name, set only where a test needs one
    "mesh_trusted_proxy_address",  # an IP literal
    "allowed_origins",  # serialised origins
    "test_clock_file",  # refused outside a keyless testnet
    "account_fixture",  # a scenario vocabulary, dev and test only
    "account_fixture_dir",  # refused outside dev and test
    "egress_ip",  # an IP literal
})  # fmt: skip


def _env_name(field: str) -> str:
    return Settings.model_fields[field].alias or f"CV_{field.upper()}"


def _text_fields() -> list[str]:
    text = (str, str | None, SecretStr, SecretStr | None)
    return [name for name, f in Settings.model_fields.items() if f.annotation in text]


def _marked(tmp_path: Path) -> dict[str, str]:
    """Every text setting but `_UNMARKABLE`, marked; paths absolute and apart, under tmp."""
    paths = {
        "parquet_root": f"{tmp_path}/{_MARKER}-data/parquet",
        "recorder_wal_dir": f"{tmp_path}/{_MARKER}-data/recorder-wal",
        "bars_state_root": f"{tmp_path}/{_MARKER}-bars",
        "backup_root": f"{tmp_path}/{_MARKER}-backups",
        "audit_lane_mac_file": f"{tmp_path}/{_MARKER}-lane/key",
        "audit_lane_previous_mac_file": f"{tmp_path}/{_MARKER}-lane/previous",
    }
    for name in ("audit_wal_path", "audit_checkpoint_path", "machine_event_wal_path"):
        paths[name] = f"{tmp_path}/{_MARKER}-audit/{name}"
    for name in ("kek_handle", "kek_prev_handle", "kek_ack_path"):
        paths[name] = f"{tmp_path}/{_MARKER}-kek/{name}"
    marked = {name: f"{_MARKER}-{name}" for name in _text_fields() if name not in _UNMARKABLE}
    marked.update(paths)
    marked["version"] = f"{_MARKER}-v1"
    marked["liquidity_pinned_symbols"] = f'["{_MARKER}"]'
    return {_env_name(name): value for name, value in marked.items()}


@pytest.fixture
def marked_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    monkeypatch.chdir(tmp_path)  # no `.env` file is read
    for name in [n for n in os.environ if n.startswith("CV_")]:
        monkeypatch.delenv(name)
    env = _marked(tmp_path)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return env


def _set(monkeypatch: pytest.MonkeyPatch, **env: str | None) -> None:
    for name, value in env.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def test_settings_marked_baseline_loads_with_every_text_setting_marked(
    marked_env: dict[str, str],
) -> None:
    """The fixture is sound: every marked value validates, so each refusal below is its own."""
    settings = Settings()
    assert settings.bybit_api_key is not None
    assert _MARKER in settings.bybit_api_key.get_secret_value()
    assert settings.liquidity_pinned_symbols == (_MARKER,)


def test_settings_every_text_setting_is_marked_or_named_unmarkable() -> None:
    """A new text setting is covered by the marker sweep unless it is named here."""
    assert _UNMARKABLE <= set(_text_fields())
    assert "bybit_api_key" in _text_fields() and "pg_dsn" in _text_fields()


#: (id, env that triggers the refusal, the field it reports, a sentence of its message).
_REFUSALS = [
    pytest.param(
        {"CV_LIQUIDITY_BANDS_TICKS": "[10, 5]"},
        "liquidity_bands_ticks",
        "CV_LIQUIDITY_BANDS_TICKS must be distinct, positive and ascending",
        id="liquidity-bands",
    ),
    pytest.param(
        {"CV_LIQUIDITY_PINNED_SYMBOLS": '["BTCUSDT", "BTCUSDT"]'},
        "liquidity_pinned_symbols",
        "CV_LIQUIDITY_PINNED_SYMBOLS must not repeat a symbol",
        id="liquidity-pins-repeat",
    ),
    pytest.param(
        {"CV_LIQUIDITY_PINNED_SYMBOLS": f'["{_MARKER}", "ETHUSDT"]', "CV_LIQUIDITY_PIN_MAX": "1"},
        "liquidity_pin_max",
        "CV_LIQUIDITY_PINNED_SYMBOLS holds 2 symbols; CV_LIQUIDITY_PIN_MAX is 1",
        id="liquidity-pin-cap",
    ),
    pytest.param(
        {"CV_ENVIRONMENT": "demo", "CV_ALLOW_SHARED_VOLUME": "true"},
        "allow_shared_volume",
        "CV_ALLOW_SHARED_VOLUME is refused when CV_ENVIRONMENT is live or demo",
        id="shared-volume",
    ),
    pytest.param(
        {"CV_ENVIRONMENT": "live", "CV_KEK_SOURCE": "file"},
        "kek_source",
        "kek_source_not_permitted: CV_KEK_SOURCE=file is refused in live",
        id="file-kek-on-live",
    ),
    pytest.param(
        {"CV_ENVIRONMENT": "live", "CV_STORAGE_BACKEND": "real", "CV_QUESTDB_PG_PASSWORD": "quest"},
        "storage_backend",
        "CV_QUESTDB_PG_PASSWORD must be set to a non-default value",
        id="questdb-dev-password-on-live",
    ),
    pytest.param(
        {"CV_REPLAY_READAHEAD_BYTES": "67108864", "CV_REPLAY_MEMORY_CEILING_BYTES": "67108864"},
        "replay_memory_ceiling_bytes",
        "CV_REPLAY_MEMORY_CEILING_BYTES must exceed CV_REPLAY_READAHEAD_BYTES",
        id="replay-ceiling",
    ),
    pytest.param(
        {"CV_RECORDER_WAL_DIR": "relative/recorder-wal"},
        "recorder_wal_dir",
        "CV_RECORDER_WAL_DIR must be an absolute path",
        id="recorder-wal-dir",
    ),
    pytest.param(
        {"CV_RECORDER_WAL_DIR": "/srv/outside-the-data-dir"},
        "recorder_wal_dir",
        "CV_RECORDER_WAL_DIR must be inside the data dir (the parent of CV_PARQUET_ROOT)",
        id="recorder-wal-dir-outside",
    ),
    pytest.param(
        {"CV_BARS_STATE_ROOT": "relative/bars"},
        "bars_state_root",
        "CV_BARS_STATE_ROOT must be an absolute path",
        id="bars-state-root",
    ),
    pytest.param(
        {"CV_MESH_TRUSTED_PROXY_ADDRESS": "10.0.0.1"},
        "mesh_trusted_proxy_address",
        "CV_MESH_TRUSTED_PROXY_HEADER and CV_MESH_TRUSTED_PROXY_ADDRESS must be set together",
        id="trusted-proxy-pair",
    ),
    pytest.param(
        {"CV_FEED": "live", "CV_BYBIT_API_KEY": None},
        "feed",
        "CV_FEED=live requires CV_BYBIT_API_KEY and CV_BYBIT_API_SECRET to be set",
        id="feed-live-half-configured",
    ),
]  # fmt: skip


def _renderings(error: ValidationError) -> dict[str, str]:
    return {
        "str": str(error),
        "repr": repr(error),
        "errors": repr(error.errors()),
        "errors-with-input": repr(error.errors(include_input=True)),
        "json": error.json(),
    }


@pytest.mark.parametrize(("trigger", "field", "message"), _REFUSALS)
def test_settings_refusal_reports_only_the_offending_field(
    monkeypatch: pytest.MonkeyPatch,
    marked_env: dict[str, str],
    trigger: dict[str, str | None],
    field: str,
    message: str,
) -> None:
    _set(monkeypatch, **trigger)
    with pytest.raises(ValidationError) as refused:
        Settings()

    error = refused.value
    for rendering, text in _renderings(error).items():
        assert _MARKER not in text, rendering
    assert message in str(error)
    [detail] = error.errors()
    assert detail["loc"] == (field,)
    assert not isinstance(detail["input"], dict)


@pytest.mark.parametrize(("trigger", "field", "message"), _REFUSALS)
def test_load_settings_refusal_carries_messages_only(
    monkeypatch: pytest.MonkeyPatch,
    marked_env: dict[str, str],
    trigger: dict[str, str | None],
    field: str,
    message: str,
) -> None:
    _set(monkeypatch, **trigger)
    with pytest.raises(SettingsRefusedError) as refused:
        load_settings()

    error = refused.value
    assert message in str(error) and field in str(error)
    assert _MARKER not in str(error) + repr(error) + repr(error.args)
    assert error.__context__ is None and error.__cause__ is None


def test_refusal_messages_name_the_field_and_message_without_inputs(
    monkeypatch: pytest.MonkeyPatch, marked_env: dict[str, str]
) -> None:
    _set(monkeypatch, CV_ENVIRONMENT="live", CV_KEK_SOURCE="file")
    with pytest.raises(ValidationError) as refused:
        Settings()
    assert refusal_messages(refused.value) == [
        "kek_source: Value error, kek_source_not_permitted: CV_KEK_SOURCE=file is refused in live"
    ]


def test_load_settings_returns_the_settings_when_nothing_refuses(
    marked_env: dict[str, str],
) -> None:
    assert isinstance(load_settings(), Settings)


@pytest.mark.parametrize(
    ("main", "argv", "prog"),
    [
        pytest.param(breakglass.main, ["--owner", "alice"], "break-glass", id="breakglass"),
        pytest.param(
            bootstrap_owner.main, ["--owner", "owner@example.test"], "bootstrap-owner", id="owner"
        ),
    ],
)
def test_cli_settings_refusal_reports_messages_only_and_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    marked_env: dict[str, str],
    main: Callable[[Sequence[str] | None], int],
    argv: list[str],
    prog: str,
) -> None:
    _set(monkeypatch, CV_ENVIRONMENT="live", CV_KEK_SOURCE="file")
    assert main(argv) == breakglass.EXIT_INVALID

    captured = capsys.readouterr()
    assert captured.err.startswith(f"{prog}: invalid settings (ValidationError); nothing ran\n")
    assert "  kek_source: Value error, kek_source_not_permitted" in captured.err
    assert _MARKER not in captured.err + captured.out


_NO_USER = "~nosuchuser5303"


def test_load_settings_unknown_user_home_is_a_message_only_refusal(
    monkeypatch: pytest.MonkeyPatch, marked_env: dict[str, str]
) -> None:
    _set(monkeypatch, CV_PARQUET_ROOT=f"{_NO_USER}/{_MARKER}/parquet", CV_BACKUP_ROOT=None)
    with pytest.raises(SettingsRefusedError) as refused:
        load_settings()

    error = refused.value
    text = str(error) + repr(error) + repr(error.args)
    assert str(error) == UNKNOWN_HOME_REFUSAL
    assert "nosuchuser5303" not in text and _MARKER not in text
    assert error.__context__ is None and error.__cause__ is None


@pytest.mark.parametrize(
    ("main", "argv", "prog"),
    [
        pytest.param(breakglass.main, ["--owner", "alice"], "break-glass", id="breakglass"),
        pytest.param(
            bootstrap_owner.main, ["--owner", "owner@example.test"], "bootstrap-owner", id="owner"
        ),
    ],
)
def test_cli_unknown_user_home_reports_a_message_only_and_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    marked_env: dict[str, str],
    main: Callable[[Sequence[str] | None], int],
    argv: list[str],
    prog: str,
) -> None:
    _set(monkeypatch, CV_PARQUET_ROOT=f"{_NO_USER}/{_MARKER}/parquet", CV_BACKUP_ROOT=None)
    assert main(argv) == breakglass.EXIT_INVALID

    captured = capsys.readouterr()
    assert captured.err == f"{prog}: {UNKNOWN_HOME_REFUSAL}; nothing ran\n"
    assert "nosuchuser5303" not in captured.err + captured.out


def test_migrate_command_refuses_a_setting_with_messages_only(
    monkeypatch: pytest.MonkeyPatch, marked_env: dict[str, str]
) -> None:
    from candleviewer.storage import migrate

    _set(monkeypatch, CV_ENVIRONMENT="live", CV_KEK_SOURCE="file")
    with pytest.raises(SettingsRefusedError) as refused:
        migrate.main([])
    assert _MARKER not in str(refused.value) + repr(refused.value.args)


def test_lane_release_command_refuses_a_setting_with_its_class_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    marked_env: dict[str, str],
) -> None:
    from candleviewer.admin import lane_release

    _set(monkeypatch, CV_ENVIRONMENT="live", CV_KEK_SOURCE="file")
    argv = ["--hold", "1:0", "--operator", "o", "--ticket", "t", "--operator-reason", "r"]
    assert lane_release.main(argv) == lane_release.ReleaseExit.LANE_UNAVAILABLE
    out = capsys.readouterr()
    assert "unusable lane (SettingsRefusedError)" in out.out
    assert _MARKER not in out.out + out.err
