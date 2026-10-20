"""uvicorn's own loggers use the app's log config (SR-121, `observability/logging.py`).

`candleviewer.server` builds `uvicorn.Config(APP, **uvicorn_kwargs())`. uvicorn applies its logging
config in `Config.__init__`; the app module is imported afterwards, and importing it calls
`configure_logging()` (`candleviewer/main.py`). These tests replay that boot order with no sleep
and no network (two of them drive a real server on loopback). They call the loggers the way
uvicorn's server and protocols do and check what reached stdout, stderr and the support bundle's
log buffer: uvicorn's lines must be redacted JSON from the root handler, and nothing may come
from a handler uvicorn installed itself.

Secret-shaped canaries are assembled at runtime so no literal sits in the repo
(`tests/security/test_e04_abuse_cases.py`).
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
import socket
import traceback
from collections.abc import Awaitable, Callable, Iterator
from contextlib import redirect_stderr, redirect_stdout, suppress
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

import pytest
import uvicorn
from websockets.frames import Frame, Opcode

from candleviewer.observability.logging import UpgradeLineFilter, configure_logging, reset_logging
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_server import MetricsRuntime
from candleviewer.observability.support_bundle_wiring import LogRingBuffer
from candleviewer.server import APP, uvicorn_kwargs
from candleviewer.settings import Settings

#: The loggers uvicorn's server and protocols write to (`uvicorn/config.py`, `uvicorn/protocols`).
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi")

#: 24 alphanumerics: value-shaped (`observability/redaction.py`), so BOTH the structlog processor
#: and the handler filter redact it.
SHAPED = "".join(("Zq9X", "w3Lm", "Pv7R", "t2Yb", "Nc4H", "dK8s"))
#: Short and not value-shaped. Only the handler filter redacts it: it sees the `api_secret` key of
#: a dict argument, while the processor only sees the formatted string. A root handler without the
#: filter therefore shows up here and nowhere else.
KEYED = "-".join(("canary", "key", "name", "only"))

_MARKER = re.compile(r"\[redacted:[a-z-]+\]")
_EPOCH = datetime.fromtimestamp(0, UTC)
#: uvicorn's HTTP access-line format (`uvicorn/protocols/http/h11_impl.py`).
_ACCESS = '%s - "%s %s HTTP/%s" %d'


class _LoggerState(NamedTuple):
    handlers: list[logging.Handler]
    propagate: bool
    level: int
    disabled: bool


_FRESH = _LoggerState([], True, logging.NOTSET, False)


def _state(name: str) -> _LoggerState:
    lg = logging.getLogger(name)
    return _LoggerState(list(lg.handlers), lg.propagate, lg.level, lg.disabled)


def _apply(name: str, state: _LoggerState) -> None:
    lg = logging.getLogger(name)
    lg.handlers = list(state.handlers)
    lg.propagate = state.propagate
    lg.setLevel(state.level)
    lg.disabled = state.disabled


@pytest.fixture(autouse=True)
def _fresh_uvicorn_loggers() -> Iterator[None]:
    """Start from the loggers a fresh interpreter has, and put back what was there.

    A `uvicorn.Config` changes these loggers for the whole process: `log_level` sets their level
    (the real-socket server tests pass `log_level="warning"`), and uvicorn's default `log_config`
    adds handlers and `propagate=False` (the regression this file guards against).
    `configure_logging()` undoes neither.
    """
    before = {name: _state(name) for name in _UVICORN_LOGGERS}
    for name in _UVICORN_LOGGERS:
        _apply(name, _FRESH)
    yield
    for name, state in before.items():
        _apply(name, state)


class _Captured(NamedTuple):
    out: str
    err: str
    ring: tuple[str, ...] = ()

    def lines(self) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = [json.loads(line) for line in self.out.splitlines()]
        return parsed

    def events(self) -> list[tuple[str, str]]:
        """`(level, event)` per JSON line, with redaction markers collapsed to `<redacted>`."""
        return [(rec["level"], _MARKER.sub("<redacted>", rec["event"])) for rec in self.lines()]

    def ring_lines(self) -> list[str]:
        """The support bundle's log buffer, oldest first, markers collapsed to `<redacted>`."""
        return [_MARKER.sub("<redacted>", line) for line in self.ring]


