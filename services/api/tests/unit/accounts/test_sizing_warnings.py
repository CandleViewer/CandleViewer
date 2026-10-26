"""E28-T03 (#907): the save-time sizing warnings `sizing_below_min_order` and
`stop_beyond_liquidation` (SR-E28-26; #907's ruling of 2026-10-25 17:27Z) and their optional port on
the second pass."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.accounts import profile_validator as pv
from candleviewer.accounts import sizer as sz
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.domain.primitives import Environment
from tests.unit.accounts.test_sizer import atr, instrument, profile, wallet

D = Decimal
_MMR: Final = D("0.005")  # a sample rate; BTCUSDT's recorded lowest tier is 0.0033
_AT_MID: Final = sz.SizingMarket(mid=D(64000))
_TINY: Final = wallet("10")  # 0.5 % of 10 USDT over a 120 USDT stop: 0.0004 BTC, under 0.001


def save(
    market: sz.SizingMarket = _AT_MID, figures: Any = None, *, stale: bool = False,
    mmr: Decimal | None = _MMR, symbol: str = "BTCUSDT",
) -> pv.SaveFigures:  # fmt: skip
    one = pv.SymbolFigures(instrument(symbol), market, mmr)
    return pv.SaveFigures(figures or wallet(), stale, {symbol: one})


def warned(p: AccountProfile, s: pv.SaveFigures, symbols: Sequence[str] = ("BTCUSDT",)) -> Any:
    return pv.sizing_warnings(p, s, symbols)


def test_warning_symbols_take_exact_allow_entries_then_open_positions_bounded() -> None:
    risk = profile("P-RISK")  # allows BTCUSDT, ETHUSDT
    assert pv.warning_symbols(risk, ["SOLUSDT", "BTCUSDT"]) == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    assert pv.warning_symbols(profile("P-PCT"), ["SOLUSDT"]) == ("SOLUSDT",)  # all_symbols
    patterns = profile("P-RISK", allowed_symbols=["*USDT", "*CUSDT"])
    assert pv.warning_symbols(patterns, ()) == ()
    many = [f"S{n:02d}USDT" for n in range(30)]
    assert pv.warning_symbols(risk, many) == ("BTCUSDT", "ETHUSDT", *many[:23])


@pytest.mark.parametrize(
    ("p", "s", "estimated"),
    [
        (profile("P-RISK"), save(figures=_TINY), False),  # at mid, a ticks stop, fresh equity
        (profile("P-RISK"), save(sz.SizingMarket(last_price=D(64000)), _TINY), True),  # at last
        (profile("P-RISK"), save(figures=_TINY, stale=True), True),  # a stale equity
        (profile("P-PCT", pct_equity="0.0001"), save(figures=_TINY), True),  # the ATR fallback
    ],
    ids=["mid", "last", "stale-equity", "atr-fallback"],
)
def test_sizing_below_min_order_warns_estimated_as_ruled(
    p: AccountProfile, s: pv.SaveFigures, estimated: bool
) -> None:
    (found,), dropped = warned(p, s)
    assert (found.code, found.symbol, found.field, found.estimated) == (
        "sizing_below_min_order", "BTCUSDT", "sizing", estimated,
    )  # fmt: skip
    assert "skipped: below_min_notional" in found.message and dropped == ()


def test_sizing_below_min_order_judges_a_kernel_atr_stop_as_exact() -> None:
    market = sz.SizingMarket(mid=D(64000), atr=atr(D(400)))
    (found,), _ = warned(profile("P-PCT", pct_equity="0.0001"), save(market, _TINY))
    assert found.estimated is False


def test_stop_beyond_liquidation_warns_always_estimated() -> None:
    """AC-27: a 50x profile with a 2 % stop; a long's stop is judged first."""
    p = profile("P-PCT", leverage="50", max_leverage_cap="50")
    (found,), dropped = warned(p, save())
    message = (
        "BTCUSDT: a long's stop at 62720 USDT is not inside the estimated liquidation price"
        " 63040 USDT at 50x by the 10 % buffer: it must be above 63136 USDT."
    )
    assert (found.code, found.symbol, found.field, found.estimated, found.message) == (
        "stop_beyond_liquidation", "BTCUSDT", "stop_loss", True, message,
    )  # fmt: skip
    assert dropped == ()
    assert found.to_dict()["estimated"] is True


