"""Lifecycle contract for the exchange.bybit module (M4).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. This is an
empty scaffold — the supervisor (Sec.6.2) can construct and sequence this
module, but it does no real work until its owning epic lands.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

import httpx
import structlog

from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.exchange.base.models import RateLane
from candleviewer.exchange.base.reconnect import ConnectionBudget
from candleviewer.exchange.bybit.archive import (
    DEFAULT_ARCHIVE_BASE,
    ArchiveConfig,
    BybitTradeArchive,
)
from candleviewer.exchange.bybit.capabilities import capabilities_for
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
from candleviewer.exchange.bybit.key_ws_probe import (
    KeyWsProbe,
    PrivateWsConnect,
    WsProbeResult,
    connect_private_stream,
)
from candleviewer.exchange.bybit.klines import BybitKlineFetcher, TickSizeFor
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.exchange.bybit.private_stream import PrivateStreams, StreamConnect
from candleviewer.exchange.bybit.public_ws import (
    PublicSocket,
    frame_route,
    public_socket_factory,
    stream_for_topic,
    topic_kind,
)
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.ticker import parse_ticker_frame, ticker_topic
from candleviewer.exchange.bybit.trades import (
    parse_trade_frame,
    recent_trades_fetcher,
    trade_topic,
)
from candleviewer.exchange.bybit.trading import (
    CRITICAL_WAIT_S,
    DEFAULT_ENTRY_WAIT_S,
    POLL_WAIT_S,
    BybitTradingPort,
)
from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.secrets import WithdrawPermissionRejected

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.secrets import CandidateSigner, CredentialBorrower, SigningCapability


def _logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _NonClosingTransport(httpx.AsyncBaseTransport):
    """#2893 S4: the adapter's one account REST transport as its clients see it. Requests go
    through; `aclose()` does not, since each key's client is closed after its check while the
    transport serves the next key. Only its owner, the composition root, may close it. A lane's
    own transport is wrapped alike (#913 L3b)."""

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
        private_ws_connect: PrivateWsConnect | None = None,
        environment: str | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._started = False
        #: E27-T02: the one caller-bound signing capability, injected by `admin.wiring`.
        #: M2 computes the request MAC (`credentials.sign(...)`) and returns the key id,
        #: never the secret (C-2.7, #2339). Never minted here.
        self._credentials = credentials
        #: OM-D08 (#2877 ruling R5): the process's one governor, so its IP bucket and `10018`
        #: hold cover every REST client built here, public, trading and key verification alike.
        self._governor = TokenBucketGovernor()
        self._verify_governor = verification_governor(self._governor)
        #: #2893 S4: the transport of every account REST client built here, chosen once. None in
        #: production, so httpx keeps its own; the composition root passes the dev-only account
        #: fixture's only when `CV_ACCOUNT_FIXTURE` is set, and the clients get a view of it that
        #: cannot close it. Never in a repr or a log line.
        self._rest_transport = (
            None if rest_transport is None else _NonClosingTransport(rest_transport)
        )
        #: G-8b (#3963): the one per-IP WebSocket connection budget (C-12.7, OM-D07; 24 §14.2 rule
        #: 13) every socket of this process draws on: the public stream's lane (the composition
        #: root hands it over), the private streams' and the key probe's.
        self._ws_budget = ConnectionBudget(monotonic)
        #: #836 slice 2b5: `testApiKey`'s private-WS `auth` probe. One per adapter, so one open
        #: budget per deployment (SR-E27-05), counted in the connection budget. It dials with
        #: production's connector unless the composition root passes the dev-only account
        #: fixture's, behind its door (#2893).
        self._ws_probe = (
            KeyWsProbe(budget=self._ws_budget)
            if private_ws_connect is None
            else KeyWsProbe(private_ws_connect, budget=self._ws_budget)
        )
        #: The process's own environment (`Settings.environment`), the only one whose keys M2
        #: signs: a stored key's probe dials no other stream (C-2.11). None refuses every probe.
        self._environment = environment
        #: G-8b (#3963): the private streams dial with production's stream connector, or with the
        #: dev-only account fixture's when the composition root passes it (#2893), as the probe.
        self._stream_connect: StreamConnect = (
            connect_private_stream if private_ws_connect is None else private_ws_connect
        )
        self._monotonic = monotonic
        #: G-8b: this environment's private streams, one registry per adapter (one per account,
        #: at most 64, on the one connection budget), built with the first trading port.
        self._private_streams: PrivateStreams | None = None

    #: E08-T06: venue name for the `exchange` metric label (owned here, C-2.2).
    venue = "bybit"

    @property
    def ws_connection_budget(self) -> ConnectionBudget:
        """G-8b: the process's one WebSocket connection budget (24 §14.2 rule 13); the composition
        root gives its `public` lane to the public stream."""
        return self._ws_budget

    #: E08-T04: venue topic -> neutral stream kind, for ingestion's watchdog.
    topic_kind = staticmethod(topic_kind)
    #: #2188 S4b: venue topic -> (symbol, neutral streams), for the recorder's sessions.
    stream_for_topic = staticmethod(stream_for_topic)
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

    def public_rest_client(self, env: str) -> BybitRestClient:
        """E04-T06: credential-less public REST client (server-time probe), on the process's
        one governor (OM-D08). Public data always uses the live host (demo has no public feed)."""
        base = "https://api-testnet.bybit.com" if env == "testnet" else "https://api.bybit.com"
        return BybitRestClient(RestClientConfig(base_url=base), governor=self._governor)

    @staticmethod
    def kline_fetcher(
        client: BybitRestClient, tick_size_for: TickSizeFor | None = None
    ) -> BybitKlineFetcher:
        """E12-S05: validated kline pages over a public governed client (`MARKET_DATA`)."""
        return BybitKlineFetcher(client, tick_size_for)

    def funding_fetcher(
        self, env: str
    ) -> tuple[BybitFundingFetcher, Callable[[], Awaitable[None]]]:
        """E24-T02-F1: settled-funding history fetcher over a governed public REST
        client (`MARKET_DATA` bucket) plus the closer for that client."""
        client = self.public_rest_client(env)
        return BybitFundingFetcher(client), client.aclose

    #: E27-T03: `(reason, code)` when a key-verification refusal is a verdict about the key.
    key_refusal = staticmethod(refusal)
    #: E27-T03: the contract's `KeyProbeError` name of any other key-verification failure.
    key_probe_error = staticmethod(probe_error)

    @staticmethod
    def key_borrow_refused(error: Exception) -> bool:
        """E27-T03: M2's borrow re-check refused the stored row (C-2.8, SR-E27-14), a verdict
        about the key: `WithdrawPermissionRejected` or its subclass `SnapshotInvalid`."""
        return isinstance(error, WithdrawPermissionRejected)

    #: E27-T03: the bound on one key-verification call, its budget wait and M2's signing included.
    #: The composition root cuts each call at this value, read here (C-2.2), never imported.
    key_call_timeout_s: float = CALL_TIMEOUT_S

    async def key_ws_probe(
        self, env: str, credential_id: UUID, *, clock_offset_ms: Callable[[], int] | None = None
    ) -> WsProbeResult:
        """E27-T03: one private-WS `auth` for a stored key, `testApiKey`'s WebSocket half (its
        caller is #836 slice 2b6; nothing calls it before that): on `env`'s own stream only
        (C-2.11), signed by M2 under `sign_ws_auth`, never a subscribe; diagnostic only. The
        scheduled self-check never calls it (SR-E27-05). M2 signs only the process environment's
        keys, so any other `env` is refused before anything is signed or dialled, as a candidate
        of another environment is (KV-T10)."""
        if self._credentials is None:
            raise RuntimeError("no signing capability is wired")
        if env != self._environment:
            raise ValueError("not this process's environment")
        return await self._ws_probe.probe(
            self._credentials, env, credential_id, clock_offset_ms=clock_offset_ms
        )

    def trading_port(
        self,
        env: str,
        *,
        clock_offset_ms: Callable[[], int | None] | None = None,
        entry_wait_s: float = DEFAULT_ENTRY_WAIT_S,
    ) -> BybitTradingPort:
        """G-8 (#2877): the exchange `TradingPort` of this process's environment only (C-2.11),
        signed by M2 under `sign_rest`, on the process's one governor (OM-D08) and the adapter's
        account REST transport (#2893 S4); `entry_wait_s` bounds an `entry` token wait (24 §8.7).
        Any other environment is refused before a client exists, and testnet, which has no
        capability record (ruling R6), is refused too. A factory, not trading methods: the
        service itself trades nothing. Every port shares the adapter's one private-stream
        registry (G-8b), so its one-stream-per-account rule and its cap hold across ports.
        `clock_offset_ms` is the measured offset, `None` while unmeasured."""
        if self._credentials is None:
            raise RuntimeError("no signing capability is wired")
        if env != self._environment:
            raise ValueError("not this process's environment")
        streams = self._streams(capabilities_for(env).environment, self._credentials)
        return BybitTradingPort(
            environment=env,
            credentials=self._credentials,
            governor=self._governor,
            transport=self._rest_transport,
            clock_offset_ms=clock_offset_ms,
            entry_wait_s=entry_wait_s,
            private_streams=streams,
        )

    def lane_trading_port(
        self,
        env: str,
        *,
        credentials: CredentialBorrower,
        transport: httpx.AsyncBaseTransport | None = None,
        clock_offset_ms: Callable[[], int | None] | None = None,
        entry_wait_s: float = DEFAULT_ENTRY_WAIT_S,
    ) -> BybitTradingPort:
        """#913 L3b: `trading_port` for the order lane's loop, signed by M2's borrower for that
        loop, with no private stream; refused as `trading_port` is, and for the adapter's own.
        `transport` is the lane's, never the adapter's: no transport is shared across loops. With
        the dev-only account fixture the composition root (L1b) builds one on the lane's loop and
        closes it there; without one, a fixture-mode lane is refused, never dialling the host.
        `clock_offset_ms` is called on the lane's loop, so it must be a side-effect-free read:
        never the serving clock guard's reader, whose host-step check can change the guard and
        spawn its resync on the calling loop."""
        if credentials is self._credentials:
            raise ValueError("the lane signs through its own loop's borrower")
        if env != self._environment:
            raise ValueError("not this process's environment")
        if (shared := self._rest_transport) is not None:  # the account fixture's (#2893)
            if transport is None:
                raise RuntimeError("a fixture-mode lane needs a transport of its own loop")
            if transport is shared or transport is shared._transport:
                raise ValueError("the lane never uses the adapter's transport")
        return BybitTradingPort(
            environment=env,
            credentials=credentials,
            governor=self._governor,
            transport=None if transport is None else _NonClosingTransport(transport),
            clock_offset_ms=clock_offset_ms,
            entry_wait_s=entry_wait_s,
        )

    @staticmethod
    def lane_waits(entry_wait_s: float = DEFAULT_ENTRY_WAIT_S) -> Mapping[RateLane, float]:
        """#913 ruling Q19: how long each rate lane of a port `trading_port` builds with
        `entry_wait_s` waits for its token (24 §8.7), for the OMS router's rate step, so the
        composition root reads them here and imports no venue module (C-2.2)."""
        waits: dict[RateLane, float] = {
            "critical": CRITICAL_WAIT_S,
            "entry": entry_wait_s,
            "poll": POLL_WAIT_S,
        }
        return MappingProxyType(waits)

    async def close_private_streams(
        self, key_ref: str, *, reason: Literal["key_revoked", "key_rotated"] = "key_revoked"
    ) -> tuple[AccountId, ...]:
        """G-8b (SR-E27-17, KV-E13, AC-28): close every private stream on `key_ref` before
        returning, and return their accounts. E27-S04 (#898) calls it before a revoke,
        force-disable, mark-compromised or account-disable returns, and with `key_rotated` at the
        start of a rotation's overlap (the consumer then subscribes with the new key). A key it
        closed opens no stream again. Before any trading port exists there is none to close, and
        M2 refuses a destroyed key's next `auth` borrow either way (24 §14.2 rule 13)."""
        streams = self._private_streams
        return () if streams is None else await streams.close_key(key_ref, reason=reason)

    def reopen_private_streams(self, key_ref: str) -> bool:
        """G-8b ruling 10: an operator lets a key that three `auth` refusals closed open streams
        again; `True` when it was so marked. A revoked or rotated key stays closed."""
        streams = self._private_streams
        return False if streams is None else streams.reopen(key_ref)

    def _streams(self, environment: Environment, credentials: CredentialBorrower) -> PrivateStreams:
        if self._private_streams is None:
            self._private_streams = PrivateStreams(
                environment=environment,
                credentials=credentials,
                connect=self._stream_connect,
                budget=self._ws_budget,
                monotonic=self._monotonic,
            )
        return self._private_streams

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

    def candidate_verification_calls(
        self,
        env: str,
        candidate: CandidateSigner,
        *,
        uid: str,
        recv_window_ms: int,
        clock_offset_ms: Callable[[], int] | None = None,
    ) -> KeyVerificationCalls:
        """E27-T03 (SR-E27-01): key info and the probe for a candidate key M2 holds for one import,
        signed by M2 under `key_verify` and built as a stored key's are (`_signed_calls`), on
        `env`'s own host only. A candidate of another environment is refused before any client
        exists, so no host of one environment gets a request signed with another's key (C-2.11)."""
        if candidate.env != env:
            raise ValueError("the candidate key belongs to another environment")
        return self._signed_calls(
            candidate, env, candidate.key_id, uid, recv_window_ms, clock_offset_ms
        )

    async def start(self, ctx: AppContext) -> None:
        """Start the module. No-op until the owning epic implements it."""
        self._started = True

    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds: every private stream ends with
        `closed(shutdown)` and its socket closes (G-8b); the rest is a no-op scaffold."""
        streams = self._private_streams
        if streams is not None:
            try:
                async with asyncio.timeout(grace_s):
                    await streams.aclose()
            except TimeoutError:
                _logger().warning("bybit_private_streams_stop_overran", grace_s=grace_s)
        self._started = False

    def health(self) -> HealthReport:
        """Report module health. Scaffold modules report `ok` when constructed."""
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        return HealthReport(module="", status=status, detail="scaffold module — no real logic yet")
