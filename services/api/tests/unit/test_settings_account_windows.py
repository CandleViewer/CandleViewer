"""E27-T04 (US-ACCT-010): the `CV_ACCOUNT_HEARTBEAT_S` and `CV_ACCOUNT_DOWN_S` windows.

`Settings` bounds the heartbeat window at 10 s and the down window at 30 s, the limits of
US-ACCT-010 that no value may move (C-4.14), and refuses a pair whose heartbeat window does not
end inside its down window. The order check is a field validator on the second window, so a
refusal never carries another setting (C-12.6, #2728). No network, no sleeps.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.settings import Settings

#: An inert marker standing in for a secret value; never a credential.
_MARKER = "cv-837-marker-not-a-secret"
_ORDER = "CV_ACCOUNT_HEARTBEAT_S must be less than CV_ACCOUNT_DOWN_S"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CV_ACCOUNT_HEARTBEAT_S", "CV_ACCOUNT_DOWN_S"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    "bad",
    [
        {"account_heartbeat_s": 10.001},
        {"account_down_s": 30.001},
        {"account_heartbeat_s": 0},
        {"account_down_s": 0},
    ],
)
def test_health_windows_cannot_exceed_the_us_acct_010_nfr(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Settings(**bad)


@pytest.mark.parametrize(
    "pair",
    [
        {"account_heartbeat_s": 10, "account_down_s": 10},
        {"account_heartbeat_s": 10, "account_down_s": 5},
        {"account_heartbeat_s": 2.5, "account_down_s": 2},
        {"account_down_s": 5},
    ],
    ids=["equal", "inverted", "fractional", "below-the-default-heartbeat"],
)
def test_settings_reject_a_heartbeat_window_not_inside_the_down_window(
    pair: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError, match=_ORDER):
        Settings(**pair)


def test_an_invalid_heartbeat_window_reports_its_own_error_and_not_the_order() -> None:
    """The order check needs a valid heartbeat window: one whose own check failed is absent from
    the validator's `info.data`, so only its error is reported."""
    with pytest.raises(ValidationError) as refused:
        Settings(account_heartbeat_s=11, account_down_s=5)

    assert [e["loc"] for e in refused.value.errors()] == [("account_heartbeat_s",)]


@pytest.mark.parametrize(
    "refused",
    [
        {"CV_ACCOUNT_DOWN_S": "5"},
        {"CV_ACCOUNT_HEARTBEAT_S": "10", "CV_ACCOUNT_DOWN_S": "10"},
    ],
    ids=["below-the-default-heartbeat", "equal"],
)
def test_a_refused_window_pair_never_echoes_another_setting(
    monkeypatch: pytest.MonkeyPatch, refused: dict[str, str]
) -> None:
    """C-12.6: the key reaches the process as an environment string, and a refusal must carry it
    in none of `str()`, `errors()` and `json()`. `hide_input_in_errors` covers `str()` only; a model
    validator's input is every setting, so the check is a field validator whose error's input is
    the one value it refuses (#2728, #2778)."""
    monkeypatch.setenv("CV_BYBIT_API_KEY", _MARKER)
    for name, value in refused.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match=_ORDER) as err:
        Settings()

    for rendered in (str(err.value), repr(err.value.errors()), err.value.json()):
        assert _MARKER[:12] not in rendered
    assert "input_value" not in str(err.value)
    assert [e["input"] for e in err.value.errors()] == [refused["CV_ACCOUNT_DOWN_S"]]
