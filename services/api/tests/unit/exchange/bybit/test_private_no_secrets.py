"""#3963 scenario "Nothing secret leaves the adapter" (SR-E29-08, C-2.7, C-12.6; 24 §14.2 rule 13).

A Hypothesis run seeds the stream's own key id and `auth` signature, and the `auth` frame they
make, where a venue or a socket could echo them: the `auth` reply's text and connection id (a
grant and three refusals), the subscribe acknowledgements, the pongs, a pushed row's fields
known and unknown, a dropped socket's error and a failed dial's. None of it may reach an item
the stream yields, an exception it raises (its text, chain or traceback), a structlog event, a
stdlib log record (the `websockets` and `xstate_statemachine` loggers at DEBUG included) or the
metric exposition. The stream masks its own values in every frame before reading it, as the REST
client masks its answers, and raises bare fixed texts only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from prometheus_client import REGISTRY, generate_latest
from structlog.testing import capture_logs

from candleviewer.exchange.base.models import PrivateEvent
from tests._signing import Call, fake_capability, stand_in_signature
from tests.chaos.ingestion._clock import VirtualClock
from tests.unit.exchange.bybit._private import frame, push, raw, row
from tests.unit.exchange.bybit._private_venue import (
    Consumer,
    PrivateVenue,
    VenueSocket,
    make_streams,
)
from tests.unit.exchange.bybit._trading import account

_KEY_IDS = st.text(
    alphabet="ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789", min_size=18, max_size=36
)
_WHERE = st.sampled_from(
    ["auth-reply", "refused-auth", "subscribe-reply", "pong", "push-fields", "socket-error"]
)


class _Echo(PrivateVenue):
    """A venue that echoes the `auth` frame's key id and signature in one place (`where`)."""

    where: str = ""
    seeded: str = ""

    def answer(self, sock: VenueSocket, message: dict[str, Any]) -> None:
        op = message.get("op")
        if op == "auth":
            key, _, signature = message["args"]
            self.seeded = f"seen {key} and {signature} in {json.dumps(message)}"
            if self.where == "auth-reply":
                sock.push(_reply("auth-ok", ret_msg=self.seeded, conn_id=signature))
                return
            if self.where == "refused-auth":
                sock.push(_reply("auth-ok", success=False, ret_msg=self.seeded, conn_id=key))
                return
        if op == "subscribe" and self.where == "subscribe-reply":
            sock.push(_reply("subscribe-ok", ret_msg=self.seeded, conn_id=self.seeded))
            return
        if op == "ping" and self.where == "pong":
            sock.push(_reply("pong", req_id=self.seeded, args=[self.seeded]))
            return
        super().answer(sock, message)


def _reply(name: str, **fields: Any) -> str:
    return json.dumps(frame(name) | fields)


def _seeded_push(seeded: str, key: str, signature: str) -> str:
    """A fill whose ids are our own key id and signature, and an unknown field the whole echo."""
    echoed = row("execution") | {"orderLinkId": key, "execId": signature, "echo": seeded}
    return push("execution.linear", echoed)


def _texts(error: BaseException) -> list[str]:
    out = ["".join(traceback.format_exception(error)), repr(error), str(error)]
    chained: BaseException | None = error
    while chained is not None:
        out.append(repr(chained))
        chained = chained.__cause__ or chained.__context__
    return out


async def _run(key_id: str, where: str, calls: list[Call]) -> list[str]:
    """Everything the stream yields or raises in a minute of virtual time, as text."""
    clock = VirtualClock()
    venue = _Echo(clock)
    venue.where = where
    streams = make_streams(venue, credentials=fake_capability(key_id, calls))
    consumer = Consumer(await streams.open(account(), clock_offset_ms=lambda: 0))
    await clock.advance(1)
    if where == "push-fields":
        venue.socket.push(_seeded_push(venue.seeded, key_id, stand_in_signature(calls[-1][1])))
    elif where == "socket-error":
        venue.socket.drop_text = venue.seeded  # the failed read carries the echo
        venue.socket.drop()
    await clock.advance(60)
    out = [item.model_dump_json() for item in consumer.items]
    out += [repr(item) for item in consumer.items]
    try:
        await streams.open(account(), clock_offset_ms=lambda: 0)  # refused: still open, or marked
    except Exception as refused:  # every refusal's text is checked below
        out += _texts(refused)
    await consumer.stop()
    await streams.aclose()
    return out


@settings(
    max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(key_id=_KEY_IDS, where=_WHERE)
def test_no_seeded_credential_reaches_an_item_an_error_a_log_or_a_metric(
    key_id: str, where: str, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[Call] = []
    caplog.clear()
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="xstate_statemachine")
    caplog.set_level(logging.DEBUG, logger="websockets")
    with capture_logs() as logs:
        texts = asyncio.run(_run(key_id, where, calls))
    texts += [json.dumps(logs, default=str), caplog.text, generate_latest(REGISTRY).decode()]
    signatures = {stand_in_signature(message) for _, message, _ in calls}
    assert calls, where  # an `auth` was signed and sent
    for secret in (key_id, *signatures):
        assert all(secret not in text for text in texts), where


async def test_a_masked_echo_still_reads_as_the_row_it_is() -> None:
    """The mask replaces only our own values: the fill is delivered, its ids masked."""
    calls: list[Call] = []
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue, credentials=fake_capability("fixture-key-id-0123", calls))
    consumer = Consumer(await streams.open(account()))
    await clock.advance(1)
    signature = stand_in_signature(calls[-1][1])
    venue.socket.push(_seeded_push("x", "fixture-key-id-0123", signature), raw("pong"))
    await clock.advance(1)
    [event] = [i for i in consumer.items if isinstance(i, PrivateEvent)]
    shown = event.model_dump_json()
    assert "fixture-key-id-0123" not in shown and signature not in shown
    assert "**redacted**" in shown
    await consumer.stop()
    await streams.aclose()
