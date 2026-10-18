"""REST client configuration for the `exchange.bybit` module (E08-T02).

Base URLs are **configuration, never hardcoded** (ticket body) — but they
are also constrained to an explicit allowlist so an operator typo can never
turn into an SSRF-style signed request to an arbitrary host (security notes:
"the regional-host allowlist prevents an operator misconfiguration from
sending signed requests to an arbitrary host").
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from pydantic import BaseModel, ConfigDict, field_validator

#: `docs/plan/24-internal-schemas.md` §14.3 "Endpoints" + "Environment
#: differences" tables. Every host CandleViewer is allowed to talk to,
#: verbatim. Adding a host is a deliberate, reviewed change to this file —
#: never a runtime string.
ALLOWED_REST_HOSTS: frozenset[str] = frozenset(
    {
        "api.bybit.com",
        "api.bybit.nl",
        "api.bybit.tr",
        "api.bybit.kz",
        "api.bybit.ae",
        "api.bybit.eu",
        "api.bybit.id",
        "api.bytick.com",
        "api-demo.bybit.com",
        "api-testnet.bybit.com",
    }
)

#: The signed REST host of each environment (`20-architecture.md` §7.1, US-ACCT-007, C-2.11). A
#: key is signed for and sent to its own environment's host only; nothing falls back to another.
SIGNED_REST_BASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "live": "https://api.bybit.com",
        "demo": "https://api-demo.bybit.com",
        "testnet": "https://api-testnet.bybit.com",
    }
)

#: The private WS stream of each environment (`20-architecture.md` §7.1, US-ACCT-007, C-2.11): a
#: key authenticates on its own environment's stream only; nothing falls back to another. The
#: `testApiKey` probe dials it (#836); the streaming private socket (#2877, #848) can reuse it.
PRIVATE_WS_URLS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "live": "wss://stream.bybit.com/v5/private",
        "demo": "wss://stream-demo.bybit.com/v5/private",
        "testnet": "wss://stream-testnet.bybit.com/v5/private",
    }
)


class EndpointClass(StrEnum):
    """Bybit's per-UID rate budgets differ per endpoint family (`Exchange
    Capabilities.order_rate_per_uid_per_s` is a dict, technical notes). This
    is the key the token bucket is keyed on alongside `uid`."""

    MARKET_DATA = "market_data"
    ORDER = "order"
    POSITION = "position"
    ACCOUNT = "account"


class RestClientConfig(BaseModel):
    """Explicit, reviewable client configuration — no hidden defaults.

    `base_url` must be `https://<allowlisted host>` with no path/query
    (validated below). `recv_window_ms` is pinned at 5000 per §14.3 / the
    security notes ("we fix clocks rather than widening the window") and
    the schema's own `recv_window_ms <= 10000` cross-field rule.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str
    recv_window_ms: int = 5000
    connect_timeout_s: float = 5.0
    total_timeout_s: float = 10.0
    max_connections: int = 20
    max_keepalive_connections: int = 20
    ip_budget_per_5s: int = 600
    max_retries: int = 3

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("base_url must use https://")
        host = value.removeprefix("https://").split("/", 1)[0]
        if "/" in value.removeprefix("https://") or "?" in value:
            raise ValueError("base_url must be a bare origin — no path or query")
        if host not in ALLOWED_REST_HOSTS:
            raise ValueError(
                f"base_url host {host!r} is not in the regional-host allowlist "
                f"(docs/plan/24-internal-schemas.md §14.3)"
            )
        return value

    @field_validator("recv_window_ms")
    @classmethod
    def _validate_recv_window(cls, value: int) -> int:
        if not (0 < value <= 10_000):
            raise ValueError("recv_window_ms must be in (0, 10000]")
        return value
