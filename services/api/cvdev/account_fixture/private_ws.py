"""#2893 S12: the account fixture's private-WS socket, which plays the pack's WS script (ADR-0036).

`FixtureSockets.connect` is a fixture stack's private-socket connector, the seam S4 threads into
the adapter's key probe and private streams (`private_ws_connect`); S14 wires it in. It is built
on the stack's `FixtureTransport`, so the socket shares the transport's guard latch
(`guards.LATCH` unless a test injects one), read-only gate, fixture clock, key files and request
log. The guards run in the transport's order: admit, trip, refuse, signature, serve, and the latch
is checked again before every frame sent.

- **Connect.** Only the adapter's demo private stream, `guards.DEMO_PRIVATE_WS` exactly (C-2.11);
  any other URL is refused as `refused_host`, a P0. A latched process refuses (`refused_key`).
  Then the stack default's script answers (`CV_ACCOUNT_FIXTURE`, from boot; ADR-0036 decision 6,
  TC-115): `on_connect: refuse`, or reconnects its timeline refuses, raise
  `ConnectionRefusedError` as a closed port does.
- **`auth`.** A first argument that is not a pack key id trips the process latch and the socket
  closes unanswered (`refused_key`, a P0). A latched process closes it. A signature other than
  HMAC-SHA256 with the stored-under scenario's derived secret over `GET/realtime` and `expires`
  gets the failed-auth reply (the pack's `ws_auth_ok.json` with `success` false, an unverified
  stand-in) and `verified=false`. Otherwise the key's scenario answers (`KeyStates`, as its REST
  calls, anchored at its first signed call): `on_auth` (`reply`, `ignore`, `close`), and the
  socket follows that scenario from then on; reconnects its timeline refuses close it.
- **Script.** `on_ping` answers a ping, `on_subscribe` a subscribe naming only the adapter's
  private topics once authed. Any other frame (another op, topic or shape, a subscribe before
  auth, a frame over `MAX_FRAME_CHARS`) is unstubbed: the socket closes, never acked, so no
  withdrawal or transfer topic or op is answered. After an `auth` reply, `after_auth` frames go at
  `after_ms` from it, then every `every_ms`; one a clock jump made overdue is sent once, no
  backlog. The timeline runs on scenario time, equal times in list order: `drop` closes a socket
  open before it, `refuse_reconnects`/`accept_reconnects` gate later connects and `auth`s, and
  `silence` stops every frame the script sends. Its frames are the pack's, served as they are.

The clock and the key's file are read, off the event loop, on every read, so a switch reaches an
open socket. A read waits for the next due frame, at most `POLL_S`, on the injected `sleep`, or
until a frame is sent: no task outlives a read. At most `OUTBOX_FRAMES` replies wait unread;
one more drops the socket. Each connect, `auth` and close is one request-log line (transport
`ws`, the event as `method`, prefixed so it is never taken for an HTTP method: `WS:CONNECT`,
`WS:REFUSE`, `WS:AUTH`, `WS:DROP`, `WS:CLOSE`), never a frame, a signature or a secret; a line
that cannot be written refuses the connect or closes the socket. A push's integer `creationTime`
is sent on the stub exchange's clock, as REST's envelope `time` (pack README, 'Clock').
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta
from typing import Any, Final
from urllib.parse import urlsplit

from candleviewer.exchange.bybit.errors import FrameTooLarge
from candleviewer.observability import spawn
from cvdev.account_fixture import guards
from cvdev.account_fixture.control import KeyStateError
from cvdev.account_fixture.pack import PrivateWs, Scenario, WsReaction, merge_patch, payload
from cvdev.account_fixture.requestlog import KeyClass, Outcome, RequestLogFileError, WsMethod
from cvdev.account_fixture.transport import ClockInvalid, FixtureTransport, logger

#: The adapter's private topics (24 section 14.2 rule 13): the only ones a subscribe may name.
PRIVATE_TOPICS: Final = frozenset(
    {"order.linear", "execution.linear", "position.linear", "wallet", "execution.fast.linear"}
)
#: The failed-auth reply: the pack's auth reply refused (an unverified stand-in, #2893 scope 10).
_AUTH_REPLY: Final = "_base/ws_auth_ok.json"
_REFUSED: Final = {"success": False}
MAX_FRAME_CHARS: Final = 4096
#: An `auth` op's arguments: the key id, `expires` and the signature.
_AUTH_ARGS: Final = 3
OUTBOX_FRAMES: Final = 32
POLL_S: Final = 1.0
_PATH: Final = urlsplit(guards.DEMO_PRIVATE_WS).path
_MS: Final = timedelta(milliseconds=1)
_P0: Final = "p0-critical"
#: The socket's wait: `asyncio.sleep` on a stack, a fake in tests.
Sleep = Callable[[float], Coroutine[Any, Any, None]]


def _message(code: str) -> str:
    """A refusal's text: a fixed code, never a URL, a frame or a key (FX-I01)."""
    return f"the account fixture socket refused: {code}"


