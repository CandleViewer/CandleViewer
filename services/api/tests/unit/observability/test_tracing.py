"""E04-T06: OTel scaffolding — only ADR-0014 §5 spans; W3C context propagation."""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from candleviewer.observability.tracing import (
    ORDER_PATH_SPANS,
    SANCTIONED_SPANS,
    UnsanctionedSpanError,
    attach_context,
    inject_context,
    span,
)

_EXPORTER = InMemorySpanExporter()
_PROVIDER = TracerProvider()
_PROVIDER.add_span_processor(SimpleSpanProcessor(_EXPORTER))


@pytest.fixture(autouse=True)
def _tracer(monkeypatch: pytest.MonkeyPatch) -> None:
    _EXPORTER.clear()
    monkeypatch.setattr(trace, "get_tracer", _PROVIDER.get_tracer)


def test_span_order_path_names_are_the_adr_0014_set() -> None:
    assert ORDER_PATH_SPANS == (
        "http.request",
        "oms.validate",
        "oms.fanout",
        "exchange.place_order",
        "private_ws.fill",
    )
    assert "replay.session_start" in SANCTIONED_SPANS


def test_span_rejects_market_data_hot_loop_names() -> None:
    with pytest.raises(UnsanctionedSpanError):
        with span("ingest.book_delta"):
            pass


def test_span_nests_order_path_under_one_trace() -> None:
    with span("http.request"), span("oms.validate", {"env": "demo"}):
        pass
    spans = {s.name: s for s in _EXPORTER.get_finished_spans()}
    assert spans["oms.validate"].parent is not None
    assert spans["oms.validate"].context.trace_id == spans["http.request"].context.trace_id


def test_context_propagates_across_boundary() -> None:
    with span("oms.fanout"):
        carrier = inject_context({})
    assert "traceparent" in carrier
    with attach_context(carrier), span("exchange.place_order"):
        pass
    by = {s.name: s for s in _EXPORTER.get_finished_spans()}
    assert by["exchange.place_order"].context.trace_id == by["oms.fanout"].context.trace_id


def test_a_raised_error_leaves_only_its_class_on_the_span() -> None:
    """20 Sec.12.3 (C-12.6): a span that ends in an exception is `ERROR` with the exception's class
    alone, the span it raises through too. Its message, which may name an account, a price or a
    key, reaches no span: no exception event, no status text beyond the class."""
    message = "account 9b2f7c1e refused at 60000.5"
    with pytest.raises(ValueError, match="refused"):
        with span("http.request"), span("oms.validate"):
            raise ValueError(message)
    finished = _EXPORTER.get_finished_spans()
    assert [s.name for s in finished] == ["oms.validate", "http.request"]
    for ended in finished:
        assert (ended.status.status_code, ended.status.description) == (
            StatusCode.ERROR,
            "ValueError",
        )
        assert list(ended.events) == []
        assert "refused" not in ended.to_json()


def test_a_span_that_ends_cleanly_keeps_its_status_unset() -> None:
    with span("oms.validate"):
        pass
    [ended] = _EXPORTER.get_finished_spans()
    assert ended.status.status_code is StatusCode.UNSET
