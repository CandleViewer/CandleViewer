"""E27-T03 key-verification replies: key info, the signed probe and refusal classes (#836).

Inputs are the documented-shape fixtures in `tests/fixtures/key_verification/` (README there) plus
the shared corpus's 10002/10018 replies. Field semantics follow the E27 threat model §5 item 3.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from candleviewer.exchange.base.errors import (
    AuthError,
    ExchangeError,
    RateLimitError,
    TransportError,
    UnknownStateError,
)
from candleviewer.exchange.bybit.key_info import (
    KEY_INFO_PATH,
    PROBE_PATH,
    ApiKeyFacts,
    parse_key_info,
    parse_probe,
    probe_error,
    refusal,
)
from candleviewer.exchange.bybit.mapping import map_ret_code
from candleviewer.exchange.bybit.rest import validate_rest_path
from tests._corpus import rest

FIXTURES = Path(__file__).parents[3] / "fixtures" / "key_verification"
#: Stand-in key id and secret in a reply; the dummy prefix is the gitleaks allow-list's (SR-145).
MARKER = "DUMMYKEY_NOT_A_KEY_0001"


def load(name: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return body


def key_info(**result: Any) -> dict[str, Any]:
    body = copy.deepcopy(load("key_info_trade.json"))
    body["result"].update(result)
    return body


@pytest.mark.parametrize("uid", [1000001, "1000001"])
def test_parse_key_info_reads_the_gate_fields(uid: int | str) -> None:
    assert parse_key_info(key_info(userID=uid)) == ApiKeyFacts(
        uid="1000001",
        uta=True,
        read_only=False,
        permissions=load("key_info_trade.json")["result"]["permissions"],
        ip_whitelist=("203.0.113.7",),
        expires_at=datetime(2027, 4, 13, tzinfo=UTC),
    )


@pytest.mark.parametrize(("flag", "deprecated", "uta"), [(0, 1, False), (1, 0, True)])
def test_uta_flag_decides_uta_not_the_deprecated_unified_flag(
    flag: int, deprecated: int, uta: bool
) -> None:
    assert parse_key_info(key_info(uta=flag, unified=deprecated)).uta is uta


@pytest.mark.parametrize("raw", ["", None, "1970-01-01T00:00:00Z", "0001-01-01T00:00:00Z"])
def test_absent_or_zero_time_expiry_is_none(raw: str | None) -> None:
    assert parse_key_info(key_info(expiredAt=raw)).expires_at is None


def test_a_deadline_day_of_minus_one_means_no_expiry() -> None:
    assert parse_key_info(key_info(deadlineDay=-1)).expires_at is None


def test_key_id_and_secret_fields_never_reach_the_facts() -> None:
    facts = parse_key_info(key_info(apiKey=MARKER, secret=MARKER))
    assert MARKER not in repr(facts)


_FIELD_EDITS: list[dict[str, Any]] = [
    {"userID": "10x"},
    {"userID": True},
    {"readOnly": 2},
    {"uta": "1"},
    {"ips": "203.0.113.7"},
    {"permissions": ["ContractTrade"]},
    {"expiredAt": "soon"},
    {"expiredAt": "2027-04-13T00:00:00"},
]
MALFORMED = [
    *[pytest.param(key_info(apiKey=MARKER, **edit), id=next(iter(edit))) for edit in _FIELD_EDITS],
    pytest.param({"retCode": 0, "result": f"apiKey={MARKER}"}, id="result_not_an_object"),
    pytest.param({"retCode": 0, "retMsg": MARKER}, id="result_missing"),
]


@pytest.mark.parametrize("body", MALFORMED)
def test_malformed_key_info_message_never_echoes_the_reply(body: dict[str, Any]) -> None:
    with pytest.raises(UnknownStateError) as caught:
        parse_key_info(body)
    assert MARKER not in str(caught.value)


@pytest.mark.parametrize("body", MALFORMED)
def test_malformed_key_info_chains_no_exception(body: dict[str, Any]) -> None:
    with pytest.raises(UnknownStateError) as caught:
        parse_key_info(body)
    assert (caught.value.__cause__, caught.value.__context__) == (None, None)


def test_parse_probe_takes_the_exchange_clock() -> None:
    seen = parse_probe(load("wallet_balance.json"), sent_at_ms=10, received_at_ms=30)
    assert (seen.server_time_ms, seen.sent_at_ms, seen.received_at_ms) == (1792054800000, 10, 30)


@pytest.mark.parametrize(
    "change", [{"time": "1792054800000"}, {"time": None}, {"time": 5}, {"retCode": 1}]
)
def test_malformed_probe_is_unknown_state(change: dict[str, Any]) -> None:
    with pytest.raises(UnknownStateError):
        parse_probe({**load("wallet_balance.json"), **change}, sent_at_ms=0, received_at_ms=1)


def _error(body: dict[str, Any]) -> ExchangeError:
    return map_ret_code(int(body["retCode"]), str(body["retMsg"]))


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("error_10003.json", ("unknown_key", 10003)),
        ("error_10010.json", ("ip_not_allowed", 10010)),
        ("error_33004.json", ("key_expired", 33004)),
    ],
)
def test_refusals_with_a_verdict(name: str, expected: tuple[str, int]) -> None:
    assert refusal(_error(load(name))) == expected


def test_permission_denied_is_a_verdict() -> None:
    assert refusal(map_ret_code(10005, "permission denied")) == ("permission_denied", 10005)


def test_expired_key_is_a_verdict_once_classed_as_an_auth_error() -> None:
    assert refusal(AuthError("expired", exchange_ret_code=33004)) == ("key_expired", 33004)


@pytest.mark.parametrize(
    "error",
    [
        _error(load("error_10004.json")),
        _error(rest("rest/error_10002.json")),
        _error(rest("rest/error_10018.json")),
        TransportError("HTTP 503"),
        UnknownStateError("malformed"),
        UnknownStateError("not an auth error", exchange_ret_code=10003),
        RateLimitError("not an expiry", exchange_ret_code=33004),
    ],
    ids=[
        "signature",
        "clock",
        "rate_limit",
        "5xx",
        "malformed",
        "verdict_code_not_auth",
        "expiry_code_wrong_class",
    ],
)
def test_other_failures_are_inconclusive(error: ExchangeError) -> None:
    assert refusal(error) is None


@pytest.mark.parametrize("path", [KEY_INFO_PATH, PROBE_PATH])
def test_paths_pass_the_rest_path_guard(path: str) -> None:
    assert validate_rest_path(path) == path


@pytest.mark.parametrize(
    ("code", "name"),
    [
        (10002, "clock_drift"),
        (10003, "auth_error"),
        (10004, "auth_error"),
        (10005, "permission_denied"),
        (10006, "rate_limited"),
        (10010, "ip_not_allowed"),
        (10016, "service_unavailable"),
        (10018, "rate_limited"),
        (10019, "service_unavailable"),
        (10429, "rate_limited"),
    ],
)
def test_probe_error_is_named_by_the_exchange_code(code: int, name: str) -> None:
    """Its own table (#3089), not `map_ret_code`, which folds 10005 and 10010 into an auth error."""
    assert probe_error(map_ret_code(code, "exchange text")) == name


@pytest.mark.parametrize("code", [10001, 10403, 33004, 110001, 3400139])
def test_any_other_exchange_code_is_exchange_unknown_whatever_its_error_class(code: int) -> None:
    """A code outside the contract's table (#3089) is unknown, whatever class the mapping gives."""
    assert probe_error(map_ret_code(code, "exchange text")) == "exchange_unknown"


def test_the_local_ip_hold_refusal_is_rate_limited_without_an_exchange_code() -> None:
    assert probe_error(RateLimitError("an IP-level hold is in force", retry_after_s=600.0)) == (
        "rate_limited"
    )


@pytest.mark.parametrize(
    "error",
    [UnknownStateError("malformed key-info reply"), ExchangeError("untyped")],
    ids=["malformed_reply", "untyped"],
)
def test_an_error_with_no_exchange_code_and_no_class_of_its_own_is_exchange_unknown(
    error: ExchangeError,
) -> None:
    assert probe_error(error) == "exchange_unknown"


@pytest.mark.parametrize(
    ("cause", "name"),
    [
        (None, "service_unavailable"),
        (httpx.ConnectError("unreachable"), "transport_error"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectTimeout("slow"), "timeout"),
        (TimeoutError(), "timeout"),
        (ValueError("not json"), "transport_error"),
    ],
    ids=["5xx", "reset", "read_timeout", "connect_timeout", "deadline", "non_json_body"],
)
def test_a_transport_error_is_refined_by_its_cause(cause: Exception | None, name: str) -> None:
    error = TransportError("transport fault")
    error.__cause__ = cause
    assert probe_error(error) == name