def _replay_boot(
    emit: Callable[[], None],
    *,
    level: str = "info",
    config_first: bool = True,
    ring: bool = False,
) -> _Captured:
    """Boot logging the way the server does, call `emit()`, return what reached each sink.

    `config_first` is the server's own order (uvicorn's `Config.__init__`, then the app import).
    `False` builds the `uvicorn.Config` after the app configured logging, as a second uvicorn
    server in the process would; the `/metrics` listener's own `Config` is the subject of
    `test_metrics_listener_mutes_the_http_access_line_but_not_websocket_lines`. `ring` adds the
    support bundle's `LogRingBuffer` to the root logger, as `build_support_bundle_service` does.
    """
    out, err = io.StringIO(), io.StringIO()
    buffer = LogRingBuffer() if ring else None
    with redirect_stdout(out), redirect_stderr(err):
        if config_first:
            uvicorn.Config(APP, **uvicorn_kwargs(Settings()))
        configure_logging(env="ci", level=level, fmt="json")
        if buffer is not None:
            logging.getLogger().addHandler(buffer)
        if not config_first:
            uvicorn.Config(APP, **uvicorn_kwargs(Settings()))
        try:
            emit()
        finally:
            if buffer is not None:
                logging.getLogger().removeHandler(buffer)
            reset_logging()  # stops the QueueListener, which writes every queued record first
    window = buffer.window(_EPOCH, datetime.now(UTC) + timedelta(hours=1)) if buffer else []
    # `window` is newest first; the tests read the lines in emission order
    return _Captured(out.getvalue(), err.getvalue(), tuple(reversed(window)))


def _lifespan_failure_text(*, detail: str = "") -> str:
    """The text Starlette hands uvicorn when the lifespan fails (`traceback.format_exc()`).

    uvicorn logs it as one message with no `exc_info` and no args (`uvicorn/lifespan/on.py`).
    """
    try:
        raise ConnectionRefusedError(111, f"Connect call failed ('127.0.0.1', 5432){detail}")
    except ConnectionRefusedError:
        return traceback.format_exc()


def _emit_as_uvicorn(*, with_exception: bool = True) -> None:
    """The calls uvicorn makes: an application exception, a failed start, warnings, access lines."""
    error = logging.getLogger("uvicorn.error")
    if with_exception:
        try:
            raise RuntimeError(f"failed with {SHAPED}")
        except RuntimeError as exc:
            error.error("Exception in ASGI application\n", exc_info=exc)  # h11/httptools `run_asgi`
    error.error(_lifespan_failure_text())  # no secret in it: the class name alone is value-shaped
    error.error(_lifespan_failure_text(detail=f" {SHAPED}"))  # `lifespan.startup.failed`
    error.warning("upstream replied %s", SHAPED)
    error.warning("request context %s", {"api_secret": KEYED})
    access = logging.getLogger("uvicorn.access")
    shaped_path = f"/ws?x={SHAPED}"
    access.info(_ACCESS, "127.0.0.1:50000", "GET", shaped_path, "1.1", 200)
    access.info(_ACCESS, "127.0.0.1:50000", "GET", "/health/live", "1.1", 200)


def test_uvicorn_kwargs_leave_logging_config_to_the_app() -> None:
    kwargs = uvicorn_kwargs(Settings())
    assert "log_config" in kwargs, "uvicorn would apply its own default logging config"
    assert kwargs["log_config"] is None

    uvicorn.Config(APP, **kwargs)

    for name in _UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        assert logger.handlers == [], f"{name} has a handler of its own"
        assert logger.propagate is True, f"{name} does not propagate to the root handler"


