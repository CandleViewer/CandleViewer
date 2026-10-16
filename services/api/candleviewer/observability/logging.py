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
  already a string by the time it is scanned.
- A stdlib bridge (`structlog.stdlib.ProcessorFormatter`) *and* a
  `RedactionFilter` attached directly to the handler — the ProcessorFormatter
  path only runs for stdlib records that reach that handler, so the filter is
  the actual backstop for anything that formats its own message.
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import logging.handlers
import queue
import sys
from typing import Any, Final

import structlog
from structlog.types import EventDict, Processor

from candleviewer.observability.redaction import _redact_mapping, _redact_value

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
        if isinstance(record.msg, str):
            record.msg = _redact_value(record.msg, depth=0)
        if record.args:
            if isinstance(record.args, dict):
                record.args = _redact_mapping(record.args)
            else:
                record.args = tuple(_redact_value(a, depth=0) for a in record.args)
        for key, value in list(record.__dict__.items()):
            if key in ("msg", "args", "exc_info", "exc_text", "stack_info"):
                continue
            if isinstance(value, (str, dict, list, tuple)):
                record.__dict__[key] = _redact_value(value, depth=0)
        if record.exc_info and not record.exc_text:
            # Materialise the traceback now so the handler's formatter cannot
            # render the raw exception text after the filter has run.
            record.exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_info = None
        if record.exc_text:
            record.exc_text = _redact_value(record.exc_text, depth=0)


def _redaction_processor(logger: object, method_name: str, event_dict: EventDict) -> EventDict:
    """`structlog` processor form of the same redaction rule set."""
    return _redact_mapping(dict(event_dict))


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
        foreign_pre_chain=shared_processors,
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

    # `env` is bound onto every subsequent structlog call via contextvars so
    # every log line carries it without every call site passing it manually.
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(env=env)


def reset_logging() -> None:
    """Undo `configure_logging()`: stop the listener, drop its root handler, reset structlog.

    Test-isolation helper (C-13.7); safe to call when nothing was configured.
    """
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not isinstance(h, _RawQueueHandler)]
    root.setLevel(logging.WARNING)
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
