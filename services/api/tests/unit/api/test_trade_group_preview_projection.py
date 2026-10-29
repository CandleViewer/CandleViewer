"""E28-T05 S3b (#909): the preview's document, 22's `TradeGroupPreview` as S0 shaped it, from
the planner's plan, and its `trade_group.previewed` row (ruling 2).

Each leg states its `status` as text and `would_submit` (true exactly for `ready` and `warn`); a
skipped or blocked one carries 22's code with CandleViewer's own sentence, never another text
(SR-E29-09); `figure_unknown` says the figures are not available yet (ruling 1, #881). A leg the
comparator admitted shows what it would send, its stop, its take-profit (the ladder's last rung),
its risk with both taker fees and those fees, the figure the totals sum. Decimals are plain. The
row holds ids, the symbol, the side, the role and the legs' outcome counts, never a figure."""

from __future__ import annotations

import inspect
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, cast, get_args
from uuid import UUID

from candleviewer.accounts.override_comparator import RefusalActor, Violation
from candleviewer.accounts.sizer import FailReason, SkipReason
from candleviewer.accounts.sizer_metrics import SizerMetrics
from candleviewer.accounts.trade_group_readiness import ReadinessReason
from candleviewer.api._generated.openapi_models import Rejection, TradeGroupPreview
from candleviewer.api.trade_group_preview_projection import (
    MESSAGES,
    PREVIEWED_ACTION,
    preview_document,
    previewed_entry,
)
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.models import AuditOutcome, ExchangeEnv, Severity
from candleviewer.audit.repository import AuditRepository
from candleviewer.audit.writer import AuditWriter
from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.observability.metrics import Metrics
from candleviewer.oms import ports
from candleviewer.oms.fanout import plan as planner
from candleviewer.oms.fanout.guard import RejectionCode
from candleviewer.oms.fanout.plan import GroupPlan, GroupRefused, LegProfiles, LegRequest, LegTerms
from tests.unit.oms.submit_rig import figures, instrument, profile

D = Decimal
A, B, C, E, F, G = (AccountId(UUID(int=n)) for n in range(1, 7))
LADDER = {"tp_ladder": [{"qty_pct": "0.5", "r": "1"}, {"qty_pct": "0.5", "r": "2"}]}
ACTOR = RefusalActor(
    user_id=UUID(int=77), role="manager", env="demo", request_id=UUID(int=78), ip="203.0.113.7"
)


class _Ready:
    def __init__(self, table: dict[UUID, Any]) -> None:
        self.table = table

    def reason(self, account_id: UUID, environment: Environment, *, account_enabled: bool) -> Any:
        return self.table.get(account_id)


class _Guard:
    def refusal(self, order: Any, *, profile: Any, instrument: Any) -> None:
        return None


def _plan(
    held: dict[AccountId, Any], legs: tuple[LegRequest, ...], known: dict[UUID, Any]
) -> tuple[planner.GroupRequest, GroupPlan]:
    """A limit buy of BTCUSDT at 60000 on demo; F's key failed; `known` overrides the figures."""
    request = planner.GroupRequest("BTCUSDT", "buy", "limit", legs, LegTerms(price=D(60000)))
    snapshot = planner.take_snapshot(
        [(leg.account_id, True) for leg in legs], environment="demo", instrument=instrument(),
        mid=None, last=None, figures=lambda account: known.get(account, figures()),
        readiness=_Ready({F: "key_invalid"}),
    )  # fmt: skip
    plan = planner.plan_group(
        request, profiles={a: LegProfiles(p) for a, p in held.items()}, snapshot=snapshot,
        guard=_Guard(), stops=ports.InterimStopResolver(),
        observer=SizerMetrics.register(Metrics("demo")),
    )  # fmt: skip
    assert isinstance(plan, GroupPlan)
    return request, plan


def _scenario() -> tuple[planner.GroupRequest, GroupPlan]:
    """A ready on a two-rung ladder; B `warn`, its `atr` stop fallen back to 2 %; C skipped by the
    request; E's profile allows only ETHUSDT; F's key failed; G's figures are not cached."""
    held = {A: profile(A, **LADDER), B: profile(B, sl_offset_unit="atr"), F: profile(F)}
    held |= {E: profile(E, allowed_symbols=["ETHUSDT"]), G: profile(G)}
    legs = (LegRequest(A), LegRequest(B), LegRequest(C, skip=True), *map(LegRequest, (E, F, G)))
    return _plan(held, legs, {G: None})