@pytest.mark.parametrize("config_first", [True, False], ids=["config-then-app", "app-then-config"])
def test_uvicorn_lines_reach_the_redacted_json_log_and_nowhere_else(config_first: bool) -> None:
    got = _replay_boot(_emit_as_uvicorn, config_first=config_first)

    assert got.err == "", "a handler uvicorn installed itself wrote to stderr"
    for canary in (SHAPED, KEYED):
        assert canary not in got.err
        assert canary not in got.out
    assert got.events() == [
        ("error", "Exception in ASGI application\n"),
        # a failed start: uvicorn logs the whole traceback as one text, and any value-shaped token
        # in it (here the class name `ConnectionRefusedError`) turns the whole text into one marker
        ("error", "<redacted>"),
        ("error", "<redacted>"),
        ("warning", "upstream replied <redacted>"),
        ("warning", "request context {'api_secret': '<redacted>'}"),
        ("info", '127.0.0.1:50000 - "GET <redacted> HTTP/1.1" 200'),
        ("info", '127.0.0.1:50000 - "GET /health/live HTTP/1.1" 200'),
    ]
    # A record's traceback is rendered, then redacted where each value stands (#415): its frames
    # stay, and the value-shaped text of the exception is a marker.
    exception = got.lines()[0]["exception"]
    assert exception.startswith("Traceback (most recent call last):\n")
    assert exception.endswith("RuntimeError: failed with [redacted:key-shape]")


@pytest.mark.parametrize("name", _UVICORN_LOGGERS)
def test_every_uvicorn_logger_writes_through_the_root_handler(name: str) -> None:
    got = _replay_boot(lambda: logging.getLogger(name).warning("upstream replied %s", SHAPED))

    assert got.err == ""
    assert SHAPED not in got.out
    assert got.events() == [("warning", "upstream replied <redacted>")]


def test_uvicorn_lines_reach_the_support_bundle_log_buffer_redacted() -> None:
    """The buffer filters on its own: for a record with no args, only its `RedactionFilter` does."""
    got = _replay_boot(lambda: _emit_as_uvicorn(with_exception=False), ring=True)

    assert got.err == ""
    for canary in (SHAPED, KEYED):
        assert canary not in "\n".join(got.ring)
    assert got.ring_lines() == [
        "ERROR uvicorn.error <redacted>",
        "ERROR uvicorn.error <redacted>",
        "WARNING uvicorn.error upstream replied <redacted>",
        "WARNING uvicorn.error request context {'api_secret': '<redacted>'}",
        'INFO uvicorn.access 127.0.0.1:50000 - "GET <redacted> HTTP/1.1" 200',
        'INFO uvicorn.access 127.0.0.1:50000 - "GET /health/live HTTP/1.1" 200',
    ]
    assert len(got.events()) == len(got.ring)  # the same records reached stdout


def test_uvicorn_lines_follow_the_app_log_level() -> None:
    got = _replay_boot(_emit_as_uvicorn, level="warning")

    assert got.err == ""
    # the two INFO access lines are below `CV_LOG_LEVEL`; uvicorn imposes no level of its own
    assert [level for level, _ in got.events()] == ["error"] * 3 + ["warning"] * 2


def test_metrics_listener_mutes_the_http_access_line_but_not_websocket_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The listener's `uvicorn.Config(log_config=None, access_log=False)` clears the shared
    `uvicorn.access` logger. uvicorn's protocols emit the HTTP access line only if it
    `hasHandlers()`, so that line stops. WebSocket handshake lines log on `uvicorn.error` and stay.
    """

    async def no_serve(self: uvicorn.Server, sockets: object = None) -> None:
        """The real `serve` binds the listener's socket; only its `Config` matters here."""

    monkeypatch.setattr(uvicorn.Server, "serve", no_serve)

    def emit() -> None:
        async def start_the_listener_then_log() -> None:
            runtime = MetricsRuntime(Metrics("dev"), "127.0.0.1:9108")
            runtime.start()
            try:
                access = logging.getLogger("uvicorn.access")
                assert not access.hasHandlers(), "uvicorn would still emit the HTTP access line"
                access.info(_ACCESS, "127.0.0.1:50000", "GET", "/health/live", "1.1", 200)
                logging.getLogger("uvicorn.error").info(
                    '%s - "WebSocket %s" [accepted]', "127.0.0.1:50000", "/ws"
                )
            finally:
                await runtime.stop()

        asyncio.run(start_the_listener_then_log())

    got = _replay_boot(emit)

    assert got.err == ""
    assert got.events() == [("info", '127.0.0.1:50000 - "WebSocket /ws" [accepted]')]


