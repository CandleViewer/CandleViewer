"""E43-T01 (SR-112): `POST /api/v1/csp-report`. Public (no credential, no CSRF token), capped body,
per-IP rate limit, and a violation reduced to a closed directive + blocked type (+ host): no URL
path, query, source file or sample reaches the counter or the log."""

from __future__ import annotations

import json
from collections.abc import MutableMapping
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

import candleviewer.app as appmod
from candleviewer.api.csp_report import (
    MAX_BODY_BYTES,
    MAX_REPORTS_PER_WINDOW,
    MAX_TRACKED_CLIENTS,
    WINDOW_S,
    CspReportReceiver,
    classify_blocked,
    extract_violations,
    normalise_directive,
)
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.settings import Settings

LEGACY = "application/csp-report"
MODERN = "application/reports+json"


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Counter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def labels(self, *values: str) -> _Counter:
        self.calls.append(values)
        return self

    def inc(self) -> None:
        return None


def _client(
    counter: _Counter | None = None, clock: _Clock | None = None, enabled: bool = True
) -> TestClient:
    inner = FastAPI()  # the stack behind the receiver: answers 404 to everything else
    app = CspReportReceiver(inner, counter=counter, enabled=enabled, clock=clock or _Clock())
    return TestClient(app, client=("10.0.0.1", 5000))


def _legacy(**body: str) -> bytes:
    return json.dumps({"csp-report": body}).encode()


SCRIPT_INLINE = _legacy(
    **{"effective-directive": "script-src-elem", "blocked-uri": "inline", "script-sample": "SECRET"}
)


@pytest.mark.parametrize("path", ["/api/v1/csp-report", "/csp-report"])
def test_a_legacy_report_is_accepted_without_credentials_and_counted(path: str) -> None:
    counter = _Counter()
    with capture_logs() as logs:
        r = _client(counter).post(path, content=SCRIPT_INLINE, headers={"content-type": LEGACY})
    assert (r.status_code, r.content) == (204, b"")
    assert counter.calls == [("script-src-elem", "inline")]
    assert logs == [
        {
            "event": "security.csp_violation",
            "log_level": "warning",
            "directive": "script-src-elem",
            "blocked_type": "inline",
            "blocked_host": None,
        }
    ]


def test_a_reporting_api_list_is_accepted_and_reduced_to_scheme_and_host() -> None:
    counter = _Counter()
    body = json.dumps(
        [
            {
                "type": "csp-violation",
                "body": {
                    "effectiveDirective": "connect-src",
                    "blockedURL": "https://User:pw@Api.Bybit.com:443/v5/x?token=abc#frag",
                    "documentURL": "https://app/secret?token=zzz",
                },
            },
            {"type": "deprecation", "body": {"id": "x"}},
        ]
    ).encode()
    with capture_logs() as logs:
        r = _client(counter).post(
            "/api/v1/csp-report", content=body, headers={"content-type": MODERN + "; charset=utf-8"}
        )
    assert r.status_code == 204
    assert counter.calls == [("connect-src", "https")]
    assert logs[0]["blocked_host"] == "api.bybit.com"
    flat = json.dumps(logs)
    for leaked in ("token", "abc", "frag", "pw", "secret", "zzz", "/v5"):
        assert leaked not in flat


def test_nothing_of_the_report_but_the_closed_fields_is_logged() -> None:
    with capture_logs() as logs:
        _client().post("/csp-report", content=SCRIPT_INLINE, headers={"content-type": LEGACY})
    assert "SECRET" not in json.dumps(logs)
    assert set(logs[0]) == {"event", "log_level", "directive", "blocked_type", "blocked_host"}


