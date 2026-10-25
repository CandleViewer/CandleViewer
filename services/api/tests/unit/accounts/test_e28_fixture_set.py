"""E28-Q01 (#904): the E28 black-box fixture set in `tests/fixtures/e28/` at the repository root.

Every JSON file parses; each derived profile validates through `AccountProfile`; the instruments
select rows of the capture; the README names every file; `seed.sql`'s rows fit the models, its
profiles are theirs in stored units and its legs carry their profiles and their vectors' sizes; and
the golden vectors equal the hand recomputation, whose every row is checked step by step from its
own columns with plain `Decimal` operations. No sizer runs here (E28-T03 is not built). The
Postgres half is `tests/integration/accounts/test_e28_fixture_seed_pg.py`.
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import json
import re
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, Context, Decimal
from pathlib import Path
from typing import Any, Final

import pytest

from candleviewer.accounts.profiles import AccountProfile, profile_values
from candleviewer.accounts.verification import Rule
from candleviewer.db import models as m
from candleviewer.exchange.bybit.instruments import parse_instrument
from candleviewer.storage.repositories.account_profiles import LadderRung
from tests._corpus import rest

_E28: Final = Path(__file__).resolve().parents[5] / "tests" / "fixtures" / "e28"
_FROZEN: Final = Path(__file__).resolve().parents[2] / "fixtures" / "profiles"
#: The frozen four by content, a tripwire: `seed.sql`'s computed rows were made from these bytes.
_FROZEN_SHA256: Final = {
    "fixed_notional.json": "9e19e37c9ff34e9337bbc161bfc2c805ab85f498ae4f5cedcd63e3b6d5329962",
    "fixed_qty.json": "58ba1e5d1fc4c8d0df6eee83915ed0ff29d31775d917b9ee5bcba1540a0665f0",
    "pct_equity.json": "7d88cc11b04a99a88d0d8383ae44974475dd58db69471555ca6a463038d86eac",
    "risk_based.json": "942a3785fcdbfc880116d3df3c1ebe5aa87a77851bedc35cbf5a94e44bd58d23",
}
_CAPTURE_DATE: Final = "2026-10-05"
_CAPTURE: Final = "rest/instruments_before.json"
#: A quotient that does not end is cut at 28 significant digits, never rounded up (the md's rule).
_CUT: Final = Context(prec=28, rounding=ROUND_DOWN)
_BLOB: Final = re.compile(r"pg_temp\.e28_insert\('(\w+)', \$(\w+)\$\[\n(.*?)\n\]\$\2\$\)", re.S)
_TEXT: Final = frozenset({"id", "mode", "symbol", "side", "stop_unit", "binding_cap", "outcome"})
_LISTS: Final = frozenset({"code", "tp_qtys", "tp_prices"})
#: The vectors whose results the seeded legs carry, by the profile they were sized from.
_LEG_VECTORS: Final = {"P-RISK": "V01", "P-PCT": "V05"}


def _json(name: str) -> Any:
    return json.loads((_E28 / name).read_text(encoding="utf-8"))


def _profile(handle: str, changes: dict[str, Any] | None = None) -> AccountProfile:
    spec = _json("profiles.json")[handle]
    frozen = json.loads((_FROZEN / spec["from"]).read_text(encoding="utf-8"))
    return AccountProfile.model_validate({**frozen, **spec["set"], **(changes or {})})


def _vectors() -> dict[str, Any]:
    return {v["id"]: v for v in _json("golden_sizing_vectors.json")}


def _sheet() -> list[dict[str, str]]:
    with (_E28 / "sizing_recomputation.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _seed(table: str) -> list[dict[str, Any]]:
    text = (_E28 / "seed.sql").read_text(encoding="utf-8")
    return [r for t, _, rows in _BLOB.findall(text) if t == table for r in json.loads(f"[{rows}]")]


@pytest.mark.parametrize("name", sorted(p.name for p in _E28.glob("*.json")))
def test_every_json_file_parses(name: str) -> None:
    assert _json(name)


def test_the_profiles_are_the_frozen_four_with_named_changes() -> None:
    spec = _json("profiles.json")
    assert sorted(s["from"] for s in spec.values()) == sorted(_FROZEN_SHA256)
    digests = {n: hashlib.sha256((_FROZEN / n).read_bytes()).hexdigest() for n in _FROZEN_SHA256}
    assert digests == _FROZEN_SHA256  # these four exist, unchanged; a fifth beside them is fine
    profiles = [_profile(h) for h in spec]  # each validates through AccountProfile
    modes = ["fixed_notional", "fixed_qty", "pct_equity", "risk_based"]
    assert sorted(p.sizing_mode for p in profiles) == modes
    assert [p.name for p in profiles if not p.all_symbols and not p.allowed_symbols] == ["Fixed 1k"]
    assert [sum(r.qty_pct for r in p.tp_ladder) for p in profiles if p.tp_ladder] == [1]


def test_the_instruments_select_rows_of_the_capture() -> None:
    spec = _json("instruments.json")
    capture = rest(_CAPTURE, capture_date=_CAPTURE_DATE)["result"]["list"]
    assert spec["source"] == f"packages/fixtures/bybit/{_CAPTURE_DATE}/{_CAPTURE}"
    assert "DOGEUSDT" not in spec["patches"]  # no capture holds it; a recorded row is a follow-up
    assert not any(spec["patches"].values())  # a tripwire: the capture's rows, unpatched
    captured = {r["symbol"]: r for r in capture}
    rows = {s: {**captured[s], **patch} for s, patch in spec["patches"].items()}
    for r in _sheet():
        if r["tick"]:  # V12 is refused before any instrument row is read
            inst = parse_instrument(rows[r["symbol"]], fetched_at_us=0)
            got = (inst.tick_size, inst.qty_step, inst.min_order_qty, inst.max_order_qty)
            assert got == tuple(Decimal(r[k]) for k in ("tick", "qty_step", "min_qty", "max_qty"))
            assert inst.min_notional == Decimal(r["min_notional"])


def test_the_readme_names_every_file() -> None:
    readme = (_E28 / "README.md").read_text(encoding="utf-8")
    assert [p.name for p in sorted(_E28.iterdir()) if f"`{p.name}`" not in readme] == []


def _decimal(value: str | None) -> Decimal | None:
    """A decimal string, or `None` for a JSON null or a blank cell."""
    return Decimal(value) if value else None


def test_the_vectors_equal_the_spreadsheet() -> None:
    sheet, vectors = {r["id"]: r for r in _sheet()}, _vectors()
    assert list(vectors) == list(sheet) and len(vectors) >= 12
    column = {"min_order_qty": "min_qty", "stop_fallback": "stop_unit"}
    for v in vectors.values():
        row, intent, wallet, market = sheet[v["id"]], v["intent"], v["wallet"], v["market"]
        # The inputs. Every cap column takes a limit order's caps (Q3); a blank ATR is no ATR.
        assert intent["order_type"] == "limit", v["id"]
        assert [intent["symbol"], intent["side"]] == [row["symbol"], row["side"]], v["id"]
        given = [intent["price"], wallet["equity"], wallet["available_margin"], market["atr"]]
        cells = [row["ref"], row["equity"], row["available_margin"], row["atr"]]
        assert [_decimal(x) for x in given] == [_decimal(x) for x in cells], v["id"]
        # A blank fee or day's loss means 0: the sheet leaves the fee out where the mode takes none
        # (step 5 is risk_based only), and both out of V12, which the gate skips.
        for key, cell in (("taker_fee_rate", "taker_fee"), ("daily_loss_used", "daily_loss_used")):
            assert Decimal(market[key]) == Decimal(row[cell] or "0"), (v["id"], key)
        for key, want in {**v["expected"], **v.get("also", {}), **v.get("ladder", {})}.items():
            got = row.get(column.get(key, key), "")
            if key == "risk_with_fees_usdt":
                fees = Decimal(row["stop_distance"]) + Decimal(row["fee_per_unit"])
                assert Decimal(row["qty"]) * fees == Decimal(want)
            elif key == "stop_fallback":
                assert (got == "atr_fallback") is want
            elif isinstance(want, list):
                assert [Decimal(x) for x in got.split(";")] == [Decimal(x) for x in want], v["id"]
            elif key in ("outcome", "code", "binding_cap"):
                assert got == want, (v["id"], key)
            else:
                assert Decimal(got) == Decimal(want), (v["id"], key)


def _cap(row: dict[str, str], key: str, value: Decimal | None) -> Decimal | None:
    """The cap's column holds `value`, or nothing when the profile sets no such cap."""
    assert (Decimal(row[key]) if row[key] else None) == value, (row["id"], key)
    return value


