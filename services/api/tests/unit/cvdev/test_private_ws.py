"""#2893 S12: the private-WS fixture socket plays the pack's WS script (ADR-0036 decisions 6, 7).

The socket is built on a fixture transport, so both share one latch, gate, clock, key files and
request log. The pack is the checkout's; the log and key files sit under `tmp_path`. Time is a
fake the socket's injected `sleep` moves, which raises `Elapsed` past a horizon so a socket that
never answers ends the test. No socket opens and nothing sleeps.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import httpx
import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.bybit.config import PRIVATE_WS_URLS
from candleviewer.exchange.bybit.errors import FrameTooLarge
from candleviewer.exchange.bybit.key_ws_probe import KeyWsProbe
from candleviewer.exchange.bybit.private_stream import OPTIONAL_OPS, REQUIRED_OPS
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.secrets import CredentialBorrower, RequestSignature, Secret
from candleviewer.secrets.signing import check_message
from candleviewer.settings import Environment
from cvdev.account_fixture import guards
from cvdev.account_fixture.control import KEYS_DIR, KeyStates
from cvdev.account_fixture.pack import PrivateWs, Scenario, WsStep, payload
from cvdev.account_fixture.private_ws import PRIVATE_TOPICS, FixtureSocket, FixtureSockets
from cvdev.account_fixture.requestlog import FILE_NAME, RequestLog
from cvdev.account_fixture.transport import FixtureTransport
from tests._account_fixtures import PACK
from tests._signing import CREDENTIAL_ID, assemble
from tests.unit.cvdev.test_transport_guards import NON_FIXTURE_KEY, _get, _key, _of, _p0, _secret
from tests.unit.cvdev.test_transport_serving import KEY_IDS, WALLET
from tests.unit.exchange.bybit.test_account_fixture_pack import NOW, NOW_MS

DEMO_WS: Final = PRIVATE_WS_URLS["demo"]
EXPIRES: Final = NOW_MS + 10_000
AUTH_OK, SUBSCRIBED, PONG, WALLET_PUSH = (
    payload(PACK, f"_base/ws_{n}.json") for n in ("auth_ok", "subscribe_ok", "pong", "wallet")
)
PING: Final = '{"op":"ping"}'
SUBSCRIBE: Final = json.dumps({"op": "subscribe", "args": ["wallet"]})
_S: Final = timedelta(seconds=1)
#: How long a test's reads may wait in all before one that gets nothing ends the test.
HORIZON: Final = timedelta(minutes=1)
LINE: Final = ("method", "outcome", "key_class", "signing_key_id", "verified", "scenario")


class Elapsed(Exception):
    """The fake time passed the test's horizon: nothing more came."""


@dataclass
class Clock:
    now: datetime = NOW
    broken: bool = False

    def __call__(self) -> datetime:
        if self.broken:
            raise ValueError("the clock file is off its rule")
        return self.now


@dataclass
class Rig:
    sockets: FixtureSockets
    transport: FixtureTransport
    keys: KeyStates
    clock: Clock
    gate: ReadOnlyGate
    latch: threading.Event
    directory: Path

    def lines(self) -> list[dict[str, Any]]:
        text = (self.directory / FILE_NAME).read_text()
        return [line for line in map(json.loads, text.splitlines()) if line["transport"] == "ws"]

    def logged(self) -> list[tuple[Any, ...]]:
        return [_of(line, *LINE) for line in self.lines()]

    async def authed(self, scenario: str = "compliant") -> FixtureSocket:
        socket = await self.sockets.connect(DEMO_WS)
        await socket.send(_auth(scenario))
        assert await _frame(socket) == AUTH_OK
        return socket


@pytest.fixture
def boot(tmp_path: Path) -> Iterator[Callable[..., Rig]]:
    clock = Clock()
    with RequestLog(
        tmp_path, process_env=Environment.DEMO, clock=clock, pack_key_ids=KEY_IDS
    ) as log:
        left = [HORIZON]

        async def sleep(seconds: float) -> None:
            step = timedelta(seconds=seconds)
            if step > left[0]:
                raise Elapsed
            left[0] -= step
            clock.now += step

        def build(
            default: str = "compliant", kind: type[FixtureTransport] = FixtureTransport
        ) -> Rig:
            keys = KeyStates(tmp_path, PACK, log=log, clock=clock)
            gate, latch = ReadOnlyGate(), threading.Event()
            transport = kind(
                PACK, log=log, gate=gate, clock=clock, default=default, keys=keys, latch=latch
            )
            sockets = FixtureSockets(transport, sleep=sleep)
            return Rig(sockets, transport, keys, clock, gate, latch, tmp_path)

        yield build


