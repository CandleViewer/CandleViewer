"""E27-T04 (US-ACCT-005): the `CV_KEY_ROTATION_POLICY_DAYS` and `CV_KEY_ROTATION_WARN_DAYS` days.

`Settings` bounds the policy at 2 to 365 days and the warning window at 1 to 364, so that no value
switches the reminder off (C-4.14), and refuses a pair whose warning window does not end inside its
policy. The order check is a field validator on the second setting, so a refusal never carries
another setting (C-12.6, #2728). No network, no sleeps.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.settings import Settings

#: An inert marker standing in for a secret value; never a credential.
_MARKER = "cv-837-marker-not-a-secret"
_ORDER = "CV_KEY_ROTATION_WARN_DAYS must be less than CV_KEY_ROTATION_POLICY_DAYS"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CV_KEY_ROTATION_POLICY_DAYS", "CV_KEY_ROTATION_WARN_DAYS"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    "bad",
    [
        {"key_rotation_policy_days": 366},
        {"key_rotation_policy_days": 1},
        {"key_rotation_warn_days": 0},
        {"key_rotation_warn_days": 365},
    ],
)
def test_no_rotation_setting_switches_the_reminder_off(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Settings(**bad)


@pytest.mark.parametrize(
    "pair",
    [
        {"key_rotation_policy_days": 14, "key_rotation_warn_days": 14},
        {"key_rotation_policy_days": 2, "key_rotation_warn_days": 14},
        {"key_rotation_policy_days": 90, "key_rotation_warn_days": 364},
        {"key_rotation_policy_days": 10},
    ],
    ids=["equal", "inverted", "widest-warning", "below-the-default-warning"],
)
def test_settings_reject_a_warning_window_not_inside_the_policy(pair: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match=_ORDER):
        Settings(**pair)


def test_an_invalid_policy_reports_its_own_error_and_not_the_order() -> None:
    """The order check needs a valid policy: one whose own check failed is absent from the
    validator's `info.data`, so only its error is reported."""
    with pytest.raises(ValidationError) as refused:
        Settings(key_rotation_policy_days=1, key_rotation_warn_days=14)

    assert [e["loc"] for e in refused.value.errors()] == [("key_rotation_policy_days",)]


@pytest.mark.parametrize(
    "refused",
    [
        {"CV_KEY_ROTATION_POLICY_DAYS": "14", "CV_KEY_ROTATION_WARN_DAYS": "14"},
        {"CV_KEY_ROTATION_POLICY_DAYS": "2", "CV_KEY_ROTATION_WARN_DAYS": "14"},
    ],
    ids=["equal", "inverted"],
)
def test_a_refused_rotation_pair_never_echoes_another_setting(
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
    assert [e["input"] for e in err.value.errors()] == [refused["CV_KEY_ROTATION_WARN_DAYS"]]
