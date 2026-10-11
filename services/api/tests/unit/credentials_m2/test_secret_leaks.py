"""Leak matrix (E27-T02 AC1, ADR-0009 validation item): a Secret never renders anywhere."""

from __future__ import annotations

import copy
import io
import json
import logging
import pickle
from pathlib import Path
from typing import Any

import pytest
import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from candleviewer.observability.logging import configure_logging, reset_logging
from candleviewer.observability.redaction import redact_structure
from candleviewer.observability.tracing import SANCTIONED_SPANS, span
from candleviewer.secrets import _envelope as env
from candleviewer.secrets.secret import MASK, Secret

CANARY = "topsecret"


def test_render_paths_mask() -> None:
    s = Secret(CANARY)
    for out in (f"{s}", repr(s), str(s), format(s, ">20"), f"{s}", str([s]), str({"k": s})):
        assert CANARY not in out and MASK in out


@pytest.mark.parametrize("op", [pickle.dumps, copy.copy, copy.deepcopy, lambda s: s.model_dump()])
def test_serialise_paths_refuse(op: Any) -> None:
    with pytest.raises(TypeError):
        op(Secret(CANARY))


def test_json_default_str_masks() -> None:
    out = json.dumps({"k": Secret(CANARY)}, default=str)
    assert CANARY not in out and MASK in out


def test_redact_structure_masks_secret() -> None:
    out = redact_structure({"a": [Secret(CANARY)], "b": (Secret(CANARY),), "c": Secret(b"x")})
    assert CANARY not in str(out) and out["a"] == ["***"]


def test_structlog_and_stdlib_logs_mask(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(env="demo", level="debug", fmt="json")
    try:
        structlog.get_logger("t").info("borrow", key=Secret(CANARY), nested={"v": Secret(CANARY)})
        structlog.get_logger("t").info(f"interp {Secret(CANARY)}")
        logging.getLogger("t2").warning("std %s", Secret(CANARY))
    finally:
        reset_logging()
    out = capsys.readouterr()
    text = out.out + out.err
    assert CANARY not in text and "***" in text


def test_trace_span_attribute_masks() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)  # first set wins; fall back to local provider below
    name = sorted(SANCTIONED_SPANS)[0]
    tracer_provider = trace.get_tracer_provider()
    if tracer_provider is not provider:
        pytest.skip("global tracer provider already set by another test")  # pragma: no cover
    with span(name, {"key": Secret(CANARY), "key_id": "k1"}):
        pass
    attrs = dict(exporter.get_finished_spans()[0].attributes or {})
    assert attrs["key"] == "***" and CANARY not in str(attrs)


def test_problem_body_masks() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from candleviewer.api.error_redaction import install_error_redaction

    app = FastAPI()
    install_error_redaction(app)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError(f"failed with {Secret(CANARY)}")

    r = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500 and CANARY not in r.text


def test_support_bundle_masks(tmp_path: Path) -> None:
    from candleviewer.observability.support_bundle import _write_json

    p = tmp_path / "health.json"
    _write_json(p, {"secrets": {"detail": Secret(CANARY)}})
    assert CANARY not in p.read_text() and MASK in p.read_text()


def test_exception_text_never_contains_key_material() -> None:
    from candleviewer.secrets.errors import CredentialUnavailable

    e = CredentialUnavailable("credential_unavailable")
    assert str(e) == "credential_unavailable"


def test_zero_wipes_buffer() -> None:
    b = bytearray(b"abc")
    env.zero(b)
    assert b == bytearray(3)


def test_stream_handler_never_sees_plaintext() -> None:
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    lg = logging.getLogger("leakcheck")
    lg.addHandler(h)
    try:
        lg.error("value=%r", Secret(CANARY))
    finally:
        lg.removeHandler(h)
    assert CANARY not in buf.getvalue()
