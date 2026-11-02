"""The API's Content-Security-Policy header (SR-112, C-12.10, E43-T01).

A MIRROR of the one policy builder `packages/config/src/csp-policy.mjs` (the web `<meta>` comes
from it; `apps/desktop/src/main/csp.ts` is the other mirror). `tests/unit/api/test_csp_policy.py`
asserts every output equals `packages/config/src/csp-policy.golden.json`, so the three cannot drift.

No `'unsafe-inline'` / `'unsafe-eval'`, no wildcard. `connect-src` is the app itself, the loopback
backend origin and, only when `security.csp.tailnet_host` (`CV_CSP_TAILNET_HOST`) is a valid DNS
name, its https/wss origin: an invalid host refuses startup (`CspConfigError`), it is never
widened to or reflected from a request. `frame-ancestors`, `report-uri` and `report-to` ride in the
header (a `<meta>` ignores them), which is this surface.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

if TYPE_CHECKING:  # stdlib-only at runtime: tools/ci/csp_assertion.py loads this file by path
    from candleviewer.settings import Settings

DEFAULT_BACKEND_ORIGIN: Final = "http://127.0.0.1:8000"
CSP_REPORT_PATH: Final = "/api/v1/csp-report"
CSP_REPORT_GROUP: Final = "csp-endpoint"
CSP_HEADER: Final = "Content-Security-Policy"
REPORTING_ENDPOINTS_HEADER: Final = "Reporting-Endpoints"

_LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "localhost", "[::1]"})
_LABEL: Final = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_TAILNET_HOST_RE: Final = re.compile(rf"^{_LABEL}(?:\.{_LABEL})+(?::[0-9]{{1,5}})?$")
_IPV4_LIKE_RE: Final = re.compile(r"^[0-9.]+$")


class CspConfigError(ValueError):
    """`security.csp.tailnet_host` is not a valid DNS name (startup refuses; never echoed)."""


def resolve_backend_origin(raw: str) -> str:
    """Loopback-only origin; anything else falls back to the default (never widens connect-src)."""
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return DEFAULT_BACKEND_ORIGIN
    if not parsed.scheme or host is None:
        return DEFAULT_BACKEND_ORIGIN
    host_token = f"[{host}]" if ":" in host else host
    if host_token not in _LOOPBACK_HOSTS or parsed.scheme not in ("http", "https"):
        return DEFAULT_BACKEND_ORIGIN
    default_port = 443 if parsed.scheme == "https" else 80
    suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{parsed.scheme}://{host_token}{suffix}"


def parse_tailnet_host(raw: object) -> str | None:
    """A validated tailnet host (lowercase DNS name, optional port), or `None`."""
    if not isinstance(raw, str):
        return None
    host = raw.strip().lower()
    if not host or len(host) > 253 or _TAILNET_HOST_RE.fullmatch(host) is None:
        return None
    name, _, port = host.partition(":")
    if _IPV4_LIKE_RE.fullmatch(name) or (port and not 1 <= int(port) <= 65535):
        return None
    return host


def build_csp_policy(
    backend_origin: str = DEFAULT_BACKEND_ORIGIN, tailnet_host: str | None = None
) -> str:
    """The header policy (frame-ancestors and report directives included)."""
    origin = resolve_backend_origin(backend_origin)
    connect = ["'self'", origin, "ws" + origin[len("http") :]]
    if (tailnet := parse_tailnet_host(tailnet_host)) is not None:
        connect += [f"https://{tailnet}", f"wss://{tailnet}"]
    return "; ".join(
        [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self'",
            f"connect-src {' '.join(connect)}",
            "img-src 'self' data: blob:",
            "worker-src 'self' blob:",
            "object-src 'none'",
            "frame-ancestors 'none'",
            "base-uri 'none'",
            "form-action 'none'",
            f"report-uri {_report_origin(origin, tailnet_host)}{CSP_REPORT_PATH}",
            f"report-to {CSP_REPORT_GROUP}",
        ]
    )


def _report_origin(origin: str, tailnet_host: str | None) -> str:
    """Where reports go: the tailnet https origin when a valid one is set, else the backend."""
    tailnet = parse_tailnet_host(tailnet_host)
    return origin if tailnet is None else f"https://{tailnet}"


def build_reporting_endpoints(
    backend_origin: str = DEFAULT_BACKEND_ORIGIN, tailnet_host: str | None = None
) -> str:
    """Value of the `Reporting-Endpoints` header that `report-to` names."""
    origin = _report_origin(resolve_backend_origin(backend_origin), tailnet_host)
    return f'{CSP_REPORT_GROUP}="{origin}{CSP_REPORT_PATH}"'


def backend_origin_for(settings: Settings) -> str:
    """The API's own loopback origin from its bind port (not the desktop shell's default 8000)."""
    return f"http://127.0.0.1:{settings.bind_port}"


def tailnet_host_from(settings: Settings) -> str | None:
    """The validated configured tailnet host; an invalid one raises `CspConfigError`."""
    raw = settings.csp_tailnet_host
    if raw is None or not raw.strip():
        return None
    if (host := parse_tailnet_host(raw)) is None:
        raise CspConfigError("CV_CSP_TAILNET_HOST must be a DNS name such as host.tailnet.ts.net")
    return host
