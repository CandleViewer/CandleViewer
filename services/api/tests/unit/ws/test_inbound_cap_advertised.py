"""#572: `welcome.limits.max_inbound_frame_bytes` is the cap the gateway enforces. The
setting `CV_WS_MAX_INBOUND_FRAME_BYTES` may lower it and never raise it (23 section 4.3): the
gateway's cap is the contract value, and the transport closes a frame 4 KiB above it."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from candleviewer.settings import Settings
from candleviewer.ws.lifecycle import welcome_payload
from candleviewer.ws.limits import MAX_INBOUND_FRAME_BYTES

_ENV = "CV_WS_MAX_INBOUND_FRAME_BYTES"


def _welcome(**cap: int) -> dict[str, int]:
    welcome = welcome_payload(
        encoding="json",
        server_version="1.0.0",
        connection_id="ws_1",
        server_time_ms=1,
        client_clock_ms=None,
        features={},
        **cap,
    )
    limits: dict[str, int] = welcome["limits"]
    return limits


def test_welcome_advertises_the_contract_cap_by_default() -> None:
    assert _welcome()["max_inbound_frame_bytes"] == MAX_INBOUND_FRAME_BYTES == 262_144


def test_welcome_advertises_the_cap_the_gateway_was_given() -> None:
    limits = _welcome(max_inbound_frame_bytes=4096)
    assert limits["max_inbound_frame_bytes"] == 4096
    assert limits["max_subscriptions"] == _welcome()["max_subscriptions"]  # nothing else moves


@pytest.mark.parametrize("value", [1024, 65_536, MAX_INBOUND_FRAME_BYTES])
def test_the_setting_may_be_lowered_to_its_floor(
    monkeypatch: pytest.MonkeyPatch, value: int
) -> None:
    monkeypatch.setenv(_ENV, str(value))
    assert Settings().ws_max_inbound_frame_bytes == value


@pytest.mark.parametrize("value", [1023, MAX_INBOUND_FRAME_BYTES + 1, 1_048_576])
def test_the_setting_is_refused_above_the_contract_cap_and_below_its_floor(
    monkeypatch: pytest.MonkeyPatch, value: int
) -> None:
    monkeypatch.setenv(_ENV, str(value))
    with pytest.raises(ValidationError):
        Settings()


def test_the_setting_defaults_to_the_contract_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    assert Settings().ws_max_inbound_frame_bytes == MAX_INBOUND_FRAME_BYTES
