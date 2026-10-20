"""E17-R-23 (#415, E17-X02): nightly fuzz of the JSON client-frame path, decode and dispatch.

Each input is one structured text frame, handed to a real gateway (the `_auth_rig` router, on the
test's loop) by a fresh socket in one of three states: before `hello`, after `welcome`, or after
`auth_ok`. The frames hold deep and wide nesting, escapes and lone surrogates (as escapes: a server
delivers only UTF-8), huge and negative integers, NaN and the infinities, duplicate keys, and sizes
up to and just past the cap. Whatever one holds, the socket answers it with a reply, an `err` of
the §10.2 catalogue or a strike, or ends it with a `bye` whose reason §4.4 lists: never
`internal_error` (in a `bye` or a top-level `err`), never `1011`, no `ws connection fault` line,
and the handler ends cleanly.

A failure names only its target and a sha256 digest of (seed, input). Hypothesis reports nothing
(no example, blob or explanation) and nothing writes the input: `CV_FUZZ_SEED` and
`CV_FUZZ_EXAMPLES` replay a run (200 examples by default; the nightly sets both). The helper block
is self-contained; its names (`Input`, `drive`, `save_failure`) follow the shared fuzz helper
planned under #415, so the target can move onto it with an import. The fuzz test is deselected
from the PR lane (`fuzz`); `test_each_named_frame_gets_an_answer_and_no_fault` runs the same check
there on named frames.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import os
from collections.abc import Callable
from typing import Any, Final

import pytest
from hypothesis import HealthCheck, Phase, Verbosity, given, seed, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.ws._generated.error_codes import WS_ERROR_CODES
from candleviewer.ws.lifecycle import CLOSE_REASONS
from candleviewer.ws.limits import (
    MAX_INBOUND_FRAME_BYTES,
    MAX_JSON_CONTAINERS,
    MAX_JSON_DEPTH,
    MAX_PREAUTH_FRAME_BYTES,
)
from tests.unit.ws._auth_rig import Rig, Sock, hang_up

# -- the helper block (digest-only reporting) ----------------------------------------------------
EXAMPLES: Final[int] = int(os.environ.get("CV_FUZZ_EXAMPLES", "200"))
SEED: Final[int] = int(os.environ.get("CV_FUZZ_SEED", "12648430"))


def digest(data: bytes) -> str:
    """How a failure names its input without printing it: sha256 over the seed and the input."""
    return hashlib.sha256(f"{SEED}:".encode() + data).hexdigest()


class Input:
    """One fuzz input, built on demand. Its `repr` is its target and digest alone."""

    __slots__ = ("_build", "target")

    def __init__(self, target: str, build: Callable[[], bytes]) -> None:
        self.target = target
        self._build = build

    @property
    def data(self) -> bytes:
        return self._build()

    def __repr__(self) -> str:
        return f"{self.target} sha256={digest(self.data)}"


def save_failure(case: Input) -> str:
    """The only text a failure may carry: its target and digest. Nothing is written: the seed and
    the example count replay the run."""
    return repr(case)


FUZZ_SETTINGS: Final = settings(
    max_examples=EXAMPLES,
    deadline=None,
    suppress_health_check=list(HealthCheck),
    database=None,
    print_blob=False,
    verbosity=Verbosity.quiet,
    phases=[p for p in Phase if p is not Phase.explain],
)


def drive(cases: st.SearchStrategy[Input], check: Callable[[Input], None]) -> None:
    """Runs `check` on `cases` under `FUZZ_SETTINGS`, from `SEED`."""
    seed(SEED)(FUZZ_SETTINGS(given(cases)(check)))()


# -- frames --------------------------------------------------------------------------------------
_STATES: Final = ("fresh", "hello", "auth")
#: Integers at the edges a field or an encoder has, and past 64 bits up to the int-string limit.
_EDGES: Final = (0, -1, 2**31, 2**53 - 1, 2**53, 2**63, 2**64 - 1, -(2**63))
_HUGE: Final = (2**64, -(2**64) - 1, 10**306, 10**400, -(10**4300 - 1))
_EDGE_INTS: Final = _EDGES + _HUGE
#: Lone surrogates, built at run time: a literal one breaks tools that encode the source.
_LONE: Final = tuple(chr(c) for c in (0xD800, 0xDBFF, 0xDC00, 0xDFFF))
_TOPICS: Final = (
    *("book.BTCUSDT.50", "trades.BTCUSDT", "bars.BTCUSDT.time.1", "positions", "orders"),
    *("wallet", "alerts", "system"),
)
_TYPES: Final = ("hello", "auth", "ping", "pong", "sub", "unsub", "ctl", "resync")
#: What each frame type's `p` may hold; the gateway reads these keys.
_PAYLOAD_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "hello": ("clock_ms", "protocol", "client", "capabilities"),
    "auth": ("access_token",),
    "ping": ("client_ms",),
    "pong": ("server_ms",),
    "sub": ("topics", "snapshot", "replay_session_id"),
    "unsub": ("topics",),
    "ctl": ("throttle_ms", "paused", "encoding", "exchange_account_ids"),
    "resync": ("sub_id", "last_seq", "reason"),
}
#: Sorted, so a seed draws the same keys in every process (a set's order follows the hash seed).
_READ: Final = sorted({k for keys in _PAYLOAD_KEYS.values() for k in keys})
_KEYS: Final = ("t", "id", "p", "ch", "rs", *_READ)
_SCALARS: Final = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.sampled_from(_EDGE_INTS),
    st.floats(),  # NaN and the infinities included: `json.dumps` writes NaN and Infinity
    st.text(max_size=24),
    st.sampled_from(_LONE).map(lambda s: f"a{s}b"),
    st.sampled_from(_TOPICS),
)


def _containers(inner: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    keys = st.sampled_from(_KEYS) | st.text(max_size=8)
    return st.lists(inner, max_size=6) | st.dictionaries(keys, inner, max_size=6)


_VALUES: Final = st.recursive(_SCALARS, _containers, max_leaves=24)


def _pick(draw: st.DrawFn, *weighted: tuple[int, st.SearchStrategy[Any]]) -> Any:
    """A draw from one of `weighted`, each picked in proportion to its weight."""
    n = draw(st.integers(0, sum(w for w, _ in weighted) - 1))
    for weight, strategy in weighted:
        if n < weight:
            return draw(strategy)
        n -= weight
    raise AssertionError("unreachable")


@st.composite
def _field(draw: st.DrawFn) -> Any:
    """A value for a field the gateway reads: an integer past 64 bits two times in five, one at an
    edge one in five, else any value."""
    edges, huge = st.sampled_from(_EDGES), st.sampled_from(_HUGE)
    return _pick(draw, (2, huge), (1, edges), (1, _SCALARS), (1, _VALUES))


_ENTRY: Final = st.sampled_from(_TOPICS) | st.fixed_dictionaries(
    {"ch": st.sampled_from(_TOPICS) | _SCALARS},
    optional={"opts": st.dictionaries(st.sampled_from(_KEYS) | st.text(max_size=8), _VALUES)},
)


def _payload(kind: str) -> st.SearchStrategy[Any]:
    """The `p` of a frame of `kind`: the first key the gateway reads for it, then maybe the
    others, each drawn as a field; any value for a type it does not know."""
    keys = _PAYLOAD_KEYS.get(kind)
    if keys is None:
        return _VALUES
    special = {
        "topics": st.lists(_ENTRY | _VALUES, max_size=8),
        "access_token": st.sampled_from(["good-1", "bad"]) | _SCALARS,
    }
    drawn = {k: special.get(k, _field()) for k in keys}
    first, *rest = keys
    return st.fixed_dictionaries({first: drawn[first]}, optional={k: drawn[k] for k in rest})


def _render(members: list[tuple[str, Any]], ascii_only: bool) -> str:
    """The members as one JSON object's text, in order, a repeated key included."""

    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=ascii_only)

    return "{" + ",".join(f"{dumps(k)}:{dumps(v)}" for k, v in members) + "}"


