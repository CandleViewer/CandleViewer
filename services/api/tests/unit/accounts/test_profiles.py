"""`AccountProfile` and its row adapter (E28-T01 #905; 24-internal-schemas.md Sec.9.2).

The database's rules are pinned on real Postgres by
`tests/integration/storage/test_account_profiles_migration.py`; these tests pin the same rules on
the domain model (SR-E28-08: every layer), the percent/fraction mapping in both directions, and
the exact round trip domain -> row -> domain.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from candleviewer.accounts.profiles import (
    AccountProfile,
    SymbolEntries,
    SymbolScope,
    TakeProfitRung,
    profile_from_row,
    profile_values,
)
from candleviewer.domain.events import Instrument
from candleviewer.exchange.bybit.instruments import parse_instrument
from candleviewer.storage.repositories.account_profiles import AccountProfileRow, LadderRung
from tests._corpus import rest

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "profiles"
_MODES = ("risk_based", "fixed_qty", "pct_equity", "fixed_notional")
_SIZE_FIELDS = ("fixed_qty", "fixed_notional", "pct_equity", "risk_pct_equity")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CREATED = datetime(2026, 10, 20, 9, tzinfo=UTC)


def _fixture(mode: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((_FIXTURES / f"{mode}.json").read_text(encoding="utf-8"))
    return data


def _profile(mode: str = "risk_based", /, **changes: Any) -> AccountProfile:
    return AccountProfile.model_validate({**_fixture(mode), **changes})


def _row(profile: AccountProfile) -> AccountProfileRow:
    """What the store reads back for `profile` (the database writes version and times)."""
    return AccountProfileRow(
        id=profile.profile_id,
        exchange_account_id=profile.account_id,
        version=profile.version,
        values=profile_values(profile),
        created_by=None,
        updated_by=None,
        created_at=_CREATED,
        updated_at=_EPOCH + timedelta(microseconds=profile.updated_at),
        deleted_at=None,
    )


@pytest.mark.parametrize("mode", _MODES)
def test_every_fixture_is_a_valid_trading_enabled_profile_of_its_mode(mode: str) -> None:
    profile = _profile(mode)
    assert profile.sizing_mode == mode and profile.trading_enabled
    assert profile.require_native_sl is True


@pytest.mark.parametrize("mode", _MODES)
def test_a_profile_round_trips_through_its_row_unchanged(mode: str) -> None:
    profile = _profile(mode)
    assert profile_from_row(_row(profile)) == profile


def test_percentages_are_stored_as_the_percent_a_user_sees() -> None:
    values = profile_values(
        _profile(
            "pct_equity",
            pct_equity="0.05",
            max_position_pct_equity="0.25",
            max_daily_loss_pct="0.02",
            fallback_sl_offset_pct="0.02",
        )
    )
    assert values.size_pct_equity == Decimal("5")
    assert values.max_position_pct_equity == Decimal("25")
    assert values.max_daily_loss_pct == Decimal("2")
    assert values.fallback_sl_offset_pct == Decimal("2")


def test_risk_and_ladder_percentages_map_both_ways() -> None:
    profile = _profile("risk_based")
    values = profile_values(profile)
    assert values.risk_pct_equity == Decimal("1")
    assert values.tp_ladder == (
        LadderRung(pct=Decimal("50"), r=Decimal("1")),
        LadderRung(pct=Decimal("50"), r=Decimal("2")),
    )
    back = profile_from_row(_row(profile))
    assert back.risk_pct_equity == Decimal("0.01")
    assert back.tp_ladder == (
        TakeProfitRung(qty_pct=Decimal("0.5"), r=Decimal("1")),
        TakeProfitRung(qty_pct=Decimal("0.5"), r=Decimal("2")),
    )


def test_an_offset_in_percent_is_a_fraction_here_and_a_percent_in_the_row() -> None:
    profile = _profile("fixed_qty")  # sl 0.01 percent, tp 2 r_multiple
    values = profile_values(profile)
    assert values.sl_offset_value == Decimal("1") and values.sl_offset_unit == "percent"
    assert values.tp_offset_value == Decimal("2") and values.tp_offset_unit == "r_multiple"
    assert profile_from_row(_row(profile)).sl_offset_value == Decimal("0.01")


def test_offsets_in_other_units_are_stored_as_they_are() -> None:
    values = profile_values(_profile("fixed_notional"))  # 50 / 100 ticks
    assert (values.sl_offset_value, values.tp_offset_value) == (Decimal("50"), Decimal("100"))


def test_names_and_empty_lists_follow_the_columns() -> None:
    values = profile_values(_profile("pct_equity"))  # all symbols, DOGEUSDT denied, no ladder
    assert values.allowed_symbols is None and values.all_symbols is True
    assert values.blocked_symbols == ("DOGEUSDT",)
    assert values.tp_ladder is None
    assert profile_from_row(_row(_profile("pct_equity"))).denied_symbols == ("DOGEUSDT",)


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("extra", _SIZE_FIELDS)
def test_sizing_mode_takes_exactly_its_own_size_field(mode: str, extra: str) -> None:
    """The `ap_sizing_shape` matrix: four modes x four size fields, on the domain model."""
    own = {
        "fixed_qty": "fixed_qty",
        "fixed_notional": "fixed_notional",
        "pct_equity": "pct_equity",
        "risk_based": "risk_pct_equity",
    }[mode]
    if extra == own:
        assert _profile(mode).sizing_mode == mode
        return
    with pytest.raises(ValidationError, match="does not match the sizing fields"):
        _profile(mode, **{extra: "0.01"})


def test_risk_based_takes_exactly_one_of_percent_and_fixed_amount() -> None:
    assert _profile(risk_pct_equity=None, risk_fixed_amount="250").risk_fixed_amount == 250
    with pytest.raises(ValidationError, match="does not match the sizing fields"):
        _profile(risk_fixed_amount="250")
    with pytest.raises(ValidationError, match="does not match the sizing fields"):
        _profile(risk_pct_equity=None)


@pytest.mark.parametrize(
    "cleared",
    [
        ("max_position_notional",),
        ("max_daily_loss", "max_daily_loss_pct"),
        ("max_open_positions",),
        ("max_concurrent_orders",),
        ("max_leverage_cap",),
    ],
)
def test_trading_enabled_profile_requires_loss_caps(cleared: tuple[str, ...]) -> None:
    """SR-E28-01 / D11: "no cap" is not representable on a trading-enabled profile."""
    unbounded = dict.fromkeys(cleared)
    with pytest.raises(ValidationError, match="bounds every cap"):
        _profile(**unbounded)
    assert _profile(trading_enabled=False, **unbounded).trading_enabled is False


def test_either_unit_of_a_paired_cap_bounds_it() -> None:
    assert _profile(max_position_notional=None, max_position_pct_equity="0.5").trading_enabled
    assert _profile(max_daily_loss=None).max_daily_loss_pct == Decimal("0.03")


def test_the_native_stop_cannot_be_switched_off() -> None:
    with pytest.raises(ValidationError, match="require_native_sl"):
        _profile(require_native_sl=False)


def test_the_stop_is_never_expressed_in_r() -> None:
    with pytest.raises(ValidationError, match="sl_offset_unit"):
        _profile(sl_offset_unit="r_multiple")


def test_a_ladder_takes_at_most_the_whole_leg() -> None:
    rungs = [{"qty_pct": "0.6", "r": "1"}, {"qty_pct": "0.6", "r": "2"}]
    with pytest.raises(ValidationError, match="more than the whole leg"):
        _profile(tp_ladder=rungs)
    whole = [{"qty_pct": "0.5", "r": "1"}, {"qty_pct": "0.5", "r": "2"}]
    assert len(_profile(tp_ladder=whole).tp_ladder) == 2


def test_the_take_profit_offset_and_unit_come_together() -> None:
    with pytest.raises(ValidationError, match="set together"):
        _profile(tp_offset_value="2")


def test_leverage_stays_within_its_own_cap() -> None:
    with pytest.raises(ValidationError, match="above max_leverage_cap"):
        _profile(leverage="11")


def test_all_symbols_takes_no_allow_list() -> None:
    with pytest.raises(ValidationError, match="takes no allow-list"):
        _profile(all_symbols=True)


@pytest.mark.parametrize("pattern", ["*", "*USD", "btcusdt", "BTC-USDT", "**USDT"])
def test_a_symbol_entry_is_a_symbol_or_an_anchored_suffix_pattern(pattern: str) -> None:
    with pytest.raises(ValidationError, match="allowed_symbols"):
        _profile(allowed_symbols=[pattern])
    with pytest.raises(ValidationError, match="denied_symbols"):
        _profile(denied_symbols=[pattern])


@pytest.mark.parametrize(
    ("field", "entry", "bound"),
    [
        ("tp_ladder", {"qty_pct": "0.05", "r": "1"}, 10),
        ("allowed_symbols", "BTCUSDT", 500),
        ("denied_symbols", "BTCUSDT", 500),
    ],
)
def test_a_list_holds_at_most_the_bound_the_rest_contract_sets(
    field: str, entry: Any, bound: int
) -> None:
    """The REST `maxItems`; no column bounds a jsonb ladder or a `text[]` (24 Sec.9.2)."""
    assert len(getattr(_profile(**{field: [entry] * bound}), field)) == bound
    with pytest.raises(ValidationError) as refused:
        _profile(**{field: [entry] * (bound + 1)})
    assert [(e["loc"], e["type"]) for e in refused.value.errors()] == [((field,), "too_long")]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pct_equity", "0.123456789"),  # 12.3456789 % needs 7 places; the column keeps 6
        ("leverage", "2.555"),
        ("sl_atr_multiple", "1.23456"),
        ("fixed_qty", "0.0000000000000000001"),
        ("sl_atr_multiple", "1000000"),  # whole digits past numeric(10,4)
        ("fixed_qty", "1E+20"),  # whole digits past numeric(38,18)
        ("max_position_notional", "1E+20"),
    ],
)
def test_a_value_the_column_would_round_is_refused(field: str, value: str) -> None:
    mode = {"pct_equity": "pct_equity", "fixed_qty": "fixed_qty"}.get(field, "risk_based")
    with pytest.raises(ValidationError, match="does not fit numeric"):
        _profile(mode, **{field: value})


def test_unknown_fields_are_refused() -> None:
    """`extra="forbid"`: no field can ride along, so no secret-shaped one can either."""
    with pytest.raises(ValidationError, match="owner_note"):
        _profile(owner_note=None)


_SECRET_SHAPED = re.compile(r"secret|key|token|password|nonce|dek|kek|signature|cipher|enc", re.I)


def test_profile_snapshot_carries_no_secret_material() -> None:
    """SR-E28-07 / Q6: the snapshot a leg keeps is this model's projection; no field of it, nested
    ones included, can name key material."""
    fields = set(AccountProfile.model_fields) | set(TakeProfitRung.model_fields)
    assert not {name for name in fields if _SECRET_SHAPED.search(name)}
    dumped = _profile("risk_based").model_dump_json()
    assert not _SECRET_SHAPED.search(" ".join(json.loads(dumped)))


# -- property: any valid profile round-trips with Decimal equality ------------------------------

_MONEY = st.decimals(min_value=Decimal("0.000001"), max_value=Decimal("1000000000"), places=6)
_FRACTION = st.decimals(min_value=Decimal("0.00000001"), max_value=Decimal("1"), places=8)


@st.composite
def _profiles(draw: st.DrawFn) -> AccountProfile:
    mode = draw(st.sampled_from(_MODES))
    size: dict[str, Any] = dict.fromkeys(_SIZE_FIELDS)
    size["risk_fixed_amount"] = None
    if mode == "fixed_qty":
        size["fixed_qty"] = draw(_MONEY)
    elif mode == "fixed_notional":
        size["fixed_notional"] = draw(_MONEY)
    elif mode == "pct_equity":
        size["pct_equity"] = draw(_FRACTION)
    elif draw(st.booleans()):
        size["risk_pct_equity"] = draw(_FRACTION)
    else:
        size["risk_fixed_amount"] = draw(_MONEY)
    cap = draw(st.decimals(min_value=1, max_value=100, places=2))
    sl_unit = draw(st.sampled_from(["ticks", "percent", "atr"]))
    tp_unit = draw(st.sampled_from([None, "ticks", "percent", "r_multiple", "atr"]))
    n_rungs = draw(st.integers(min_value=0, max_value=4))
    rungs = [
        {"qty_pct": Decimal("0.25"), "r": draw(_MONEY)} for _ in range(n_rungs)
    ]  # fmt: skip
    return AccountProfile.model_validate(
        {
            **_fixture("risk_based"),
            **size,
            "profile_id": UUID(int=draw(st.integers(min_value=1, max_value=2**64))),
            "sizing_mode": mode,
            "version": draw(st.integers(min_value=1, max_value=10_000)),
            "leverage": draw(st.decimals(min_value=1, max_value=cap, places=2)),
            "max_leverage_cap": cap,
            "sl_offset_unit": sl_unit,
            "sl_offset_value": draw(_FRACTION if sl_unit == "percent" else _MONEY),
            "tp_offset_unit": tp_unit,
            "tp_offset_value": None if tp_unit is None else draw(_MONEY),
            "tp_ladder": rungs,
            "fallback_sl_offset_pct": draw(_FRACTION.filter(lambda f: f < 1)),
            "max_position_pct_equity": draw(st.none() | _FRACTION),
            "max_daily_loss_pct": draw(st.none() | _FRACTION),
            "updated_at": draw(st.integers(min_value=0, max_value=4_102_444_800_000_000)),
        }
    )


@settings(max_examples=200, deadline=None)
@given(profile=_profiles())
def test_any_valid_profile_round_trips_with_decimal_equality(profile: AccountProfile) -> None:
    assert profile_from_row(_row(profile)) == profile


def test_a_digit_beyond_the_context_precision_is_still_refused() -> None:
    """The 28-digit default context must not round away a digit the column cannot store."""
    with pytest.raises(ValidationError, match="does not fit numeric"):
        _profile("fixed_qty", fixed_qty="1.0000000000000000000000000001")


def test_percent_conversions_are_exact_beyond_the_context_precision() -> None:
    """29 significant digits stored: `x 100` and `/ 100` move the exponent, never round."""
    offset = Decimal("123456789.01123456789012345678")  # a percent-unit stop, as a fraction
    profile = _profile("fixed_qty", sl_offset_value=offset)
    stored = profile_values(profile).sl_offset_value
    assert stored.as_tuple().digits == offset.as_tuple().digits
    assert stored == Decimal("12345678901.123456789012345678")
    assert profile_from_row(_row(profile)).sl_offset_value == offset


# -- the model's bounds equal the columns' CHECKs (21 Sec.3.2.4), each edge pinned ----------------

_LOOSE: dict[str, Any] = {"trading_enabled": False, "max_leverage_cap": None}
#: (field, mode, valid values, invalid values), in domain units (fractions where the column is %).
_BOUNDS: list[tuple[str, str, list[Any], list[Any]]] = [
    ("name", "risk_based", ["x", "x" * 80], ["", "x" * 81]),
    ("leverage", "risk_based", ["1", "100"], ["0.99", "100.01"]),
    ("max_leverage_cap", "risk_based", ["1", "100"], ["0.99", "100.01"]),
    ("max_orders_per_minute", "risk_based", [1, 600], [0, 601]),
    ("sl_atr_period", "risk_based", [2, 200], [1, 201]),
    ("slippage_tolerance_bps", "risk_based", [0, 1000], [-1, 1001]),
    ("max_open_positions", "risk_based", [1, 50], [0, 51]),
    ("max_concurrent_orders", "risk_based", [1, 500], [0, 501]),
    ("fallback_sl_offset_pct", "risk_based", ["0.000001", "0.999999"], ["0", "1"]),
    ("min_leg_notional", "risk_based", ["0"], ["-0.01"]),
    ("sl_offset_value", "risk_based", ["0.000001"], ["0", "-1"]),
    ("sl_atr_multiple", "risk_based", ["0.0001"], ["0"]),
    ("risk_pct_equity", "risk_based", ["0.000001", "1"], ["0", "1.000001"]),
    ("pct_equity", "pct_equity", ["0.000001", "1"], ["0", "1.000001"]),
    ("max_position_pct_equity", "risk_based", ["0.000001", "1"], ["0", "1.000001"]),
    ("max_daily_loss_pct", "risk_based", ["0.000001", "1"], ["0", "1.000001"]),
    ("max_position_notional", "risk_based", ["0.000001"], ["0"]),
    ("max_daily_loss", "risk_based", ["0.000001"], ["0"]),
    ("fixed_qty", "fixed_qty", ["0.000000000000000001"], ["0"]),
    ("fixed_notional", "fixed_notional", ["0.01"], ["0"]),
    ("margin_mode", "risk_based", ["cross", "isolated"], ["portfolio"]),
    ("position_mode", "risk_based", ["one_way", "hedge"], ["both"]),
    ("time_in_force_default", "risk_based", ["GTC", "IOC", "FOK", "PostOnly"], ["DAY"]),
    ("sl_offset_unit", "risk_based", ["ticks", "percent", "atr"], ["r_multiple", "bps"]),
    ("risk_fixed_amount", "risk_based", ["0.000001"], ["0"]),
    ("version", "risk_based", [1], [0]),
    ("qty_rounding", "risk_based", ["floor"], ["ceil"]),
]


@pytest.mark.parametrize(
    ("field", "mode", "valid", "invalid"), _BOUNDS, ids=[bound[0] for bound in _BOUNDS]
)
def test_every_bound_matches_its_column(
    field: str, mode: str, valid: list[Any], invalid: list[Any]
) -> None:
    """The model repeats each CHECK (SR-E28-08): edges pass, the first value past each fails."""
    loose = _LOOSE | ({"leverage": "1"} if field == "max_leverage_cap" else {})
    loose |= {"risk_pct_equity": None} if field == "risk_fixed_amount" else {}
    for value in valid:
        assert getattr(_profile(mode, **(loose | {field: value})), field) is not None
    for value in invalid:
        with pytest.raises(ValidationError):
            _profile(mode, **(loose | {field: value}))


@pytest.mark.parametrize("unit", ["ticks", "percent", "r_multiple", "atr"])
def test_the_take_profit_offset_takes_every_unit_and_a_positive_value(unit: str) -> None:
    assert _profile(tp_offset_value="2", tp_offset_unit=unit).tp_offset_unit == unit
    with pytest.raises(ValidationError):
        _profile(tp_offset_value="0", tp_offset_unit=unit)


@pytest.mark.parametrize(
    "rung",
    [{"qty_pct": "0", "r": "1"}, {"qty_pct": "1.000001", "r": "1"}, {"qty_pct": "0.5", "r": "0"}],
    ids=["no-quantity", "past-the-leg", "no-r"],
)
def test_a_rung_takes_a_share_of_the_leg_and_a_positive_r(rung: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        _profile(tp_ladder=[rung])


def test_a_ladder_too_precise_to_sum_exactly_is_refused() -> None:
    with pytest.raises(ValidationError, match="too precise to sum exactly"):
        _profile(tp_ladder=[{"qty_pct": "0." + "1" * 250, "r": "1"}])


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "sNaN"])
def test_no_profile_number_is_nan_or_infinite(value: str) -> None:
    """`ap_finite` refuses NaN in the database; the model refuses every non-finite value."""
    with pytest.raises(ValidationError):
        _profile(max_daily_loss=value)


def test_a_value_out_of_any_columns_range_is_refused_not_trapped() -> None:
    """An exponent no column comes near is a refusal, never a raw `decimal.InvalidOperation`."""
    with pytest.raises(ValidationError, match="out of range"):
        _profile("fixed_qty", sl_offset_value="1E+999999999999999998")  # a percent-unit stop


@pytest.mark.parametrize(
    ("change", "error", "message"),
    [
        ({"allowed_symbols": ("btcusdt",)}, ValidationError, "allowed_symbols"),
        ({"allowed_symbols": ("BTCUSDT",) * 501}, ValidationError, "allowed_symbols"),
        ({"size_fixed_qty": None}, ValidationError, "sizing"),
        ({"tp_ladder": (LadderRung(Decimal("NaN"), Decimal("1")),)}, ValueError, "finite"),
        ({"fallback_sl_offset_pct": Decimal("1E-1000")}, ValueError, "out of range"),
    ],
    ids=["symbol", "symbol-count", "sizing-drift", "nan-rung", "out-of-range"],
)
def test_a_stored_row_the_model_refuses_raises_rather_than_reads(
    change: dict[str, Any], error: type[Exception], message: str
) -> None:
    """`profile_from_row`'s contract (its consumers catch `ValueError`): a row the model refuses
    raises `ValidationError`, and a value no adapter can move raises a plain `ValueError`."""
    row = _row(_profile("fixed_qty"))
    drifted = dataclasses.replace(row, values=dataclasses.replace(row.values, **change))
    with pytest.raises(error, match=message):
        profile_from_row(drifted)


def test_a_zero_fits_whatever_exponent_it_carries_within_the_limit() -> None:
    profile = _profile(min_leg_notional="0E-19")
    assert profile.min_leg_notional == 0 and profile_values(profile).min_leg_notional_usd == 0


def test_a_ladder_summed_exactly_past_the_whole_leg_is_refused() -> None:
    """0.5 + 0.5000000000000000000000000001 rounds to 1 in a 28-digit context; it is not 1."""
    rungs = [{"qty_pct": "0.5", "r": "1"}, {"qty_pct": "0.5000000000000000000000000001", "r": "2"}]
    with pytest.raises(ValidationError, match="more than the whole leg"):
        _profile(tp_ladder=rungs)


# -- one symbol matcher for saves and orders (E28-T02 #906 B2a; SR-E28-06, PF-T07) ---------------


# `oms.validator._listed` as it stood before `SymbolEntries` replaced it (0f0afa09b), verbatim.
def _listed(symbol: str, patterns: Iterable[str], *, wildcard: bool) -> bool:
    for pattern in patterns:
        if pattern == symbol:
            return True
        suffix = pattern.removeprefix("*")
        if wildcard and suffix != pattern and len(symbol) > len(suffix) and symbol.endswith(suffix):
            return True
    return False


@settings(max_examples=300, deadline=None)
@given(
    symbol=st.from_regex(r"[AU1T]{1,8}", fullmatch=True),
    entries=st.lists(st.from_regex(r"\*?[AU1T]{0,8}", fullmatch=True)),
)
@example(symbol="AU1T", entries=["*"])  # a bare `*`: the empty suffix
@example(symbol="AU1T", entries=[""])  # an empty entry
@example(symbol="AU1T", entries=["*AU1T"])  # a pattern as long as the symbol
@example(symbol="AU1T", entries=["AU1T", "*T"])  # the symbol itself, and a one-character suffix
def test_symbol_entries_match_as_the_order_path_did(symbol: str, entries: list[str]) -> None:
    """Both values of `wildcard`, over four characters so that suffixes collide often. A symbol
    never holds `*`; the entries reach past what a profile stores (a bare `*`, `""`)."""
    compiled = SymbolEntries.of(entries)
    for wildcard in (False, True):
        expected = _listed(symbol, entries, wildcard=wildcard)
        assert compiled.matches(symbol, wildcard=wildcard) is expected


def _recorded_btcusdt(**edits: str) -> Instrument:
    """The recorded BTCUSDT row (C-13.5) as the adapter parses it, then `edits`."""
    rows = rest("rest/instruments_before.json")["result"]["list"]
    recorded = parse_instrument(next(r for r in rows if r["symbol"] == "BTCUSDT"), fetched_at_us=0)
    return Instrument.model_validate({**recorded.model_dump(), **edits})


@pytest.mark.parametrize(
    ("edits", "matched"),
    [
        ({}, True),
        ({"status": "pre_launch"}, False),
        ({"status": "delivering"}, False),
        ({"status": "closed"}, False),
        ({"quote_coin": "USDC"}, False),
        ({"settle_coin": "USDC"}, False),
        ({"symbol": "USDT"}, False),  # the suffix alone: a pattern never matches a whole symbol
        ({"symbol": "USDTBTC"}, False),  # anchored: never a substring
    ],
    ids=["recorded", "pre_launch", "delivering", "closed", "quote", "settle", "whole", "inside"],
)
def test_wildcard_matches_only_listed_linear_usdt_perps(
    edits: dict[str, str], matched: bool
) -> None:
    """SR-E28-06 (PF-T07, AC-08): `*USDT` matches a listed, trading perpetual quoted and settled
    in USDT, by an anchored suffix, and nothing else."""
    scope = SymbolScope.of(_profile("fixed_notional"))  # allowed_symbols: ["*USDT"]
    assert scope.allows(_recorded_btcusdt(**edits)) is matched
