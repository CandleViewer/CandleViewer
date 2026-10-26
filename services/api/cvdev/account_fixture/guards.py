"""#2893 S7: the per-request guards of the account fixture transport (ADR-0036 decision 4).

Layer 3 of the fence (E27 threat model section 12.1). Every request meets them in this order, before
anything is answered:

1. Host (C-2.11): REST is answered for the demo REST host alone, over https on its default port.
   Every other host, the rest of the adapter's table (`ALLOWED_REST_HOSTS`) included, is refused
   and logged as `refused_host`, a P0 (test plan section 0.1).
2. Fund paths (C-1.2 item 5, C-2.8): any path under `/v5/asset/`, where withdraw and transfer
   live, is refused as a P0, whatever its case, slashes or dot segments. It keys on the prefix,
   which the pack never serves, so no withdraw or transfer endpoint is written here (ADR-0036,
   Enforcement).
3. Key id (FX-S01): a signed request, one carrying any of the four auth headers, must carry a
   pack key id (`pack.fixture_key_ids`) exactly as its key header; the `fixture-<scenario>-NNNN`
   shape alone is not enough. Otherwise it is never answered and the transport latches. An
   unsigned request is answered only under `/v5/market/` (`is_public_path`, normalised as fund
   paths are); any other is refused as `refused_key`, without a latch or a P0.
4. Signature (FX-S02): HMAC-SHA256 with the derived secret of the scenario the key is stored under
   (`pack.derived_secret`), over the string the adapter's signer has M2 sign: timestamp, key id,
   receive window, then the query string for GET and DELETE or the body otherwise (the REST
   client's `_payload_string`). Compared in constant time; a mismatch answers 10004.

S12's private-WS socket meets the same guards: the adapter's demo private stream alone
(`DEMO_PRIVATE_WS`) at connect, then on its `auth` op a pack key id, then the signature the
adapter's signer has M2 make there (`ws_signature_verifies`).

The venue's hosts and header names are this stub's vocabulary by design (ADR-0036, Enforcement), so
`cvdev/**` is excluded from the two adapter-vocabulary Semgrep rules (S9).

This module decides, and holds one piece of state: `LATCH`, the process's one key-id guard latch.
`transport.FixtureTransport` refuses, latches, logs and answers. Nothing here imports
`candleviewer.secrets` or `candleviewer.audit`.
"""

from __future__ import annotations

import hashlib
import hmac
import posixpath
import threading
from dataclasses import dataclass
from typing import Final
from urllib.parse import unquote, urlsplit

import httpx

from candleviewer.exchange.bybit.config import ALLOWED_REST_HOSTS, PRIVATE_WS_URLS
from cvdev.account_fixture.pack import derived_secret
from cvdev.account_fixture.requestlog import HostEnv, KeyClass, Refusal

#: The adapter's host table names no host per environment, so the demo and testnet hosts the guard
#: tells apart are spelled here; the tests pin both to `ALLOWED_REST_HOSTS`. The rest are live.
_HOSTS: Final = ("api-demo.bybit.com", "api-testnet.bybit.com")
DEMO_REST_HOST, TESTNET_REST_HOST = _HOSTS
#: What the signer sends (the REST client's signed path): key id, timestamp, window, signature.
_AUTH_HEADERS: Final = ("X-BAPI-API-KEY", "X-BAPI-TIMESTAMP", "X-BAPI-RECV-WINDOW", "X-BAPI-SIGN")
KEY_HEADER, TIMESTAMP_HEADER, RECV_WINDOW_HEADER, SIGN_HEADER = _AUTH_HEADERS
FUND_PATH_PREFIX: Final = "/v5/asset/"
#: The read-only gate's reason code on a key-id trip (ADR-0036 decision 4).
GUARD_REASON_CODE: Final = "account_fixture_guard"
_FUND_SEGMENTS: Final = FUND_PATH_PREFIX.strip("/").split("/")
#: The public market allow-list: the only prefix an unsigned request is answered under (guard 3).
PUBLIC_PATH_PREFIX: Final = "/v5/market/"
_PUBLIC_SEGMENTS: Final = PUBLIC_PATH_PREFIX.strip("/").split("/")
QUERY_SIGNED: Final = frozenset({"GET", "DELETE"})
#: The one private stream the socket answers: the adapter's demo URL, exactly (C-2.11).
DEMO_PRIVATE_WS: Final = PRIVATE_WS_URLS["demo"]
#: What the signer has M2 sign for a WS `auth`, before `expires` (24 section 14.3, "Auth (WS)").
WS_AUTH_PREFIX: Final = b"GET/realtime"
_WS_HOSTS: Final[dict[str | None, HostEnv]] = {
    urlsplit(PRIVATE_WS_URLS["demo"]).hostname: "demo",
    urlsplit(PRIVATE_WS_URLS["live"]).hostname: "live",
    urlsplit(PRIVATE_WS_URLS["testnet"]).hostname: "testnet",
}
#: The process's one key-id guard latch (S7 lens MINOR-1), `wiring.LATCH`: every fixture transport,
#: and S12's socket, is built with it unless a test injects its own. Set by the first trip of any;
#: only a restart clears it (FX-D01).
LATCH: Final = threading.Event()


