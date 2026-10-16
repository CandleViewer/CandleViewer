"""`redact_exchange_payload()` (E29-T01 #845 slice 2/3; SR-E29-08 second pass).

The ticket's fixture is a signed order create carrying `X-BAPI-SIGN`, `X-BAPI-API-KEY` and the
recv-window header (24-internal-schemas.md Sec.14.3 documents the four signing headers and the WS
`auth` frame). Its key and MAC are synthetic and built at run time, so no file holds a
credential-shaped literal (SR-145).
"""

from __future__ import annotations

import copy
import hashlib
import json
import string
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.domain.order_link import ext_key
from candleviewer.storage.repositories.exchange_payload import (
    MAX_DEPTH,
    MAX_ITEMS,
    MAX_PAYLOAD_CHARS,
    MAX_STRING_CHARS,
    OVERSIZE,
    REDACTED,
    redact_exchange_payload,
)

_KEY = "DUMMYKEY_" + "Q3w9" * 5  # synthetic, shaped like an API key (letters and digits)
_MAC = hashlib.sha256(b"cv-test-vector").hexdigest()  # synthetic 64-hex HMAC shape
_OUR = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"  # the #845 Gherkin id (24 Sec.8.3)
_ORDER_ID = "fd4300ae-7847-404e-b947-b46980a4d140"


@pytest.fixture
def signed_create_call() -> dict[str, Any]:
    """A signed REST order create and its answer, with the headers both nested and flattened."""
    headers = {
        "X-BAPI-API-KEY": _KEY,
        "X-BAPI-SIGN": _MAC,
        "X-BAPI-TIMESTAMP": "1760630400000",
        "X-BAPI-RECV-WINDOW": "5000",
        "Content-Type": "application/json",
    }
    body = {"category": "linear", "symbol": "BTCUSDT", "side": "Buy", "orderType": "Limit"}
    body |= {"qty": "0.010", "price": "63099.80", "orderLinkId": _OUR, "stopLoss": "62000"}
    result = {"orderId": _ORDER_ID, "orderLinkId": _OUR}
    response = {"retCode": 0, "retMsg": "OK", "result": result, "time": 1760630400123}
    call = {"method": "POST", "endpoint": "/v5/order/create", "headers": headers}
    return call | headers | {"body": body, "response": response}


def _blob(value: object) -> str:
    return json.dumps(value, allow_nan=False)


def test_signed_create_call_keeps_no_credential(signed_create_call: dict[str, Any]) -> None:
    out = redact_exchange_payload(signed_create_call)
    assert _KEY not in _blob(out) and _MAC not in _blob(out)
    for header in ("headers", "X-BAPI-API-KEY", "X-BAPI-SIGN", "X-BAPI-RECV-WINDOW"):
        assert out[header] == REDACTED
    assert out["X-BAPI-TIMESTAMP"] == REDACTED


def test_signed_create_call_keeps_the_order_data(signed_create_call: dict[str, Any]) -> None:
    out = redact_exchange_payload(signed_create_call)
    assert (out["method"], out["endpoint"]) == ("POST", "/v5/order/create")
    assert out["body"] == signed_create_call["body"]
    assert out["response"] == signed_create_call["response"]


def test_input_is_never_mutated(signed_create_call: dict[str, Any]) -> None:
    before = copy.deepcopy(signed_create_call)
    redact_exchange_payload(signed_create_call)
    assert signed_create_call == before


def test_auth_frame_args_are_redacted_and_the_frame_kept() -> None:
    frame = {"op": "auth", "args": [_KEY, 1760630405000, _MAC], "req_id": "auth-1"}
    assert redact_exchange_payload({"frame": frame}) == {
        "frame": {"op": "auth", "args": REDACTED, "req_id": "auth-1"}
    }


def test_args_of_other_frames_are_kept() -> None:
    frame = {"op": "subscribe", "args": ["order.linear", "execution.linear"]}
    assert redact_exchange_payload(frame) == frame


@pytest.mark.parametrize(
    ("url", "kept"),
    [
        (f"wss://ws.example/v5/private?api_key={_KEY}&signature={_MAC}", "wss://ws.example/v5/private?"),
        (f"/v5/order/realtime?symbol=BTCUSDT&sign={_MAC}", "/v5/order/realtime?"),
    ],
)  # fmt: skip
def test_a_url_keeps_its_path_and_loses_its_query(url: str, kept: str) -> None:
    assert redact_exchange_payload({"url": url}) == {"url": kept + REDACTED}