def test_the_codes_are_22s_and_every_reason_maps_onto_one() -> None:
    """22's `rejection.code` (S0) is the planner's and the guard's `RejectionCode`, and holds every
    sizer and enabled-member reason; each code has CandleViewer's own sentence."""
    (codes,) = (a for a in get_args(Rejection.model_fields["code"].annotation) if get_args(a))
    assert get_args(RejectionCode) == get_args(codes)
    reasons = {r.value for r in (*SkipReason, *FailReason)} | set(get_args(ReadinessReason))
    assert reasons - set(get_args(codes)) == {"member_disabled"}
    assert set(MESSAGES) == set(get_args(codes))


def test_each_leg_states_its_status_and_a_skipped_or_blocked_one_its_code() -> None:
    """SCR-061: a status as text, `would_submit` exactly for `ready` and `warn`, a `warn` leg's
    caveat, a skipped or blocked leg's code; what the comparator admitted shows, blocked or not."""
    doc: Any = preview_document(_scenario()[1], {A: "Main", B: "Hedge"})
    TradeGroupPreview.model_validate(doc)
    legs = doc["legs"]
    assert [(leg["status"], leg["would_submit"], leg["warnings"]) for leg in legs] == [
        ("ready", True, []), ("warn", True, ["stop_fallback"]), ("skipped", False, []),
        ("skipped", False, []), ("blocked", False, []), ("blocked", False, []),
    ]  # fmt: skip
    assert [leg["rejection"] and leg["rejection"]["code"] for leg in legs] == [
        None, None, "skipped", "symbol_not_allowed", "key_invalid", "figure_unknown"
    ]  # fmt: skip
    assert [leg.get("account_label") for leg in legs] == ["Main", "Hedge", None, None, None, None]
    profiled = [leg["account_profile_id"] is not None for leg in legs]
    assert profiled == [True, True, False, True, True, True]  # C's skip names no profile
    admitted = ["resolved" in leg and "take_profits" in leg for leg in legs]
    assert admitted == [True, True, False, False, True, False]
    assert legs[4]["take_profits"] == [{"price": "66000", "qty": "0.01"}]


def test_a_message_is_cvs_own_sentence_for_its_code_never_another_text() -> None:
    """Whatever the leg holds (its figures, its explanation), the code's sentence alone: no figure,
    no slug; `figure_unknown` says the figures are not available yet."""
    doc: Any = preview_document(_scenario()[1], {})
    said = [(leg["rejection"]["code"], leg["rejection"]["message"]) for leg in doc["legs"][2:]]
    codes: list[RejectionCode] = ["skipped", "symbol_not_allowed", "key_invalid", "figure_unknown"]
    assert said == [(code, MESSAGES[code]) for code in codes]
    assert MESSAGES["figure_unknown"] == "The account's figures are not available yet."
    assert not [text for text in MESSAGES.values() if re.search(r"[0-9_]", text)]
    assert all(text[0].isupper() and text.endswith(".") for text in MESSAGES.values())


def test_a_ready_leg_resolves_what_it_would_send_and_its_ladder() -> None:
    """0.01 at 60000, its stop 5 % under, its take-profit the last of its two rungs, or the one the
    request names (64000) with the rungs still the profile's; its risk is 1R (30) plus both taker
    fees (0.00055 of 60000 twice a unit: 0.66), plain."""
    plan = _scenario()[1]
    sized = plan.legs[0].sizing
    doc: Any = preview_document(plan, {A: "Main"})
    rungs = [{"price": "63000", "qty": "0.005"}, {"price": "66000", "qty": "0.005"}]
    assert sized is not None and doc["legs"][0] == {
        "exchange_account_id": str(A), "account_label": "Main",
        "account_profile_id": str(profile(A).profile_id), "would_submit": True,
        "status": "ready", "warnings": [], "rejection": None,
        "resolved": {
            "qty": "0.01", "price": "60000", "leverage": "10", "stop_loss_price": "57000",
            "take_profit_price": "66000", "notional_usd": "600", "risk_usd": "30.66",
            "estimated_fee_usd": "0.66", "sizing_explanation": sized.render(),
        },
        "take_profits": rungs, "estimated_margin_usd": "60", "estimated_risk_usd": "30.66",
    }  # fmt: skip
    near = LegRequest(A, LegTerms(take_profit=ports.StopOffset(unit="price", value=D(64000))))
    named: Any = preview_document(_plan({A: profile(A, **LADDER)}, (near,), {})[1], {})
    leg = named["legs"][0]
    assert (leg["resolved"]["take_profit_price"], leg["take_profits"]) == ("64000", rungs)