def test_a_body_over_the_cap_is_refused_413_declared_or_streamed() -> None:
    big = b"x" * (MAX_BODY_BYTES + 1)
    counter = _Counter()
    r = _client(counter).post("/csp-report", content=big, headers={"content-type": LEGACY})
    assert r.status_code == 413
    assert r.headers["content-type"] == "application/problem+json"
    assert counter.calls == []

    chunks = [b"x" * (MAX_BODY_BYTES // 2 + 1)] * 2  # no Content-Length: counted as it streams
    r = _client(counter).post("/csp-report", content=iter(chunks), headers={"content-type": LEGACY})
    assert r.status_code == 413
    assert counter.calls == []


def test_a_body_at_the_cap_is_read() -> None:
    head = '{"csp-report": {"effective-directive": "img-src", "pad": "'
    tail = '"}}'
    body = head + "x" * (MAX_BODY_BYTES - len(head) - len(tail)) + tail
    assert len(body) == MAX_BODY_BYTES
    r = _client().post("/csp-report", content=body, headers={"content-type": LEGACY})
    assert r.status_code == 204


def test_the_rate_limit_is_per_client_ip_with_retry_after_and_reopens() -> None:
    clock = _Clock()
    client = _client(clock=clock)

    def post() -> Any:
        return client.post("/csp-report", content=SCRIPT_INLINE, headers={"content-type": LEGACY})

    assert [post().status_code for _ in range(MAX_REPORTS_PER_WINDOW)] == [204] * (
        MAX_REPORTS_PER_WINDOW
    )
    limited = post()
    assert limited.status_code == 429
    assert 1 <= int(limited.headers["retry-after"]) <= int(WINDOW_S) + 1
    clock.now += WINDOW_S
    assert post().status_code == 204


def test_one_noisy_ip_does_not_limit_another() -> None:
    clock = _Clock()
    inner = FastAPI()
    app = CspReportReceiver(inner, counter=None, clock=clock)
    noisy, quiet = TestClient(app, client=("10.0.0.1", 1)), TestClient(app, client=("10.0.0.2", 1))
    kw: dict[str, Any] = {"content": SCRIPT_INLINE, "headers": {"content-type": LEGACY}}
    for _ in range(MAX_REPORTS_PER_WINDOW + 1):
        noisy.post("/csp-report", **kw)
    assert noisy.post("/csp-report", **kw).status_code == 429
    assert quiet.post("/csp-report", **kw).status_code == 204


def test_the_client_table_is_bounded() -> None:
    clock = _Clock()
    app = CspReportReceiver(FastAPI(), counter=None, clock=clock)
    kw: dict[str, Any] = {"content": SCRIPT_INLINE, "headers": {"content-type": LEGACY}}
    for i in range(MAX_TRACKED_CLIENTS + 40):
        TestClient(app, client=(f"10.1.{i // 250}.{i % 250}", 1)).post("/csp-report", **kw)
    assert len(app._windows._windows) <= MAX_TRACKED_CLIENTS
    clock.now += WINDOW_S
    TestClient(app, client=("10.9.9.9", 1)).post("/csp-report", **kw)
    assert len(app._windows._windows) <= MAX_TRACKED_CLIENTS


@pytest.mark.parametrize(
    ("content_type", "body", "status"),
    [
        ("text/plain", SCRIPT_INLINE, 415),
        (LEGACY, b"{not json", 400),
        (LEGACY, b"\xff\xfe", 400),
    ],
)
def test_a_bad_type_or_body_is_refused_and_not_counted(
    content_type: str, body: bytes, status: int
) -> None:
    counter = _Counter()
    r = _client(counter).post("/csp-report", content=body, headers={"content-type": content_type})
    assert r.status_code == status
    assert counter.calls == []


def test_a_valid_body_with_no_violation_is_accepted_and_counts_nothing() -> None:
    counter = _Counter()
    r = _client(counter).post("/csp-report", content=b"[]", headers={"content-type": MODERN})
    assert (r.status_code, counter.calls) == (204, [])


def test_other_methods_and_paths_and_a_disabled_receiver_fall_through() -> None:
    assert _client().get("/csp-report").status_code == 404
    kw: dict[str, Any] = {"content": SCRIPT_INLINE, "headers": {"content-type": LEGACY}}
    assert _client().post("/elsewhere", **kw).status_code == 404
    assert _client(enabled=False).post("/csp-report", **kw).status_code == 404


async def test_a_non_http_scope_and_a_disconnect_are_left_alone() -> None:
    seen: list[str] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        seen.append(scope["type"])

    async def no_receive() -> MutableMapping[str, Any]:
        return {}

    async def no_send(message: MutableMapping[str, Any]) -> None:
        return None

    await CspReportReceiver(inner, counter=None)({"type": "lifespan"}, no_receive, no_send)
    assert seen == ["lifespan"]

    sent: list[MutableMapping[str, Any]] = []

    async def disconnect() -> MutableMapping[str, Any]:
        return {"type": "http.disconnect"}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/csp-report",
        "headers": [(b"content-type", LEGACY.encode())],
        "client": None,
    }
    await CspReportReceiver(inner, counter=None)(scope, disconnect, send)
    assert sent[0]["status"] == 400  # an empty body is not a report


def test_directive_and_blocked_classification_is_closed() -> None:
    assert normalise_directive("script-src-elem 'self'") == "script-src-elem"
    assert normalise_directive("Evil-Directive") == "other"
    assert normalise_directive(None) == "other"
    assert classify_blocked("eval") == ("eval", None)
    assert classify_blocked("wasm-eval") == ("eval", None)
    assert classify_blocked("data:text/html;base64,AAAA") == ("data", None)
    assert classify_blocked("blob:https://x/abc") == ("blob", None)
    assert classify_blocked("wss://Stream.Bybit.com/v5/public?x=1") == ("wss", "stream.bybit.com")
    assert classify_blocked("https://exa mple.com/") == ("https", None)
    assert classify_blocked("ftp://x") == ("other", None)
    assert classify_blocked("http://[bad") == ("other", None)
    assert classify_blocked("x" * 3000) == ("other", None)
    assert classify_blocked(None) == ("other", None)


def test_extract_reads_at_most_ten_violations_and_ignores_junk() -> None:
    many = [{"type": "csp-violation", "body": {"effectiveDirective": "img-src"}}] * 25
    assert len(extract_violations(many)) == 10
    assert extract_violations({"csp-report": "x"}) == []
    assert extract_violations("x") == []
    assert extract_violations([1, {"type": "csp-violation", "body": 3}]) == []


def test_the_deployed_app_serves_the_receiver_with_the_policy_header_and_counts() -> None:
    app = appmod.create_app(Settings())
    client = TestClient(app, client=("127.0.0.1", 50000))
    r = client.post("/api/v1/csp-report", content=SCRIPT_INLINE, headers={"content-type": LEGACY})
    assert r.status_code == 204
    assert "content-security-policy" in r.headers
    series = app.state.csp.counter.series_count
    assert series == 1
    off = appmod.create_app(Settings(csp_report_enabled=False))
    r = TestClient(off, client=("127.0.0.1", 50000)).post(
        "/api/v1/csp-report", content=SCRIPT_INLINE, headers={"content-type": LEGACY}
    )
    assert r.status_code != 204


def test_the_metric_is_catalogued_with_the_two_closed_labels() -> None:
    registered = register_r0(Metrics("demo"))
    metric = registered["cv_csp_violations_total"]
    metric.labels("script-src", "inline").inc()
    assert metric.series_count == 1