#: A 43-character URL-safe value, assembled at runtime (no literal).
VALUE = "".join(
    ("Zq9X", "w3Lm", "Pv7R", "t2Yb", "Nc4H", "dK8s", "Ae5F", "gJ6u", "Vx1o", "Bq3Y", "m0W")
)
#: Request targets an upgrade may carry (`{p}` is the path, `{v}` the value).
_TARGETS = {
    "plain": "{p}?access_token={v}",
    "short-name": "{p}?token={v}",
    "second": "{p}?a=1&access_token={v}",
    "prefixed": "{p}?access_token=Bearer%20{v}",
    "quoted": "{p}?access_token=%22{v}%22",
    "encoded": "{p}%3Faccess_token={v}",
    "parameter": "{p};access_token={v}",
    "absolute": "ws://localhost{p}?access_token=%22{v}%22",
}


#: A cookie that an accepted upgrade sets in its response: only the header's name can hide it.
_SET_COOKIE = [(b"set-cookie", f"access_token=%22{VALUE}%22".encode())]


async def _bare_app(scope: Any, receive: Any, send: Any) -> None:
    """Accepts a WebSocket upgrade whose target names `/ws`, however it is spelled, with a cookie
    in the response, and refuses every other."""
    if scope["type"] == "websocket":
        await receive()  # websocket.connect
        if b"/ws" in scope["raw_path"]:
            await send({"type": "websocket.accept", "headers": _SET_COOKIE})
            await receive()  # the client's close
        else:
            await send({"type": "websocket.close"})


async def _denial_app(scope: Any, receive: Any, send: Any) -> None:
    """Refuses every WebSocket upgrade with a response of its own, a status line and a body
    (`websocket.http.response.*`): uvicorn logs that refusal with its status code."""
    if scope["type"] == "websocket":
        await receive()  # websocket.connect
        await send({"type": "websocket.http.response.start", "status": 404, "headers": []})
        await send({"type": "websocket.http.response.body", "body": b""})


