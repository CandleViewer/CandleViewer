"""Integration (E28-T05 S3d, #909): AC 5 and AC 6 over the E28 seed on Postgres 16. Each leg is
sized by its account's profile as the seed stores it, read through the real stores, against its
golden vector's wallet and market: QA's (`tests/fixtures/e28/golden_sizing_vectors.json`) and
E28-T03's own (`tests/unit/accounts/golden/e28_sizer_vectors.json`), computed against the
2026-10-05 capture's BTCUSDT, which the route lists. A preview takes no ATR reading, so P-PCT's ATR
stop falls back (T25). The composition is `serving`'s, with each account's figures its vector's."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from candleviewer.accounts.override_comparator import AccountFigures
from candleviewer.api.trade_group_preview_projection import MESSAGES
from tests.integration.oms.test_trade_group_preview_read_only_pg import (
    A,
    B,
    C,
    D,
    Readiness,
    buy,
    pg_dsn,
    seeded,
    serving,
)
from tests.unit.accounts.test_sizer import profile

pytestmark = pytest.mark.integration
__all__ = ["pg_dsn", "seeded"]  # the read-only module's database, seeded, for this module

_ROOT = Path(__file__).resolve().parents[2]  # services/api/tests
_VECTORS = {
    v["id"]: v
    for path in (_ROOT.parents[2] / "tests/fixtures/e28/golden_sizing_vectors.json",
                 _ROOT / "unit/accounts/golden/e28_sizer_vectors.json")
    for v in json.loads(path.read_text(encoding="utf-8"))
}  # fmt: skip
#: Each account's handle in `profiles.json`, whose leverage its leg resolves to.
_HANDLES: dict[UUID, str] = {A: "P-RISK", B: "P-QTY", C: "P-PCT", D: "P-NOTIONAL"}
D_ = Decimal


class Vectors:
    """The legs' cached figures: each account's vector's wallet, day's loss and taker fee, nothing
    committed, and the maintenance rate the sizer's own tests take (0.005)."""

    def __init__(self, vectors: dict[UUID, str]) -> None:
        self.figures = {}
        for account, vid in vectors.items():
            wallet, market = _VECTORS[vid]["wallet"], _VECTORS[vid]["market"]
            known = {
                "equity": wallet["equity"], "available_margin": wallet["available_margin"],
                "realised_loss_today": market["daily_loss_used"], "committed_risk": "0",
                "taker_fee_rate": market["taker_fee_rate"], "maintenance_margin_rate": "0.005",
            }  # fmt: skip
            fields = dict.fromkeys(AccountFigures.model_fields) | known
            self.figures[account] = AccountFigures.model_validate(fields)

    async def peeked(self, symbol: str, fallbacks: dict[UUID, Any]) -> dict[UUID, Any]:
        return {account: self.figures.get(account) for account in fallbacks}


def _as_vector(leg: dict[str, Any], vid: str) -> None:
    """`leg` resolved as vector `vid` says: its quantity, notional, stop, risk and margin, its
    take-profits, and its profile's leverage."""
    v = _VECTORS[vid]
    want, also = v["expected"], v.get("also", {})
    got = leg["resolved"]
    assert {k: D_(got[k]) for k in ("qty", "notional_usd", "stop_loss_price")} == {
        "qty": D_(want["qty"]), "notional_usd": D_(want.get("notional", also.get("notional"))),
        "stop_loss_price": D_(want["stop"]),
    }, vid  # fmt: skip
    risk = also.get("risk_with_fees_usdt", also["risk_usdt"])
    assert (D_(got["risk_usd"]), D_(leg["estimated_margin_usd"])) == (
        D_(risk),
        D_(also["initial_margin"]),
    ), vid
    assert D_(got["leverage"]) == profile(_HANDLES[UUID(leg["exchange_account_id"])]).leverage
    ladder = v.get("ladder", {"tp_prices": also.get("tp_prices", [])})
    sizes = ladder.get("tp_qtys", [want["qty"]] * len(ladder["tp_prices"]))
    assert [(D_(tp["price"]), D_(tp["qty"])) for tp in leg["take_profits"]] == [
        (D_(p), D_(q)) for p, q in zip(ladder["tp_prices"], sizes, strict=True)
    ], vid


