"""Guard rails of the E29-K01 harness (#843), enforced in code before any request leaves.

Every REST request goes through `GuardedTransport`, which refuses before anything is sent: a host
other than the demo REST host, a method or path outside `ALLOWED_PATHS` (no fund-movement endpoint
is listed, so none is reachable), and an order body that breaks the native-SL rule (C-2.6), the
symbol allow-list, the per-order notional cap or the 24 §8.3 `orderLinkId` format. The private
stream dials `DEMO_WS_URL` only (`check_ws_url`). Refusals name the rule, never a value.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping, MutableMapping
from decimal import Decimal, InvalidOperation
from typing import Any, Final
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx

from candleviewer.accounts._permissions import reject_withdraw
from candleviewer.accounts.errors import WithdrawPermissionError
from candleviewer.domain.order_link import OUR_ID
from candleviewer.domain.primitives import AccountId, GroupId
from candleviewer.exchange.bybit.config import PRIVATE_WS_URLS, SIGNED_REST_BASES
from candleviewer.oms.order_link import OrderLinkIdParts, OrderPurpose
from candleviewer.secrets import Purpose, RequestSignature, Secret
from candleviewer.secrets.signing import SigningMessage, check_message, request_signature

DEMO: Final = "demo"
DEMO_REST_BASE: Final = SIGNED_REST_BASES[DEMO]
DEMO_WS_URL: Final = PRIVATE_WS_URLS[DEMO]
DEMO_REST_HOST: Final = urlsplit(DEMO_REST_BASE).hostname
#: USDT linear perpetuals only: the corpus symbols (packages/fixtures/bybit/README.md).
SYMBOLS: Final = frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT"})
#: Hard ceilings in USDT. The CLI may lower them, never raise them.
MAX_ORDER_NOTIONAL: Final = Decimal(250)
MAX_RUN_EXPOSURE: Final = Decimal(1000)
#: Every call the harness makes, by method. No other endpoint is reachable.
_GETS: Final = "market/time market/tickers market/instruments-info user/query-api order/realtime"
_GETS_MORE: Final = "order/history execution/list position/list"
ALLOWED_PATHS: Final[Mapping[str, frozenset[str]]] = {
    "GET": frozenset(f"/v5/{p}" for p in f"{_GETS} {_GETS_MORE}".split()),
    "POST": frozenset({"/v5/order/create", "/v5/order/amend", "/v5/order/cancel"}),
}
#: An amend changes price or qty only: the protection is never amended, so no amend can remove
#: or loosen the native SL.
_AMEND_FIELDS: Final = frozenset({"category", "symbol", "orderLinkId", "price", "qty"})
#: A credential field: 1 to 128 visible ASCII characters (as M2's candidate check).
_FIELD: Final = re.compile(r"[\x21-\x7e]{1,128}")
ENV_VAR: Final = "CV_SPIKE_BYBIT_ENV"
#: The demo key pair: key id, then its signing secret.
PAIR_VARS: Final = ("CV_SPIKE_BYBIT_API_KEY", "CV_SPIKE_BYBIT_API_SECRET")


class SafetyRefusal(RuntimeError):
    """A guard rail refused. The message names the rule, never a credential or a payload."""


def check_target(env: str, rest_base: str, ws_url: str) -> None:
    """Demo only, on exactly the demo REST and stream hosts of `exchange/bybit/config.py`."""
    if env != DEMO:
        raise SafetyRefusal(f"{ENV_VAR} must be demo")
    if rest_base != DEMO_REST_BASE or ws_url != DEMO_WS_URL:
        raise SafetyRefusal("hosts must be the demo REST and private-stream hosts")


def check_ws_url(url: str) -> None:
    if url != DEMO_WS_URL:
        raise SafetyRefusal("the private stream must be the demo stream")


def check_permissions(read_only: bool, permissions: Mapping[str, object]) -> None:
    """C-2.8: refuse a key with any withdrawal or transfer right (M13's predicate), and a
    read-only key, which cannot trade."""
    try:
        reject_withdraw(permissions)
    except WithdrawPermissionError:
        raise SafetyRefusal("key grants a withdrawal or transfer right (C-2.8)") from None
    if read_only:
        raise SafetyRefusal("key is read-only")


def _positive(value: object, name: str) -> Decimal:
    try:
        parsed = Decimal(value) if isinstance(value, str) else None
    except InvalidOperation:
        parsed = None
    if parsed is None or not parsed.is_finite() or parsed <= 0:
        raise SafetyRefusal(f"{name} must be a positive decimal string")
    return parsed


def _check_market(body: Mapping[str, Any]) -> None:
    if body.get("category") != "linear":
        raise SafetyRefusal("category must be linear (USDT perpetuals only)")
    if body.get("symbol") not in SYMBOLS:
        raise SafetyRefusal("symbol is not on the allow-list")


def _check_link(body: Mapping[str, Any]) -> None:
    link = body.get("orderLinkId")
    if not isinstance(link, str) or OUR_ID.fullmatch(link) is None or link[2] != "d":
        raise SafetyRefusal("orderLinkId must be a demo id in the 24 §8.3 format")


def new_link(account_id: AccountId, purpose: OrderPurpose) -> str:
    """A demo `orderLinkId` in the 24 §8.3 format, minted once per logical order (each order is
    its own trade group); every re-send of that order reuses it unchanged (C-2.10)."""
    return OrderLinkIdParts.generate(
        mode="exchange",
        environment=DEMO,
        group_id=GroupId(uuid4()),
        account_id=account_id,
        seq=0,
        purpose=purpose,
    ).value


def check_order(body: Mapping[str, Any], *, max_notional: Decimal) -> None:
    """A create body. An opening order (not reduce-only) is a Buy limit within the per-order cap
    that carries a native stopLoss below its price (C-2.6); a Sell must be reduce-only."""
    _check_market(body)
    _check_link(body)
    qty = _positive(body.get("qty"), "qty")
    if body.get("reduceOnly") is True:
        return
    if body.get("side") != "Buy" or body.get("orderType") != "Limit":
        raise SafetyRefusal("an opening order must be a Buy limit; a Sell must be reduce-only")
    price = _positive(body.get("price"), "price")
    if body.get("stopLoss") in (None, ""):
        raise SafetyRefusal("an opening order must carry a native stopLoss (C-2.6)")
    if _positive(body.get("stopLoss"), "stopLoss") >= price:
        raise SafetyRefusal("the stopLoss of a Buy must be below its price (C-2.6)")
    if qty * price > max_notional:
        raise SafetyRefusal("order notional is above the per-order cap")


def check_amend(body: Mapping[str, Any]) -> None:
    _check_market(body)
    _check_link(body)
    if not set(body) <= _AMEND_FIELDS:
        raise SafetyRefusal("an amend may change price or qty only, never the protection")


def check_request(method: str, url: httpx.URL, content: bytes, *, max_notional: Decimal) -> None:
    """Refuse, before anything is sent, a request the harness must never make."""
    if url.scheme != "https" or url.host != DEMO_REST_HOST or url.port not in (None, 443):
        raise SafetyRefusal("request host is not the demo REST host")
    if url.path not in ALLOWED_PATHS.get(method, frozenset()):
        raise SafetyRefusal("request method and path are not on the harness allow-list")
    if method != "POST":
        return
    try:
        body = json.loads(content)
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise SafetyRefusal("an order request body must be a JSON object")
    if url.path == "/v5/order/create":
        check_order(body, max_notional=max_notional)
    elif url.path == "/v5/order/amend":
        check_amend(body)
    else:
        _check_market(body)


#: `(request, http_status, headers, decoded body, round trip in seconds)`.
OnResponse = Callable[[httpx.Request, int, httpx.Headers, bytes, float], None]
#: Framing headers of the inner reply; the reply handed back carries the decoded body.
_FRAMING: Final = frozenset({"content-encoding", "content-length", "transfer-encoding"})


class GuardedTransport(httpx.AsyncBaseTransport):
    """The transport of every REST client of the harness: `check_request` first, then the send,
    timed from the hand-off to the end of the body (the REST round trip, signing and the
    adapter's governor excluded), then `on_response` with the reply's bytes."""

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        on_response: OnResponse,
        *,
        max_notional: Decimal,
        body_cap: int = 2 << 20,
    ) -> None:
        self._inner, self._on_response = inner, on_response
        self._max_notional, self._body_cap = max_notional, body_cap

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        check_request(request.method, request.url, request.content, max_notional=self._max_notional)
        request.headers["Accept-Encoding"] = "identity"
        started = time.perf_counter()
        response = await self._inner.handle_async_request(request)
        body = bytearray()
        try:
            async for chunk in response.aiter_bytes():  # decoded, bounded
                body += chunk
                if len(body) > self._body_cap:
                    raise httpx.ReadError("reply above the harness cap", request=request)
        finally:
            await response.aclose()
        rtt_s = time.perf_counter() - started
        self._on_response(request, response.status_code, response.headers, bytes(body), rtt_s)
        headers = [(k, v) for k, v in response.headers.multi_items() if k.lower() not in _FRAMING]
        return httpx.Response(
            response.status_code,
            headers=headers,
            content=bytes(body),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._inner.aclose()


class EnvCredentials:
    """The run's signing capability: the demo key pair from the process environment, held only in
    M2's `Secret` wrappers and MAC'd by M2's own `request_signature` (C-2.7). Never rendered."""

    __slots__ = ("_pair",)

    def __init__(self, key_id: Secret[str], secret: Secret[str]) -> None:
        self._pair = (key_id, secret)

    @property
    def key_id(self) -> Secret[str]:
        """For the scrubber's known-value check only."""
        return self._pair[0]

    async def sign(
        self, key_id: UUID, message: SigningMessage, *, purpose: Purpose
    ) -> RequestSignature:
        return request_signature(*self._pair, check_message(message))

    def __repr__(self) -> str:
        return "EnvCredentials(***)"


def load_credentials(environ: MutableMapping[str, str]) -> EnvCredentials:
    """Take the key pair out of the environment (popped: no child process inherits it)."""
    key_id, secret = (Secret(environ.pop(name, "")) for name in PAIR_VARS)
    if not all(_FIELD.fullmatch(part.reveal()) for part in (key_id, secret)):
        raise SafetyRefusal(f"{' and '.join(PAIR_VARS)} must hold 1-128 visible ASCII chars")
    return EnvCredentials(key_id, secret)