@st.composite
def _frames(draw: st.DrawFn) -> tuple[str, str]:
    """(state, text): a frame of a known type seven times in eight (as a socket's first frame, a
    `hello` three times in four), with a drawn `p`, maybe a `ch` and more members (a repeated key
    among them); then, one time in seven each, its `p` nested about `MAX_JSON_DEPTH` deep, widened
    to about `MAX_JSON_CONTAINERS` containers, or padded to about the state's size cap."""
    state = draw(st.sampled_from(_STATES))
    kind = _pick(draw, (7, st.sampled_from(_TYPES)), (1, st.text(max_size=8)))
    if state == "fresh" and draw(st.integers(0, 3)) > 0:
        kind = "hello"  # most first frames are a `hello`: anything else ends the socket at once
    members: list[tuple[str, Any]] = [("t", kind), ("id", draw(_SCALARS))]
    members.append(("p", _pick(draw, (3, _payload(kind)), (1, _VALUES))))
    if draw(st.booleans()):
        members.append(("ch", draw(st.sampled_from(_TOPICS) | _SCALARS)))
    members += draw(st.lists(st.tuples(st.sampled_from(_KEYS), _VALUES), max_size=3))
    shape = draw(st.sampled_from(("plain", "plain", "plain", "plain", "deep", "wide", "padded")))
    if shape == "deep":
        depth = draw(st.integers(MAX_JSON_DEPTH - 4, MAX_JSON_DEPTH + 4))
        nested: Any = members[2][1]
        for _ in range(depth):
            nested = [nested] if draw(st.booleans()) else {"a": nested}
        members[2] = ("p", nested)
    elif shape == "wide":
        wide = draw(st.integers(MAX_JSON_CONTAINERS - 8, MAX_JSON_CONTAINERS + 8))
        members[2] = ("p", [[]] * wide)
    text = _render(members, ascii_only=draw(st.booleans()))
    try:
        text.encode()
    except UnicodeEncodeError:  # a lone surrogate unescaped: no server delivers that
        text = _render(members, ascii_only=True)
    if shape == "padded":
        cap = MAX_INBOUND_FRAME_BYTES if state == "auth" else MAX_PREAUTH_FRAME_BYTES
        room = cap + draw(st.integers(-2, 1)) - len(text.encode()) - len(',"pad":""')
        if room > 0:
            text = text[:-1] + ',"pad":"' + "x" * room + '"}'
    return state, text


