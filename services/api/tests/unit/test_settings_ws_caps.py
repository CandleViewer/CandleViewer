"""#415 (E17-R-25): the WS settings that size a per-frame or per-user bound may be lowered, never
raised past the protocol's values (E17 threat model §6: a raise needs a security review).
`settings.py` may not import `ws`, so it spells the values out; this pins them to `ws.limits` and
`ws.lifecycle`, and the largest frame cap it accepts to the server's transport cap, so that the
gateway, not the transport alone, answers a frame past the configured cap (23 §4.4)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.settings import Settings
from candleviewer.ws.lifecycle import MAX_AUTHS_PER_USER_PER_MIN, MAX_CONNECTIONS_PER_USER
from candleviewer.ws.limits import (
    MAX_DEEP_BOOK_SUBSCRIPTIONS,
    MAX_INBOUND_FRAME_BYTES,
    SERVER_WS_MAX_SIZE,
)

#: Each capped setting and the protocol value it may not pass.
_CEILING = {
    "ws_max_inbound_frame_bytes": MAX_INBOUND_FRAME_BYTES,
    "ws_max_connections_per_user": MAX_CONNECTIONS_PER_USER,
    "ws_max_auths_per_user_per_min": MAX_AUTHS_PER_USER_PER_MIN,
    # E21-T01 (BQ-2): the deep-book cap, the deep book's DoS control.
    "ws_max_deep_book_subs": MAX_DEEP_BOOK_SUBSCRIPTIONS,
}


def _env(field: str) -> str:
    return f"CV_{field.upper()}"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for field in _CEILING:
        monkeypatch.delenv(_env(field), raising=False)


def _largest(field: str) -> Any:
    """The `le` bound `Settings` declares for `field`."""
    return next(m.le for m in Settings.model_fields[field].metadata if hasattr(m, "le"))


@pytest.mark.parametrize("field", sorted(_CEILING))
def test_a_capped_setting_defaults_to_its_protocol_value_and_may_be_lowered(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    assert (getattr(Settings(), field), _largest(field)) == (_CEILING[field], _CEILING[field])
    monkeypatch.setenv(_env(field), str(_CEILING[field] - 1))
    assert getattr(Settings(), field) == _CEILING[field] - 1


@pytest.mark.parametrize("field", sorted(_CEILING))
def test_a_capped_setting_one_past_its_protocol_value_is_refused(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    monkeypatch.setenv(_env(field), str(_CEILING[field] + 1))
    with pytest.raises(ValidationError) as refused:
        Settings()
    assert field in str(refused.value)


def test_the_largest_frame_cap_accepted_stays_under_the_servers_transport_cap() -> None:
    """A frame past the configured cap gets the gateway's `bye` before `1009`, whatever the
    setting (23 §4.4): the transport cap, from the protocol constant, is above every value the
    setting accepts."""
    assert _largest("ws_max_inbound_frame_bytes") < SERVER_WS_MAX_SIZE