@pytest.mark.parametrize(
    "query", [f"api_key={_KEY}&timestamp=1", "symbol=BTCUSDT&recvWindow=5000", "a=1;token=x"]
)
def test_a_query_string_naming_a_credential_is_redacted(query: str) -> None:
    assert redact_exchange_payload({"query": query}) == {"query": REDACTED}


@pytest.mark.parametrize(
    "name",
    [
        "sign", "signature", "Signature", "key", "apiKey", "api_key", "API-KEY", "api_secret",
        "secret", "secretKey", "token", "access_token", "Authorization", "auth", "Cookie",
        "set-cookie", "password", "passphrase", "private_key", "credentials", "session",
        "recvWindow", "recv_window", "headers", "Header", "x-anything", "X_BAPI_SIGN",
    ],
)  # fmt: skip
def test_a_credential_or_header_name_is_redacted_at_any_depth(name: str) -> None:
    raw = {name: "v", "nested": [{name: {"deep": "v"}}]}
    assert redact_exchange_payload(raw) == {name: REDACTED, "nested": [{name: REDACTED}]}


@pytest.mark.parametrize(
    "name",
    ["symbol", "orderId", "orderLinkId", "stopLoss", "takeProfit", "retMsg", "op", "reqId",
     "monkey", "keyword", "design", "time", "side"],
)  # fmt: skip
def test_ordinary_names_are_kept(name: str) -> None:
    assert redact_exchange_payload({name: "v"}) == {name: "v"}


@pytest.mark.parametrize(
    "text",
    [
        f"bad key {_KEY}",
        f"sig={_MAC}",
        _MAC.upper(),
        "0123456789abcdefgh",  # 18: letters and digits
        "connection 1760630400000Q3w9a stalled",
    ],
)
def test_a_credential_shaped_string_is_redacted(text: str) -> None:
    assert redact_exchange_payload({"retMsg": text}) == {"retMsg": REDACTED}


@pytest.mark.parametrize(
    "text",
    [
        _OUR,
        f"order {_OUR} accepted",
        ext_key(_ORDER_ID),
        f"adopted as {ext_key('1321003749386327552')}",
        _ORDER_ID,
        "1760630400000",
        "1321003749386327552",
        "63099.800000000000000000",
        "insufficient available balance for this order",
        "ABCDEFGHIJKLMNOPQRST",  # letters only: a word, not a key
        "abcdefghijklmnopqrstuvwxyz",
        "CreateByPartialTakeProfit",  # a CamelCase enum value
        "EC_PostOnlyWillTakeLiquidity",
    ],
)
def test_ids_numbers_and_words_are_kept(text: str) -> None:
    assert redact_exchange_payload({"retMsg": text}) == {"retMsg": text}


def test_values_become_plain_json() -> None:
    raw: dict[str, Any] = {
        "price": Decimal("63099.80"),
        "fee": 2.5,
        "n": 3,
        "flag": True,
        "none": None,
        "pair": ("a", 1),
    }
    out = redact_exchange_payload(raw)
    assert out == {
        "price": "63099.80",
        "fee": 2.5,
        "n": 3,
        "flag": True,
        "none": None,
        "pair": ["a", 1],
    }
    assert _blob(out)


@pytest.mark.parametrize(
    "value",
    [
        float("nan"), float("inf"), Decimal("NaN"), Decimal("-Infinity"), b"raw-bytes",
        bytearray(b"x"), {"a"}, object(), datetime(2026, 10, 16, tzinfo=UTC), uuid.uuid4(),
    ],
)  # fmt: skip
def test_a_value_that_is_not_finite_json_is_redacted(value: object) -> None:
    assert redact_exchange_payload({"v": value, "kept": "x"}) == {"v": REDACTED, "kept": "x"}


def test_non_string_and_credential_shaped_keys_are_dropped() -> None:
    raw: dict[Any, Any] = {1: "a", ("t",): "b", _KEY: "c", "kept": "d"}
    assert redact_exchange_payload(raw) == {"kept": "d"}


@pytest.mark.parametrize("bad", ["a\x00b", "lone \ud800 surrogate", "\udfff"])
def test_text_that_jsonb_refuses_is_replaced_or_dropped(bad: str) -> None:
    """Either would fail the whole insert, so it never reaches the statement."""
    assert redact_exchange_payload({"v": bad, bad: "x", "kept": "a\U0001f600b"}) == {
        "v": REDACTED,
        "kept": "a\U0001f600b",
    }