@pytest.fixture
def rig(boot: Callable[..., Rig]) -> Rig:
    return boot()


def _mac(signed_as: str, expires: object = EXPIRES) -> str:
    message = b"GET/realtime" + str(expires).encode()
    return hmac.new(_secret(signed_as).encode(), message, hashlib.sha256).hexdigest()


def _auth(scenario: str = "compliant", *, signed_as: str | None = None, key: str = "") -> str:
    args = [key or _key(scenario), EXPIRES, _mac(signed_as or scenario)]
    return json.dumps({"op": "auth", "args": args})


async def _frame(socket: FixtureSocket, max_bytes: int = 1_048_576) -> Any:
    return json.loads(await socket.recv(max_bytes))


async def _dropped(socket: FixtureSocket) -> list[Any]:
    """Every frame until the socket drops."""
    frames = []
    with pytest.raises(ConnectionResetError):
        while True:
            frames.append(await _frame(socket))
    return frames


async def test_auth_then_the_after_auth_frames_on_the_script(rig: Rig) -> None:
    socket = await rig.authed()
    assert [await _frame(socket) for _ in range(3)] == [WALLET_PUSH] * 3
    assert rig.clock.now == NOW + 10 * _S  # the snapshot at 0, then every 5 s
    rig.clock.now += timedelta(hours=1)  # an overdue periodic frame is sent once, no backlog
    assert await _frame(socket) == WALLET_PUSH
    assert rig.clock.now == NOW + timedelta(hours=1, seconds=10)
    assert await _frame(socket) == WALLET_PUSH
    assert rig.clock.now == NOW + timedelta(hours=1, seconds=15)
    assert rig.logged() == [
        ("CONNECT", "served", "unsigned", None, None, "compliant"),
        ("AUTH", "served", "fixture", _key("compliant"), True, "compliant"),
    ]
    line = rig.lines()[0]
    assert _of(line, "host", "host_env", "path", "transport") == (
        "stream-demo.bybit.com", "demo", "/v5/private", "ws",
    )  # fmt: skip


async def test_ping_answers_the_packs_pong_before_and_after_auth(rig: Rig) -> None:
    socket = await rig.sockets.connect(DEMO_WS)
    await socket.send(PING)
    assert await _frame(socket) == PONG
    await socket.send(_auth())
    await socket.send(PING)
    assert [await _frame(socket) for _ in range(2)] == [AUTH_OK, PONG]


async def test_subscribe_acks_the_private_topics_once_authed(rig: Rig) -> None:
    socket = await rig.authed()
    for topics in (*REQUIRED_OPS, *OPTIONAL_OPS):
        await socket.send(json.dumps({"op": "subscribe", "args": list(topics)}))
        assert await _frame(socket) == SUBSCRIBED
    assert {t for op in (*REQUIRED_OPS, *OPTIONAL_OPS) for t in op} == PRIVATE_TOPICS


async def test_ws_auth_then_drop_drops_at_5s_and_refuses_reconnects(
    boot: Callable[..., Rig],
) -> None:
    rig = boot("ws_auth_then_drop")
    socket = await rig.authed("ws_auth_then_drop")
    assert await _dropped(socket) == [WALLET_PUSH]
    assert rig.clock.now == NOW + 5 * _S
    with pytest.raises(ConnectionRefusedError):
        await rig.sockets.connect(DEMO_WS)
    assert [line[:2] for line in rig.logged()] == [
        ("CONNECT", "served"), ("AUTH", "served"), ("DROP", "served"), ("REFUSE", "served"),
    ]  # fmt: skip


