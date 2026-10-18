"""Lifecycle contract for the exchange.bybit module (M4).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. This is an
empty scaffold — the supervisor (Sec.6.2) can construct and sequence this
module, but it does no real work until its owning epic lands.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from uuid import UUID

import httpx

from candleviewer.exchange.bybit.archive import (
    DEFAULT_ARCHIVE_BASE,
    ArchiveConfig,
    BybitTradeArchive,
)
from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.funding import BybitFundingFetcher
from candleviewer.exchange.bybit.instruments import make_instruments_info_fetcher
from candleviewer.exchange.bybit.key_info import probe_error, refusal
from candleviewer.exchange.bybit.key_verify import (
    CALL_TIMEOUT_S,
    KeyVerificationCalls,
    key_verification_calls,
    verification_governor,
)
from candleviewer.exchange.bybit.klines import BybitKlineFetcher, TickSizeFor
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.exchange.bybit.public_ws import (
    PublicSocket,
    frame_route,
    public_socket_factory,
    topic_kind,
)
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.ticker import parse_ticker_frame, ticker_topic
from candleviewer.exchange.bybit.trades import (
    parse_trade_frame,
    recent_trades_fetcher,
    trade_topic,
)
from candleviewer.observability.health import HealthReport, HealthStatus

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.secrets import CredentialBorrower, SigningCapability


class _NonClosingTransport(httpx.AsyncBaseTransport):
    """#2893 S4: the adapter's one account REST transport as its clients see it. Requests go
    through; `aclose()` does not, since each key's client is closed after its check while the
    transport serves the next key. Only its owner, the composition root, may close it."""

    def __init__(self, transport: httpx.AsyncBaseTransport) -> None:
        self._transport = transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._transport.handle_async_request(request)

    async def aclose(self) -> None:
        """Leaves the shared transport open."""


class ExchangeBybitService:
    """Empty scaffold for the M4 `exchange.bybit` module lifecycle."""

    def __init__(
        self,
        credentials: CredentialBorrower | None = None,
        *,
        rest_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._started = False
        #: E27-T02: the one caller-bound signing capability, injected by `admin.wiring`.
        #: M2 computes the request MAC (`credentials.sign(...)`) and returns the key id,
        #: never the secret (C-2.7, #2339). Never minted here.
        self._credentials = credentials
        self._verify_governor = verification_governor()
        #: #2893 S4: the transport of every account REST client built here, chosen once. None in
        #: production, so httpx keeps its own; the composition root passes the dev-only account
        #: fixture's only when `CV_ACCOUNT_FIXTURE` is set, and the clients get a view of it that
        #: cannot close it. Never in a repr or a log line.
        self._rest_transport = (
            None if rest_transport is None else _NonClosingTransport(rest_transport)
        )

    #: E08-T06: venue name for the `exchange` metric label (owned here, C-2.2).
    venue = "bybit"
    #: E08-T04: venue topic -> neutral stream kind, for ingestion's watchdog.
    topic_kind = staticmethod(topic_kind)
    #: #1916: raw frame -> (topic, kind, symbol) for per-topic dispatch lanes.
    frame_route = staticmethod(frame_route)
    #: E08-S03: ticker topic naming + frame parser, injected into ingestion.
    ticker_topic = staticmethod(ticker_topic)
    parse_ticker_frame = staticmethod(parse_ticker_frame)
    #: E08-S04: tape topic naming, frame parser and REST gap-backfill fetcher.
    trade_topic = staticmethod(trade_topic)
    parse_trade_frame = staticmethod(parse_trade_frame)
    recent_trades_fetcher = staticmethod(recent_trades_fetcher)

    @staticmethod
    def trade_archive(
        *,
        max_concurrency: int,
        max_mbps: float,
        max_uncompressed_mb: int,
        base_url: str | None = None,
    ) -> BybitTradeArchive:
        """E16-T10: the public trade-archive source (`exchange.base.archive` port)."""
        cfg = ArchiveConfig(
            base_url=base_url or DEFAULT_ARCHIVE_BASE,
            max_concurrency=max_concurrency,
            max_mbps=max_mbps,
            max_uncompressed_mb=max_uncompressed_mb,
        )
        return BybitTradeArchive(cfg)

    #: E08-S01-2: the neutral instruments-info fetcher over a public client (#2561).
    instruments_fetcher = staticmethod(make_instruments_info_fetcher)
    #: E08-S05: order-book topic naming + frame parser.
    book_topic = staticmethod(book_topic)
    parse_book_frame = staticmethod(parse_book_frame)

    @staticmethod
    def public_socket_factory(
        env: str, *, max_frame_bytes: int
    ) -> Callable[[], Awaitable[PublicSocket]]:
        """E08-T04: unauthenticated public-stream socket factory for `env`."""
        return public_socket_factory(env, max_frame_bytes=max_frame_bytes)

    @staticmethod
    def public_rest_client(env: str) -> BybitRestClient:
        """E04-T06: credential-less public REST client (server-time probe).
        Public data always uses the live host (demo has no public feed)."""
        base = "https://api-testnet.bybit.com" if env == "testnet" else "https://api.bybit.com"
        return BybitRestClient(RestClientConfig(base_url=base))

    @staticmethod
    def kline_fetcher(
        client: BybitRestClient, tick_size_for: TickSizeFor | None = None
    ) -> BybitKlineFetcher:
        """E12-S05: validated kline pages over a public governed client (`MARKET_DATA`)."""
        return BybitKlineFetcher(client, tick_size_for)

    @classmethod
    def funding_fetcher(cls, env: str) -> tuple[BybitFundingFetcher, Callable[[], Awaitable[None]]]:
        """E24-T02-F1: settled-funding history fetcher over a governed public REST
        client (`MARKET_DATA` bucket) plus the closer for that client."""
        client = cls.public_rest_client(env)
        return BybitFundingFetcher(client), client.aclose

    #: E27-T03: `(reason, code)` when a key-verification refusal is a verdict about the key.
    key_refusal = staticmethod(refusal)
    #: E27-T03: the contract's `KeyProbeError` name of any other key-verification failure.
    key_probe_error = staticmethod(probe_error)
    #: E27-T03: the bound on one key-verification call, its budget wait and M2's signing included.
    #: The composition root cuts each call at this value, read here (C-2.2), never imported.
    key_call_timeout_s: float = CALL_TIMEOUT_S

    def key_verification_calls(
        self,
        env: str,
        credential_id: UUID,
        *,
        uid: str,
        recv_window_ms: int,
        clock_offset_ms: Callable[[], int] | None = None,
    ) -> KeyVerificationCalls:
        """E27-T03: key info and the probe for one stored key, signed by M2 under `key_verify`
        on `env`'s own host only (US-ACCT-007, C-2.11), on the shared verification budget,
        stamped on the exchange's clock when `clock_offset_ms` gives the measured offset, sent
        through the adapter's account REST transport (#2893 S4)."""
        if self._credentials is None:
            raise RuntimeError("no signing capability is wired")
        return self._signed_calls(
            self._credentials, env, credential_id, uid, recv_window_ms, clock_offset_ms
        )

    def _signed_calls(
        self,
        signer: SigningCapability,
        env: str,
        key_id: UUID,
        uid: str,
        recv_window_ms: int,
        clock_offset_ms: Callable[[], int] | None,
    ) -> KeyVerificationCalls:
        """The one body of every key's verification calls: the verification budget and the
        account REST transport (#2893 S4) are chosen here only, whatever M2 signer signs."""
        return key_verification_calls(
            signer, env, key_id, uid=uid, recv_window_ms=recv_window_ms,
            governor=self._verify_governor, clock_offset_ms=clock_offset_ms,
            transport=self._rest_transport,
        )  # fmt: skip

    async def start(self, ctx: AppContext) -> None:
        """Start the module. No-op until the owning epic implements it."""
        self._started = True

    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds. No-op scaffold."""
        self._started = False

    def health(self) -> HealthReport:
        """Report module health. Scaffold modules report `ok` when constructed."""
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        return HealthReport(module="", status=status, detail="scaffold module — no real logic yet")
