"""E24-S03 (#778) serving slice: the per-position estimate (22 `FundingEstimate`, 24 §19.110),
`domain.funding.estimate_funding`, on the recorded BTCUSDT ticker's values
(`ws/recorded_tickers_BTCUSDT.jsonl`). Property tests hold the contract's invariants."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.domain.funding import estimate_funding

_RATE = Decimal("0.0000771")  # the recorded ticker's `fundingRate`
_MARK = Decimal("82751.20")  # the recorded ticker's `markPrice`
_NEXT = 1_792_396_800_000_000  # the recorded ticker's `nextFundingTime`, in us


def _estimate(side: str | None, size: str, rate: Decimal | None = _RATE) -> object:
    return estimate_funding(
        side=side,  # type: ignore[arg-type]  # the test passes None for a flat position
        size=Decimal(size),
        mark_price=_MARK,
        funding_rate=rate,
        settles_at_us=_NEXT,
        computed_at_us=_NEXT - 1,
    )


def test_a_long_pays_and_a_short_receives_a_positive_rate_at_8_dp_half_up() -> None:
    long_ = estimate_funding(
        side="long", size=Decimal("0.200"), mark_price=_MARK, funding_rate=_RATE,
        settles_at_us=_NEXT, computed_at_us=_NEXT - 1,
    )  # fmt: skip
    assert long_ is not None
    assert long_.amount == Decimal("1.27602350")  # 0.2 x 82751.20 x 0.0000771 = 1.276023504
    assert (long_.direction, long_.funding_rate, long_.settles_at) == ("pay", _RATE, _NEXT)
    short = estimate_funding(
        side="short", size=Decimal("0.200"), mark_price=_MARK, funding_rate=-_RATE,
        settles_at_us=_NEXT, computed_at_us=_NEXT - 1,
    )  # fmt: skip
    assert short is not None and short.direction == "pay" and short.amount == long_.amount


@pytest.mark.parametrize(
    ("side", "size", "rate", "expected"),
    [
        (None, "0", _RATE, None),  # flat
        ("long", "0", _RATE, None),  # a zero size is flat whatever the side
        ("long", "0.2", None, None),  # no accruing rate held
    ],
)
def test_no_charge_is_none_never_a_zero(
    side: str | None, size: str, rate: Decimal | None, expected: None
) -> None:
    assert _estimate(side, size, rate) is expected


def test_a_zero_rate_is_direction_none_with_a_zero_amount() -> None:
    found = estimate_funding(
        side="short", size=Decimal("1"), mark_price=_MARK, funding_rate=Decimal(0),
        settles_at_us=_NEXT, computed_at_us=_NEXT,
    )  # fmt: skip
    assert found is not None and found.direction == "none" and found.amount == 0


@given(
    side=st.sampled_from(["long", "short"]),
    size=st.decimals(min_value=Decimal("0.001"), max_value=Decimal("100000"), places=3),
    mark=st.decimals(min_value=Decimal("0.0001"), max_value=Decimal("500000"), places=4),
    rate=st.decimals(min_value=Decimal("-0.05"), max_value=Decimal("0.05"), places=8),
)
def test_the_amount_is_never_negative_and_the_direction_follows_side_and_sign(
    side: str, size: Decimal, mark: Decimal, rate: Decimal
) -> None:
    found = estimate_funding(
        side=side, size=size, mark_price=mark, funding_rate=rate,  # type: ignore[arg-type]
        settles_at_us=_NEXT, computed_at_us=_NEXT,
    )  # fmt: skip
    assert found is not None and found.amount >= 0
    assert found.amount.as_tuple().exponent == -8
    assert abs(found.amount - abs(size * mark * rate)) <= Decimal("0.000000005")
    if rate == 0:
        assert found.direction == "none"
    else:
        assert found.direction == ("pay" if (rate > 0) == (side == "long") else "receive")