async def test_a_keys_drop_counts_from_its_start_and_refuses_its_reconnect(rig: Rig) -> None:
    socket = await rig.authed("ws_auth_then_drop")  # the stack default stays compliant
    assert await _dropped(socket) == [WALLET_PUSH]
    rig.clock.now += _S  # after the drop, so only the refusal can end the next socket
    again = await rig.sockets.connect(DEMO_WS)  # the connect is the stack default's
    await again.send(_auth("ws_auth_then_drop"))  # the key's script refuses it at auth
    assert await _dropped(again) == []
    assert rig.logged()[-2:] == [
        ("AUTH", "served", "fixture", _key("ws_auth_then_drop"), True, "ws_auth_then_drop"),
        ("DROP", "served", "fixture", _key("ws_auth_then_drop"), True, "ws_auth_then_drop"),
    ]


async def test_ws_drop_rest_fail_drops_the_socket_and_fails_rest(boot: Callable[..., Rig]) -> None:
    rig = boot("ws_drop_rest_fail")
    socket = await rig.authed("ws_drop_rest_fail")
    assert await _dropped(socket) == [WALLET_PUSH]
    response = await rig.transport.handle_async_request(_get("ws_drop_rest_fail", path=WALLET))
    assert response.status_code == 503
    with pytest.raises(ConnectionRefusedError):
        await rig.sockets.connect(DEMO_WS)


async def test_ws_blip_20s_switched_in_counts_from_the_switch(rig: Rig) -> None:
    socket = await rig.authed()
    assert await _frame(socket) == WALLET_PUSH  # the snapshot
    rig.clock.now += 100 * _S
    switched = rig.keys.switch(_key("compliant"), "ws_blip_20s").started
    assert await _dropped(socket) == [WALLET_PUSH] * 2  # the overdue one, then +5 s
    assert rig.clock.now == switched + 10 * _S
    rig.clock.now = switched + 20 * _S  # inside the blip, after its drop
    rest = await rig.transport.handle_async_request(_get("compliant", path=WALLET))
    assert rest.status_code == 503
    blipped = await rig.sockets.connect(DEMO_WS)
    await blipped.send(_auth())
    assert await _dropped(blipped) == []  # reconnects refused until 30 s
    rig.clock.now = switched + 30 * _S
    back = await rig.sockets.connect(DEMO_WS)
    await back.send(_auth(signed_as="ws_blip_20s"))  # the secret stays the stored-under one
    assert await _frame(back) == {"success": False, "op": "auth"}
    await back.send(_auth())
    assert await _frame(back) == AUTH_OK


async def test_demo_ws_unreachable_refuses_every_connect(boot: Callable[..., Rig]) -> None:
    rig = boot("demo_ws_unreachable")
    for _ in range(2):
        with pytest.raises(ConnectionRefusedError):
            await rig.sockets.connect(DEMO_WS)
    assert rig.logged() == [("REFUSE", "served", "unsigned", None, None, "demo_ws_unreachable")] * 2


async def test_on_connect_follows_the_stack_default_not_the_key(rig: Rig) -> None:
    socket = await rig.authed("demo_ws_unreachable")  # TC-115 needs CV_ACCOUNT_FIXTURE
    assert await _frame(socket) == WALLET_PUSH


async def test_live_key_on_demo_closes_on_auth(rig: Rig) -> None:
    socket = await rig.sockets.connect(DEMO_WS)
    await socket.send(_auth("live_key_on_demo"))
    assert await _dropped(socket) == []
    assert [line[:2] for line in rig.logged()][-1] == ("DROP", "served")


async def test_ws_auth_timeout_never_answers_auth(rig: Rig) -> None:
    socket = await rig.sockets.connect(DEMO_WS)
    await socket.send(_auth("ws_auth_timeout"))
    await socket.send(PING)
    assert await _frame(socket) == PONG
    with pytest.raises(Elapsed):
        await socket.recv(4096)