@pytest.mark.parametrize(
    ("ticks", "warns"), [("8640", True), ("8639", False)], ids=["at-the-edge", "a-tick-inside"]
)
def test_stop_beyond_liquidation_warns_at_the_buffer_edge(ticks: str, warns: bool) -> None:
    """SR-E28-26's buffer, as the leg refusal judges it: at 50x the long's edge is 63136 and the
    short's 64864, 8640 ticks of 0.1 from 64000 each."""
    p = profile("P-QTY", sl_offset_unit="ticks", sl_offset_value=ticks, leverage="50",
                max_leverage_cap="50")  # fmt: skip
    found, dropped = warned(p, save())
    assert [w.code for w in found] == ["stop_beyond_liquidation"] * warns and dropped == ()


def test_a_profile_inside_every_limit_warns_nothing() -> None:
    assert warned(profile("P-RISK"), save()) == ((), ())


def test_a_disabled_profile_is_judged_on_its_figures() -> None:
    p = profile("P-RISK", enabled=False, trading_enabled=False)
    (found,), _ = warned(p, save(figures=_TINY))
    assert found.code == "sizing_below_min_order"


@pytest.mark.parametrize(
    ("s", "symbols", "dropped"),
    [
        (save(), ("ETHUSDT",), [("sizing_below_min_order", "ETHUSDT", "figures_missing"),
                                ("stop_beyond_liquidation", "ETHUSDT", "figures_missing")]),
        (save(sz.SizingMarket()), ("BTCUSDT",), [
            ("sizing_below_min_order", "BTCUSDT", "no_reference_price"),
            ("stop_beyond_liquidation", "BTCUSDT", "no_reference_price"),
        ]),
        (save(mmr=None), ("BTCUSDT",), [
            ("stop_beyond_liquidation", "BTCUSDT", "maintenance_margin_rate"),
        ]),
        (save(figures=wallet(None)), ("BTCUSDT",), [
            ("sizing_below_min_order", "BTCUSDT", "figure_unknown"),
        ]),
    ],
    ids=["no-entry", "no-price", "no-rate", "no-equity"],
)  # fmt: skip
def test_a_missing_input_drops_the_warning(
    s: pv.SaveFigures, symbols: tuple[str, ...], dropped: list[tuple[str, str, str]]
) -> None:
    found, got = warned(profile("P-RISK"), s, symbols)
    assert found == ()
    assert [(d.code, d.symbol, d.reason) for d in got] == dropped


def test_a_symbol_entry_without_an_instrument_is_dropped_as_instrument() -> None:
    one = pv.SymbolFigures(None, _AT_MID, _MMR)
    _, dropped = warned(profile("P-RISK"), pv.SaveFigures(wallet(), False, {"BTCUSDT": one}))
    assert {d.reason for d in dropped} == {"instrument"}


def test_the_reference_is_the_mid_else_the_last_price() -> None:
    assert pv._price(sz.SizingMarket(mid=D(4), last_price=D(5))) == 4
    assert pv._price(sz.SizingMarket(last_price=D(5))) == 5


def test_a_leg_the_sizer_cannot_judge_logs_its_reason() -> None:
    low = instrument("BTCUSDT").model_copy(update={"max_leverage": D(2)})  # under the profile's
    one = pv.SymbolFigures(low, _AT_MID, _MMR)
    s = pv.SaveFigures(wallet(), False, {"BTCUSDT": one})
    p = profile("P-PCT", leverage="50", max_leverage_cap="50")
    found, dropped = warned(p, s)
    assert [(d.code, d.reason) for d in dropped] == [
        ("sizing_below_min_order", "leverage_unavailable")
    ]
    assert [f.code for f in found] == ["stop_beyond_liquidation"]  # still judged


def test_an_instrument_of_another_symbol_is_dropped() -> None:
    s = pv.SaveFigures(wallet(), False, {"ETHUSDT": save().symbols["BTCUSDT"]})
    _, dropped = warned(profile("P-RISK"), s, ("ETHUSDT",))
    assert {d.reason for d in dropped} == {"instrument"}


def test_the_shown_liquidation_price_is_rounded_at_100_digits() -> None:
    big = D("123456789012345678901234567890.123")  # 33 digits: a 28-digit context would cut it
    assert pv._on_tick(big, D("0.001"), "ROUND_FLOOR") == big
    assert pv._on_tick(D("1.0004"), D("0.001"), "ROUND_CEILING") == D("1.001")