@dataclass(frozen=True, slots=True)
class Admission:
    """What guards 1 to 3 make of a request, and what of it may be logged."""

    #: The first guard it fails, or None.
    refusal: Refusal | None
    #: The host when it is in the adapter's table, else None: no other host is ever logged.
    host: str | None
    host_env: HostEnv | None
    key_class: KeyClass
    #: The pack key id that signed it, else None: no character of any other key is kept.
    key_id: str | None


def host_env(host: str) -> HostEnv | None:
    if host not in ALLOWED_REST_HOSTS:
        return None
    if host == DEMO_REST_HOST:
        return "demo"
    return "testnet" if host == TESTNET_REST_HOST else "live"


def ws_host_env(host: str | None) -> HostEnv | None:
    """The environment of a private-stream host of the adapter's table, else None."""
    return _WS_HOSTS.get(host)


def _segments(path: str) -> list[str]:
    """`path`'s segments, percent-decoded until nothing decodes, lower-cased, with repeated
    slashes and dot segments resolved. Each decode that changes the text shortens it."""
    while (decoded := unquote(path)) != path:
        path = decoded
    return [part for part in posixpath.normpath(path.lower()).split("/") if part]


def is_fund_path(path: str) -> bool:
    """Under `/v5/asset/`, whatever the case, repeated slashes, percent-encoding or dot segments."""
    return _segments(path)[:2] == _FUND_SEGMENTS


def is_public_path(path: str) -> bool:
    """Under `/v5/market/`, normalised as in `is_fund_path`: where an unsigned call may go."""
    return _segments(path)[:2] == _PUBLIC_SEGMENTS


def stored_under(key_id: str) -> str:
    """The scenario a pack key id is stored under: the `<scenario>` of `fixture-<scenario>-NNNN`
    (README), which the pack's checks hold to the manifest that names the key."""
    return key_id.removeprefix("fixture-")[:-5]


def admit(request: httpx.Request, key_ids: frozenset[str]) -> Admission:
    """Guards 1 to 3, in order (module docstring)."""
    url, headers = request.url, request.headers
    env = host_env(url.host)
    key = headers.get(KEY_HEADER)
    key_id = key if key in key_ids else None
    signed = any(name in headers for name in _AUTH_HEADERS)
    key_class: KeyClass = "fixture" if key_id else "non_fixture" if signed else "unsigned"
    refusal: Refusal | None = None
    if (url.scheme, url.host, url.port) != ("https", DEMO_REST_HOST, None):
        refusal = "refused_host"
    elif is_fund_path(url.path):
        refusal = "refused_fund_path"
    elif key_class == "non_fixture":
        refusal = "refused_key"
    return Admission(refusal, url.host if env else None, env, key_class, key_id)


def signature_verifies(request: httpx.Request, key_id: str, body: bytes) -> bool:
    """Guard 4 for a request a pack key id signed: false when a part is missing or differs."""
    headers = request.headers
    timestamp, window = headers.get(TIMESTAMP_HEADER), headers.get(RECV_WINDOW_HEADER)
    given = headers.get(SIGN_HEADER)
    if timestamp is None or window is None or given is None:
        return False
    payload = request.url.query if request.method in QUERY_SIGNED else body
    message = f"{timestamp}{key_id}{window}".encode() + payload
    secret = derived_secret(stored_under(key_id)).encode()
    expected = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), given.encode())


def ws_signature_verifies(key_id: str, expires: object, given: object) -> bool:
    """Guard 4 for a WS `auth` a pack key id signed: HMAC-SHA256 with the stored-under scenario's
    derived secret over `GET/realtime` and `expires` (an integer, as the adapter sends it); false
    for any other part. The stub never judges `expires` itself, as it never judges REST time."""
    if type(expires) is not int or not isinstance(given, str) or not given.isascii():
        return False  # a hex digest is ASCII; a lone surrogate would not even encode
    secret = derived_secret(stored_under(key_id)).encode()
    message = WS_AUTH_PREFIX + str(expires).encode()
    expected = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), given.encode())