async def test_a_wrong_secret_answers_success_false_and_verified_false(rig: Rig) -> None:
    socket = await rig.sockets.connect(DEMO_WS)
    with capture_logs() as events:
        await socket.send(_auth(signed_as="ws_quiet"))
    assert await _frame(socket) == {"success": False, "op": "auth"}
    assert rig.logged()[-1] == (
        "AUTH",
        "signature_mismatch",
        "fixture",
        _key("compliant"),
        False,
        None,
    )
    assert [e["log_level"] for e in events] == ["warning"]
    with pytest.raises(Elapsed):  # no wallet frame follows a refused auth
        await socket.recv(4096)
    for bad in ([_key("compliant"), str(EXPIRES), _mac("compliant")], [_key("compliant"), EXPIRES]):
        await socket.send(json.dumps({"op": "auth", "args": bad}))
        assert (await _frame(socket))["success"] is False
    assert not rig.latch.is_set()


MISMATCH: Final = ("AUTH", "signature_mismatch", "fixture", _key("compliant"), False, None)


@pytest.mark.parametrize("given", ["\udc80", "\u00e9" * 64], ids=["lone-surrogate", "non-ascii"])
async def test_a_non_ascii_signature_is_a_mismatch_not_an_error(rig: Rig, given: str) -> None:
    """`json.loads` hands a lone surrogate through; it must not escape `send` unclassified."""
    socket = await rig.sockets.connect(DEMO_WS)
    await socket.send(json.dumps({"op": "auth", "args": [_key("compliant"), EXPIRES, given]}))
    assert await _frame(socket) == {"success": False, "op": "auth"}
    assert rig.logged()[-1] == MISMATCH


async def test_a_reauth_with_the_sockets_key_and_a_wrong_secret_stays_open(rig: Rig) -> None:
    """The line says `verified=false` though the key is the one the socket follows."""
    socket = await rig.authed()
    with capture_logs() as events:
        await socket.send(_auth(signed_as="ws_quiet"))
    assert await _frame(socket) == {"success": False, "op": "auth"}
    assert rig.logged()[-1] == MISMATCH
    assert [_of(e, "event", "verified") for e in events] == [
        ("exchange.account_fixture_signature_mismatch", False)
    ]
    await socket.send(PING)
    assert await _frame(socket) == PONG


@pytest.mark.parametrize(
    "args",
    [
        [NON_FIXTURE_KEY, EXPIRES, "0" * 64],
        ["fixture-compliant-9999", EXPIRES, "0" * 64],
        [],
        None,
        "x",
        [7],
    ],
    ids=["non-fixture", "fixture-shaped", "empty", "none", "text", "number"],
)
async def test_a_non_pack_key_trips_the_process_latch_unanswered(rig: Rig, args: Any) -> None:
    socket = await rig.sockets.connect(DEMO_WS)
    with capture_logs() as events:
        await socket.send(json.dumps({"op": "auth", "args": args}))
    assert _p0(events, "refused_key")
    assert rig.latch.is_set() and rig.gate.latched_reason_code == guards.GUARD_REASON_CODE
    assert await _dropped(socket) == []
    assert rig.logged()[-1] == ("AUTH", "refused_key", "non_fixture", None, None, None)
    with pytest.raises(ConnectionRefusedError, match="refused_key"):
        await rig.sockets.connect(DEMO_WS)
    with pytest.raises(httpx.ConnectError):  # the REST transport shares the latch
        await rig.transport.handle_async_request(_get())
    assert NON_FIXTURE_KEY not in (rig.directory / FILE_NAME).read_text() + str(events)


@pytest.mark.parametrize(
    ("url", "host", "env"),
    [
        (PRIVATE_WS_URLS["live"], "stream.bybit.com", "live"),
        (PRIVATE_WS_URLS["testnet"], "stream-testnet.bybit.com", "testnet"),
        ("wss://stream.bybit.com/v5/public/linear", "stream.bybit.com", "live"),
        ("ws://stream-demo.bybit.com/v5/private", "stream-demo.bybit.com", "demo"),
        ("wss://stream-demo.bybit.com:443/v5/private", "stream-demo.bybit.com", "demo"),
        (f"{DEMO_WS}?x=1", "stream-demo.bybit.com", "demo"),
        ("wss://example.invalid/v5/private", None, None),
    ],
)
async def test_every_other_url_is_refused_p0(rig: Rig, url: str, host: str, env: str) -> None:
    with capture_logs() as events, pytest.raises(ConnectionRefusedError) as refused:
        await rig.sockets.connect(url)
    assert str(refused.value).endswith("refused_host") and url not in str(refused.value)
    assert _p0(events, "refused_host") and not rig.latch.is_set()
    [line] = rig.lines()
    assert _of(line, "host", "host_env", "method", "outcome") == (
        host,
        env,
        "CONNECT",
        "refused_host",
    )


