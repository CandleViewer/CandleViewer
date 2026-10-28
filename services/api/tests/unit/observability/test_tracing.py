"""E04-T06: OTel scaffolding — only ADR-0014 §5 spans; W3C context propagation."""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode

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


def test_span_order_path_names_are_20_12_3s() -> None:
    """`20-architecture.md` §12.3's names (`tests/contract/test_order_path_spans_contract.py` ties
    them to the text): a single order's submission and its children, the fan-out, the create and
    the fill."""
    assert ORDER_PATH_SPANS == (
        "http.request",
        "oms.submit",
        "oms.validate",
        "oms.persist",
        "oms.send",
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


def test_an_order_link_id_reaches_its_span_as_the_logs_keep_it() -> None:
    """20 Sec.12.3's `oms.submit` carries its `order_link_id`: a Sec.8.3 id under that key is kept
    as the log redactor's typed pass keeps it (#3865), where a scan alone would mask its key-shape
    word; any other value under the key, or a Sec.8.3 id under another key, is scanned."""
    link = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"  # 24 Sec.8.3's worked example
    with span("oms.submit", {"order_link_id": link, "symbol": link}):
        pass
    with span("oms.submit", {"order_link_id": link + "-x"}):  # no Sec.8.3 form: scanned
        pass
    with span("oms.submit", {"order_link_id": 7}):  # the typed pass comes before an int's own
        pass
    kept, scanned, numbered = (dict(s.attributes or {}) for s in _EXPORTER.get_finished_spans())
    assert kept["order_link_id"] == link and kept["symbol"] != link
    assert scanned["order_link_id"].startswith("[redacted")
    assert numbered["order_link_id"] == "7"


_REFUSED = "account 9b2f7c1e refused at 60000.5"  # a message no span may carry (C-12.6)


def test_a_recorded_exception_leaves_only_its_class_on_the_span() -> None:
    """The proxy's `record_exception` (20 Sec.12.3): the class as the span's `ERROR` status, with
    no exception event, no message and no traceback, as a raised one leaves."""
    with span("oms.submit") as current:
        current.record_exception(ValueError(_REFUSED))
    [ended] = _EXPORTER.get_finished_spans()
    assert (ended.status.status_code, ended.status.description) == (StatusCode.ERROR, "ValueError")
    assert list(ended.events) == [] and "refused" not in ended.to_json()


def test_an_events_attributes_pass_the_spans_allow_list() -> None:
    link = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"  # 24 Sec.8.3's worked example
    with span("oms.submit") as current:
        current.add_event("checkpoint", {"order_link_id": link, "detail": _REFUSED})
    [ended] = _EXPORTER.get_finished_spans()
    [event] = ended.events
    assert (event.name, dict(event.attributes or {})) == ("checkpoint", {"order_link_id": link})


@pytest.mark.parametrize(
    ("status", "kept"),
    [
        ((Status(StatusCode.ERROR, "ValueError"),), "ValueError"),
        ((Status(StatusCode.ERROR, f"ValueError: {_REFUSED}"),), None),
        ((StatusCode.ERROR, _REFUSED), None),
    ],
    ids=["a_class_name", "a_message_in_a_status", "a_message_beside_a_code"],
)
def test_a_status_keeps_its_description_only_as_a_class_name(
    status: tuple[object, ...], kept: str | None
) -> None:
    with span("oms.submit") as current:
        current.set_status(*status)  # each of the two forms `Span.set_status` takes
    [ended] = _EXPORTER.get_finished_spans()
    assert (ended.status.status_code, ended.status.description) == (StatusCode.ERROR, kept)
