"""E08-X02 (e): credential / leakage probes on signed REST error paths. Register E.

Gherkin "secrets must not appear anywhere in output": every forced error path is
run, then logs, metric exposition, exception messages and client-visible bodies
are scanned with the repo's secret-pattern set (`tools/fixtures/redact.py`, which
mirrors `.gitleaks.toml`'s bybit rules) plus the literal synthetic credentials.
A planted token proves the scan fires.
"""

from __future__ import annotations

import importlib
import io
import logging
import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import structlog
from prometheus_client import REGISTRY, generate_latest

from candleviewer.exchange.base.errors import ExchangeError

# nosemgrep: cv-adapter-isolation reason=X02 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.config import EndpointClass, RestClientConfig

# nosemgrep: cv-adapter-isolation reason=X02 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor

# nosemgrep: cv-adapter-isolation reason=X02 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.rest import BybitRestClient

# nosemgrep: cv-adapter-isolation reason=X02 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.signer import BybitSigner
from tests._corpus import rest
from tests._signing import CREDENTIAL_ID, fake_capability

_REPO = Path(__file__).resolve().parents[5]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

#: One definition of "secret": the repo fixture redactor (mirrors `.gitleaks.toml`).
#: `tools/` lives outside the mypy root, so the callable is typed at the boundary.
find_leaks: Callable[[str], list[str]] = importlib.import_module("tools.fixtures.redact").find_leaks

# Synthetic, obviously fake, assembled at runtime (never a literal secret in the repo).
API_KEY = "DUMMYKEY" + "x02" + "Q" * 9
API_SECRET = "DUMMYSECRET" + "z" * 21
UID = "998877" + "6655"
_GITLEAKS = [
    re.compile(r'(?i)"(api[_-]?key|api[_-]?secret)"\s*:\s*"[A-Za-z0-9]{16,}"'),
    re.compile(r'(?i)"sign(ature)?"\s*:\s*"[A-Fa-f0-9]{32,}"'),
    re.compile(r"(?i)X-BAPI-(API-KEY|SIGN)\s*[:=]\s*[\"']?[A-Za-z0-9]{16,}"),
]


#: The REST client's placeholder is `**redacted**`; the fixture redactor's token is
#: `REDACTED` (case-sensitive). `X-BAPI-TIMESTAMP`/`RECV-WINDOW` are public, non-secret
#: values (`.gitleaks.toml` bybit-bapi-header covers only API-KEY|SIGN), so both are
#: normalised before the stricter fixture scan. A real key/signature still matches.
_NON_SECRET = re.compile(r"(X-BAPI-(?:TIMESTAMP|RECV-WINDOW)[\"']?\s*[:=]\s*[\"']?)\d+", re.I)


def scan(text: str, extra: tuple[str, ...] = ()) -> list[str]:
    norm = _NON_SECRET.sub(r"\1REDACTED", text.replace("**redacted**", "REDACTED"))
    hits = list(find_leaks(norm))
    hits += [rx.pattern[:24] for rx in _GITLEAKS if rx.search(text)]
    hits += [f"literal:{s[:4]}" for s in (API_KEY, API_SECRET, UID, *extra) if s in text]
    return hits


def _responder(kind: str) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if kind == "transport":
            raise httpx.ConnectError("refused", request=req)
        if kind == "html":
            return httpx.Response(502, text="<html>bad gateway</html>")
        if kind == "auth":
            return httpx.Response(200, json={"retCode": 10003, "retMsg": "API key is invalid."})
        if kind == "unmapped":
            return httpx.Response(200, json={"retCode": 999999, "retMsg": "weird"})
        if kind == "4xx_no_code":
            return httpx.Response(403, json={"msg": "forbidden"})
        name = {"drift": "error_10002", "rate": "error_10018", "503": "error_503"}[kind]
        body = rest(f"rest/{name}.json")
        return httpx.Response(503 if kind == "503" else 200, json=body)

    return handler


ERROR_PATHS = ["transport", "html", "auth", "unmapped", "4xx_no_code", "drift", "rate", "503"]


@pytest.fixture
def captured() -> Iterator[io.StringIO]:
    buf = io.StringIO()
    structlog.configure(
        processors=[structlog.processors.JSONRenderer()],
        logger_factory=structlog.PrintLoggerFactory(file=buf),
    )
    handler = logging.StreamHandler(buf)
    logging.getLogger().addHandler(handler)
    try:
        yield buf
    finally:
        logging.getLogger().removeHandler(handler)
        structlog.reset_defaults()


async def _no_sleep(_s: float) -> None:
    return None


async def _drive(kind: str) -> str:
    now = [0.0]  # virtual time: a 10018 IP hold (#1908) elapses instantly

    async def _advance(s: float) -> None:
        now[0] += s

    client = BybitRestClient(
        RestClientConfig(base_url="https://api-demo.bybit.com", max_retries=1),
        uid=UID,
        signer=BybitSigner(fake_capability(API_KEY), CREDENTIAL_ID),
        governor=TokenBucketGovernor(clock=lambda: now[0], sleep=_advance),
        transport=httpx.MockTransport(_responder(kind)),
        sleep=_no_sleep,
        random_fn=lambda: 0.0,
    )
    out: list[str] = []
    async with client:
        try:
            await client.signed_request(
                "GET", "/v5/account/wallet-balance", params={"accountType": "UNIFIED"}
            )
        except (ExchangeError, httpx.HTTPError) as exc:
            out += [str(exc), repr(exc), repr(exc.__cause__)]
            out += [str(getattr(exc, "to_problem", lambda: "")())]
    return "\n".join(out)


@pytest.mark.parametrize("kind", ERROR_PATHS)
async def test_signed_error_path_leaks_nothing(kind: str, captured: io.StringIO) -> None:
    surfaced = await _drive(kind)
    blob = "\n".join([captured.getvalue(), surfaced, generate_latest(REGISTRY).decode()])
    assert scan(blob) == [], f"{kind}: leak in output"


def test_scan_detects_planted_token() -> None:
    # Proves the scanner works: each planted shape is caught by the same scan.
    planted: list[Any] = [
        f'{{"api_key":"{API_KEY}"}}',
        f"X-BAPI-SIGN: {'ab' * 32}",
        f"uid={UID}",
        f'{{"sign":"{"cd" * 32}"}}',
        'headers={"X-BAPI-SIGN": "' + "ef" * 32 + '", "X-BAPI-TIMESTAMP": "1"}',
    ]
    for text in planted:
        assert scan(text), text


def test_signer_repr_never_contains_secret() -> None:
    # #2339: the signer holds no secret at all; M2 computes the MAC (C-2.7).
    assert API_SECRET not in repr(BybitSigner(fake_capability(API_KEY), CREDENTIAL_ID))


def test_signer_repr_masks_api_key() -> None:
    # #1895: fixed by #2339, the signer holds a capability and a credential id, not the key.
    assert scan(repr(BybitSigner(fake_capability(API_KEY), CREDENTIAL_ID))) == []


def test_metric_labels_carry_no_uid() -> None:
    names = {"bybit_rate_limit_remaining", "bybit_rest_requests_total", "exchange_errors_total"}
    for fam in REGISTRY.collect():
        if fam.name in names:
            for s in fam.samples:
                assert UID not in s.labels.values()
                assert "uid" not in s.labels


def test_endpoint_classes_cover_market_data() -> None:
    assert EndpointClass.MARKET_DATA.value == "market_data"
