"""uvicorn's own loggers use the app's log config (SR-121, `observability/logging.py`).

`candleviewer.server` builds `uvicorn.Config(APP, **uvicorn_kwargs())`. uvicorn applies its logging
config in `Config.__init__`; the app module is imported afterwards, and importing it calls
`configure_logging()` (`candleviewer/main.py`). These tests replay that boot order with no socket,
no sleep and no network. They call the loggers the way uvicorn's server and protocols do and check
what reached stdout, stderr and the support bundle's log buffer: uvicorn's lines must be redacted
JSON from the root handler, and nothing may come from a handler uvicorn installed itself.

Secret-shaped canaries are assembled at runtime so no literal sits in the repo
(`tests/security/test_e04_abuse_cases.py`).
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import traceback
from collections.abc import Callable, Iterator
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

import pytest
import uvicorn

from candleviewer.observability.logging import configure_logging, reset_logging
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
    # Today a record's traceback is not rendered at all: `RedactionFilter` moves `exc_info` to
    # `exc_text`, which the JSON formatter drops. Pinning the absence tells "dropped" from
    # "redacted"; rendering it redacted is a follow-up that changes this assertion on purpose.
    assert "exception" not in got.lines()[0]


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
