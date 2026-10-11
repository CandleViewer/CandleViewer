from __future__ import annotations

import pytest

from candleviewer.recorder.retention import (
    HARD_DEFAULT_DAYS,
    PolicyRow,
    RetentionStepUpRequired,
    resolve_policy,
)

SYM = PolicyRow("BTCUSDT", "trades", 7, 90)
SYM_PIN = PolicyRow("BTCUSDT", "trades", 7, 90, applies_to_pinned=True)
DFLT = PolicyRow(None, "trades", 3, 60)


def test_resolve_pinned_without_override_is_infinite() -> None:
    p = resolve_policy(
        "BTCUSDT", "trades", pinned=True, policies={("BTCUSDT", "trades"): SYM}, elevated=False
    )
    assert p.source == "pinned" and p.total_days is None


def test_resolve_symbol_policy_wins_over_default() -> None:
    pol = {("BTCUSDT", "trades"): SYM, (None, "trades"): DFLT}
    p = resolve_policy("BTCUSDT", "trades", pinned=False, policies=pol, elevated=False)
    assert (p.source, p.total_days) == ("symbol", 90)


def test_resolve_default_policy_when_no_symbol_policy() -> None:
    p = resolve_policy(
        "ETHUSDT", "trades", pinned=False, policies={(None, "trades"): DFLT}, elevated=False
    )
    assert (p.source, p.total_days) == ("default", 60)


def test_resolve_hard_default_30d() -> None:
    p = resolve_policy("ETHUSDT", "trades", pinned=False, policies={}, elevated=False)
    assert (p.source, p.total_days) == ("hard_default", HARD_DEFAULT_DAYS)


def test_resolve_applies_to_pinned_without_step_up_raises() -> None:
    with pytest.raises(RetentionStepUpRequired):
        resolve_policy(
            "BTCUSDT",
            "trades",
            pinned=True,
            policies={("BTCUSDT", "trades"): SYM_PIN},
            elevated=False,
        )


def test_resolve_applies_to_pinned_with_step_up_uses_policy() -> None:
    p = resolve_policy(
        "BTCUSDT", "trades", pinned=True, policies={("BTCUSDT", "trades"): SYM_PIN}, elevated=True
    )
    assert (p.source, p.total_days) == ("symbol", 90)


def test_validator_rejects_bars_outliving_trades() -> None:
    from candleviewer.recorder.retention import InvalidRetentionPolicy, validate_policies

    ok = {(None, "trades"): PolicyRow(None, "trades", 30, 730), (None, "bars"): DFLT_BARS}
    validate_policies(ok)
    for bad_days in (731, None):
        bad = ok | {("BTCUSDT", "bars"): PolicyRow("BTCUSDT", "bars", 30, bad_days)}
        with pytest.raises(InvalidRetentionPolicy):
            validate_policies(bad)
    validate_policies({(None, "bars"): PolicyRow(None, "bars", 1, None)})  # no trades row


DFLT_BARS = PolicyRow(None, "bars", 90, 730)
