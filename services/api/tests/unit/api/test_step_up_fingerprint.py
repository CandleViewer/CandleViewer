"""#2304: the fingerprint a no-grace step-up grant is bound to (pure helpers, no I/O).

SHA-256 of the method, the raw request target and the RFC 8785 (JCS) serialisation of the
validated body. The JCS vectors are RFC 8785's own (Appendix B and sections 3.2.2-3.2.3).
"""

from __future__ import annotations

import hashlib
import json
import random
import struct

import pytest
from hypothesis import given
from hypothesis import strategies as st
from starlette.requests import Request

from candleviewer.api.step_up_challenge import (
    canonical_json,
    raw_request_target,
    request_fingerprint,
)

#: RFC 8785 Appendix B: IEEE-754 bit pattern -> ECMAScript serialisation.
_NUMBER_VECTORS = [
    ("0000000000000000", "0"),
    ("8000000000000000", "0"),
    ("0000000000000001", "5e-324"),
    ("8000000000000001", "-5e-324"),
    ("7fefffffffffffff", "1.7976931348623157e+308"),
    ("ffefffffffffffff", "-1.7976931348623157e+308"),
    ("4340000000000000", "9007199254740992"),
    ("c340000000000000", "-9007199254740992"),
    ("4430000000000000", "295147905179352830000"),
    ("44b52d02c7e14af5", "9.999999999999997e+22"),
    ("44b52d02c7e14af6", "1e+23"),
    ("44b52d02c7e14af7", "1.0000000000000001e+23"),
    ("444b1ae4d6e2ef4e", "999999999999999700000"),
    ("444b1ae4d6e2ef4f", "999999999999999900000"),
    ("444b1ae4d6e2ef50", "1e+21"),
    ("3eb0c6f7a0b5ed8c", "9.999999999999997e-7"),
    ("3eb0c6f7a0b5ed8d", "0.000001"),
    ("41b3de4355555553", "333333333.3333332"),
    ("41b3de4355555554", "333333333.33333325"),
    ("41b3de4355555555", "333333333.3333333"),
    ("41b3de4355555556", "333333333.3333334"),
    ("41b3de4355555557", "333333333.33333343"),
    ("becbf647612f3696", "-0.0000033333333333333333"),
    ("43143ff3c1cb0959", "1424953923781206.2"),
]


@pytest.mark.parametrize(("bits", "text"), _NUMBER_VECTORS)
def test_canonical_json_writes_rfc_8785_numbers(bits: str, text: str) -> None:
    assert canonical_json(struct.unpack(">d", bytes.fromhex(bits))[0]) == text.encode()


def test_canonical_json_matches_the_rfc_8785_example() -> None:
    """RFC 8785 §3.2.2: number forms, string escapes and literals."""
    source = (
        '{"numbers": [333333333.33333329, 1E30, 4.50, 2e-3, 0.000000000000000000000000001],'
        ' "string": "\\u20ac$\\u000F\\u000aA\'\\u0042\\u0022\\u005c\\\\\\"\\/",'
        ' "literals": [null, true, false]}'
    )
    expected = (
        '{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
        '"string":"\u20ac$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}'
    )
    assert canonical_json(json.loads(source)) == expected.encode()


def test_canonical_json_sorts_members_by_utf16_code_units() -> None:
    """RFC 8785 §3.2.3: U+1F600 (a surrogate pair) sorts before U+FB33, unlike code points."""
    names = ["\u20ac", "\r", "\ufb33", "1", "\U0001f600", "\u0080", "\u00f6"]
    order = list(json.loads(canonical_json(dict.fromkeys(names, 0))))
    assert order == ["\r", "1", "\u0080", "\u00f6", "\u20ac", "\U0001f600", "\ufb33"]


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), "\ud800", {"a": "\udfff"}, 2**53 + 1, {1: 0}, object()],
    ids=["nan", "infinity", "lone-surrogate", "nested-surrogate", "beyond-2-53", "int-key", "obj"],
)
def test_canonical_json_refuses_what_is_not_i_json(value: object) -> None:
    with pytest.raises((ValueError, TypeError)):
        canonical_json(value)


#: I-JSON text: no lone surrogates, which RFC 8785 refuses (UTF-8 cannot encode them).
_TEXT = st.text(st.characters(codec="utf-8"), max_size=8)
_SCALAR = (
    st.none()
    | st.booleans()
    | st.integers(-(2**53), 2**53)
    | st.floats(allow_nan=False, allow_infinity=False)
    | _TEXT
)
_JSON = st.recursive(
    _SCALAR,
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(_TEXT, inner, max_size=4),
    max_leaves=12,
)


@given(st.dictionaries(_TEXT, _JSON, max_size=6), st.randoms())
def test_member_order_and_whitespace_never_change_the_fingerprint(
    body: dict[str, object], rnd: random.Random
) -> None:
    items = list(body.items())
    rnd.shuffle(items)
    sent = json.dumps(dict(items), indent=3)
    assert request_fingerprint("PUT", b"/r", json.loads(sent)) == request_fingerprint(
        "PUT", b"/r", body
    )


@given(_JSON)
def test_canonical_json_round_trips_to_an_equal_value(value: object) -> None:
    """Numbers re-read as IEEE-754 doubles, the data model RFC 8785 serialises."""
    assert json.loads(canonical_json(value), parse_int=float) == value


def test_request_fingerprint_is_sha256_of_method_target_and_jcs_body() -> None:
    body = {"scope": "global", "engaged": False}
    expected = b'POST\n/trading/kill-switch\n{"engaged":false,"scope":"global"}'
    assert request_fingerprint("POST", b"/trading/kill-switch", body) == (
        hashlib.sha256(expected).hexdigest()
    )
    assert request_fingerprint("DELETE", b"/x", None) == hashlib.sha256(b"DELETE\n/x\n").hexdigest()


@pytest.mark.parametrize(
    ("one", "other"),
    [
        (("POST", b"/k", {"engaged": False}), ("PUT", b"/k", {"engaged": False})),
        (("POST", b"/k?a=1&b=2", None), ("POST", b"/k?b=2&a=1", None)),
        (("POST", b"/k/", None), ("POST", b"/k", None)),
        (("POST", b"/a%2Fb", None), ("POST", b"/a/b", None)),
        (("POST", b"/k", {"scope": "global"}), ("POST", b"/k", {"scope": "account"})),
        (("POST", b"/k", None), ("POST", b"/k", {})),
    ],
    ids=["method", "query-order", "trailing-slash", "percent-encoding", "body", "empty-body"],
)
def test_request_fingerprint_tells_requests_apart(
    one: tuple[str, bytes, object], other: tuple[str, bytes, object]
) -> None:
    assert request_fingerprint(*one) != request_fingerprint(*other)


@pytest.mark.parametrize(
    ("scope", "target"),
    [
        ({"raw_path": b"/rules/a%2Fb/mode", "path": "/rules/a/b/mode", "query_string": b""},
         b"/rules/a%2Fb/mode"),
        ({"raw_path": b"/k", "path": "/k", "query_string": b"b=2&a=1"}, b"/k?b=2&a=1"),
        ({"path": "/k", "query_string": b""}, b"/k"),
    ],
    ids=["percent-encoded", "query-as-received", "no-raw-path"],
)  # fmt: skip
def test_raw_request_target_is_the_target_as_received(
    scope: dict[str, object], target: bytes
) -> None:
    assert raw_request_target(Request({"type": "http", **scope})) == target
