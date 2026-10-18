"""E27-T03 (#836 slice 2b5): the one-shot private-WS `auth` probe on an injected socket.

Replies: the documented-shape `tests/fixtures/key_verification/ws_auth_*.json` (README there; no
recorded capture exists, #2240). `Stream` stands in for the private stream and records every dial
and frame. Clocks are fakes; a hang ends at a bound cut to zero, never a sleep. No network.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import get_args
from uuid import UUID

import pytest
from prometheus_client import REGISTRY, generate_latest
from structlog.testing import capture_logs
from websockets.exceptions import ConnectionClosedError, InvalidHandshake

from candleviewer.exchange.bybit import key_ws_probe
from candleviewer.exchange.bybit.config import PRIVATE_WS_URLS
from candleviewer.exchange.bybit.key_info import PROBE_ERRORS
from candleviewer.exchange.bybit.key_ws_probe import KeyWsProbe, WsProbeError, WsProbeResult
from candleviewer.observability.logging import reset_logging
from candleviewer.secrets import CredentialBorrower, CredentialUnavailable, RequestSignature
from tests._signing import CREDENTIAL_ID, Call, fake_capability, stand_in_signature

ROOT = Path(__file__).resolve().parents[6]
FIXTURES = Path(__file__).parents[3] / "fixtures" / "key_verification"
OK, DENIED = (
    (FIXTURES / f"ws_auth_{n}.json").read_text(encoding="utf-8") for n in ("ok", "denied")
)
URLS = {
    "live": "wss://stream.bybit.com/v5/private",
    "demo": "wss://stream-demo.bybit.com/v5/private",
    "testnet": "wss://stream-testnet.bybit.com/v5/private",
}
#: The key id the fake M2 returns, a marker no output may show.
NOW_MS, MARK = 1_792_054_800_000, "cv-2b5-key-id-mark"


class Clock:
    """A monotonic clock that moves only when told."""

    now = 1000.0

    def __call__(self) -> float:
        return self.now


class Stream:
    """The private stream, its own socket: answers `auth` with `reply`, raises it, or never
    answers (None); `dial` fails the dial, `hang_dial` never completes it."""

    def __init__(
        self,
        reply: str | BaseException | None = OK,
        *,
        dial: BaseException | None = None,
        hang_dial: bool = False,
        clock: Clock | None = None,
    ) -> None:
        self.reply, self.dial, self.hang_dial, self.clock = reply, dial, hang_dial, clock
        self.dialled: list[str] = []
        self.sent: list[str] = []
        self.bounds: list[int] = []
        self.closes = 0
        self.waiting = asyncio.Event()

    async def connect(self, url: str) -> Stream:
        self.dialled.append(url)
        if self.hang_dial:
            await asyncio.Event().wait()
        if self.dial is not None:
            raise self.dial
        return self

    async def send(self, frame: str) -> None:
        self.sent.append(frame)

    async def recv(self, max_bytes: int) -> str:
        self.bounds.append(max_bytes)
        if self.clock is not None:
            self.clock.now += 0.118
        if self.reply is None:
            self.waiting.set()
            await asyncio.Event().wait()
        if isinstance(self.reply, BaseException):
            raise self.reply
        return str(self.reply)

    async def close(self) -> None:
        self.closes += 1


class BadClose(Stream):
    """A close that raises `error`, or stalls when there is none."""

    def __init__(self, error: BaseException | None) -> None:
        super().__init__()
        self.error = error

    async def close(self) -> None:
        self.closes += 1
        if self.error is not None:
            raise self.error
        await asyncio.Event().wait()


def probe_for(stream: Stream, clock: Clock | None = None) -> KeyWsProbe:
    return KeyWsProbe(stream.connect, monotonic=clock or Clock(), wall_ms=lambda: NOW_MS)


async def run(stream: Stream, env: str = "demo", calls: list[Call] | None = None) -> WsProbeResult:
    return await probe_for(stream).probe(fake_capability(MARK, calls), env, CREDENTIAL_ID)


@pytest.fixture
def bounds(monkeypatch: pytest.MonkeyPatch) -> list[float | None]:
    """The bound of each `timeout` the probe enters, each cut to zero: a hang ends at once."""
    seen: list[float | None] = []
    real = asyncio.timeout

    def cut(delay: float | None) -> asyncio.Timeout:
        seen.append(delay)
        return real(0)

    monkeypatch.setattr(key_ws_probe, "timeout", cut)
    return seen


@pytest.mark.parametrize("env", sorted(URLS))
async def test_each_environment_dials_its_own_private_stream_and_no_other(env: str) -> None:
    """US-ACCT-007 "No silent fallback" at unit level: a demo key never reaches a live host, a
    live key never a demo or testnet one, a testnet key neither."""
    stream = Stream()
    assert (await run(stream, env)).ok
    assert stream.dialled == [URLS[env]]


async def test_an_unknown_environment_is_refused_before_any_dial_or_signature() -> None:
    stream, calls = Stream(), list[Call]()
    with pytest.raises(ValueError, match="unknown environment"):
        await run(stream, "mainnet", calls)
    assert (stream.dialled, calls) == ([], [])


def test_the_hosts_are_the_architecture_tables_and_one_table_holds_them() -> None:
    doc = (ROOT / "docs/plan/20-architecture.md").read_text(encoding="utf-8")
    row = next(line for line in doc.splitlines() if line.startswith("| WS private"))
    assert re.findall(r"`(wss://[^`]+)`", row) == [URLS["live"], URLS["demo"], URLS["testnet"]]
    assert dict(PRIVATE_WS_URLS) == URLS


@pytest.mark.parametrize("skew", [None, -12_000, 3_000])
async def test_auth_is_signed_by_m2_with_expires_10_s_ahead_of_the_exchange_clock(
    skew: int | None,
) -> None:
    """SR-E27-17: M2 signs `GET/realtime` + `expires` under `sign_ws_auth`; `expires` is 10 s
    ahead of the exchange clock as measured (exchange minus host), of the host's when unmeasured."""
    stream, calls = Stream(), list[Call]()
    offset = None if skew is None else (lambda: skew or 0)
    probe = probe_for(stream)
    await probe.probe(fake_capability(MARK, calls), "demo", CREDENTIAL_ID, clock_offset_ms=offset)
    expires = NOW_MS + (skew or 0) + 10_000
    signed = b"GET/realtime" + str(expires).encode()
    assert calls == [(CREDENTIAL_ID, signed, "sign_ws_auth")]
    sent = [json.loads(frame) for frame in stream.sent]
    assert sent == [{"op": "auth", "args": [MARK, expires, stand_in_signature(signed)]}]


