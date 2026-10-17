"""E27-T04 (US-ACCT-005): the `CV_KEY_ROTATION_POLICY_DAYS` and `CV_KEY_ROTATION_WARN_DAYS` days.

`Settings` bounds the policy at 2 to 365 days and the warning window at 1 to 364, so that no value
switches the reminder off (C-4.14), and refuses a pair whose warning window does not end inside its
policy. The order check is a field validator on the second setting, so a refusal never carries
another setting (C-12.6, #2728). The day counts are no secret, so their field names
(`rotation_policy_days`, `rotation_warn_days`) stay clear of the redaction pattern: it names only
`SecretStr` fields. An alias keeps each documented variable, and the variable is also the keyword
`Settings(...)` takes. No network, no sleeps.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.settings import Settings

#: An inert marker standing in for a secret value; never a credential.
_MARKER = "cv-837-marker-not-a-secret"
_POLICY = "CV_KEY_ROTATION_POLICY_DAYS"
_WARN = "CV_KEY_ROTATION_WARN_DAYS"
_ORDER = "CV_KEY_ROTATION_WARN_DAYS must be less than CV_KEY_ROTATION_POLICY_DAYS"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (_POLICY, _WARN):
        monkeypatch.delenv(name, raising=False)


def test_the_defaults_are_ninety_days_and_a_fortnight_of_warning() -> None:
    settings = Settings()
    assert (settings.rotation_policy_days, settings.rotation_warn_days) == (90, 14)


def test_the_rotation_days_are_read_from_their_documented_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_POLICY, "180")
    monkeypatch.setenv(_WARN, "7")
    settings = Settings()
    assert (settings.rotation_policy_days, settings.rotation_warn_days) == (180, 7)


def test_the_rotation_days_are_not_read_from_their_own_field_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CV_ROTATION_POLICY_DAYS", "180")  # the field's own name: not a variable
    monkeypatch.setenv("CV_ROTATION_WARN_DAYS", "7")
    settings = Settings()
    assert (settings.rotation_policy_days, settings.rotation_warn_days) == (90, 14)


def test_the_rotation_days_are_shown_by_the_redacting_repr() -> None:
    """They hold no secret and their names no longer match the redaction pattern: not masked."""
    shown = repr(Settings(CV_KEY_ROTATION_POLICY_DAYS=180, CV_KEY_ROTATION_WARN_DAYS=7))
    assert "rotation_policy_days=180" in shown
    assert "rotation_warn_days=7" in shown


@pytest.mark.parametrize(
    ("name", "value", "bound"),
    [
        (_POLICY, 366, "less_than_equal"),
        (_POLICY, 1, "greater_than_equal"),
        (_WARN, 0, "greater_than_equal"),
        (_WARN, 365, "less_than_equal"),
    ],
)
def test_no_rotation_setting_switches_the_reminder_off(name: str, value: int, bound: str) -> None:
    """The refusal is the bound's, so the keyword must be the documented variable: an unknown
    keyword is refused too, and would pass this test for the wrong reason."""
    given: dict[str, Any] = {name: value}
    with pytest.raises(ValidationError) as refused:
        Settings(**given)

    assert [(e["loc"], e["type"]) for e in refused.value.errors()] == [((name,), bound)]


@pytest.mark.parametrize(
    "pair",
    [{_POLICY: 14, _WARN: 14}, {_POLICY: 2, _WARN: 14}, {_POLICY: 90, _WARN: 364}, {_POLICY: 10}],
    ids=["equal", "inverted", "widest-warning", "below-the-default-warning"],
)
def test_settings_reject_a_warning_window_not_inside_the_policy(pair: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match=_ORDER):
        Settings(**pair)


def test_an_invalid_policy_reports_its_own_error_and_not_the_order() -> None:
    """The order check needs a valid policy: one whose own check failed is absent from the
    validator's `info.data`, so only its error is reported."""
    with pytest.raises(ValidationError) as refused:
        Settings(CV_KEY_ROTATION_POLICY_DAYS=1, CV_KEY_ROTATION_WARN_DAYS=14)

    assert [e["loc"] for e in refused.value.errors()] == [(_POLICY,)]


@pytest.mark.parametrize(
    "refused",
    [{_POLICY: "14", _WARN: "14"}, {_POLICY: "2", _WARN: "14"}],
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
    assert [e["input"] for e in err.value.errors()] == [refused[_WARN]]