def test_an_integer_past_64_bits_is_cut() -> None:
    raw = {"ok": 2**64 - 1, "neg": -(2**63), "big": 2**64, "huge": 10**5000}
    assert redact_exchange_payload(raw) == {
        "ok": 2**64 - 1,
        "neg": -(2**63),
        "big": OVERSIZE,
        "huge": OVERSIZE,
    }


@pytest.mark.parametrize("raw", [[1, 2], "text", None, 7])
def test_a_payload_that_is_not_an_object_is_replaced(raw: Any) -> None:
    assert redact_exchange_payload(raw) == {"redacted": REDACTED}


def _nest(depth: int) -> dict[str, Any]:
    tree: dict[str, Any] = {"leaf": "x"}
    for _ in range(depth):
        tree = {"n": tree}
    return tree


def test_nesting_past_the_depth_bound_is_cut() -> None:
    assert redact_exchange_payload(_nest(MAX_DEPTH - 1)) == _nest(MAX_DEPTH - 1)
    out: Any = redact_exchange_payload(_nest(MAX_DEPTH))
    for _ in range(MAX_DEPTH):
        out = out["n"]
    assert out == OVERSIZE


def test_nested_lists_past_the_depth_bound_are_cut() -> None:
    tree: Any = ["x"]
    for _ in range(MAX_DEPTH - 1):
        tree = [tree]
    assert redact_exchange_payload({"l": tree}) == {"l": [[[[[[[OVERSIZE]]]]]]]}


def test_a_root_past_the_item_bound_is_replaced_whole() -> None:
    fits = {f"k{i}": i for i in range(MAX_ITEMS)}
    assert redact_exchange_payload(fits) == fits
    assert redact_exchange_payload(fits | {"one_more": 1}) == {"redacted": OVERSIZE}


def test_containers_and_strings_past_their_bounds_are_cut() -> None:
    fits = {"l": list(range(MAX_ITEMS)), "s": ("a b" * MAX_STRING_CHARS)[:MAX_STRING_CHARS]}
    assert redact_exchange_payload(fits) == fits
    over = {"l": list(range(MAX_ITEMS + 1)), "d": {f"k{i}": i for i in range(MAX_ITEMS + 1)}}
    over |= {"s": "a" * (MAX_STRING_CHARS + 1)}
    assert redact_exchange_payload(over) == {"l": OVERSIZE, "d": OVERSIZE, "s": OVERSIZE}


def test_an_oversize_result_is_replaced_whole() -> None:
    chunk = "word " * (MAX_STRING_CHARS // 6)
    raw = {f"k{i}": chunk for i in range(MAX_PAYLOAD_CHARS // len(chunk) + 1)}
    assert redact_exchange_payload(raw) == {"redacted": OVERSIZE}


# -- properties: no seeded secret survives, and a second pass changes nothing --------------------

_ALNUM = string.ascii_letters + string.digits
_SECRETS = st.text(_ALNUM, min_size=18, max_size=64).filter(
    lambda s: not s.isalpha() and not s.isdigit()
)
_WORDS = st.text(string.ascii_lowercase + " .,:", max_size=24)


def _containers(inner: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    keys = st.sampled_from(["a", "b", "symbol", "result", "list"])
    return st.lists(inner, max_size=4) | st.dictionaries(keys, inner, max_size=4)


_JSON = st.recursive(st.none() | st.booleans() | st.integers() | _WORDS, _containers, max_leaves=12)
_PLACES = st.sampled_from(["name", "header", "auth", "text", "url"])


def _plant(tree: Any, secret: str, place: str) -> dict[str, Any]:
    planted = {
        "name": {"apiKey": secret},
        "header": {"headers": {"Accept": secret}},
        "auth": {"op": "auth", "args": [secret]},
        "text": {"retMsg": f"rejected: {secret} is invalid"},
        "url": {"url": f"https://host.example/v5/x?k={secret}"},
    }[place]
    return {"tree": tree, "at": [planted]}


@given(tree=_JSON, secret=_SECRETS, place=_PLACES)
def test_no_seeded_secret_survives_and_redaction_is_idempotent(
    tree: Any, secret: str, place: str
) -> None:
    out = redact_exchange_payload(_plant(tree, secret, place))
    assert secret not in _blob(out)
    assert redact_exchange_payload(out) == out