def _ms(now: datetime, since: datetime) -> int:
    return max(0, (now - since) // _MS)


def _timeline(ws: PrivateWs, at_ms: int) -> tuple[bool, bool]:
    """Whether reconnects are refused, and whether the socket is silent, at `at_ms`."""
    refusing = silent = False
    for step in sorted(ws.timeline, key=lambda step: step.at_ms):  # stable: list order on ties
        if step.at_ms <= at_ms:
            refusing = {"refuse_reconnects": True, "accept_reconnects": False}.get(
                step.do, refusing
            )
            silent = silent or step.do == "silence"
    return refusing, silent


class FixtureSockets:
    """The connector (module docstring). `sleep` is the socket's wait, which only a test fakes."""

    def __init__(
        self,
        transport: FixtureTransport,
        *,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._rest, self._sleep = transport, sleep
        refused = merge_patch(payload(transport.pack, _AUTH_REPLY), _REFUSED)
        self._refused_auth = json.dumps(refused, separators=(",", ":"))

    async def connect(self, url: str) -> FixtureSocket:
        socket = FixtureSocket(self._rest, url, sleep=self._sleep, refused_auth=self._refused_auth)
        if url != guards.DEMO_PRIVATE_WS:
            socket.refuse("WS:CONNECT", "refused_host", p0=True)
        if self._rest.latched:
            socket.refuse("WS:CONNECT", "refused_key", p0=False)
        now, scenario, started = await socket.state()
        refusing, _ = _timeline(scenario.ws, _ms(now, started))
        refused = scenario.ws.on_connect == "refuse" or refusing
        event: WsMethod = "WS:REFUSE" if refused else "WS:CONNECT"
        if not socket.record(event, "served", scenario):
            raise ConnectionRefusedError(_message("request_log_failed"))
        if refused:
            raise ConnectionRefusedError(_message("refused"))
        socket.opened = now
        return socket


class FixtureSocket:
    """One private-stream connection (`PrivateSocket`): frames out by `send`, script in `recv`."""

    def __init__(
        self,
        transport: FixtureTransport,
        url: str,
        *,
        sleep: Sleep,
        refused_auth: str,
    ) -> None:
        self._rest, self._sleep, self._refused_auth = transport, sleep, refused_auth
        split = urlsplit(url)
        self._env = guards.ws_host_env(split.hostname)
        self._host = split.hostname if self._env else None
        self._path = _PATH if split.path == _PATH else None
        self.opened: datetime | None = None
        #: The pack key whose verified `auth` the socket follows; when its reply was sent.
        self._key: str | None = None
        self._authed: datetime | None = None
        self._sent: dict[int, int] = {}
        self._outbox: deque[str] = deque()
        self._wake = asyncio.Event()
        self._closed = False

    async def send(self, frame: str) -> None:
        if self._closed:
            raise ConnectionResetError(_message("closed"))
        parsed = _parse(frame)
        op, args = parsed if parsed else (None, None)
        if op == "auth":
            await self._auth(args)
            return
        self._open()
        now, scenario, started = await self.state()
        _, silent = _timeline(scenario.ws, _ms(now, started))
        if op == "ping":
            reaction = scenario.ws.on_ping
        elif op == "subscribe" and self._authed is not None and _topics(args):
            reaction = scenario.ws.on_subscribe
        else:
            self._drop("unstubbed", scenario)
            return
        if not silent:
            self._react(reaction, scenario)

    async def recv(self, max_bytes: int) -> str:
        while True:
            self._wake.clear()
            self._open()
            now, scenario, started = await self.state()
            frame, due = self._next(now, scenario, started)
            if frame is not None:
                self._open()  # the latch, again: it may have tripped while the state was read
                if len(frame.encode()) > max_bytes:  # bytes, as the adapter's real socket
                    self._drop("served", scenario)
                    raise FrameTooLarge("a fixture frame above the read bound")
                return frame
            await self._wait(POLL_S if due is None else min(POLL_S, due))

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._wake.set()
            self.record("WS:CLOSE", "served", None)

    async def state(self) -> tuple[datetime, Scenario, datetime]:
        """The fixture clock and the scenario the socket follows: its key's once a verified `auth`
        named one, else the stack default. Read off the event loop; a state off its rule closes
        the socket by a fixed code, never a path or a key."""
        try:
            return await asyncio.to_thread(self._rest.select, self._key)
        except ClockInvalid:
            code = "clock_invalid"
        except (KeyStateError, OSError):
            code = "key_state_invalid"
        logger().error(f"exchange.account_fixture_{code}", **self._fields())
        self._closed = True
        error = ConnectionRefusedError if self.opened is None else ConnectionResetError
        raise error(_message(code)) from None

    def _next(
        self, now: datetime, scenario: Scenario, started: datetime
    ) -> tuple[str | None, float | None]:
        """The frame to read now, else the seconds to the next one due or the next drop."""
        ws, at_ms = scenario.ws, _ms(now, started)
        drops = [started + step.at_ms * _MS for step in ws.timeline if step.do == "drop"]
        if any(self.opened is not None and self.opened <= drop <= now for drop in drops):
            self._drop("served", scenario)
            self._open()
        if self._outbox:
            return self._outbox.popleft(), None
        waits = [(drop - now).total_seconds() for drop in drops if drop > now]
        if self._authed is not None and not _timeline(ws, at_ms)[1]:
            since = _ms(now, self._authed)
            for index, push in enumerate(ws.after_auth):
                count = self._sent.get(index, 0)
                if count and push.every_ms is None:
                    continue
                due = push.after_ms + count * (push.every_ms or 0)
                if due <= since:
                    missed = (since - push.after_ms) // push.every_ms if push.every_ms else 0
                    self._sent[index] = max(count, missed) + 1
                    frame = _anchored(push.frame, scenario.at(now, started=started))
                    return json.dumps(frame, separators=(",", ":")), None
                waits.append((due - since) / 1000)
        return None, min(waits, default=None)

    async def _auth(self, args: object) -> None:
        key = args[0] if isinstance(args, list) and args else None
        if not isinstance(key, str) or key not in self._rest.key_ids:
            self._rest.trip()  # FX-S01: a key the pack does not hold
            self.refuse("WS:AUTH", "refused_key", p0=True, key_class="non_fixture", close=True)
            return
        self._open()  # then the latch: a pack key on a latched process is refused, unanswered
        if not (
            isinstance(args, list)
            and len(args) == _AUTH_ARGS
            and guards.ws_signature_verifies(key, args[1], args[2])
        ):
            logger().warning(
                "exchange.account_fixture_signature_mismatch", **self._fields(key, verified=False)
            )
            if self.record("WS:AUTH", "signature_mismatch", None, key=key, verified=False):
                self._queue(self._refused_auth)
            else:
                self._closed = True
            return
        self._key = key
        now, scenario, started = await self.state()
        if not self.record("WS:AUTH", "served", scenario):
            self._closed = True
            return
        refusing, silent = _timeline(scenario.ws, _ms(now, started))
        if refusing:
            self._drop("served", scenario)
        elif not silent and self._react(scenario.ws.on_auth, scenario):
            self._authed, self._sent = now, {}

    def _react(self, reaction: WsReaction, scenario: Scenario) -> bool:
        """The script's reaction: queue its reply, ignore, or close. True when it replied."""
        if reaction.do == "close":
            self._drop("served", scenario)
        elif reaction.do == "reply":
            self._queue(json.dumps(reaction.frame, separators=(",", ":")))
            return True
        return False

    def _queue(self, frame: str) -> None:
        if len(self._outbox) >= OUTBOX_FRAMES:  # a reader that never reads: dropped, bounded
            self._drop("served", None)
            self._open()
        self._outbox.append(frame)
        self._wake.set()

    async def _wait(self, seconds: float) -> None:
        """Until `seconds` pass or a frame is sent, whichever is first; both tasks are reaped, and
        what the sleep raised propagates."""
        sleeper = spawn(self._sleep(seconds), name="account-fixture-ws-wait")
        waits = (sleeper, spawn(self._wake.wait(), name="account-fixture-ws-wake"))
        try:
            await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in waits:
                task.cancel()
            await asyncio.gather(*waits, return_exceptions=True)
        if not sleeper.cancelled():
            sleeper.result()

    def _open(self) -> None:
        """Raise if the socket is closed; close it first when the process is latched."""
        if not self._closed and self._rest.latched:
            self._closed = True
            self._log("WS:DROP", "refused_key", p0=False)
        if self._closed:
            raise ConnectionResetError(_message("closed"))

    def _drop(self, outcome: Outcome, scenario: Scenario | None) -> None:
        if not self._closed:
            self._closed = True
            self.record("WS:DROP", outcome, scenario)

    def refuse(
        self,
        event: WsMethod,
        outcome: Outcome,
        *,
        p0: bool,
        key_class: KeyClass | None = None,
        close: bool = False,
    ) -> None:
        """Never answered: logged, then the connect raises, or the socket closes."""
        self._log(event, outcome, p0=p0, key_class=key_class)
        self._closed = True
        if not close:
            raise ConnectionRefusedError(_message(outcome))

    def _log(
        self, event: WsMethod, outcome: Outcome, *, p0: bool, key_class: KeyClass | None = None
    ) -> None:
        fields = self._fields(key_class=key_class)
        record: dict[str, object] = {"outcome": outcome, "priority": _P0 if p0 else None}
        record |= {"transport": "ws", "latched": self._rest.latched, **fields}
        (logger().critical if p0 else logger().error)("exchange.account_fixture_refused", **record)
        self.record(event, outcome, None, key_class=key_class)

    def _fields(
        self,
        key: str | None = None,
        key_class: KeyClass | None = None,
        verified: bool | None = None,
    ) -> dict[str, Any]:
        """What both logs hold of the socket: never a frame, but a pack key id. The key the socket
        follows verified, unless the line says otherwise (a failed re-auth with that key); another
        key's line says how it fared."""
        key = key or self._key
        named: KeyClass = key_class or ("fixture" if key else "unsigned")
        signing = key if named == "fixture" else None
        if verified is None and signing is not None and signing == self._key:
            verified = True
        return {
            "host": self._host,
            "host_env": self._env,
            "path": self._path,
            "key_class": named,
            "signing_key_id": signing,
            "verified": verified,
        }

    def record(
        self,
        event: WsMethod,
        outcome: Outcome,
        scenario: Scenario | None,
        *,
        key: str | None = None,
        verified: bool | None = None,
        key_class: KeyClass | None = None,
    ) -> bool:
        """One request-log line; false (and reported) when it cannot be written."""
        line = self._fields(key, key_class, verified)
        signing = line["signing_key_id"]
        stored = None if signing is None else guards.stored_under(signing)
        try:
            self._rest.log.write(
                outcome=outcome,
                transport="ws",
                method=event,
                scenario=None if scenario is None else scenario.name,
                stored_under=stored,
                overlays=() if scenario is None else _overlays(scenario),
                **line,
            )
        except (ValueError, RequestLogFileError, OSError) as exc:  # a clock off its rule too
            logger().error(
                "exchange.account_fixture_log_failed", outcome=outcome, error=type(exc).__name__
            )
            return False
        return True


def _anchored(frame: Any, scenario: Scenario) -> Any:
    """The push sent now: an integer `creationTime` on the stub exchange's clock, which the
    adapter's push envelope requires; any other frame as the pack holds it."""
    if isinstance(frame, dict) and type(frame.get("creationTime")) is int:
        return {**frame, "creationTime": scenario.clock.server_ms}
    return frame


def _overlays(scenario: Scenario) -> tuple[str, ...]:
    return tuple(str(overlay["scenario"]) for overlay in scenario.overlays)


def _parse(frame: str) -> tuple[object, object] | None:
    """A frame's `op` and `args`, or None for one the script cannot read."""
    if len(frame) > MAX_FRAME_CHARS:
        return None
    try:
        body = json.loads(frame)
    except (ValueError, RecursionError):
        return None
    return (body.get("op"), body.get("args")) if isinstance(body, dict) else None


def _topics(args: object) -> bool:
    """A subscribe naming only the adapter's private topics, at least one."""
    return (
        isinstance(args, list)
        and bool(args)
        and all(isinstance(topic, str) and topic in PRIVATE_TOPICS for topic in args)
    )
