"""The order routes' `ETag` (E29-T04 slice 4, ruling Q5; `api.order_etag`): the strong tag 22's
`OrderETag` pattern takes, and `If-Match` read as one strong tag of this order, else no version."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.order_etag import NO_VERSION, expected_seq, order_etag

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
ORDER = UUID("0d1e2f30-4152-4637-8899-aabbccddeeff")
OTHER = UUID("0d1e2f30-4152-4637-8899-aabbccddee00")


@pytest.mark.parametrize("seq", [0, 7, 9_223_372_036_854_775_807])
def test_order_etag_is_22s_strong_tag_and_reads_back_as_its_seq(seq: int) -> None:
    pattern = _SPEC["components"]["headers"]["OrderETag"]["schema"]["pattern"]
    tag = order_etag(ORDER, seq)
    assert tag == f'"{ORDER}:{seq}"'
    assert re.fullmatch(pattern, tag)
    assert expected_seq(tag, ORDER) == seq
    assert expected_seq(f" {tag}\t", ORDER) == seq  # the field value's whitespace is no part


@pytest.mark.parametrize("seq", [-1, True])
def test_order_etag_refuses_a_seq_no_order_holds(seq: int) -> None:
    with pytest.raises(ValueError, match="event_seq"):
        order_etag(ORDER, seq)


def test_expected_seq_without_if_match_checks_no_version() -> None:
    """22 `IfMatch`: omitting it accepts last-write-wins (ruling Q5, D3)."""
    assert expected_seq(None, ORDER) is None


@pytest.mark.parametrize(
    "if_match",
    [
        "*",
        f'"{ORDER}:3", "{ORDER}:4"',
        f'W/"{ORDER}:3"',
        f"{ORDER}:3",
        f'"{str(ORDER).upper()}:3"',
        f'"{ORDER}:03"',
        f'"{ORDER}:-3"',
        f'"{ORDER}:"',
        f'"{ORDER}:{10**19}"',
        f'"{OTHER}:3"',
        "",
    ],
    ids=[
        "any", "list", "weak", "unquoted", "upper-case", "leading-zero", "negative", "no-seq",
        "past-bigint", "another-order", "empty",
    ],
)  # fmt: skip
def test_expected_seq_reads_any_other_if_match_as_no_version(if_match: str) -> None:
    """`*`, a list, a weak or malformed tag and another order's are refused alike, 412, where the
    facade compares the version (22 `amendOrder`): no version equals `NO_VERSION`."""
    assert expected_seq(if_match, ORDER) == NO_VERSION
    assert NO_VERSION < 0
