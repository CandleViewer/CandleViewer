"""`OUR_ID`, `EXT_ID` and `ext_key` (§8.3; E29-T02, #846). The patterns are the two
`ord_link_fmt` arms (`21-database-schema.md` §3.3.4), transcribed here so this suite
fails if the code drifts from the contract."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.domain.order_link import EXT_ID, OUR_ID, ext_key

ORD_LINK_FMT_OUR_ARM = (
    r"^cv[ldtp]-[0-7][0-9A-Za-z]{21}-[0-9A-Za-z]{4}-[0-9A-Za-z]{2}(en|sl|tp|sc|fl|ac)$"
)
ORD_LINK_FMT_EXT_ARM = r"^ext-[0-9a-f]{32}$"
EXAMPLE = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"  # the §8.3 worked example
CANONICAL = "1A2B3C4D-5E6F-4A7B-8C9D-0E1F2A3B4C5D"


def test_our_id_is_the_first_ord_link_fmt_arm() -> None:
    assert OUR_ID.pattern == ORD_LINK_FMT_OUR_ARM


def test_ext_id_is_the_second_ord_link_fmt_arm() -> None:
    assert EXT_ID.pattern == ORD_LINK_FMT_EXT_ARM


def test_our_id_accepts_the_contract_example() -> None:
    assert OUR_ID.fullmatch(EXAMPLE) is not None


@pytest.mark.parametrize(
    "value",
    [
        EXAMPLE + "\n",  # Postgres `~` rejects a trailing newline, so fullmatch must too
        EXAMPLE[:-1],
        "cvl-8TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en",  # a 128-bit group never leads with 8
        "cvx-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en",
        "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00xx",
        "cv-l0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en",
        "ext-" + "0" * 32,
    ],
)
def test_our_id_rejects_a_value_the_generator_cannot_produce(value: str) -> None:
    assert OUR_ID.fullmatch(value) is None


@pytest.mark.parametrize("value", ["ext-" + "a" * 32 + "\n", "ext-" + "A" * 32, "ext-" + "a" * 31])
def test_ext_id_rejects_other_shapes(value: str) -> None:
    assert EXT_ID.fullmatch(value) is None


def test_ext_key_keeps_a_canonical_uuid_order_id_lowercased_without_hyphens() -> None:
    assert ext_key(CANONICAL) == "ext-1a2b3c4d5e6f4a7b8c9d0e1f2a3b4c5d"


@pytest.mark.parametrize(
    "order_id",
    [
        CANONICAL.replace("-", ""),  # the right digits, but not the 8-4-4-4-12 form
        "{" + CANONICAL + "}",
        CANONICAL + "0",
        "0" + CANONICAL,
        "1234567890",
        "",
    ],
)
def test_ext_key_hashes_an_order_id_that_is_not_a_canonical_uuid(order_id: str) -> None:
    assert ext_key(order_id) == "ext-" + hashlib.sha256(order_id.encode()).hexdigest()[:32]


@given(st.uuids())
def test_ext_key_of_any_canonical_uuid_keeps_its_digits(order_id: uuid.UUID) -> None:
    assert ext_key(str(order_id).upper()) == "ext-" + order_id.hex


@given(st.text())
def test_ext_key_is_always_a_36_char_ext_id_and_never_our_id(order_id: str) -> None:
    key = ext_key(order_id)

    assert EXT_ID.fullmatch(key) is not None
    assert len(key) == 36
    assert OUR_ID.fullmatch(key) is None
    assert ext_key(order_id) == key
