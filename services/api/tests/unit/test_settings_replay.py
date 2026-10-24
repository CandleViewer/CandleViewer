"""Replay settings (`CV_REPLAY_*`; E26-T01, #2668 G1): the defaults and the validated bounds."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from candleviewer.replay.budget import MAX_BURST_S, MAX_SHARE, MIN_BURST_S, SHARE_ABOVE
from candleviewer.settings import Settings


def _settings(**overrides: float) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg, arg-type]  # pydantic-settings kwarg


def test_replay_settings_default_to_the_ticket_values() -> None:
    s = _settings()
    assert (s.replay_idle_ttl_s, s.replay_reclaim_interval_s) == (7200.0, 60.0)
    assert (s.replay_max_sessions_per_user, s.replay_max_window_hours) == (2, 24)
    assert (s.replay_loop_share, s.replay_loop_burst_ms) == (0.25, 50)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("replay_idle_ttl_s", 59), ("replay_idle_ttl_s", 86_401),
        ("replay_reclaim_interval_s", 0.5), ("replay_reclaim_interval_s", 3_601),
        ("replay_max_sessions_per_user", 0), ("replay_max_sessions_per_user", 17),
        ("replay_max_window_hours", 0), ("replay_max_window_hours", 24 * 31 + 1),
        ("replay_loop_share", 0.0), ("replay_loop_share", 0.5000001),
        ("replay_loop_burst_ms", 4), ("replay_loop_burst_ms", 251),
    ],
)  # fmt: skip
def test_replay_settings_outside_their_bounds_are_refused(name: str, value: float) -> None:
    with pytest.raises(ValidationError):
        _settings(**{name: value})


def test_the_replay_loop_budget_settings_take_their_bounds_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-4.14: the budget has no off value; its bounds themselves are accepted."""
    monkeypatch.setenv("CV_REPLAY_LOOP_SHARE", "1e-9")
    monkeypatch.setenv("CV_REPLAY_LOOP_BURST_MS", "250")
    s = _settings()
    assert (s.replay_loop_share, s.replay_loop_burst_ms) == (1e-9, 250)
    assert _settings(replay_loop_share=0.5, replay_loop_burst_ms=5).replay_loop_share == 0.5


def _bound(name: str, kind: str) -> float:
    return float(
        next(getattr(m, kind) for m in Settings.model_fields[name].metadata if hasattr(m, kind))
    )


def test_the_replay_loop_settings_bounds_are_the_budgets_own() -> None:
    """M1 may not import `replay`, so settings repeats the budget's bounds: they never drift. The
    share's lower bound is exclusive (`gt`) on both sides."""
    share = ("replay_loop_share", "gt"), ("replay_loop_share", "le")
    assert tuple(_bound(n, k) for n, k in share) == (SHARE_ABOVE, MAX_SHARE)
    burst = ("replay_loop_burst_ms", "ge"), ("replay_loop_burst_ms", "le")
    assert tuple(_bound(n, k) / 1000 for n, k in burst) == (MIN_BURST_S, MAX_BURST_S)