# -- the check -----------------------------------------------------------------------------------
_TARGET: Final = "json_frame_dispatch"
_END: Final = "cv-fuzz-end"  # the id of the `ping` that follows the frame
_BOUND_S: Final = 5.0


async def _until(sock: Sock, kind: str) -> None:
    while (await sock.sent.get())["t"] != kind:
        pass


async def _answer(sock: Sock) -> str:
    """Reads what the socket sent until the `ping` after the frame is answered or a `bye` comes:
    why that is a fault, or "". A top-level `err` of `internal_error` is one, as a `bye` of it is:
    the catalogue lists the code, but this rig never sends it at the top level."""
    while True:
        frame = await sock.sent.get()
        kind, p = frame.get("t"), frame.get("p")
        if kind == "err" and isinstance(p, dict):
            if p.get("code") == "internal_error":
                return "internal_error"
            if p.get("code") not in WS_ERROR_CODES:
                return "err outside the catalogue"
        if kind == "bye" and isinstance(p, dict):
            reason = p.get("reason")
            if reason == "internal_error":
                return "internal_error"
            return "" if reason in CLOSE_REASONS else "bye outside the catalogue"
        if kind == "pong" and frame.get("id") == _END:
            return ""


async def _one(rig: Rig, state: str, text: str, user: int) -> str:
    """One socket taken to `state` (as user `user`, after `auth_ok`), then `text` and a `ping`: why
    the result is a fault, or ""."""
    sock, why = Sock(), ""
    handler = rig.start(sock)
    try:
        async with asyncio.timeout(_BOUND_S):
            if state != "fresh":
                sock.feed({"t": "hello", "id": "h"})
                await _until(sock, "welcome")
            if state == "auth":
                sock.feed({"t": "auth", "id": "a", "p": {"access_token": f"good-{user}"}})
                await _until(sock, "auth_ok")
            sock.inbound.put_nowait({"type": "websocket.receive", "text": text})
            sock.feed({"t": "ping", "id": _END})
            why = await _answer(sock)
    except TimeoutError:
        why = "" if sock.codes and 1011 not in sock.codes else "no answer"
    hang_up(sock)
    try:
        async with asyncio.timeout(_BOUND_S):
            await handler
    except Exception as exc:  # the handler raised, or did not end
        why = why or f"handler ended with {type(exc).__name__}"
    return why or ("closed 1011" if 1011 in sock.codes else "")


