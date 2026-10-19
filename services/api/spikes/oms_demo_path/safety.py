"""Guard rails of the E29-K01 harness (#843), enforced in code before any request leaves.

Every REST request goes through `GuardedTransport`, which refuses before anything is sent: a host
other than the demo REST host, a method or path outside `ALLOWED_PATHS` (no fund-movement endpoint
is listed, so none is reachable), an order body that breaks the native-SL rule (C-2.6), the
symbol allow-list, the per-order notional cap or the 24 §8.3 `orderLinkId` format, and an amend
that touches anything but the price of an order the run created, or moves it to its stop. The
private stream dials `DEMO_WS_URL` only (`check_ws_url`). Refusals name the rule, never a value.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, Final
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx

# M13's own key judgements (E27-T03), applied unchanged: its fund-right gate (the C-2.8 deny-list,
# then `withdraw_enabled` for any right of `Wallet`, a fiat or a card group, or a lookalike
# spelling) and its single-host test for a whitelist entry (`createApiKey` step 5).
from candleviewer.accounts.verification import _gate_failures, _host
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
#: An amend changes the price only: never the qty (the per-order cap holds) and never the
#: protection, so no amend can remove or loosen the native SL.
_AMEND_FIELDS: Final = frozenset({"category", "symbol", "orderLinkId", "price"})
#: A credential field: 1 to 128 visible ASCII characters (as M2's candidate check).
_FIELD: Final = re.compile(r"[\x21-\x7e]{1,128}")
ENV_VAR: Final = "CV_SPIKE_BYBIT_ENV"
#: The demo key pair: key id, then its signing secret.
PAIR_VARS: Final = ("CV_SPIKE_BYBIT_API_KEY", "CV_SPIKE_BYBIT_API_SECRET")
#: The start of every `orderLinkId` the harness sends (24 §8.3: `cv`, the demo letter, `-`): what
#: the owner filters the demo UI's open orders by when a cleanup did not finish.
LINK_PREFIX: Final = "cvd-"


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


def check_permissions(
    read_only: bool, permissions: Mapping[str, object], *, ips: Sequence[str]
) -> None:
    """C-2.8: refuse a key that may move funds (M13's `withdraw_enabled` judgement: a withdrawal
    or transfer right, any right of `Wallet` or of a fiat or card group, or one named for either
    in another spelling) and a key with no IP allowlist (empty, a wildcard or a range: every
    entry must be one host address). Then refuse a read-only key, which cannot trade."""
    if _gate_failures(permissions)[1]:
        raise SafetyRefusal(
            "key may move funds: a withdrawal, transfer, wallet, fiat or card right (C-2.8)"
        )
    if not ips or any(_host(entry) is None for entry in ips):
        raise SafetyRefusal("key has no IP allowlist of host addresses (C-2.8)")
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


def check_order(body: Mapping[str, Any], *, max_notional: Decimal) -> Decimal | None:
    """A create body. An opening order (not reduce-only) is a Buy limit within the per-order cap
    that carries a native stopLoss below its price (C-2.6); a Sell must be reduce-only. Returns
    the opening order's stopLoss (`None` for a reduce-only order)."""
    _check_market(body)
    _check_link(body)
    qty = _positive(body.get("qty"), "qty")
    if body.get("reduceOnly") is True:
        return None
    if body.get("side") != "Buy" or body.get("orderType") != "Limit":
        raise SafetyRefusal("an opening order must be a Buy limit; a Sell must be reduce-only")
    price = _positive(body.get("price"), "price")
    if body.get("stopLoss") in (None, ""):
        raise SafetyRefusal("an opening order must carry a native stopLoss (C-2.6)")
    stop = _positive(body.get("stopLoss"), "stopLoss")
    if stop >= price:
        raise SafetyRefusal("the stopLoss of a Buy must be below its price (C-2.6)")
    if qty * price > max_notional:
        raise SafetyRefusal("order notional is above the per-order cap")
    return stop


def check_amend(body: Mapping[str, Any], *, stops: Mapping[str, Decimal]) -> None:
    """An amend of an opening order this run created (`stops`: its `orderLinkId` to its
    stopLoss): the price only, and still above that stopLoss (C-2.6). The qty never changes, so
    the per-order cap holds; the protection is never touched."""
    _check_market(body)
    _check_link(body)
    if not set(body) <= _AMEND_FIELDS:
        raise SafetyRefusal("an amend may change the price only, never the qty or the protection")
    stop = stops.get(str(body.get("orderLinkId")))
    if stop is None:
        raise SafetyRefusal("an amend must target an opening order this run created")
    if _positive(body.get("price"), "price") <= stop:
        raise SafetyRefusal("an amend may not move the price to or below the stopLoss (C-2.6)")


def check_request(
    method: str,
    url: httpx.URL,
    content: bytes,
    *,
    max_notional: Decimal,
    stops: MutableMapping[str, Decimal],
) -> None:
    """Refuse, before anything is sent, a request the harness must never make. An opening
    create that passes leaves its stopLoss in `stops`, the bound for later amends of it."""
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
        stop = check_order(body, max_notional=max_notional)
        if stop is not None:
            stops[body["orderLinkId"]] = stop
    elif url.path == "/v5/order/amend":
        check_amend(body, stops=stops)
    else:
        _check_market(body)


#: `(request, http_status, headers, decoded body, round trip in seconds)`.
OnResponse = Callable[[httpx.Request, int, httpx.Headers, bytes, float], None]
#: Framing headers of the inner reply; the reply handed back carries the decoded body.
_FRAMING: Final = frozenset({"content-encoding", "content-length", "transfer-encoding"})


class GuardedTransport(httpx.AsyncBaseTransport):
    """The transport of every REST client of the harness: `check_request` first, then the send,
    timed from the hand-off to the end of the body (the REST round trip, signing and the
    adapter's governor excluded), then `on_response` with the reply's bytes. It keeps the
    stopLoss of every opening create it let through, the bound of the amend check."""

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
        self._stops: dict[str, Decimal] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        check_request(
            request.method,
            request.url,
            request.content,
            max_notional=self._max_notional,
            stops=self._stops,
        )
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
    M2's `Secret` wrappers and MAC'd by M2's own `request_signature`. Never rendered. Holding the
    pair outside `services/api/secrets/` is a deviation from C-2.7 and C-3.2 that this throwaway,
    never-merged spike records (README.md, Deviations)."""

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
    """Take the key pair out of the environment. Popped, so no child process inherits it; the
    process's own initial environment block keeps it, so the README scopes the pair to the one
    command."""
    key_id, secret = (Secret(environ.pop(name, "")) for name in PAIR_VARS)
    if not all(_FIELD.fullmatch(part.reveal()) for part in (key_id, secret)):
        raise SafetyRefusal(f"{' and '.join(PAIR_VARS)} must hold 1-128 visible ASCII chars")
    return EnvCredentials(key_id, secret)
