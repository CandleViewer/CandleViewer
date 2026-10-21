"""Bybit v5 REST client (`docs/plan/24-internal-schemas.md` §14.3; ticket
body "Scope / Deliverables").

One `httpx.AsyncClient` per `BybitRestClient` instance, explicit connection
pool and timeouts (technical notes: "no global default timeouts"). Signing,
per-UID token-bucket shaping, retry-with-jitter and retCode mapping all live
here so every consumer — instrument catalogue, kline backfill, and later
the OMS order path (E29) — goes through one governed choke point (ticket
Context paragraph).

Out of scope (ticket body): WebSocket transport, any authenticated trading
call wired to live keys, key storage/encryption.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx
import structlog

from candleviewer.exchange.base.boundary import exchange_errors_total
from candleviewer.exchange.base.errors import (
    AmbiguousResultError,
    ClockDriftError,
    ExchangeError,
    RateBudgetExceededError,
    RateLimitError,
    TransportError,
    UnknownStateError,
)
from candleviewer.exchange.base.models import RateLane
from candleviewer.exchange.bybit.config import EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.mapping import map_ret_code
from candleviewer.exchange.bybit.metrics import (
    bybit_rate_limit_remaining,
    bybit_rate_limited_total,
    bybit_rest_latency_seconds,
    bybit_rest_requests_total,
)
from candleviewer.exchange.bybit.models import ServerTime
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.signer import BybitSigner


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: Header/field name fragments that must never reach a log line, verbatim or
#: via a nested dict repr (ticket scenario "Secrets never reach a log or a
#: fixture"). Matched case-insensitively against header/query-param keys.
_SECRET_KEY_MARKERS = ("api_key", "api-key", "sign", "secret", "authorization")

_REDACTED = "**redacted**"

#: `10018` is the IP-level limit: hold every caller >=10 min (24-internal-schemas §8.6).
_IP_RATE_LIMIT_CODE = 10018
_IP_HOLD_S = 600.0
#: Cap on any venue-advertised wait (header is untrusted input).
_MAX_RESET_WAIT_S = 900.0
#: Bound on the injected re-measure hook so a hung server-time call cannot stall the retry.
_SIGNATURE_RESYNC_TIMEOUT_S = 5.0

#: SR-040a: a request path is a relative `/v5/...` path of URL-safe segment
#: characters only. No scheme, authority, backslash, whitespace/control char,
#: query/fragment or percent-escape can match, so httpx can never be steered
#: to another host (it honours an absolute/scheme-relative URL over base_url).
_SAFE_PATH = re.compile(r"/v5/[A-Za-z0-9_\-]+(?:/[A-Za-z0-9_\-]+)*\Z")

#: 24 §8.6 "Order creates" (SR-E29-15): a create that has left is never sent again; amend,
#: cancel and trading-stop keep their retries. 10016/10019 leave a create's outcome unknown.
_BATCH_PATH = "/v5/order/create-batch"
_CREATE_PATHS = frozenset({"/v5/order/create", _BATCH_PATH})
_AMBIGUOUS_RET_CODES = frozenset({10016, 10019})
#: SR-054: the signed paths that take a `category`, which must be `linear`, stated by the caller.
_CATEGORY_PREFIXES = ("/v5/order/", "/v5/position/", "/v5/execution/")
_CATEGORY_PATHS = frozenset({"/v5/account/fee-rate"})
#: SR-E29-08: our own key id and signature are masked in an answer before it is decoded, so a
#: venue that echoes them puts them in no error, record or log line. A shorter value is no
#: credential the venue issues, and masking it would rewrite the body's own words.
_MIN_MASKED_LEN = 8
_MASK = b"**redacted**"
#: Raised while connecting or waiting for a pooled connection: nothing left. Any other failure
#: may follow the send, a bare `TimeoutError` too (httpx maps its own; an unmapping transport
#: raises it at a point this client cannot place).
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


class RestPathRejected(ExchangeError, ValueError):
    """The request `path` is not a plain relative `/v5/...` path (SR-040a).

    Raised before signing or sending. The message never carries the key or
    signature, and never echoes the rejected path (it may hold control chars)."""


def validate_rest_path(path: str) -> str:
    """Return `path` unchanged if it is a safe relative `/v5/` path, else raise."""
    if not isinstance(path, str) or not _SAFE_PATH.match(path):
        raise RestPathRejected("REST path must be a relative /v5/ path (SR-040a)")
    return path


#: Per-endpoint-class cap on the raw response body (SR-E12-09, #2046), enforced
#: while streaming and BEFORE JSON decode. A 1000-row kline page is ~80 KiB and
#: the largest legitimate market-data reply (instruments-info, ~600 symbols) is
#: well under 1 MiB, so 2 MiB leaves >2x headroom without letting a hostile or
#: broken upstream make us buffer unbounded memory. Signed account/order/position
#: replies are small; 1 MiB is generous.
_MAX_BODY_BYTES: Mapping[EndpointClass, int] = {
    EndpointClass.MARKET_DATA: 2 * 1024 * 1024,
    EndpointClass.ORDER: 1024 * 1024,
    EndpointClass.POSITION: 1024 * 1024,
    EndpointClass.ACCOUNT: 1024 * 1024,
}


class RestBodyTooLarge(ExchangeError):
    """The response body exceeded the per-endpoint-class byte cap (SR-E12-09).

    Never retryable: a hostile/broken upstream will not shrink on resend. The
    message carries sizes only, never any payload bytes. An order create's oversized
    answer is the cause of an `AmbiguousResultError` instead (24 §8.6 "Order creates")."""


async def _read_capped(response: httpx.Response, cap: int) -> bytes | None:
    """Stream the body; return None if it exceeds `cap` (checked per chunk, so
    peak memory is ~cap + one chunk). `Content-Length` is an early hint only."""
    declared = response.headers.get("Content-Length")
    if declared is not None and declared.isdigit() and int(declared) > cap:
        return None
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > cap:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


ClockOffsetProvider = Callable[[], Awaitable[int]] | Callable[[], int]
"""Returns the current clock offset in milliseconds, injected by the caller
(E08-S07 owns measurement; this client only *applies* it, per the ticket's
technical notes: "The clock offset is injected, not read from a global")."""


class _LaneBudget:
    """The lane's wait for one call (24 §8.7), on the client's monotonic clock: every attempt's
    token wait and every pause before a retry come out of it. Without one, nothing is bounded."""

    __slots__ = ("_clock", "_until", "left")

    def __init__(self, wait_s: float | None, clock: Callable[[], float]) -> None:
        self._clock = clock
        #: The next token wait's bound: the whole wait on the first attempt, what is left after.
        self.left = wait_s
        self._until = None if wait_s is None else clock() + wait_s

    def allows(self, pause_s: float) -> bool:
        """Whether a pause of `pause_s` from now ends within the budget."""
        return self._until is None or self._clock() + pause_s <= self._until

    def refresh(self) -> None:
        if self._until is not None:
            self.left = max(0.0, self._until - self._clock())


def _redact(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of `mapping` with any secret-shaped key's value
    replaced by a fixed placeholder — used before anything is logged."""
    out: dict[str, Any] = {}
    for key, value in mapping.items():
        lowered = key.lower()
        if any(marker in lowered for marker in _SECRET_KEY_MARKERS):
            out[key] = _REDACTED
        else:
            out[key] = value
    return out


