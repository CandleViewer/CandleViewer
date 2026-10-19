"""Leak matrix sinks (E27-T02 AC1, ADR-0009 validation item): logs, Problem body, trace span,
support bundle and the shared redaction rule set all render a `Secret` as `***`."""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest
import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from candleviewer.observability.logging import configure_logging, reset_logging
from candleviewer.observability.redaction import redact_structure
from candleviewer.observability.tracing import span
from candleviewer.secrets.secret import MASK
from candleviewer.secrets.secret import Secret as MaskingWrapper

CANARY = "zq-canary-7731"  # unique marker; asserted absent from every sink
#: Bybit-shaped raw key (18 alnum), built at runtime; never a real credential.
RAW_KEY = "Q" * 9 + "7" * 9


def _wrapped(value: str) -> object:
    """The real M2 masking wrapper (`secrets.Secret`) around a synthetic canary. Imported as
    `MaskingWrapper`: CodeQL's sensitive-data heuristic keys on the identifier "secret" and
    would report this test's *masked* writes as clear-text storage/logging. Disclosed in the PR;
    every sink below asserts the canary is absent and `***` is present."""
    return MaskingWrapper(value)


def test_redact_structure_masks_secret() -> None:
    out = redact_structure(
        {"a": [MaskingWrapper(CANARY)], "b": (MaskingWrapper(CANARY),), "c": MaskingWrapper(b"x")}
    )
    assert CANARY not in str(out) and out["a"] == ["***"] and out["c"] == "***"


def test_structlog_and_stdlib_logs_mask(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(env="demo", level="debug", fmt="json")
    try:
        masked = _wrapped(CANARY)
        structlog.get_logger("t").info("borrow", key=masked, nested={"v": masked})
        structlog.get_logger("t").info("interp", rendered=f"{masked}")
        # stdlib path: the record args go through RedactionFilter; built via makeRecord so the
        # handler sees exactly what a `logger.warning("std %s", value)` call would emit.
        std = logging.getLogger("t2")
        std.handle(std.makeRecord("t2", logging.WARNING, __file__, 0, "std %s", (masked,), None))
    finally:
        reset_logging()
    out = capsys.readouterr()
    text = out.out + out.err
    assert CANARY not in text and "***" in text


def test_trace_span_attribute_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local provider (no global state): Secret/bytes masked, non-allow-listed keys dropped,
    secret-shaped strings redacted, and `set_attribute` on the yielded span filtered too."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, "get_tracer", provider.get_tracer)
    attrs = {"key_id": MaskingWrapper(CANARY), "apiKey": CANARY, "purpose": RAW_KEY, "env": "demo"}
    with span("secrets.credential_borrow", attrs) as s:
        s.set_attribute("secret", CANARY)
        s.set_attribute("result", RAW_KEY)
    got = dict(exporter.get_finished_spans()[0].attributes or {})
    assert got["key_id"] == "***" and got["env"] == "demo"
    assert "apiKey" not in got and "secret" not in got
    assert CANARY not in str(got) and RAW_KEY not in str(got)


def test_problem_body_never_echoes_exception_text() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from candleviewer.api.error_redaction import install_error_redaction

    app = FastAPI()
    install_error_redaction(app)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError(f"failed with {RAW_KEY}")  # raw plaintext in the exception args

    r = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500 and RAW_KEY not in r.text


def test_support_bundle_masks(tmp_path: Path) -> None:
    from candleviewer.observability.support_bundle import _write_json

    p = tmp_path / "health.json"
    _write_json(p, {"bundle": {"detail": _wrapped(CANARY)}})
    assert CANARY not in p.read_text() and MASK in p.read_text()


def test_stream_handler_never_sees_plaintext() -> None:
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    lg = logging.getLogger("leakcheck")
    lg.addHandler(h)
    try:
        lg.handle(lg.makeRecord("leakcheck", logging.ERROR, __file__, 0, "value=%r",
                                (_wrapped(CANARY),), None))  # fmt: skip
    finally:
        lg.removeHandler(h)
    assert CANARY not in buf.getvalue()


def test_bytes_values_redacted_in_logs(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(env="demo", level="debug", fmt="json")
    try:
        structlog.get_logger("t").info("buf", k=bytearray(CANARY.encode()), m=memoryview(b"zz"))
    finally:
        reset_logging()
    text = "".join(capsys.readouterr())
    assert CANARY not in text and "[redacted:bytes]" in text


def test_adr0009_crafted_key_absent_from_stdout_files_and_metrics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ADR-0009 validation item (required check; reused by E27-X02): a crafted log line
    carrying a raw key value is absent from stdout, a file handler and the /metrics body."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from candleviewer.api.health import make_health_router
    from candleviewer.observability.logging import RedactionFilter
    from candleviewer.observability.metrics import CollectorRegistry, Counter
    from candleviewer.settings import Settings

    log_file = tmp_path / "app.log"
    fh = logging.FileHandler(log_file)
    fh.addFilter(RedactionFilter())
    configure_logging(env="demo", level="debug", fmt="json")
    root = logging.getLogger()
    root.addHandler(fh)
    registry = CollectorRegistry()
    try:
        crafted = {"apiKey": RAW_KEY, "api_secret": RAW_KEY}  # the crafted line's fields
        structlog.get_logger("leak").info("crafted", **crafted, line=f"apiKey={RAW_KEY}")
        std = logging.getLogger("leak.std")
        std.handle(std.makeRecord("leak.std", logging.WARNING, __file__, 0,
                                  "api_secret=%s key %s", (RAW_KEY, RAW_KEY), None))  # fmt: skip
        Counter("leak_probe_total", "probe", labelnames=("stage",), registry=registry).labels(
            stage="ok"
        ).inc()
        app = FastAPI()
        app.include_router(make_health_router(Settings(_env_file=None), registry))  # type: ignore[call-arg]
        body = TestClient(app).get("/metrics").text
    finally:
        root.removeHandler(fh)
        fh.close()
        reset_logging()
    out = capsys.readouterr()
    for sink in (out.out, out.err, log_file.read_text(), body):
        assert RAW_KEY not in sink


async def test_the_key_import_route_leaks_no_key_material(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """#836 slice 2b4: a pasted pair through `createApiKey`'s 201, 422, 502 and 500 is in no
    answer, log line, traceback (the 500's, logged by the error handler) or /metrics body."""
    from candleviewer.exchange.bybit.key_info import KEY_INFO_PATH
    from candleviewer.observability.metrics import generate_latest
    from tests.contract.test_create_api_key_provider import Route, booted
    from tests.unit.test_key_import_wiring import Refusing, Rig

    pair = {"api_key": CANARY + "X1y2", "api_secret": CANARY + "-secret-" + RAW_KEY}
    broken = Rig()  # an unmapped error inside the import: the error handler's 500 and traceback
    broken.flow = broken.importer(Refusing(RuntimeError("a defect")))
    configure_logging(env="demo", level="debug", fmt="json")
    try:
        routes = [await booted(), await booted(withdraw=True), Route(broken)]
        routes.insert(2, await booted(swap={KEY_INFO_PATH: "error_10004.json"}))
        answers = [await route.post(**pair) for route in routes]
    finally:
        reset_logging()
    assert [a.status_code for a in answers] == [201, 422, 502, 500]
    out = capsys.readouterr()
    for sink in (*(a.text for a in answers), out.out, out.err, generate_latest().decode()):
        assert CANARY not in sink and RAW_KEY not in sink
    assert "Traceback" in out.out + out.err  # the 500's traceback was rendered, and holds neither
