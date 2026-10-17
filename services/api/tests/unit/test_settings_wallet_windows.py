"""E27-T04 (US-ACCT-008): the `CV_WALLET_STALE_S` and `CV_WALLET_RECONCILE_S` windows. Two different
thresholds that must not be conflated: the display flag and the REST truth-check. `Settings` accepts
any positive pair whose stale flag comes first, at or under the defaults (10 s and 60 s): config may
tighten the windows, never loosen them (C-4.14). The order check is a field validator on the second
window, so a refusal never carries another setting (C-12.6, #2728). No network, no sleeps."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.settings import Settings

#: An inert marker standing in for a secret value; never a credential.
_MARKER = "cv-837-marker-not-a-secret"
_ORDER = "CV_WALLET_STALE_S must be less than CV_WALLET_RECONCILE_S"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CV_WALLET_STALE_S", "CV_WALLET_RECONCILE_S"):
        monkeypatch.delenv(name, raising=False)


def test_the_wallet_windows_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_WALLET_STALE_S", "5")
    monkeypatch.setenv("CV_WALLET_RECONCILE_S", "30")
    assert (Settings().wallet_stale_s, Settings().wallet_reconcile_s) == (5.0, 30.0)


@pytest.mark.parametrize("bad", [0, -1, float("inf"), float("nan")])
def test_a_wallet_window_must_be_positive_and_finite(bad: float) -> None:
    """Both invalid at once, so neither error can hide behind the order check."""
    with pytest.raises(ValidationError) as refused:
        Settings(wallet_stale_s=bad, wallet_reconcile_s=bad)

    locs = {e["loc"] for e in refused.value.errors()}
    assert locs == {("wallet_stale_s",), ("wallet_reconcile_s",)}


@pytest.mark.parametrize(
    "pair",
    [
        {"wallet_stale_s": 8, "wallet_reconcile_s": 8},
        {"wallet_stale_s": 8, "wallet_reconcile_s": 4},
        {"wallet_reconcile_s": 5},
    ],
    ids=["equal", "inverted", "below-the-default-stale"],
)
def test_settings_reject_a_stale_flag_not_before_the_reconcile_window(pair: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match=_ORDER):
        Settings(**pair)


def test_the_wallet_windows_may_equal_their_defaults() -> None:
    settings = Settings(wallet_stale_s=10, wallet_reconcile_s=60)
    assert (settings.wallet_stale_s, settings.wallet_reconcile_s) == (10.0, 60.0)


@pytest.mark.parametrize(
    "windows",
    [
        {"wallet_stale_s": 11},
        {"wallet_reconcile_s": 61},
        {"wallet_stale_s": 10_000, "wallet_reconcile_s": 60_000},
    ],
    ids=["stale-past-10-s", "reconcile-past-60-s", "milliseconds-for-seconds"],
)
def test_a_wallet_window_past_its_default_is_refused(windows: dict[str, Any]) -> None:
    """The defaults are the contract's windows (balances older than 10 s are stale; a truth-check
    after 60 s of silence), not tuning room. Milliseconds mistaken for seconds would hold a balance
    hours old fresh and let risk-based sizing run on it (C-4.14)."""
    with pytest.raises(ValidationError) as refused:
        Settings(**windows)

    assert {e["loc"] for e in refused.value.errors()} == {(name,) for name in windows}


def test_a_refused_wallet_pair_never_echoes_another_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-12.6: a key in the environment reaches none of `str()`, `errors()` and `json()` of the
    refusal, whose error's input is the one value it refuses (#2728, #2778)."""
    monkeypatch.setenv("CV_BYBIT_API_KEY", _MARKER)
    monkeypatch.setenv("CV_WALLET_RECONCILE_S", "5")

    with pytest.raises(ValidationError, match=_ORDER) as err:
        Settings()

    for rendered in (str(err.value), repr(err.value.errors()), err.value.json()):
        assert _MARKER[:12] not in rendered
    assert [e["input"] for e in err.value.errors()] == ["5"]