def _floor(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def _allows(p: AccountProfile, symbol: str) -> bool:
    """US-PROF-003 and D11, written out here rather than taken from the order path: `all_symbols`,
    or an allow-list entry that is the symbol or a `*` suffix of it, so an empty list allows
    nothing; then a denied entry wins."""

    def listed(entries: tuple[str, ...]) -> bool:
        return any(e == symbol or (e.startswith("*") and symbol.endswith(e[1:])) for e in entries)

    return (p.all_symbols or listed(p.allowed_symbols)) and not listed(p.denied_symbols)


@pytest.mark.parametrize("row", _sheet(), ids=lambda r: r["id"])
def test_each_spreadsheet_row_is_consistent_step_by_step(row: dict[str, str]) -> None:
    v = _vectors()[row["id"]]
    p = _profile(v["profile"]["id"], v["profile"]["set"])
    d = {k: Decimal(x) for k, x in row.items() if x and k not in _TEXT | _LISTS}
    size = {"fixed_qty": p.fixed_qty, "fixed_notional": p.fixed_notional}
    size |= {"pct_equity": p.pct_equity, "risk_based": p.risk_pct_equity}
    assert row["mode"] == p.sizing_mode
    profile = [p.leverage, p.min_leg_notional, size[p.sizing_mode]]
    assert [d["leverage"], d["min_leg_notional"], d["size_param"]] == profile
    if row["outcome"] != "ok":  # a skip or a failure sizes no leg: no risk, margin or take-profit
        assert not any(row[k] for k in ("risk_usdt", "initial_margin", "tp_qtys", "tp_prices"))
    # 24 Sec.9.3 step 1, the gate: no vector's profile is disabled, and only V12's symbol is refused
    assert p.enabled and p.trading_enabled
    if row["code"] == "symbol_not_allowed":  # an empty list allows nothing (D11)
        assert not p.all_symbols and not p.allowed_symbols and not _allows(p, row["symbol"])
        return
    assert _allows(p, row["symbol"]), row["id"]
    ref, tick, equity, unit, param = (
        d["ref"],
        d["tick"],
        d["equity"],
        row["stop_unit"],
        d["stop_param"],
    )
    sign = Decimal(-1 if row["side"] == "Buy" else 1)  # a long's stop is below its entry
    stops = {
        "ticks": (p.sl_offset_value, ref + sign * param * tick),
        "percent": (p.sl_offset_value, ref * (1 + sign * param)),
        "atr": (p.sl_atr_multiple, ref + sign * d.get("atr", Decimal(0)) * param),
        "atr_fallback": (p.fallback_sl_offset_pct, ref * (1 + sign * param)),
    }
    assert stops[unit] == (param, d["raw_stop"])
    assert p.sl_offset_unit == unit.removesuffix("_fallback") and ("atr" in d) == (unit == "atr")
    away = ROUND_FLOOR if sign < 0 else ROUND_CEILING  # further from entry (24 Sec.9.3.1)
    assert (d["raw_stop"] / tick).to_integral_value(rounding=away) * tick == d["stop"]
    assert abs(ref - d["stop"]) == d["stop_distance"]
    if p.sizing_mode == "risk_based":
        assert p.risk_pct_equity is not None and equity * p.risk_pct_equity == d["risk_budget"]
        assert ref * d["taker_fee"] * 2 == d["fee_per_unit"]
        raw = _CUT.divide(d["risk_budget"], d["stop_distance"] + d["fee_per_unit"])
    elif p.sizing_mode == "pct_equity":
        assert p.pct_equity is not None
        raw = _CUT.divide(equity * p.pct_equity * p.leverage, ref)
    elif p.sizing_mode == "fixed_notional":
        assert p.fixed_notional is not None
        raw = _CUT.divide(p.fixed_notional, ref)
    else:
        assert p.fixed_qty is not None
        raw = p.fixed_qty
    assert raw == d["qty_raw"]
    pct, notional, loss_pct = (
        p.max_position_pct_equity,
        p.max_position_notional,
        p.max_daily_loss_pct,
    )
    daily = [x for x in (p.max_daily_loss, loss_pct and loss_pct * equity) if x is not None]
    assert p.max_leverage_cap is not None and min(daily) == d["daily_cap"]
    room = _CUT.divide(d["daily_cap"] - d["daily_loss_used"], d["stop_distance"])
    caps = {
        "leverage": _cap(row, "cap_leverage_qty", _CUT.divide(p.max_leverage_cap * equity, ref)),
        "pct_equity": _cap(row, "cap_pct_equity_qty", pct and _CUT.divide(pct * equity, ref)),
        "notional": _cap(row, "cap_notional_qty", notional and _CUT.divide(notional, ref)),
        "daily_loss": _cap(row, "cap_daily_qty", room),
        "instrument": _cap(row, "cap_instrument_qty", d["max_qty"]),
    }
    bound = {k: c for k, c in caps.items() if c is not None and c < d["qty_raw"]}
    assert min([d["qty_raw"], *bound.values()]) == d["qty_capped"]
    assert row["binding_cap"] == min(bound, key=lambda k: bound[k], default="none")
    assert _floor(d["qty_capped"], d["qty_step"]) == d["qty"]
    assert d["qty"] * ref == d["notional"]
    assert d["available_margin"] * p.leverage * Decimal("0.98") == d["margin_limit"]
    if d["qty"] < d["min_qty"] or d["notional"] < max(d["min_notional"], d["min_leg_notional"]):
        assert (row["outcome"], row["code"]) == ("skip", "below_min_notional")
        return
    if d["notional"] > d["margin_limit"]:
        assert (row["outcome"], row["code"]) == ("fail", "insufficient_margin")
        return
    assert (row["outcome"], d["qty"] * d["stop_distance"]) == ("ok", d["risk_usdt"])
    assert _CUT.divide(d["notional"], p.leverage) == d["initial_margin"]
    if row["tp_qtys"]:  # 24 Sec.9.3.3: floor each rung, the last takes the remainder
        rungs = [_floor(d["qty"] * r.qty_pct, d["qty_step"]) for r in p.tp_ladder]
        rungs[-1] = d["qty"] - sum(rungs[:-1])
        assert [Decimal(x) for x in row["tp_qtys"].split(";")] == rungs
        multiples = [r.r for r in p.tp_ladder]
    else:
        single = p.tp_offset_value if p.tp_offset_unit == "r_multiple" else None
        multiples = [] if single is None else [single]
    prices = [ref - sign * r * d["stop_distance"] for r in multiples]
    assert [Decimal(x) for x in row["tp_prices"].split(";") if x] == prices


def test_the_seed_rows_fit_the_models() -> None:
    text = (_E28 / "seed.sql").read_text(encoding="utf-8")
    tables = [t for t, _, _ in _BLOB.findall(text)]
    assert len(tables) == text.count("pg_temp.e28_insert('")
    for table in dict.fromkeys(tables):
        rows = _seed(table)
        assert set(rows[0]) <= set(getattr(m, table).c.keys()), table
        assert all(set(r) == set(rows[0]) for r in rows), table  # one column list per table
    disarmed = [a["policy_disarm_code"] for a in _seed("exchange_accounts")]
    assert [c for c in disarmed if c] == [Rule.IP_WHITELIST_MISMATCH.value]  # a key self-check rule


def test_the_seeded_profiles_are_their_profiles_in_stored_units() -> None:
    """Each seeded `account_profiles` row is `profile_values` of its E28 profile, value by value,
    so a drift in the stored units shows here as well as against Postgres."""
    profiles = {str(p.profile_id): p for p in map(_profile, _json("profiles.json"))}
    rows = _seed("account_profiles")
    assert sorted(r["id"] for r in rows) == sorted(profiles)
    for row in rows:
        p = profiles[row["id"]]
        assert row["exchange_account_id"] == str(p.account_id)
        stored = profile_values(p)
        for field in dataclasses.fields(stored):
            want, got = getattr(stored, field.name), row[field.name]
            if field.name == "tp_ladder" and got:  # jsonb numbers, as trg_ap_ladder_sum reads them
                got = tuple(LadderRung(Decimal(str(r["pct"])), Decimal(str(r["r"]))) for r in got)
            elif isinstance(want, Decimal) and got is not None:
                got = Decimal(got)
            elif isinstance(got, list):
                got = tuple(got)
            assert got == want, (p.name, field.name)


def test_the_seed_legs_carry_their_profiles_and_their_vectors_sizes() -> None:
    profiles = {str(p.profile_id): (h, p) for h in _json("profiles.json") for p in [_profile(h)]}
    legs, vectors = _seed("trade_group_legs"), _vectors()
    for leg in legs:
        handle, profile = profiles[leg["account_profile_id"]]
        assert leg["profile_snapshot"] == profile.model_dump(mode="json")
        assert Decimal(leg["resolved_leverage"]) == profile.leverage
        v = vectors[_LEG_VECTORS[handle]]
        sized = [v["expected"]["qty"], v["expected"]["stop"], v["also"]["risk_usdt"]]
        seeded = [leg["target_qty"], leg["resolved_sl_price"], leg["risk_usd"]]
        assert [Decimal(x) for x in seeded] == [Decimal(x) for x in sized]
    assert len(legs) == 4  # a tripwire: two groups of two legs; a new leg needs its vector here
