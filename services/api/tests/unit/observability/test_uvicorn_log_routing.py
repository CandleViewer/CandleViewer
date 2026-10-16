"""uvicorn's own loggers use the app's log config (SR-121, `observability/logging.py`).

`candleviewer.server` builds `uvicorn.Config(APP, **uvicorn_kwargs())`. uvicorn applies its logging
config in `Config.__init__`; the app module is imported afterwards, and importing it calls
`configure_logging()` (`candleviewer/main.py`). These tests replay that boot order with no socket,
no sleep and no network. They call the loggers the way uvicorn's server and protocols do and check
what reached stdout and stderr: uvicorn's lines must be redacted JSON from the root handler, and
nothing may come from a handler uvicorn installed itself.

Secret-shaped canaries are assembled at runtime so no literal sits in the repo
(`tests/security/test_e04_abuse_cases.py`).
"""

from __future__ import annotations

import io
import json
import logging
import re
from collections.abc import Callable, Iterator
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, NamedTuple

import pytest
import uvicorn

from candleviewer.observability.logging import configure_logging, reset_logging
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

    def lines(self) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = [json.loads(line) for line in self.out.splitlines()]
        return parsed

    def events(self) -> list[tuple[str, str]]:
        """`(level, event)` per JSON line, with redaction markers collapsed to `<redacted>`."""
        return [(rec["level"], _MARKER.sub("<redacted>", rec["event"])) for rec in self.lines()]


def _replay_boot(
    emit: Callable[[], None], *, level: str = "info", config_first: bool = True
) -> _Captured:
    """Boot logging the way the server does, call `emit()`, return what reached stdout/stderr.

    `config_first` is the server's own order (uvicorn's `Config.__init__`, then the app import).
    `False` builds the `uvicorn.Config` after the app configured logging, as the `/metrics`
    listener does inside the lifespan.
    """
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        if config_first:
            uvicorn.Config(APP, **uvicorn_kwargs(Settings()))
        configure_logging(env="ci", level=level, fmt="json")
        if not config_first:
            uvicorn.Config(APP, **uvicorn_kwargs(Settings()))
        emit()
        reset_logging()  # stops the QueueListener, which writes every queued record first
    return _Captured(out.getvalue(), err.getvalue())


def _emit_as_uvicorn() -> None:
    """The calls uvicorn makes: an unhandled application exception, a warning, access lines."""
    error = logging.getLogger("uvicorn.error")
    try:
        raise RuntimeError(f"failed with {SHAPED}")
    except RuntimeError as exc:
        error.error("Exception in ASGI application\n", exc_info=exc)  # h11/httptools `run_asgi`
    error.warning("upstream replied %s", SHAPED)
    error.warning("request context %s", {"api_secret": KEYED})
    access = logging.getLogger("uvicorn.access")
    shaped_path = f"/ws?x={SHAPED}"
    access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:50000", "GET", shaped_path, "1.1", 200)
    access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:50000", "GET", "/health/live", "1.1", 200)


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
        ("warning", "upstream replied <redacted>"),
        ("warning", "request context {'api_secret': '<redacted>'}"),
        ("info", '127.0.0.1:50000 - "GET <redacted> HTTP/1.1" 200'),
        ("info", '127.0.0.1:50000 - "GET /health/live HTTP/1.1" 200'),
    ]


@pytest.mark.parametrize("name", _UVICORN_LOGGERS)
def test_every_uvicorn_logger_writes_through_the_root_handler(name: str) -> None:
    got = _replay_boot(lambda: logging.getLogger(name).warning("upstream replied %s", SHAPED))

    assert got.err == ""
    assert SHAPED not in got.out
    assert got.events() == [("warning", "upstream replied <redacted>")]


def test_uvicorn_lines_follow_the_app_log_level() -> None:
    got = _replay_boot(_emit_as_uvicorn, level="warning")

    assert got.err == ""
    # the two INFO access lines are below `CV_LOG_LEVEL`; uvicorn imposes no level of its own
    assert [level for level, _ in got.events()] == ["error", "warning", "warning"]