async def test_a_granted_auth_passes_with_its_latency_after_one_frame_then_closes() -> None:
    """One frame, the `auth` op: the probe never subscribes, so nothing streams."""
    clock = Clock()
    stream = Stream(clock=clock)
    result = await probe_for(stream, clock).probe(fake_capability(), "demo", CREDENTIAL_ID)
    assert result == WsProbeResult(ok=True, error=None, latency_ms=118)
    assert ([json.loads(frame)["op"] for frame in stream.sent], stream.closes) == (["auth"], 1)
    assert stream.bounds == [4096]  # one read, bounded


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (DENIED, "auth_error"),
        ("not json", "transport_error"),
        ("[" * 100_000 + "]" * 100_000, "transport_error"),
        ("[]", "exchange_unknown"),
        ('{"op": "pong", "success": true}', "exchange_unknown"),
        ('{"op": "auth", "success": "true"}', "exchange_unknown"),
    ],
    ids=["denied", "not-json", "too-deep", "not-an-object", "other-op", "success-not-bool"],
)
async def test_each_reply_is_its_key_probe_error_and_the_socket_is_closed(
    reply: str, error: WsProbeError
) -> None:
    """`too-deep` nests past the C decoder's recursion limit, a `RecursionError` and not a
    `ValueError`. How deep that is depends on the interpreter: 3.14 decodes 10,001 levels."""
    stream = Stream(reply)
    assert await run(stream) == WsProbeResult(ok=False, error=error, latency_ms=0)
    assert stream.closes == 1


def test_the_probe_names_only_key_probe_errors_of_the_contract() -> None:
    assert set(get_args(WsProbeError)) <= PROBE_ERRORS


@pytest.mark.parametrize(
    "make",
    [
        pytest.param(lambda: Stream(dial=ConnectionRefusedError("down")), id="unreachable"),
        pytest.param(lambda: Stream(dial=InvalidHandshake("upgrade refused")), id="handshake"),
        pytest.param(lambda: Stream(ConnectionResetError("reset")), id="reset"),
        pytest.param(lambda: Stream(ConnectionClosedError(None, None)), id="closed"),
    ],
)
async def test_an_unreachable_or_dropped_stream_fails_on_its_own_host_with_no_fallback(
    make: Callable[[], Stream],
) -> None:
    """AC "No silent fallback": `transport_error`, one dial of the demo host, no retry."""
    stream = make()
    assert await run(stream) == WsProbeResult(ok=False, error="transport_error", latency_ms=None)
    assert stream.dialled == [URLS["demo"]]
    assert stream.closes == (0 if stream.dial else 1)  # a socket that opened is closed