def _summed(doc: dict[str, Any]) -> dict[str, Decimal]:
    """The totals' figures, and the sum of the legs' that would submit."""
    sent = [leg["resolved"] for leg in doc["legs"] if leg["would_submit"]]
    fee = sum((D_(r["estimated_fee_usd"]) for r in sent), D_(0))
    return {
        "total_qty": sum((D_(r["qty"]) for r in sent), D_(0)),
        "total_notional_usd": sum((D_(r["notional_usd"]) for r in sent), D_(0)),
        "total_risk_usd": sum((D_(r["risk_usd"]) for r in sent), D_(0)),
        "total_estimated_fee_usd": fee,
    }


async def test_each_leg_matches_its_golden_vector_and_totals_sum_the_legs(
    seeded: str, tmp_path: Path
) -> None:
    """AC 5: a BTCUSDT limit buy at 64000.0 on E28-A (P-RISK, V01), E28-B (P-QTY, T23; its failed
    key self-check overridden to ready, as AC 5 assumes) and E28-C (P-PCT, T25): three legs, each
    its vector's quantity, notional, stop, risk, margin and take-profits at its profile's
    leverage, and totals that sum the legs."""
    figures = Vectors({A: "V01", B: "T23", C: "T25"})
    async with serving(seeded, tmp_path / "a.wal", figures, Readiness(ready=True)) as served:
        got = await served.post(buy(A, B, C))
    doc = got.json()
    assert got.status_code == 200
    assert [(leg["status"], leg["warnings"]) for leg in doc["legs"]] == [
        ("ready", []), ("ready", []), ("warn", ["stop_fallback"]),
    ]  # fmt: skip
    for leg, vid in zip(doc["legs"], ("V01", "T23", "T25"), strict=True):
        _as_vector(leg, vid)
    totals = doc["totals"]
    assert (totals["accounts_targeted"], totals["accounts_submittable"]) == (3, 3)
    assert {k: D_(totals[k]) for k in _summed(doc)} == _summed(doc) == {
        "total_qty": D_("0.504"), "total_notional_usd": D_("32256"),
        "total_risk_usd": D_("156.16"), "total_estimated_fee_usd": D_(0),
    }  # fmt: skip


async def test_skipped_legs_state_their_reason(seeded: str, tmp_path: Path) -> None:
    """AC 6: on the same buy, E28-D (P-NOTIONAL's empty allow-list, V12) is `skipped`
    `symbol_not_allowed`, and E28-A at V04's 20 USDT of equity `skipped` `below_min_notional`,
    each with its sentence and nothing resolved, and each counted by its reason; E28-B and E28-C
    are as AC 5 has them, and the totals are theirs alone."""
    figures = Vectors({A: "V04", B: "T23", C: "T25", D: "V12"})
    async with serving(seeded, tmp_path / "a.wal", figures, Readiness(ready=True)) as served:
        got = await served.post(buy(D, A, B, C))
        skipped = {
            reason: served.metrics.registry.get_sample_value(
                "cv_tradegroup_legs_skipped_total", {"reason": reason, "env": "demo"}
            )
            for reason in ("symbol_not_allowed", "below_min_notional")
        }
    doc = got.json()
    assert got.status_code == 200
    assert [(leg["status"], leg["rejection"]) for leg in doc["legs"][:2]] == [
        ("skipped", {"code": code, "message": MESSAGES[code]})
        for code in ("symbol_not_allowed", "below_min_notional")
    ]
    assert not [leg for leg in doc["legs"][:2] if "resolved" in leg or leg["would_submit"]]
    for leg, vid in zip(doc["legs"][2:], ("T23", "T25"), strict=True):
        _as_vector(leg, vid)
    assert (doc["totals"]["accounts_targeted"], doc["totals"]["accounts_submittable"]) == (4, 2)
    assert {k: D_(doc["totals"][k]) for k in _summed(doc)} == _summed(doc)
    assert _summed(doc)["total_qty"] == D_("0.088")
    assert skipped == {"symbol_not_allowed": 1.0, "below_min_notional": 1.0}