def _faults(rig: Rig, loop: asyncio.AbstractEventLoop, state: str, text: str, user: int) -> str:
    with capture_logs() as logs:
        why = loop.run_until_complete(_one(rig, state, text, user))
    if not why and any(e.get("event") == "ws connection fault" for e in logs):
        why = "a connection fault was logged"
    return why


def _check_all(cases: st.SearchStrategy[tuple[str, str]]) -> None:
    loop, rig, users = asyncio.new_event_loop(), Rig(), itertools.count(1)

    def check(case: Input) -> None:
        state, text = json.loads(case.data)
        why = _faults(rig, loop, state, text, next(users))
        del state, text  # nothing derived from the input stays in the frame that fails
        if why:
            raise AssertionError(f"{why}: {save_failure(case)}") from None

    def as_input(pair: tuple[str, str]) -> Input:
        data = json.dumps(pair).encode()
        return Input(_TARGET, lambda: data)

    try:
        drive(cases.map(as_input), check)
    finally:
        loop.close()


@pytest.mark.fuzz
def test_json_frames_get_an_answer_and_never_a_fault() -> None:
    _check_all(_frames())


#: Named frames for the PR lane: the edges the fuzz draws, each in the state it matters in.
_HELLO: Final = '{"t":"hello","id":"h","p":{"clock_ms":'
_PING: Final = '{"t":"ping","id":"p","p":{"client_ms":'
_NAMED: Final[dict[str, tuple[str, str]]] = {
    "hello-clock-past-2-53": ("fresh", f"{_HELLO}{2**53}}}}}"),
    "hello-clock-400-digits": ("fresh", f"{_HELLO}{10**400}}}}}"),
    "ping-client-ms-negative-4300-digits": ("hello", f"{_PING}{-(10**4300 - 1)}}}}}"),
    "ping-client-ms-nan": ("hello", '{"t":"ping","id":"p","p":{"client_ms":NaN}}'),
    "ping-id-lone-surrogate": ("hello", '{"t":"ping","id":"\\ud800","p":{}}'),
    "sub-duplicate-keys": ("auth", '{"t":"sub","t":"ping","id":"s","p":{"topics":["system"]}}'),
    "sub-option-infinity": (
        "auth",
        '{"t":"sub","id":"s","p":{"topics":[{"ch":"book.BTCUSDT.50",'
        '"opts":{"throttle_ms":Infinity}}]}}',
    ),
    "ping-nested-past-the-depth": (
        "auth",
        '{"t":"ping","id":"p","p":' + "[" * MAX_JSON_DEPTH + "]" * MAX_JSON_DEPTH + "}",
    ),
    "ping-past-the-cap-before-auth-ok": (
        "hello",
        '{"t":"ping","id":"p","p":"' + "x" * MAX_PREAUTH_FRAME_BYTES + '"}',
    ),
}


@pytest.mark.parametrize(("state", "text"), list(_NAMED.values()), ids=list(_NAMED))
def test_each_named_frame_gets_an_answer_and_no_fault(state: str, text: str) -> None:
    loop = asyncio.new_event_loop()
    try:
        assert _faults(Rig(), loop, state, text, 1) == ""
    finally:
        loop.close()


@pytest.mark.parametrize(
    ("code", "fault"), [("internal_error", "internal_error"), ("forbidden", "")]
)
def test_the_check_takes_a_top_level_internal_error_for_a_fault(code: str, fault: str) -> None:
    """What the socket sent, then the `pong`: an `err` of `internal_error` is a fault, as its `bye`
    is; one of another catalogue code is an answer."""
    sock = Sock()
    for frame in ({"t": "err", "id": "x", "p": {"code": code}}, {"t": "pong", "id": _END}):
        sock.sent.put_nowait(frame)
    assert asyncio.run(_answer(sock)) == fault