@pytest.mark.parametrize("how", ["latch", "gate", "mid-read"])
async def test_the_latch_closes_a_live_socket(boot: Callable[..., Rig], how: str) -> None:
    rig = boot(kind=_Tripping)
    socket = await rig.authed()
    if how == "latch":
        rig.latch.set()
    elif how == "gate":
        rig.gate.latch(reason_code=guards.GUARD_REASON_CODE, reason_text="tripped elsewhere")
    else:
        await socket.send(PING)  # a pong is queued, then the latch trips while the state is read
        assert isinstance(rig.transport, _Tripping)
        rig.transport.trip_on_select = True
    assert await _dropped(socket) == []
    assert rig.logged()[-1][:2] == ("DROP", "refused_key")
    with pytest.raises(ConnectionResetError):
        await socket.send(PING)
    with pytest.raises(ConnectionRefusedError, match="refused_key"):
        await rig.sockets.connect(DEMO_WS)


class _Tripping(FixtureTransport):
    """Trips the latch while a state is read, as another transport can meanwhile."""

    trip_on_select = False

    def select(self, key_id: str | None) -> tuple[datetime, Scenario, datetime]:
        if self.trip_on_select:
            self.trip()
        return super().select(key_id)


#: Frames the script does not answer, after `auth`: never acked, the socket closed.
UNSCRIPTED: Final = {
    "withdraw-topic": '{"op":"subscribe","args":["withdraw"]}',
    "transfer-topic": '{"op":"subscribe","args":["wallet","asset.transfer"]}',
    "no-topic": '{"op":"subscribe","args":[]}',
    "no-args": '{"op":"subscribe"}',
    "transfer-op": '{"op":"transfer","args":[]}',
    "withdraw-op": '{"op":"withdraw"}',
    "trade-op": '{"op":"order.create","args":[]}',
    "no-op": '{"args":[]}',
    "not-an-object": "[]",
    "not-json": "not json",
    "oversize": json.dumps({"op": "ping", "pad": "a" * 4096}),
}


@pytest.mark.parametrize("frame", UNSCRIPTED.values(), ids=UNSCRIPTED.keys())
async def test_an_unscripted_frame_closes_the_socket_unanswered(rig: Rig, frame: str) -> None:
    socket = await rig.authed()
    await socket.send(frame)
    assert await _dropped(socket) == []
    assert rig.logged()[-1][:3] == ("DROP", "unstubbed", "fixture")


async def test_a_subscribe_before_auth_is_unscripted(rig: Rig) -> None:
    socket = await rig.sockets.connect(DEMO_WS)
    await socket.send(SUBSCRIBE)
    assert await _dropped(socket) == []
    assert rig.logged()[-1][:3] == ("DROP", "unstubbed", "unsigned")


class _Silenced(FixtureTransport):
    """`compliant` with a timeline the pack does not use: silence at 1 s, a drop at 3 s."""

    def _selection(self, key_id: str | None, now: datetime) -> tuple[Scenario, datetime]:
        scenario, started = super()._selection(key_id, now)
        steps = (WsStep(1000, "silence", None), WsStep(3000, "drop", None))
        return replace(scenario, ws=replace(scenario.ws, timeline=steps)), started


async def test_silence_stops_every_frame(boot: Callable[..., Rig]) -> None:
    rig = boot(kind=_Silenced)
    socket = await rig.authed()
    rig.clock.now += 2 * _S
    await socket.send(PING)
    assert await _dropped(socket) == []  # the snapshot at 0 is overdue but silenced; no pong
    assert rig.clock.now == NOW + 3 * _S


