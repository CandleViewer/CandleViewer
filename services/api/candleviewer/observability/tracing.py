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
SANCTIONED_SPANS: Final[frozenset[str]] = frozenset(ORDER_PATH_SPANS + REPLAY_SPANS)


class UnsanctionedSpanError(ValueError):
    """A span name outside the ADR-0014 §5 allow-list."""


@contextmanager
def span(name: str, attributes: Mapping[str, object] | None = None) -> Iterator[Span]:
    """Start a sanctioned span as the current span."""
    if name not in SANCTIONED_SPANS:
        raise UnsanctionedSpanError(f"span {name!r} is not on an ADR-0014 §5 path")
    tracer = trace.get_tracer(TRACER_NAME)
    attrs = {k: "***" if isinstance(v, Secret) else v for k, v in (attributes or {}).items()}
    with tracer.start_as_current_span(name, attributes=attrs) as s:
        yield s


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