class _Clock:
    """Injected wall-clock + offset, so timestamps are testable and the
    offset can be re-measured without this client owning a global."""

    def __init__(
        self,
        offset_ms_provider: ClockOffsetProvider | None,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._offset_ms_provider = offset_ms_provider
        self._wall_clock = wall_clock

    async def now_ms(self) -> int:
        base = int(self._wall_clock() * 1000)
        if self._offset_ms_provider is None:
            return base
        result = self._offset_ms_provider()
        offset = await result if asyncio.iscoroutine(result) else result
        return base + int(offset)  # type: ignore[arg-type]


class BybitRestClient:
    """Governed REST transport for one `(exchange, environment)` pair.

    Public (unauthenticated) calls work with `signer=None`; the signed path
    (`signed_request`) requires a `BybitSigner`. Every request is shaped by
    the process's one governor (`governor=`, required: OM-D08), in the lane
    its caller names, retried per the taxonomy's `retryable` flag with full
    jitter (never an order create that has left: 24 §8.6 "Order creates"),
    within the lane's wait when the caller gives one (24 §8.7), and logged
    with secrets redacted.
    """

    def __init__(
        self,
        config: RestClientConfig,
        *,
        uid: str = "public",
        signer: BybitSigner | None = None,
        governor: TokenBucketGovernor,
        clock_offset_ms_provider: ClockOffsetProvider | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_fn: Callable[[], float] = random.random,
        wall_clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        on_signature_failure: Callable[[], Awaitable[object]] | None = None,
    ) -> None:
        self._config = config
        self._on_signature_failure = on_signature_failure
        self._wall_clock = wall_clock
        #: Measures a lane's wait (24 §8.7); `sleep` must advance it, as `asyncio.sleep` does.
        self._monotonic = monotonic
        self._uid = uid
        self._signer = signer
        #: OM-D08: the process's one governor, given by the service; never built here.
        self._governor = governor
        self._clock = _Clock(clock_offset_ms_provider, wall_clock)
        self._sleep = sleep
        self._random = random_fn
        timeout = httpx.Timeout(config.total_timeout_s, connect=config.connect_timeout_s)
        limits = httpx.Limits(
            max_connections=config.max_connections,
            max_keepalive_connections=config.max_keepalive_connections,
        )
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=timeout,
            limits=limits,
            transport=transport,
            # SR-040a: a 3xx from the real host must never carry the signature elsewhere.
            follow_redirects=False,
        )

    async def check_reachable(self) -> bool:
        """Startup reachability probe for the configured `base_url` (ticket
        brief: "startup reachability check for the configured base URL").
        Calls the unauthenticated, unbudgeted server-time endpoint once and
        returns `True`/`False` rather than raising, so a caller can decide
        policy (retry, alert, refuse to start) without this client owning
        that decision."""
        try:
            await self._governor.acquire_ip_only()
            await self._client.request(
                "GET", "/v5/market/time", timeout=self._config.connect_timeout_s
            )
            return True
        except (TimeoutError, httpx.TransportError):
            return False

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> BybitRestClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def get_public(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        endpoint_class: EndpointClass = EndpointClass.MARKET_DATA,
    ) -> dict[str, Any]:
        """Unauthenticated `GET` — instrument catalogue, kline, server time, in the `poll` lane."""
        return await self._request(
            "GET",
            path,
            params=params,
            body=None,
            endpoint_class=endpoint_class,
            signed=False,
            lane="poll",
            budget_wait_s=None,
        )

    async def server_time(self) -> ServerTime:
        """Exchange server time from the public `/v5/market/time` endpoint, parsed through
        the validated `ServerTime` model (malformed payload -> `UnknownStateError`)."""
        return ServerTime.from_response(await self.get_public("/v5/market/time"))

    async def signed_request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        endpoint_class: EndpointClass = EndpointClass.ACCOUNT,
        lane: RateLane,
        budget_wait_s: float | None = None,
    ) -> dict[str, Any]:
        """Authenticated request. Raises `TypeError` if no signer was
        configured — a signed call is never silently downgraded to public.

        An order create (`/v5/order/create`, and every item of `/v5/order/create-batch`)
        **must** carry a non-empty `orderLinkId`, under any endpoint class: a create is retried
        only while it never left (24 §8.6 "Order creates"), and only the same client-generated id
        lets a duplicate read as "already accepted" rather than a second order (C-2.10). Every
        other call passes this guard: a cancel, `cancel-all` or amend by `orderId` is an exit
        that must reach the order class (OM-D09, AC-31). A path that takes a `category` must
        state `linear` (SR-054): it is refused, never filled in. All three refusals happen
        before a token is taken or anything is signed. `lane` is the caller's rate lane (20
        §4.3). `budget_wait_s` is the lane's wait, which bounds the whole call (24 §8.7): each
        attempt takes its own token within what is left of it, and a retry whose pause (a
        backoff, the venue's reset time or an IP hold) would end past it is not made, so the
        last attempt's own failure, a venue rate-limit answer included, is raised at once. A
        token refused before anything has been sent is `RateBudgetExceededError`."""
        if self._signer is None:
            raise TypeError("signed_request called without a configured BybitSigner")
        _require_create_ids(path, body)
        _require_linear_category(path, params, body)
        return await self._request(
            method,
            path,
            params=params,
            body=body,
            endpoint_class=endpoint_class,
            signed=True,
            lane=lane,
            budget_wait_s=budget_wait_s,
        )

    def _query_params(self, params: Mapping[str, Any] | None) -> httpx.QueryParams | None:
        if not params:
            return None
        return httpx.QueryParams(params)

    def _payload_string(
        self,
        method: str,
        query: httpx.QueryParams | None,
        body: Any,
    ) -> str:
        if method.upper() in ("GET", "DELETE"):
            if not query:
                return ""
            # Sign the exact wire-encoded query string (Bybit v5 signing spec:
            # the signature covers the URL-encoded query, not the raw repr of
            # the params mapping) so a value needing encoding — spaces,
            # `&`/`=`/unicode — can never desync the signature from what
            # httpx actually sends and trigger a spurious 10004.
            return str(query)
        return body if isinstance(body, str) else ("" if body is None else _json_dumps(body))

    def _assert_same_host(self, method: str, path: str) -> None:
        """Defence in depth: the built request must target the configured host."""
        built = self._client.build_request(method, path)
        expected = httpx.URL(self._config.base_url).host
        if built.url.host != expected or built.url.scheme != "https":
            raise RestPathRejected("built request host differs from configured base (SR-040a)")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        body: Mapping[str, Any] | None,
        endpoint_class: EndpointClass,
        signed: bool,
        lane: RateLane,
        budget_wait_s: float | None,
    ) -> dict[str, Any]:
        validate_rest_path(path)
        self._assert_same_host(method, path)
        creates = method.upper() == "POST" and path in _CREATE_PATHS
        attempt = 0
        clock_retry_used = False
        budget = _LaneBudget(budget_wait_s, self._monotonic)
        #: The failure of the last attempt that may have reached the venue: a token refused for a
        #: retry raises it, since "nothing was sent" no longer holds (24 §8.7).
        reached: ExchangeError | None = None
        while True:
            attempt += 1
            try:
                await self._governor.acquire(
                    self._uid, endpoint_class, lane=lane, deadline_s=budget.left
                )
            except RateBudgetExceededError:
                if reached is None:
                    raise
                raise reached from None
            headers: dict[str, str] = {}
            masked: tuple[str, ...] = ()
            query = self._query_params(params)
            payload_str = self._payload_string(method, query, body)
            if signed:
                if self._signer is None:
                    raise TypeError("signed request reached _request without a signer")
                timestamp_ms = await self._clock.now_ms()
                # C-2.7 (#2339): M2 computes the MAC; this client never holds the secret.
                auth = await self._signer.sign(
                    timestamp_ms=timestamp_ms,
                    recv_window_ms=self._config.recv_window_ms,
                    payload=payload_str,
                )
                headers.update(
                    {
                        "X-BAPI-API-KEY": auth.api_key,
                        "X-BAPI-TIMESTAMP": str(timestamp_ms),
                        "X-BAPI-RECV-WINDOW": str(self._config.recv_window_ms),
                        "X-BAPI-SIGN": auth.signature,
                    }
                )
                masked = (auth.api_key, auth.signature)
            if method.upper() in ("POST", "PUT"):
                headers["Content-Type"] = "application/json"

            logger().debug(
                "bybit_rest_request",
                method=method,
                path=path,
                attempt=attempt,
                endpoint_class=str(endpoint_class),
                headers=_redact(headers),
                params=_redact(params or {}),
            )

            start = self._monotonic()
            try:
                request = self._client.build_request(
                    method,
                    path,
                    params=query if method.upper() in ("GET", "DELETE") else None,
                    content=payload_str if method.upper() in ("POST", "PUT") else None,
                    headers=headers,
                )
                response = await self._client.send(request, stream=True)
                try:
                    raw = await _read_capped(response, _MAX_BODY_BYTES[endpoint_class])
                finally:
                    await response.aclose()
            except (TimeoutError, httpx.TransportError) as exc:
                bybit_rest_requests_total.labels(endpoint=path, result="transport_error").inc()
                if creates and not isinstance(exc, _NOT_SENT):
                    raise _ambiguous(path, body, type(exc).__name__) from exc
                # SR-E29-08: the class only, never the httpx text, which a caller logs.
                failure = TransportError(f"transport error calling {path} ({type(exc).__name__})")
                if not isinstance(exc, _NOT_SENT):
                    reached = failure
                if await self._retry(attempt, budget):
                    continue
                raise failure from exc
            except httpx.DecodingError as exc:  # a corrupt Content-Encoding: not a TransportError
                if not creates:
                    raise
                raise _answer_ambiguous(path, body, "an undecodable body") from exc
            finally:
                bybit_rest_latency_seconds.labels(endpoint=path).observe(self._monotonic() - start)

            if raw is None:
                bybit_rest_requests_total.labels(endpoint=path, result="oversized").inc()
                logger().warning(
                    "bybit_rest_body_too_large",
                    path=path,
                    endpoint_class=str(endpoint_class),
                    cap_bytes=_MAX_BODY_BYTES[endpoint_class],
                )
                too_large = RestBodyTooLarge(
                    f"{path} response body exceeds {_MAX_BODY_BYTES[endpoint_class]} bytes"
                )
                if creates:  # an answer came and was left unread: the create left
                    raise _ambiguous(path, body, "an oversized body") from too_large
                raise too_large

            raw = _mask(raw, masked)
            self._observe_rate_headers(response, endpoint_class)

            if response.status_code >= 500:
                bybit_rest_requests_total.labels(endpoint=path, result="5xx").inc()
                if creates:
                    raise _ambiguous(path, body, f"HTTP {response.status_code}")
                reached = TransportError(
                    f"{path} returned HTTP {response.status_code} after {attempt} attempts"
                )
                if await self._retry(attempt, budget):
                    continue
                raise reached

            is_http_error = response.status_code >= 400
            if is_http_error:
                bybit_rest_requests_total.labels(endpoint=path, result="4xx").inc()

            try:
                data = json.loads(raw)
            except RecursionError as exc:  # nested past the parser's limit: unread, like non-JSON
                if not creates:
                    raise
                raise _answer_ambiguous(path, body, "a body nested too deep") from exc
            except ValueError as exc:
                if creates:  # cut mid-body, or not the venue's answer: the create left
                    raise _answer_ambiguous(path, body, "a non-JSON body") from exc
                if endpoint_class is not EndpointClass.ORDER:
                    # Idempotent read: a truncated/non-JSON body (proxy, reset
                    # mid-body) is a transport fault -> retry like a 5xx (E08-Q03 #6).
                    # ORDER class keeps UnknownStateError: reconciliation owns it (C-2.10).
                    bybit_rest_requests_total.labels(endpoint=path, result="malformed_json").inc()
                    logger().warning(
                        "bybit_rest_malformed_json",
                        path=path,
                        attempt=attempt,
                        status=response.status_code,
                    )
                    reached = TransportError(
                        f"{path} returned a non-JSON body after {attempt} attempts"
                    )
                    if await self._retry(attempt, budget):
                        continue
                    raise reached from exc
                bybit_rest_requests_total.labels(endpoint=path, result="error").inc()
                exchange_errors_total.labels(**{"class": UnknownStateError.code.value}).inc()
                raise UnknownStateError(
                    f"{path} returned HTTP {response.status_code} with a non-JSON body: {exc}"
                ) from exc

            if creates and not _usable_ret_code(data, is_http_error):
                raise _answer_ambiguous(path, body, "no usable retCode")
            # A missing `retCode`, or `retCode == 0` on an HTTP error status,
            # is never treated as success — the raw body defaulted `retCode`
            # to 0 previously, which failed open on a 4xx with an unusual
            # body (review finding). HTTP status is now load-bearing.
            has_ret_code = "retCode" in data
            ret_code = int(data["retCode"]) if has_ret_code else -1
            if not has_ret_code or (is_http_error and ret_code == 0):
                bybit_rest_requests_total.labels(endpoint=path, result="error").inc()
                exchange_errors_total.labels(**{"class": UnknownStateError.code.value}).inc()
                # SR-E29-08: the body's type and size only, never its content (account figures).
                raise UnknownStateError(
                    f"{path} returned HTTP {response.status_code} with no usable retCode"
                    f" ({type(data).__name__}, {len(raw)} bytes)"
                )
            if ret_code == 0:
                bybit_rest_requests_total.labels(endpoint=path, result="ok").inc()
                return dict(data)

            ret_msg = str(data.get("retMsg", ""))
            if creates and ret_code in _AMBIGUOUS_RET_CODES:
                # Not a rate limit (#2863): no bucket drain, counted as the error raised.
                venue = {"exchange_ret_code": ret_code, "exchange_ret_msg": ret_msg}
                raise _answer_ambiguous(path, body, f"retCode {ret_code}", **venue)
            error = map_ret_code(ret_code, ret_msg, create=creates)
            if creates and isinstance(error, UnknownStateError):
                error.retryable = False  # its outcome is open: polled and reconciled, never resent
            exchange_errors_total.labels(**{"class": error.code.value}).inc()

            if isinstance(error, ClockDriftError) and not clock_retry_used:
                clock_retry_used = True
                reached = error
                bybit_rest_requests_total.labels(endpoint=path, result="clock_drift").inc()
                # Re-measure the offset (ClockGuard.resync_after_signature_failure,
                # injected by the composition root) *before* the single retry
                # re-signs with it (E08-S07 "Signature failure fallback").
                if self._on_signature_failure is not None:
                    try:
                        async with asyncio.timeout(_SIGNATURE_RESYNC_TIMEOUT_S):
                            await self._on_signature_failure()
                    except Exception as exc:  # re-measure failure must not mask the 10002
                        logger().warning("bybit_clock_resync_failed", error=type(exc).__name__)
                budget.refresh()
                continue

            if isinstance(error, RateLimitError):
                bybit_rate_limited_total.labels(code=str(ret_code)).inc()
                bybit_rest_requests_total.labels(endpoint=path, result="rate_limited").inc()
                self._account_for_rate_limit(response, endpoint_class)
                reset_wait_s = await self._reset_wait_s(response)
                if ret_code == _IP_RATE_LIMIT_CODE:
                    hold_s = min(max(_IP_HOLD_S, reset_wait_s), _MAX_RESET_WAIT_S)
                    self._governor.hold_ip(hold_s)
                    logger().warning("rest_ip_hold_started", hold_s=hold_s, code=ret_code)
                reached = error
                if error.retryable and await self._retry(
                    attempt, budget, floor_s=reset_wait_s, hint_s=error.retry_after_s
                ):
                    continue
                raise error

            bybit_rest_requests_total.labels(endpoint=path, result="error").inc()
            raise error

    async def _retry(
        self,
        attempt: int,
        budget: _LaneBudget,
        *,
        floor_s: float = 0.0,
        hint_s: float | None = None,
    ) -> bool:
        """Pause before another attempt and say so; `False` when none is made: `max_retries`
        are spent, or, under a lane's wait, the pause or an IP hold ends past it (24 §8.7), so
        no sleep runs past the lane's wait. The pause is the hint (the venue's own) or a jittered
        backoff, and never shorter than `floor_s` (the venue's reset time)."""
        if attempt > self._config.max_retries:
            return False
        pause_s = max(floor_s, hint_s or self._retry_after_default(attempt))
        if not budget.allows(max(pause_s, self._governor.ip_hold_remaining_s())):
            return False
        await self._sleep(pause_s)
        budget.refresh()
        return True

    def _observe_rate_headers(
        self, response: httpx.Response, endpoint_class: EndpointClass
    ) -> None:
        remaining_header = response.headers.get("X-Bapi-Limit-Status")
        if remaining_header is None:
            return
        try:
            remaining = int(remaining_header)
        except ValueError:
            return
        self._governor.observe_header(self._uid, endpoint_class, remaining)
        # E08-T06 security note: never a UID label (account identifier) - scope only.
        scope = "public" if self._uid == "public" else "account"
        bybit_rate_limit_remaining.labels(scope=scope, endpoint_class=str(endpoint_class)).set(
            remaining
        )

    def _account_for_rate_limit(
        self, response: httpx.Response, endpoint_class: EndpointClass
    ) -> None:
        """Reconcile the local bucket after a rate-limited response.

        `X-Bapi-Limit-Status` is the *remaining* budget, not the amount
        consumed (review finding: draining by that header's value drained
        the wrong quantity). `_observe_rate_headers` — called unconditionally
        on every response, above — already sets the bucket's `tokens` to
        that remaining value directly whenever the header is present, which
        is the correct reconciliation. When the header is absent we still
        know *some* budget was just consumed server-side that our own
        accounting did not schedule, so fall back to draining one token as a
        conservative, documented default (acceptance criterion 3's "drained
        by the advertised amount" only applies when an amount is
        advertised)."""
        if response.headers.get("X-Bapi-Limit-Status") is not None:
            return
        self._governor.drain(self._uid, endpoint_class, 1.0)

    async def _reset_wait_s(self, response: httpx.Response) -> float:
        """Seconds until `X-Bapi-Limit-Reset-Timestamp` (venue epoch ms), measured
        against the ClockGuard-corrected clock; 0.0 if absent/unparseable/past."""
        raw = response.headers.get("X-Bapi-Limit-Reset-Timestamp")
        if raw is None:
            return 0.0
        try:
            reset_ms = int(raw)
        except ValueError:
            return 0.0
        wait_s = (reset_ms - await self._clock.now_ms()) / 1000.0
        return min(max(0.0, wait_s), _MAX_RESET_WAIT_S)

    def _retry_after_default(self, attempt: int) -> float:
        base = min(2.0**attempt, 30.0)
        return base * (0.5 + self._random() * 0.5)