@pytest.mark.parametrize(
    ("steps", "refusing"),
    [
        ([(1000, "refuse_reconnects"), (1000, "accept_reconnects")], False),
        ([(1000, "accept_reconnects"), (1000, "refuse_reconnects")], True),
        ([(2000, "accept_reconnects"), (1000, "refuse_reconnects")], False),
        ([(5000, "refuse_reconnects")], False),
    ],
)
async def test_reconnects_follow_the_timeline_in_time_then_list_order(
    boot: Callable[..., Rig], steps: list[tuple[int, str]], refusing: bool
) -> None:
    timeline = tuple(WsStep(at, do, None) for at, do in steps)

    class _Timed(FixtureTransport):
        def _selection(self, key_id: str | None, now: datetime) -> tuple[Scenario, datetime]:
            scenario, started = super()._selection(key_id, now)
            ws: PrivateWs = replace(scenario.ws, timeline=timeline)
            return replace(scenario, ws=ws), started

    rig = boot(kind=_Timed)
    rig.clock.now += 3 * _S
    if refusing:
        with pytest.raises(ConnectionRefusedError):
            await rig.sockets.connect(DEMO_WS)
    else:
        await rig.sockets.connect(DEMO_WS)


async def test_close_is_logged_once_and_ends_the_socket(rig: Rig) -> None:
    socket = await rig.authed()
    await socket.close()
    await socket.close()
    for ended in (socket.recv(4096), socket.send(PING)):
        with pytest.raises(ConnectionResetError):
            await ended
    assert [line[:2] for line in rig.logged()] == [
        ("CONNECT", "served"),
        ("AUTH", "served"),
        ("CLOSE", "served"),
    ]


async def test_a_frame_above_the_read_bound_ends_the_socket(rig: Rig) -> None:
    socket = await rig.authed()
    with pytest.raises(FrameTooLarge):
        await socket.recv(64)
    with pytest.raises(ConnectionResetError):
        await socket.recv(4096)


