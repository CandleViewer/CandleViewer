"""`configure_logging()` — the single logging entry point (E04-T01).

Called exactly once at process start by every entrypoint (FastAPI lifespan
in `candleviewer/main.py`, and future ingestion/recorder/replay worker
entrypoints). Wires:

- A `QueueHandler`/`QueueListener` pair so a slow stdout pipe reader cannot
  block the asyncio event loop (Performance notes). The listener thread is a
  daemon, so an `atexit` hook stops it at exit: the queue is written out
  first, and the last lines of a failed start are not lost.
- `structlog`'s processor chain, in the exact order the ticket's Technical
  notes mandate: `merge_contextvars` -> `add_log_level` -> UTC ISO timestamp
  -> `StackInfoRenderer` -> `format_exc_info` -> **redaction** ->
  `JSONRenderer`. Redaction sits after `format_exc_info` so a traceback is
  already a string by the time it is scanned. On every path, exception text is
  rendered before it is redacted (#415): stack and traceback text is redacted
  where each value stands, so it keeps its frames and lines, and an exception
  logged as a value or an argument is turned into its text first.
- A stdlib bridge (`structlog.stdlib.ProcessorFormatter`) *and* a
  `RedactionFilter` attached directly to the handler — the ProcessorFormatter
  path only runs for stdlib records that reach that handler, so the filter is
  the actual backstop for anything that formats its own message. The filter
  renders a record's traceback and stores it redacted, with its stack; the
  formatter writes both into the line (`_record_text`).
- An `UpgradeLineFilter` on the `uvicorn.error` logger, ahead of every handler: the log lines of a
  WebSocket upgrade show the path of its request target only, and a header line shows a marker
  for the value of a header named as a secret. `reset_logging()` removes it.
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import logging.handlers
import queue
import re
import sys
from typing import Any, Final

import structlog
from structlog.types import EventDict, Processor

from candleviewer.observability.redaction import (
    _KEY_NAME_MARKER,
    _is_redact_key,
    _redact_mapping,
    _redact_runs,
    _redact_str_value,
    _redact_value,
)

_VALID_LEVELS: Final[frozenset[str]] = frozenset({"debug", "info", "warning", "error", "critical"})

#: Fields the field-shape scenario says must be omitted (never rendered as
#: the string `"None"`) when absent.
_OMIT_IF_NONE: Final[tuple[str, ...]] = (
    "request_id",
    "conn_id",
    "user_id",
    "account_id",
    "symbol",
    "order_link_id",
    "trade_group_id",
    "latency_ms",
)

_listener: logging.handlers.QueueListener | None = None


def _stop_listener_at_exit() -> None:
    """`atexit` hook: let the listener thread write the queue out before the process ends.

    The thread is a daemon, so a record logged just before the interpreter exits (uvicorn's
    `Application startup failed. Exiting.` before exit code 3) can still be on the queue and be
    lost. `stop()` returns once the queue is empty. It runs once: the listener is dropped first.
    Errors are ignored as in `logging.shutdown`: nothing is left to report them to at exit.
    """
    global _listener
    listener, _listener = _listener, None
    if listener is not None:
        with contextlib.suppress(Exception):
            listener.stop()


class _RawQueueHandler(logging.handlers.QueueHandler):
    """`QueueHandler` that passes records through unmodified.

    The stdlib `QueueHandler.prepare()` calls `self.format(record)` and
    replaces `record.msg` with the formatted *string*, which destroys the
    dict payload `structlog.stdlib.ProcessorFormatter` expects on the other
    end of the queue. Formatting must happen once, in the listener's
    handler, not twice.
    """

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        return record


class RedactionFilter(logging.Filter):
    """Stdlib `logging.Filter` — the handler-level backstop (SR-121).

    Attached to the root handler so records from *any* logger (structlog's
    own bridge, or a plain `logging.getLogger(__name__)` call site that never
    touches structlog) are scrubbed before they reach stdout.

    Per the Security notes failure mode: redaction must never crash the
    caller. Any exception inside `filter()` causes the *record* to be
    dropped (not emitted unredacted) rather than propagating.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            self._redact_record(record)
        except Exception:  # fail closed, never leak the raw record
            return False
        return True

    @staticmethod
    def _redact_record(record: logging.LogRecord) -> None:
        if isinstance(record.msg, str) and record.args:
            # A format string keeps its placeholders: no labelled value is replaced in it. The line
            # it renders gets every rule, on stdout and in the support bundle's buffer (#415).
            record.msg = _redact_str_value(record.msg, labels=False)
        elif isinstance(record.msg, (str, BaseException)):
            record.msg = _redact_value(record.msg, depth=0)
        if record.args:
            if isinstance(record.args, dict):
                record.args = _redact_mapping(record.args)
            else:
                record.args = tuple(_redact_value(a, depth=0) for a in record.args)
        for key, value in list(record.__dict__.items()):
            if key in ("msg", "args", "exc_info", "exc_text", "stack_info"):
                continue
            if isinstance(value, (str, dict, list, tuple, BaseException)):
                record.__dict__[key] = _redact_value(value, depth=0)
        exc_info, exc_text = record.exc_info, record.exc_text
        if exc_info and not exc_text:
            # Render the traceback here, so that no formatter renders it after the filter ran.
            exc_text = logging.Formatter().formatException(exc_info)
        if exc_text:
            # Stored only once redacted: the handlers of a record share it, across threads.
            record.exc_text = _redact_runs(exc_text)
            record.exc_info = None
        if record.stack_info:
            record.stack_info = _redact_runs(record.stack_info)


