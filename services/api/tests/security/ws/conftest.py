"""Fixtures for the E17-X02 WS abuse suite (#415). The contract suite's `wire` fixture is
directory-scoped (`tests/contract/ws/conftest.py`), so it is declared again here."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from structlog.contextvars import merge_contextvars
from structlog.processors import format_exc_info
from structlog.testing import capture_logs

from candleviewer.ws.backpressure_config import BackpressureConfig
from tests.contract.ws._harness import OFFERS, reset_wire, use_wire
from tests.security.ws._raw import RawWorld


@pytest.fixture(params=list(OFFERS))
def wire(request: pytest.FixtureRequest) -> Iterator[str]:
    """The wire (an `OFFERS` key) a test's sockets speak: each test with a `world` runs under both
    subprotocols, `cv.v1.json` and `cv.v1.msgpack` preferred (§2.2)."""
    name = str(request.param)
    token = use_wire(name)
    try:
        yield name
    finally:
        reset_wire(token)


@pytest.fixture
def flag() -> BackpressureConfig:
    """The outbound budget the gateway runs with: the default `BackpressureConfig` (§8.4; #2409:
    the flag-off rows went). A test that parametrizes `flag` itself overrides this."""
    return BackpressureConfig()


@pytest.fixture
def world(
    wire: str,
    flag: BackpressureConfig,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> Iterator[RawWorld]:
    """A `RawWorld` with its client running and the sinks a token must stay out of captured: the
    gateway's log events as production's chain builds them (bound context merged in, an exception
    rendered into the event as `format_exc_info` does), stdlib logging, stdout and stderr."""
    caplog.set_level(logging.DEBUG)
    w = RawWorld(caplog, capsys, flag)
    with capture_logs(processors=[merge_contextvars, format_exc_info]) as events, w.client:
        w.events = events
        yield w
