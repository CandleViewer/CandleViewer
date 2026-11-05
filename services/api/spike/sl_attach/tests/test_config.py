"""One arm's settings refuse a backstop outside 5 to 10 % (Q5), a symbol off the allow-list, a
stop that would loosen the backstop and an unbounded order lookup (D1)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from spike.oms_demo_path.safety import Refused
from spike.sl_attach.config import ArmConfig


def test_the_backstop_must_sit_five_to_ten_percent_away() -> None:
    for pct in ("4.99", "10.01"):
        with pytest.raises(Refused, match="5 to 10"):
            ArmConfig(backstop_pct=Decimal(pct))
    with pytest.raises(Refused, match="allow-list"):
        ArmConfig(symbol="SOLUSDT")
    with pytest.raises(Refused, match="tightens"):
        ArmConfig(sl_bps=Decimal(800), backstop_pct=Decimal(5))
    for bad in ({"lookup_tries": 0}, {"lookup_every_s": 0.0}, {"lookup_wait_s": 0.0}):
        with pytest.raises(Refused, match="bounded"):
            ArmConfig(**bad)