def _ambiguous(
    path: str, body: Mapping[str, Any] | None, cause: str, **detail: object
) -> AmbiguousResultError:
    """The create to `path` left and `cause` hides its outcome (24 §8.6 "Order creates"); the
    error names the create's id, or every item's of a batch (`order_link_ids`)."""
    link = body.get("orderLinkId") if body else None
    order_link_id = link if isinstance(link, str) else None
    items = body.get("request") if body and path == _BATCH_PATH else None
    order_link_ids = (
        tuple(item["orderLinkId"] for item in items if _has_link(item))
        if isinstance(items, list)
        else ()
    )
    exchange_errors_total.labels(**{"class": AmbiguousResultError.code.value}).inc()
    logger().warning(
        "bybit_rest_create_ambiguous",
        path=path,
        cause=cause,
        order_link_id=order_link_id,
        order_link_ids=list(order_link_ids),
    )
    return AmbiguousResultError(
        f"{path}: {cause} after the create left; its outcome is unknown",
        order_link_id=order_link_id,
        order_link_ids=order_link_ids,
        **detail,
    )


def _answer_ambiguous(
    path: str, body: Mapping[str, Any] | None, cause: str, **detail: object
) -> AmbiguousResultError:
    """An answer to the create arrived but hides its outcome: counted as the error raised."""
    bybit_rest_requests_total.labels(endpoint=path, result="error").inc()
    return _ambiguous(path, body, cause, **detail)


