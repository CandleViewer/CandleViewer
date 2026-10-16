"""`OUR_ID` (§8.3; E29-T02, #846) is the first `ord_link_fmt` arm (`21-database-schema.md`
§3.3.4), transcribed here so this suite fails if the code drifts from the contract."""

from __future__ import annotations

import pytest

from candleviewer.domain.order_link import OUR_ID

ORD_LINK_FMT_OUR_ARM = (
    r"^cv[ldtp]-[0-7][0-9A-Za-z]{21}-[0-9A-Za-z]{4}-[0-9A-Za-z]{2}(en|sl|tp|sc|fl|ac)$"
)
EXAMPLE = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"  # the §8.3 worked example


def test_our_id_is_the_first_ord_link_fmt_arm() -> None:
    assert OUR_ID.pattern == ORD_LINK_FMT_OUR_ARM


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