def test_the_totals_sum_the_submittable_legs_their_fees_exactly() -> None:
    """22: `total_estimated_fee_usd` is the submitted legs' `estimated_fee_usd` summed, exactly, a
    taker rate of 31 digits included (no 28-digit rounding), while `risk_usd` is rounded up to the
    column's 18 places; a figure the sizer never reached is left out, never 0."""
    doc: Any = preview_document(_scenario()[1], {})
    assert doc["totals"] == {
        "accounts_targeted": 6, "accounts_submittable": 2, "total_qty": "0.02",
        "total_notional_usd": "1200", "total_risk_usd": "43.32", "total_estimated_fee_usd": "1.32",
    }  # fmt: skip
    assert not {"estimated_margin_usd", "estimated_risk_usd"} & set(doc["legs"][5])
    rate = figures(taker_fee_rate="0.0005500000000000000000000000017")
    fine: Any = preview_document(_plan({A: profile(A)}, (LegRequest(A),), {A: rate})[1], {})
    resolved = fine["legs"][0]["resolved"]
    fee = resolved["estimated_fee_usd"]
    assert fee == fine["totals"]["total_estimated_fee_usd"] == "0.66000000000000000000000000204"
    assert resolved["risk_usd"] == "30.660000000000000001"  # 30.66000000000000000000000000204


def test_the_previewed_row_holds_ids_symbol_side_and_counts_never_a_figure(
    tmp_path: Path,
) -> None:
    """Ruling 2: one row per answered preview, 200 or 403; the audit writer builds it as is."""
    request, plan = _scenario()
    row = previewed_entry(request, plan, actor=ACTOR)
    ids = [str(account) for account in (A, B, C, E, F, G)]
    assert row["after_state"] == {
        "symbol": "BTCUSDT", "side": "buy", "role": "manager", "exchange_account_ids": ids,
        "outcomes": {"ready": 1, "warn": 1, "skipped": 2, "blocked": 2},
    }  # fmt: skip
    assert (row["outcome"], row["severity"], row["reason"]) == ("success", "info", None)
    wide = Violation(field="fixed_qty", rule="R1", reason="above_limit", limit=D(1), requested=D(2))
    refused = GroupRefused((planner.RefusedLeg(0, profile(A), None, (wide,)),))
    denied = previewed_entry(request, refused, actor=ACTOR)
    assert denied["after_state"] == {
        "symbol": "BTCUSDT", "side": "buy", "role": "manager", "exchange_account_ids": ids,
        "outcomes": {"refused": 1},
    }  # fmt: skip
    assert (denied["outcome"], denied["severity"]) == ("denied", "warning")
    assert denied["reason"] == "risk_limit_breached"
    early = previewed_entry(None, "trading_disabled", actor=ACTOR)  # S3c: before the body is read
    assert (early["after_state"], early["outcome"], early["reason"]) == (
        {"role": "manager", "outcomes": {}}, "denied", "trading_disabled",
    )  # fmt: skip
    for made in (row, denied, early):  # whose request it was, and what it was about
        assert (made["actor_ip"], made["object_kind"]) == (ACTOR.ip, "trade_group_preview")
    assert PREVIEWED_ACTION == "trade_group.previewed" and PREVIEWED_ACTION in AUDIT_ACTIONS
    assert set(row) <= set(inspect.signature(AuditWriter.emit).parameters) - {"self", "action"}
    writer = AuditWriter(cast(AuditRepository, object()), str(tmp_path / "audit.wal"))
    built = writer.build(PREVIEWED_ACTION, **denied)
    assert (built.outcome, built.severity, built.env) == (
        AuditOutcome.DENIED, Severity.WARNING, ExchangeEnv.DEMO
    )  # fmt: skip
    assert (built.after_state, built.actor_user_id, built.request_id) == (
        denied["after_state"], ACTOR.user_id, ACTOR.request_id
    )  # fmt: skip