def _has_link(item: object) -> bool:
    link = item.get("orderLinkId") if isinstance(item, Mapping) else None
    return isinstance(link, str) and link != ""


def _require_create_ids(path: str, body: Mapping[str, Any] | None) -> None:
    """An order create, or each item of a batch, carries a non-empty `orderLinkId` (C-2.10)."""
    if path not in _CREATE_PATHS:
        return
    if path == _BATCH_PATH:
        items = body.get("request") if body else None
        complete = isinstance(items, list) and bool(items) and all(map(_has_link, items))
    else:
        complete = _has_link(body)
    if not complete:
        raise ValueError(
            "signed_request: an order create needs a non-empty 'orderLinkId' (every item of a "
            "batch too): a create is retried only before it leaves, under the same id (C-2.10)"
        )


def _require_linear_category(
    path: str, params: Mapping[str, Any] | None, body: Mapping[str, Any] | None
) -> None:
    """SR-054: a category-taking path states `category=linear` itself; never filled in."""
    if not (path.startswith(_CATEGORY_PREFIXES) or path in _CATEGORY_PATHS):
        return
    stated = (params or {}).get("category", (body or {}).get("category"))
    if stated != "linear":
        raise ValueError("signed_request: this path takes category, and only 'linear' (SR-054)")


def _mask(raw: bytes, values: tuple[str, ...]) -> bytes:
    for value in values:
        if len(value) >= _MIN_MASKED_LEN:
            raw = raw.replace(value.encode(), _MASK)
    return raw