async def test_the_read_bound_counts_bytes_not_characters(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pack's frames are served ASCII-escaped, so a multi-byte frame is put in by hand."""
    frame = json.dumps("\u00e9" * 40, ensure_ascii=False)  # 42 characters, 82 bytes

    def due(*_args: object) -> tuple[str, None]:
        return frame, None

    monkeypatch.setattr(FixtureSocket, "_next", due)
    socket = await rig.sockets.connect(DEMO_WS)
    assert await socket.recv(82) == frame
    with pytest.raises(FrameTooLarge):
        await socket.recv(81)


async def test_a_reader_that_never_reads_is_dropped_at_the_bound(rig: Rig) -> None:
    socket = await rig.authed()
    with pytest.raises(ConnectionResetError):
        for _ in range(64):
            await socket.send(PING)
    assert rig.logged()[-1][:2] == ("DROP", "served")


async def test_a_state_off_its_rule_refuses_by_a_fixed_code(rig: Rig) -> None:
    (rig.directory / KEYS_DIR / f"{_key('compliant')}.json").write_text("{}")
    socket = await rig.sockets.connect(DEMO_WS)
    with capture_logs() as events, pytest.raises(ConnectionResetError, match="key_state_invalid"):
        await socket.send(_auth())
    assert events[-1]["event"] == "exchange.account_fixture_key_state_invalid"
    assert await _dropped(socket) == []
    rig.clock.broken = True
    with capture_logs() as events, pytest.raises(ConnectionRefusedError, match="clock_invalid"):
        await rig.sockets.connect(DEMO_WS)
    assert events[0]["event"] == "exchange.account_fixture_clock_invalid"


@pytest.mark.parametrize("signed_as", ["compliant", "ws_quiet"], ids=["verified", "mismatch"])
async def test_a_log_that_cannot_be_written_refuses(rig: Rig, signed_as: str) -> None:
    socket = await rig.sockets.connect(DEMO_WS)
    rig.transport.log.close()
    await socket.send(_auth(signed_as=signed_as))
    assert await _dropped(socket) == []  # the auth is never answered
    with pytest.raises(ConnectionRefusedError, match="request_log_failed"):
        await rig.sockets.connect(DEMO_WS)


async def test_the_socket_reads_its_state_off_the_event_loop(boot: Callable[..., Rig]) -> None:
    seen: list[int] = []

    class _Seen(FixtureTransport):
        def _selection(self, key_id: str | None, now: datetime) -> tuple[Scenario, datetime]:
            seen.append(threading.get_ident())
            return super()._selection(key_id, now)

    rig = boot(kind=_Seen)
    await rig.authed()
    assert seen and threading.get_ident() not in seen


async def test_no_log_holds_a_signature_or_a_secret(rig: Rig) -> None:
    with capture_logs() as events:
        socket = await rig.authed()
        await socket.send(_auth(signed_as="ws_quiet"))
        await socket.close()
    text = (rig.directory / FILE_NAME).read_text() + str(events)
    for value in (_mac("compliant"), _mac("ws_quiet"), _secret("compliant"), _secret("ws_quiet")):
        assert value not in text


async def test_a_socket_on_a_default_transport_shares_the_process_latch(rig: Rig) -> None:
    keys, log = rig.keys, rig.transport.log
    transport = FixtureTransport(
        PACK, log=log, gate=ReadOnlyGate(), clock=rig.clock, default="compliant", keys=keys
    )
    assert not guards.LATCH.is_set()
    try:
        guards.LATCH.set()
        with pytest.raises(ConnectionRefusedError, match="refused_key"):
            await FixtureSockets(transport).connect(DEMO_WS)
    finally:
        guards.LATCH.clear()


async def test_the_adapters_key_probe_reads_the_script(boot: Callable[..., Rig]) -> None:
    async def probe(rig: Rig, scenario: str, signed_as: str) -> Any:
        async def sign(credential_id: UUID, message: Any, purpose: str) -> RequestSignature:
            data = assemble(_key(scenario), check_message(message))
            mac = hmac.new(_secret(signed_as).encode(), data, hashlib.sha256).hexdigest()
            return RequestSignature(Secret(_key(scenario)), mac)

        probe = KeyWsProbe(rig.sockets.connect, wall_ms=lambda: NOW_MS)
        return await probe.probe(CredentialBorrower(sign), "demo", CREDENTIAL_ID)

    rig = boot()
    assert (await probe(rig, "compliant", "compliant")).ok
    assert (await probe(rig, "compliant", "ws_quiet")).error == "auth_error"
    assert (await probe(rig, "live_key_on_demo", "live_key_on_demo")).error == "transport_error"
    assert (
        await probe(boot("demo_ws_unreachable"), "compliant", "compliant")
    ).error == "transport_error"


async def test_a_frame_sent_while_a_read_waits_wakes_it(rig: Rig) -> None:
    """The adapter's pinger sends while its reader waits (24 section 14.2 rule 13)."""
    parked = asyncio.Event()

    async def park(seconds: float) -> None:
        parked.set()
        await asyncio.Event().wait()

    socket = await FixtureSockets(rig.transport, sleep=park).connect(DEMO_WS)
    reader = asyncio.create_task(socket.recv(4096))
    await parked.wait()
    await socket.send(PING)
    assert json.loads(await reader) == PONG


async def test_a_close_while_a_frame_is_read_logs_one_line(rig: Rig) -> None:
    socket = await rig.sockets.connect(DEMO_WS)
    sending = asyncio.create_task(socket.send("not json"))
    await asyncio.sleep(0)  # the send now waits for its state, off the event loop
    await socket.close()
    await sending
    assert [line[0] for line in rig.logged()] == ["CONNECT", "CLOSE"]


async def test_a_latched_process_trips_then_refuses_an_auth(rig: Rig) -> None:
    """Admit, trip, refuse: a non-pack key still trips and pages; a pack key is refused."""
    stranger, member = [await rig.sockets.connect(DEMO_WS) for _ in range(2)]
    rig.latch.set()
    with capture_logs() as events:
        await stranger.send(json.dumps({"op": "auth", "args": [NON_FIXTURE_KEY, EXPIRES, "0"]}))
    assert _p0(events, "refused_key") and rig.gate.latched_reason_code == guards.GUARD_REASON_CODE
    with pytest.raises(ConnectionResetError):
        await member.send(_auth())
    assert [line[:3] for line in rig.logged()[-2:]] == [
        ("AUTH", "refused_key", "non_fixture"), ("DROP", "refused_key", "unsigned"),
    ]  # fmt: skip
