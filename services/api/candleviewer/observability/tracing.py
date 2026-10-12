"""OpenTelemetry span scaffolding for the two ADR-0014 §5 paths (E04-T06).

Only these span names may be started — tracing market-data hot loops is
rejected by ADR-0014 §5 / E04-K01, so `span()` refuses any other name.
E29 (order path) and E26 (replay start) attach the real spans against this
scaffolding. With `CV_OTEL_ENABLED=false` (the default) the OpenTelemetry
API's no-op tracer is used: no exporter, no network.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Final

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import Span

from candleviewer.observability.redaction import redact_text
from candleviewer.observability.secret_type import Secret

TRACER_NAME: Final = "candleviewer"

#: Order path, in causal order, then replay session start.
ORDER_PATH_SPANS: Final[tuple[str, ...]] = (
    "http.request",
    "oms.validate",
    "oms.fanout",
    "exchange.place_order",
    "private_ws.fill",
)
REPLAY_SPANS: Final[tuple[str, ...]] = ("replay.session_start",)
#: E27-T02: one span per credential borrow (on the order path, inside `exchange.place_order`).
CREDENTIAL_SPANS: Final[tuple[str, ...]] = ("secrets.credential_borrow",)
#: Attribute keys any sanctioned span may carry (ids / bounded enums only, never values).
SPAN_ATTRIBUTE_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "key_id",
        "exchange_account_id",
        "env",
        "kek_version",
        "caller_module",
        "purpose",
        "result",
        "order_link_id",
        "symbol",
        "session_id",
        "http.method",
        "http.route",
        "http.status_code",
    }
)
SANCTIONED_SPANS: Final[frozenset[str]] = frozenset(
    ORDER_PATH_SPANS + REPLAY_SPANS + CREDENTIAL_SPANS
)


class UnsanctionedSpanError(ValueError):
    """A span name outside the ADR-0014 §5 allow-list."""


@contextmanager
def span(name: str, attributes: Mapping[str, object] | None = None) -> Iterator[Span]:
    """Start a sanctioned span as the current span."""
    if name not in SANCTIONED_SPANS:
        raise UnsanctionedSpanError(f"span {name!r} is not on an ADR-0014 §5 path")
    tracer = trace.get_tracer(TRACER_NAME)
    with tracer.start_as_current_span(name, attributes=_safe_attrs(attributes or {})) as s:
        yield _GuardedSpan(s)  # type: ignore[misc]  # wraps set_attribute with the same filter


def _safe_attrs(attributes: Mapping[str, object]) -> dict[str, str | int | bool]:
    """Allow-listed keys only; `Secret`→`***`; strings run through the redaction rule set."""
    out: dict[str, str | int | bool] = {}
    for key, value in attributes.items():
        if key not in SPAN_ATTRIBUTE_ALLOWLIST:
            continue
        if isinstance(value, Secret) or isinstance(value, bytes | bytearray | memoryview):
            out[key] = "***"
        elif isinstance(value, bool | int):
            out[key] = value
        else:
            out[key] = redact_text(str(value))
    return out


class _GuardedSpan:
    """Proxy whose `set_attribute(s)` apply `_safe_attrs`; everything else passes through."""

    __slots__ = ("_span",)

    def __init__(self, span_: Span) -> None:
        self._span = span_

    def set_attribute(self, key: str, value: object) -> None:
        for k, v in _safe_attrs({key: value}).items():
            self._span.set_attribute(k, v)

    def set_attributes(self, attributes: Mapping[str, object]) -> None:
        for k, v in _safe_attrs(attributes).items():
            self._span.set_attribute(k, v)

    def __getattr__(self, name: str) -> object:
        return getattr(self._span, name)


def inject_context(carrier: dict[str, str]) -> dict[str, str]:
    """Write W3C `traceparent` into `carrier` (outbound propagation)."""
    inject(carrier)
    return carrier


@contextmanager
def attach_context(carrier: Mapping[str, str]) -> Iterator[None]:
    """Make an inbound `traceparent` the current context for the block."""
    token = otel_context.attach(extract(dict(carrier)))
    try:
        yield
    finally:
        otel_context.detach(token)