def _upgrade_request(target: str) -> bytes:
    """The handshake of a client, written as it is: `target` as the request target, and a cookie."""
    key = base64.b64encode(bytes(16)).decode()
    headers = ["Host: localhost", "Upgrade: websocket", "Connection: Upgrade"]
    headers += [f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
    headers += [f"Cookie: access_token=%22{VALUE}%22"]
    return "\r\n".join([f"GET {target} HTTP/1.1", *headers, "", ""]).encode("ascii")


async def _upgrade_to(*targets: str, app: Callable[..., Awaitable[None]] = _bare_app) -> None:
    """Each of `targets` as the request target of a WebSocket upgrade, one after the other, to a
    real uvicorn server (the production kwargs, a loopback port) running `app`."""
    kwargs = uvicorn_kwargs(Settings())
    del kwargs["host"], kwargs["port"]  # the pre-bound loopback socket below
    config = uvicorn.Config(app, lifespan="off", **kwargs)
    config.load()
    server = uvicorn.Server(config)
    server.lifespan = config.lifespan_class(config)  # as `Server.serve` does before `startup`
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        await server.startup(sockets=[sock])
        try:
            async with asyncio.timeout(10):
                for target in targets:
                    reader, writer = await asyncio.open_connection(*sock.getsockname())
                    writer.write(_upgrade_request(target))
                    await reader.readuntil(b"\r\n\r\n")  # the 101, or the head of a refusal
                    writer.close()
                    with suppress(ConnectionError):
                        await writer.wait_closed()
        finally:
            await server.shutdown(sockets=[sock])


@pytest.mark.parametrize(
    ("level", "request_lines"),
    [
        ("info", []),
        (
            "debug",
            [
                "< GET /ws HTTP/1.1",
                "< cookie: <redacted>",
                "< GET /other HTTP/1.1",
                "< cookie: <redacted>",
            ],
        ),
    ],
)
@pytest.mark.parametrize("target", _TARGETS.values(), ids=_TARGETS.keys())
def test_websocket_upgrade_lines_name_the_path_and_not_the_query(
    target: str, level: str, request_lines: list[str]
) -> None:
    """The accepted and refused lines (INFO) and the request, cookie and set-cookie lines (DEBUG)
    of an upgrade with a query string, as a real server writes them and the app's log config
    formats them: the path alone and the cookies' markers, on stdout and in the support bundle's
    buffer."""
    targets = [target.format(p=path, v=VALUE) for path in ("/ws", "/other")]
    got = _replay_boot(lambda: asyncio.run(_upgrade_to(*targets)), level=level, ring=True)

    assert got.err == ""
    assert VALUE not in "\n".join((got.out, got.err, *got.ring))
    lines = [event for _, event in got.events()]
    upgrades = [m[1] for line in lines if (m := re.match(r'\S+ - ("WebSocket .*)', line))]
    assert upgrades == ['"WebSocket /ws" [accepted]', '"WebSocket /other" 403']
    assert [line for line in lines if line.startswith(("< GET", "< cookie"))] == request_lines
    set_cookie = ["> set-cookie: <redacted>"] if level == "debug" else []  # the response header
    assert [line for line in lines if line.startswith("> set-cookie")] == set_cookie


@pytest.mark.parametrize("level", ["info", "debug"])
def test_websocket_denial_response_lines_name_the_path_and_not_the_query(level: str) -> None:
    """The line of an upgrade that the app refuses with a response of its own: uvicorn writes it
    with the status code (`"WebSocket /other" 404`), in a call apart from the accepted line and
    the `403` of a close, so the real server checks its format against the pinned library."""
    targets = [_TARGETS["quoted"].format(p=path, v=VALUE) for path in ("/ws", "/other")]
    got = _replay_boot(
        lambda: asyncio.run(_upgrade_to(*targets, app=_denial_app)), level=level, ring=True
    )

    assert got.err == ""
    assert VALUE not in "\n".join((got.out, got.err, *got.ring))
    lines = [event for _, event in got.events()]
    upgrades = [m[1] for line in lines if (m := re.match(r'\S+ - ("WebSocket .*)', line))]
    assert upgrades == ['"WebSocket /ws" 404', '"WebSocket /other" 404']


def test_a_websocket_frame_line_reaches_the_buffer_redacted_as_on_stdout() -> None:
    """websockets logs a frame at DEBUG as `< %s` with the frame itself (`protocol.py`), so its text
    is rendered after the filters ran. The buffer redacts the rendered line as stdout's chain
    does (#415): here an auth frame whose elided preview ends with 20 characters of its token."""
    auth = {"t": "auth", "id": "c-2", "p": {"access_token": VALUE}}
    frame = Frame(Opcode.TEXT, json.dumps(auth, separators=(",", ":")).encode())
    got = _replay_boot(
        lambda: logging.getLogger("uvicorn.error").debug("< %s", frame), level="debug", ring=True
    )

    shown = str(frame)
    assert VALUE[-20:] in shown  # the preview shows 20 characters of the token
    assert VALUE[-20:] not in "\n".join((got.out, *got.ring))
    start = shown.index('"access_token":"') + len('"access_token":"')
    end = shown.index('"', start)
    line = f"< {shown[:start]}<redacted>{shown[end:]}"  # the label stays; its value is a marker
    assert got.events() == [("debug", line)]
    assert got.ring_lines() == [f"DEBUG uvicorn.error {line}"]


def _upgrade_filters() -> list[UpgradeLineFilter]:
    lg = logging.getLogger("uvicorn.error")
    return [f for f in lg.filters if isinstance(f, UpgradeLineFilter)]


def _record(msg: str, args: object) -> logging.LogRecord:
    return logging.makeLogRecord({"name": "uvicorn.error", "msg": msg, "args": args})


def test_configure_logging_installs_one_upgrade_line_filter_and_reset_removes_it() -> None:
    configure_logging(env="ci")
    configure_logging(env="ci")
    try:
        assert len(_upgrade_filters()) == 1
    finally:
        reset_logging()
    assert _upgrade_filters() == []


#: The lines that name a request target, as `(format, arguments before it, arguments after it)`.
_FORMATS = [
    ('%s - "WebSocket %s" [accepted]', ("127.0.0.1:50000",), ()),
    ('%s - "WebSocket %s" 403', ("127.0.0.1:50000",), ()),
    ('%s - "WebSocket %s" %d', ("127.0.0.1:50000",), (404,)),
    ("< %s %s %s", ("GET",), ("HTTP/1.1",)),
]
#: A target as a line names it (uvicorn's lines write it percent-encoded) and the path that stays.
_CUTS = [
    ("/ws", "/ws"),
    ("/a-b_c.d~e/ws?x=1", "/a-b_c.d~e/ws"),  # the unreserved punctuation stays
    ("/Api/V1/ws?x=1", "/Api/V1/ws"),  # so do upper case letters and digits
    ("/ws?a=b", "/ws"),
    ("/ws%3Fa=b", "/ws"),
    ("/ws;a=b", "/ws"),
    ("/ws%3Ba%3Db", "/ws"),
    ("/ws#a", "/ws"),
    ("/ws%23a", "/ws"),
    ("ws://localhost/ws?a=b", "/ws"),
    ("ws%3A//localhost%3A8000/ws?a=b", "/ws"),
    ("ws://localhost?a=/b", ""),  # no path: nothing of the query stays
    ("ws://localhost#a/b", ""),  # nor of the fragment
]


@pytest.mark.parametrize(
    ("msg", "before", "after"),
    _FORMATS,
    ids=["accepted", "refused", "status", "request-line"],
)
@pytest.mark.parametrize(("target", "path"), _CUTS)
def test_upgrade_line_filter_keeps_the_path_of_the_target_and_the_other_arguments(
    msg: str, before: tuple[str, ...], after: tuple[object, ...], target: str, path: str
) -> None:
    record = _record(msg, (*before, target, *after))

    assert UpgradeLineFilter().filter(record) is True
    assert record.args == (*before, path, *after)


@pytest.mark.parametrize(
    ("msg", "args"),
    [
        ("upstream replied %s", ("/ws?a=b",)),
        ("%s replied %s", ("peer", "/ws?a=b")),
        ("%s rejected: %s", ("token", "reason text")),
        ('%s - "WebSocket %s" [accepted]', ("127.0.0.1:50000",)),
        ('%s - "WebSocket %s" %d', ("127.0.0.1:50000", b"/ws?a=b", 404)),
        ("< %s: %s", ("Host", "localhost:8000/ws?a=b")),
        ("> %s: %s", ("Sec-WebSocket-Accept", "a?b")),
        ("%(path)s", {"path": "/ws?a=b"}),
    ],
    ids=[
        "other-line",
        "other-two-arguments",
        "other-key-name",
        "no-target",
        "not-a-str",
        "request-header",
        "response-header",
        "mapping",
    ],
)
def test_upgrade_line_filter_leaves_any_other_argument_as_it_is(msg: str, args: object) -> None:
    record = _record(msg, args)

    assert UpgradeLineFilter().filter(record) is True
    assert record.args == args


@pytest.mark.parametrize("msg", ["< %s: %s", "> %s: %s"], ids=["request", "response"])
@pytest.mark.parametrize("name", ["Cookie", "authorization", " Set-Cookie "])
def test_upgrade_line_filter_replaces_the_value_of_a_header_named_as_a_secret(
    msg: str, name: str
) -> None:
    record = _record(msg, (name, f"access_token=%22{VALUE}%22"))

    assert UpgradeLineFilter().filter(record) is True
    assert record.args == (name, "[redacted:key-name]")