#: Lines of `uvicorn.error` that name the request target of a WebSocket upgrade, by how their
#: format starts; the target is the second argument. They are uvicorn's accepted, refused and
#: HTTP-response lines (INFO) and the websockets server's request line (DEBUG).
#: A changed library format leaves its line uncut: the real-server tests are the guard.
_TARGET_LINES: Final = ('%s - "WebSocket %s"', "< %s %s %s")
#: The websockets server's request and response header lines (DEBUG): the name, then the value.
_HEADER_LINES: Final = ("< %s: %s", "> %s: %s")
#: The first character that is not part of a path: anything but unreserved characters and `/`.
#: uvicorn writes a target percent-encoded, so an encoded `?`, `;` or `#` ends the path too.
_NOT_PATH = re.compile(r"[^A-Za-z0-9/._~-]")
#: The scheme and authority in front of the path of an absolute-form target (`ws://host/ws`);
#: uvicorn writes its colon as `%3A`.
_SCHEME_AUTHORITY = re.compile(r"\A[A-Za-z][A-Za-z0-9+.-]*(?::|%3[Aa])//[^/?#]*")


class UpgradeLineFilter(logging.Filter):
    """Log lines of a WebSocket upgrade, on `uvicorn.error`, show the path of its target only.

    The gateway reads no query string (`23-ws-protocol.md` §4.3). In the `_TARGET_LINES` the target
    is cut to its path: a query string, a path parameter, a fragment and their percent-encoded
    spellings end it, and the scheme and host of an absolute-form target are dropped. In the
    `_HEADER_LINES` the value of a header named as a secret (`_REDACT_KEYS`) is replaced by its
    marker. Any other argument is left as it is. On the logger, the filter runs before every
    handler, so stdout and the support bundle's buffer get the same line.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg, args = record.msg, record.args
        if isinstance(msg, str) and isinstance(args, tuple) and len(args) > 1:
            if msg.startswith(_TARGET_LINES) and isinstance(args[1], str):
                record.args = (args[0], _path_of(args[1]), *args[2:])
            elif msg in _HEADER_LINES and _is_redact_key(args[0]):
                record.args = (args[0], _KEY_NAME_MARKER, *args[2:])
        return True


def _path_of(target: str) -> str:
    """The leading run of path characters of a request target, after its authority if it has one:
    `/ws?a=b`, `/ws%3Fa=b`, `/ws;a=b`, `/ws#a` and `http://host/ws?a=b` are all `/ws`."""
    return _NOT_PATH.split(_SCHEME_AUTHORITY.sub("", target, count=1), maxsplit=1)[0]


_UPGRADE_LOGGER: Final = "uvicorn.error"
_UPGRADE_FILTER: Final = UpgradeLineFilter()


#: Event fields that hold the text of a stack or a traceback: `StackInfoRenderer` and
#: `format_exc_info` write them, and `_record_text` for a stdlib record.
_TEXT_FIELDS: Final = ("stack", "exception")


def _redaction_processor(logger: object, method_name: str, event_dict: EventDict) -> EventDict:
    """`structlog` processor form of the same redaction rule set. The text of a stack or a
    traceback is redacted where each value stands (`_redact_runs`): its frames and lines stay."""
    if "exception" not in event_dict and "stack" not in event_dict:
        return _redact_mapping(dict(event_dict))
    fields = dict(event_dict)
    texts = {key: fields.pop(key) for key in _TEXT_FIELDS if isinstance(fields.get(key), str)}
    redacted = _redact_mapping(fields)
    for key, text in texts.items():
        redacted[key] = _redact_runs(text)
    return redacted


def _record_text(logger: object, method_name: str, event_dict: EventDict) -> EventDict:
    """A stdlib record's traceback and stack, as the handler's `RedactionFilter` stored them.

    The filter renders `exc_info` into `exc_text` and clears it, so `format_exc_info` finds no
    exception, and `StackInfoRenderer` would replace the record's `stack_info` with the stack of
    the thread that formats the line. First in the formatter's `foreign_pre_chain` only.
    """
    record = event_dict.get("_record")
    if isinstance(record, logging.LogRecord):
        if record.exc_text and "exc_info" not in event_dict:
            event_dict["exception"] = record.exc_text
        if record.stack_info:
            event_dict.pop("stack_info", None)
            event_dict["stack"] = record.stack_info
    return event_dict


def _drop_none_correlation_fields(
    logger: object, method_name: str, event_dict: EventDict
) -> EventDict:
    """Omit mandatory correlation fields entirely when their value is `None`."""
    for key in _OMIT_IF_NONE:
        if key in event_dict and event_dict[key] is None:
            del event_dict[key]
    return event_dict


def _orjson_serializer(obj: Any, **kwargs: Any) -> str:
    import orjson

    return orjson.dumps(obj, default=str).decode("utf-8")


def configure_logging(
    *,
    env: str,
    level: str = "info",
    fmt: str = "json",
) -> None:
    """Configure process-wide logging. Call exactly once, at process start.

    Args:
        env: `CV_ENV` value (`live`/`demo`/`testnet`/`dev`/`ci`...), stamped
            onto every record so demo and live logs never blur together.
        level: `CV_LOG_LEVEL`, one of debug/info/warning/error/critical
            (case-insensitive).
        fmt: `CV_LOG_FORMAT`, `"json"` or `"console"`. `"console"` is only
            permitted when `env == "dev"` (or `"ci"`) — anything else raises,
            per the ticket's config-key note.
    """
    level_name = level.lower()
    if level_name not in _VALID_LEVELS:
        raise ValueError(f"CV_LOG_LEVEL must be one of {sorted(_VALID_LEVELS)}, got {level!r}")

    if fmt not in ("json", "console"):
        raise ValueError(f"CV_LOG_FORMAT must be 'json' or 'console', got {fmt!r}")
    if fmt == "console" and env not in ("dev", "ci"):
        raise ValueError(
            f"CV_LOG_FORMAT=console is only permitted when CV_ENV is 'dev' or 'ci' (got {env!r})"
        )

    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _drop_none_correlation_fields,
        _redaction_processor,
    ]

    renderer: Processor
    if fmt == "console":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer(serializer=_orjson_serializer)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level_name.upper())),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[_record_text, *shared_processors],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    log_queue: queue.Queue[Any] = queue.Queue(-1)
    queue_handler = _RawQueueHandler(log_queue)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(RedactionFilter())

    listener = logging.handlers.QueueListener(log_queue, stream_handler, respect_handler_level=True)
    listener.start()
    _listener = listener
    atexit.unregister(_stop_listener_at_exit)  # one hook, however often this runs
    atexit.register(_stop_listener_at_exit)

    root = logging.getLogger()
    root.handlers = [queue_handler]
    root.setLevel(getattr(logging, level_name.upper()))
    logging.getLogger(_UPGRADE_LOGGER).addFilter(_UPGRADE_FILTER)  # the one instance, once

    # `env` is bound onto every subsequent structlog call via contextvars so
    # every log line carries it without every call site passing it manually.
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(env=env)


def reset_logging() -> None:
    """Undo `configure_logging()`: stop the listener, drop its root handler and the upgrade-line
    filter, reset structlog.

    Test-isolation helper (C-13.7); safe to call when nothing was configured.
    """
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not isinstance(h, _RawQueueHandler)]
    root.setLevel(logging.WARNING)
    logging.getLogger(_UPGRADE_LOGGER).removeFilter(_UPGRADE_FILTER)
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
