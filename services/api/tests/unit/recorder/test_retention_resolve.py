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


def test_resolve_no_policy_row_uses_section7_stream_default_not_30d() -> None:
    """Review H1: pinned -> symbol -> default -> §7 per-stream default -> hard default."""
    p = resolve_policy("ETHUSDT", "trades", pinned=False, policies={}, elevated=False)
    assert (p.source, p.hot_days, p.total_days) == ("stream_default", 30, 730)
    assert HARD_DEFAULT_DAYS == 30


@pytest.mark.parametrize(
    ("stream", "hot", "total"),
    [
        ("trades", 30, 730),
        ("orderbook_delta", 7, 730),
        ("orderbook_snapshot", 30, 730),
        ("tickers", 30, 730),
        ("klines", 90, None),
        ("liquidations", 90, None),
        ("open_interest", 90, None),
        ("funding_rates", 365, None),
        ("bars", 90, 730),
        ("footprint_cells", 30, 365),
        ("profiles", 90, 730),
        ("orderflow_metrics", 90, 730),
        ("heatmap_cells", 7, 90),
    ],
)
def test_resolve_every_stream_without_rows_matches_section7(
    stream: str, hot: int, total: int | None
) -> None:
    p = resolve_policy("BTCUSDT", stream, pinned=False, policies={}, elevated=False)
    assert (p.hot_days, p.total_days, p.source) == (hot, total, "stream_default")


def test_resolve_unknown_stream_keeps_forever() -> None:
    p = resolve_policy("BTCUSDT", "engine_metrics_v9", pinned=False, policies={}, elevated=False)
    assert (p.hot_days, p.total_days, p.source) == (None, None, "unknown_stream")


def test_stream_defaults_equal_the_repo_seed() -> None:
    """The in-package table (review H3) must equal `backend/db/seeds/retention_defaults.yaml`."""
    from pathlib import Path

    from candleviewer.recorder.retention_defaults import STREAM_DEFAULTS
    from candleviewer.storage.retention.policy import load_defaults

    seed = Path(__file__).resolve().parents[5] / "backend/db/seeds/retention_defaults.yaml"
    assert {r.stream.value: (r.hot_days, r.cold_days) for r in load_defaults(seed)} == dict(
        STREAM_DEFAULTS
    )


def test_stream_defaults_load_from_the_package_not_the_repo() -> None:
    """Review H3: importable from the installed package with no repo path or file read."""
    import importlib

    mod = importlib.import_module("candleviewer.recorder.retention_defaults")
    assert mod.STREAM_DEFAULTS["funding_rates"] == (365, None)
    assert mod.canonical_stream("funding") == "funding_rates"
    assert mod.__file__ is not None and "backend" not in mod.__file__


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
    validate_policies({(None, "bars"): PolicyRow(None, "bars", 1, 730)})  # == §7 trades
    with pytest.raises(InvalidRetentionPolicy):  # no trades row: §7 trades default applies
        validate_policies({(None, "bars"): PolicyRow(None, "bars", 1, None)})


DFLT_BARS = PolicyRow(None, "bars", 90, 730)