def _usable_ret_code(data: object, is_http_error: bool) -> bool:
    """A create's answer is readable only with an integer `retCode` (a bool is not one) that is
    non-zero on an HTTP error status (24 §8.6 "Order creates")."""
    code = data.get("retCode") if isinstance(data, dict) else None
    return type(code) is int and not (is_http_error and code == 0)


def _json_dumps(body: Mapping[str, Any]) -> str:
    return json.dumps(body, separators=(",", ":"), sort_keys=True)


async def paginate_cursor(
    fetch_page: Callable[[str | None], Awaitable[tuple[list[dict[str, Any]], str | None]]],
) -> list[dict[str, Any]]:
    """Generic cursor-pagination helper (ticket deliverable "Cursor
    pagination helper"). `fetch_page(cursor)` returns `(rows, next_cursor)`;
    pagination stops when `next_cursor` is falsy."""
    all_rows: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        rows, cursor = await fetch_page(cursor)
        all_rows.extend(rows)
        if not cursor:
            return all_rows


async def paginate_klines(
    fetch_range: Callable[[int, int], Awaitable[list[dict[str, Any]]]],
    *,
    start_ms: int,
    end_ms: int,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Kline-specific paging helper (ticket deliverable "the kline 1 000-row
    limit paging helper"). Bybit returns at most `limit` rows per call,
    newest-first within the window; this walks the window backwards from
    `end_ms` until `start_ms` is covered or a page returns no rows. Both bounds
    are inclusive (Bybit semantics), so `start_ms == end_ms` is a one-bar window;
    only `start_ms > end_ms` is empty."""
    all_rows: list[dict[str, Any]] = []
    window_end = end_ms
    while window_end >= start_ms:
        page = await fetch_range(start_ms, window_end)
        if not page:
            break
        all_rows.extend(page)
        oldest_ts = min(int(row["start"]) for row in page if "start" in row)
        if oldest_ts <= start_ms or len(page) < limit:
            break
        window_end = oldest_ts - 1
    return all_rows
