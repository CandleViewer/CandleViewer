"""E26-T01 replay settings (`CV_REPLAY_*`): the ticket's defaults and the validated bounds."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from candleviewer.settings import Settings


def _settings(**overrides: float) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg, arg-type]  # pydantic-settings kwarg


def test_replay_settings_default_to_the_ticket_values() -> None:
    s = _settings()
    assert (s.replay_idle_ttl_s, s.replay_reclaim_interval_s) == (7200.0, 60.0)
    assert (s.replay_max_sessions_per_user, s.replay_max_window_hours) == (2, 24)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("replay_idle_ttl_s", 59), ("replay_idle_ttl_s", 86_401),
        ("replay_reclaim_interval_s", 0.5), ("replay_reclaim_interval_s", 3_601),
        ("replay_max_sessions_per_user", 0), ("replay_max_sessions_per_user", 17),
        ("replay_max_window_hours", 0), ("replay_max_window_hours", 24 * 31 + 1),
    ],
)  # fmt: skip
def test_replay_settings_outside_their_bounds_are_refused(name: str, value: float) -> None:
    with pytest.raises(ValidationError):
        _settings(**{name: value})