async def test_an_m2_refusal_propagates_once_the_socket_is_closed_and_nothing_was_sent() -> None:
    async def refuse(key_id: UUID, message: object, purpose: str) -> RequestSignature:
        raise CredentialUnavailable("credential_unavailable")

    stream = Stream()
    with pytest.raises(CredentialUnavailable):
        await probe_for(stream).probe(CredentialBorrower(refuse), "demo", CREDENTIAL_ID)
    assert (stream.sent, stream.closes) == ([], 1)


@pytest.mark.parametrize("hang", ["dial", "reply"])
async def test_no_answer_within_the_5_s_bound_is_a_timeout(
    bounds: list[float | None], hang: str
) -> None:
    stream = Stream(None, hang_dial=hang == "dial")
    assert await run(stream) == WsProbeResult(ok=False, error="timeout", latency_ms=None)
    opened = hang == "reply"
    assert (bounds, stream.closes) == ([5.0, 1.0] if opened else [5.0], int(opened))


async def test_a_cancelled_probe_closes_its_socket_and_the_cancellation_propagates() -> None:
    stream = Stream(None)
    task = asyncio.create_task(run(stream))
    await stream.waiting.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closes == 1


@pytest.mark.parametrize("error", [OSError("reset on close"), None], ids=["fails", "stalls"])
async def test_a_failing_or_stalled_close_keeps_the_verdict(
    bounds: list[float | None], error: OSError | None
) -> None:
    stream = BadClose(error)
    assert (await run(stream)).ok
    assert (stream.closes, bounds) == (1, [5.0, 1.0])


async def test_the_open_budget_is_10_per_5_minutes_then_refused_at_once_then_open_again() -> None:
    """SR-E27-05: every key and environment draws on one budget; the 11th probe within 300 s is
    refused at once (`rate_limited`), with no signature and no dial."""
    clock, stream, calls = Clock(), Stream(), list[Call]()
    probe, capability = probe_for(stream, clock), fake_capability(MARK, calls)

    async def once(i: int) -> WsProbeResult:
        return await probe.probe(capability, sorted(URLS)[i % 3], UUID(int=i))

    assert [(await once(i)).ok for i in range(10)] == [True] * 10
    clock.now += 299
    assert await once(10) == WsProbeResult(ok=False, error="rate_limited", latency_ms=None)
    assert (len(stream.dialled), len(calls)) == (10, 10)
    clock.now += 1  # 300 s after the first open
    assert (await once(11)).ok and len(stream.dialled) == 11


async def test_the_window_slides_so_no_300_s_ever_holds_more_than_10_opens() -> None:
    """SR-E27-05 against a fixed or tumbling window: one open at 0 s and nine at 299 s. At 300 s
    only the first has left the window, so one more opens and the next is refused, and the
    window stays full until 599 s, when the nine leave it."""
    clock, stream = Clock(), Stream()
    probe = probe_for(stream, clock)

    async def at(second: float) -> WsProbeError | None:
        clock.now = 1000.0 + second
        return (await probe.probe(fake_capability(), "demo", CREDENTIAL_ID)).error

    assert [await at(0)] + [await at(299) for _ in range(9)] == [None] * 10
    later = [await at(second) for second in (300, 300, 301, 598, 599)]
    assert later == [None, "rate_limited", "rate_limited", "rate_limited", None]


async def test_a_refused_unknown_environment_takes_no_open_from_the_budget() -> None:
    stream = Stream()
    probe = probe_for(stream)
    for _ in range(10):
        with pytest.raises(ValueError, match="unknown environment"):
            await probe.probe(fake_capability(), "mainnet", CREDENTIAL_ID)
    results = [await probe.probe(fake_capability(), "demo", CREDENTIAL_ID) for _ in range(10)]
    assert ([r.ok for r in results], len(stream.dialled)) == ([True] * 10, 10)


async def test_no_key_id_signature_or_exchange_text_reaches_a_log_repr_or_metric(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A denied `auth` and a transport error whose text names the exchange's: neither the key id,
    the signature nor that text shows in any result, log line or metric."""
    calls: list[Call] = []
    text = json.loads(DENIED)["ret_msg"]
    reset_logging()  # structlog's defaults: every level reaches the capture
    caplog.set_level(logging.DEBUG)
    with capture_logs() as logs:
        results = [await run(Stream(DENIED), calls=calls)]
        results.append(await run(Stream(ConnectionResetError(text)), calls=calls))
    shown = [*map(repr, results), repr(logs), caplog.text, generate_latest(REGISTRY).decode()]
    for secret in (MARK, text, *(stand_in_signature(signed) for _, signed, _ in calls)):
        assert [s for s in shown if secret in s] == []
    assert len(calls) == 2
