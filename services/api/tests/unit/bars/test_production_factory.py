"""#2191: the production factory serves every bar kind the wire contract advertises."""

from __future__ import annotations

from decimal import Decimal

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.market_bars import _Rejected, parse_bar_request
from candleviewer.bars.builder_set import production_factory
from candleviewer.bars.errors import BarSpecError
from candleviewer.bars.models import BarSpec

from ._trades import SYM

_ENUM = load_openapi_spec()["components"]["schemas"]["BarType"]["enum"]
_PARAM = {"time": "5", "tick": "100", "volume": "50", "range": "20", "delta": "500", "renko": "30"}
_SERVED = [k for k in _ENUM if k not in ("pnf", "heikin_ashi")]
_TICK = Decimal("0.1")


def _make(*, renko: bool = True):  # type: ignore[no-untyped-def]  # test helper
    return production_factory(lambda _s: _TICK, renko_enabled=renko)


def test_wire_enum_is_fully_covered_by_the_parametrisation() -> None:
    assert set(_SERVED) == set(_PARAM)


@pytest.mark.parametrize("kind", _SERVED)
def test_factory_accepts_every_shipped_bar_kind(kind: str) -> None:
    spec = parse_bar_request(kind, _PARAM[kind], qty_step=Decimal("0.001"))
    assert _make()(spec, SYM).spec.kind == kind


def test_atr_renko_is_still_refused_with_422() -> None:
    with pytest.raises(_Rejected) as exc:
        parse_bar_request("renko", "atr:14")
    assert exc.value.response.status_code == 422


def test_renko_stays_behind_its_flag() -> None:
    spec = BarSpec(kind="renko", range_ticks=30)
    with pytest.raises(BarSpecError, match="not available yet"):
        _make(renko=False)(spec, SYM)
    assert _make(renko=False)(BarSpec(kind="range", range_ticks=20), SYM).spec.kind == "range"


@pytest.mark.parametrize("renko", [True, False])
def test_factory_refuses_unknown_kinds_with_the_typed_error(renko: bool) -> None:
    spec = BarSpec.model_construct(kind="pnf")  # type: ignore[call-arg]  # bypass kind validation
    with pytest.raises(BarSpecError, match="not available yet"):
        _make(renko=renko)(spec, SYM)


def test_range_with_unknown_symbol_is_refused_with_typed_error() -> None:
    make = production_factory(lambda _s: None, renko_enabled=False)
    with pytest.raises(BarSpecError, match="No tick size"):
        make(BarSpec(kind="range", range_ticks=20), SYM)