class Port:
    """The warnings port over one `SaveFigures`; `fails` raises, `hangs` never answers."""

    def __init__(self, s: pv.SaveFigures, open_symbols: Sequence[str] = ()) -> None:
        self.save, self.open, self.asked = s, tuple(open_symbols), list[tuple[str, ...]]()
        self.fails: Exception | None = None
        self.hangs = False

    async def open_symbols(self, account_id: UUID) -> Sequence[str]:
        if self.hangs:
            await asyncio.Event().wait()
        if self.fails is not None:
            raise self.fails
        return self.open

    async def figures(self, account_id: UUID, symbols: Sequence[str]) -> pv.SaveFigures:
        self.asked.append(tuple(symbols))
        return self.save


async def test_judge_sizing_reads_the_ruled_scope_and_logs_each_drop() -> None:
    port = Port(save(mmr=None, figures=_TINY), ["BTCUSDT"])
    with capture_logs() as logs:
        (found,) = await pv.judge_sizing(profile("P-PCT"), port)
    assert (found.code, port.asked) == ("sizing_below_min_order", [("BTCUSDT",)])
    drop = {"code": "stop_beyond_liquidation", "symbol": "BTCUSDT"}
    assert logs == [drop | {"reason": "maintenance_margin_rate", "event":
                    "profile_sizing_warning_dropped", "log_level": "info"}]  # fmt: skip


async def test_judge_sizing_skips_an_empty_scope() -> None:
    port = Port(save())
    assert await pv.judge_sizing(profile("P-PCT"), port) == ()
    assert port.asked == []


@pytest.mark.parametrize("hangs", [False, True], ids=["fails", "times-out"])
async def test_judge_sizing_drops_every_warning_when_the_port_fails(
    hangs: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pv, "WARNINGS_DEADLINE_S", 0)
    port = Port(save())
    port.fails, port.hangs = (None, True) if hangs else (RuntimeError("down"), False)
    with capture_logs() as logs:
        assert await pv.judge_sizing(profile("P-RISK"), port) == ()
    reason = "timeout" if hangs else "RuntimeError"
    said = [(log["code"], log["symbol"], log["reason"]) for log in logs]
    assert said == [
        (code, symbol, reason)
        for symbol in ("BTCUSDT", "ETHUSDT")
        for code in ("sizing_below_min_order", "stop_beyond_liquidation")
    ]


async def test_judge_sizing_logs_a_scope_unknown_when_the_open_positions_fail() -> None:
    port = Port(save())
    port.fails = RuntimeError("down")
    with capture_logs() as logs:
        assert await pv.judge_sizing(profile("P-PCT"), port) == ()
    assert [(log["symbol"], log["reason"]) for log in logs] == [(None, "RuntimeError")] * 2


class Limits:
    environment: Environment = "demo"

    async def listed(self, *, max_age_s: float, deadline_s: float) -> Any:
        return {"BTCUSDT": instrument("BTCUSDT")}


async def test_the_second_pass_appends_the_ports_warnings_after_t02s() -> None:
    p = profile("P-PCT", leverage="50", max_leverage_cap="50")
    got = await pv.check_exchange_limits(
        p, environment="demo", instruments=Limits(), stored=p, warnings=Port(save(), ["BTCUSDT"])
    )
    assert [w.code for w in got.warnings] == ["all_symbols", "stop_beyond_liquidation"]
    alone = await pv.check_exchange_limits(p, environment="demo", instruments=Limits(), stored=p)
    assert [w.code for w in alone.warnings] == ["all_symbols"]
    assert alone.warnings[0].to_dict() == {
        "code": "all_symbols",
        "message": "Allows every listed symbol — consider restricting.",
        "field": "all_symbols",
    }


async def test_a_refused_write_asks_the_port_nothing() -> None:
    p = profile("P-QTY", leverage="10", max_leverage_cap="10", allowed_symbols=["NOPEUSDT"])
    port = Port(save())
    got = await pv.check_exchange_limits(
        p, environment="demo", instruments=Limits(), stored=None, warnings=port
    )
    assert got.errors and port.asked == []


async def test_judge_sizing_drops_a_symbol_whose_judgement_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_: Any) -> Any:
        raise ValueError("programming error")

    monkeypatch.setattr(pv, "sizing_warnings", boom)
    with capture_logs() as logs:
        assert await pv.judge_sizing(profile("P-RISK"), Port(save())) == ()
    assert {(log["reason"]) for log in logs} == {"ValueError"} and len(logs) == 4
