"""Fixtures for the E17-X02 WS abuse suite (#415). The contract suite's `wire` fixture is
directory-scoped (`tests/contract/ws/conftest.py`), so it is declared again here."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from structlog.contextvars import merge_contextvars
from structlog.testing import capture_logs

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
def world(
    wire: str, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> Iterator[RawWorld]:
    """A `RawWorld` with its client running and the sinks a token must stay out of captured: the
    gateway's log events as production's chain builds them (bound context merged in), stdlib
    logging, stdout and stderr."""
    caplog.set_level(logging.DEBUG)
    w = RawWorld(caplog, capsys)
    with capture_logs(processors=[merge_contextvars]) as events, w.client:
        w.events = events
        yield w
