"""`403 kek_unavailable` at the order routes (#2331; 24 Sec.8.4 step 10, 22 `Forbidden`).

While the credential key's latch holds (`secrets.kek_unavailable`), an order mutation that opens or
increases exposure is refused at its route with zero OMS or exchange calls and its refusal record
written ahead: `placeOrder` (a `reduce_only` one too), `reversePosition`, `setPositionLeverage`
and a risk-increasing `amendOrder`. Protective paths keep their answers (C-2.6); the stranded and
rotation latches stay `trading_disabled`. Each route runs on its own test world, the latch handed
in as the composition root hands it (`kek=ctx.oms_read_only_gate`). No network (C-13.5)."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.order_cancel_all import make_cancel_all_router
from candleviewer.api.order_kek import KEK_LATCH_REASON, entry_refusal, kek_refusal
from candleviewer.api.position_close import CLOSE_ALL_PATH, CLOSE_PATH, make_position_close_router
from candleviewer.api.position_reverse import REVERSE_PATH
from candleviewer.api.trade_group_preview import make_trade_group_preview_router
from candleviewer.net import ReadOnlyGate
from candleviewer.oms.errors import (
    OmsError,
    OmsNotReady,
    OrderEntryRefused,
    OrderKekUnavailable,
    TradingDisabled,
)
from candleviewer.oms.leverage import LEVERAGE_ACTION
from candleviewer.oms.position_writes import REVERSE_ACTION
from candleviewer.oms.validator import OrderPlacementRefused, Validator
from candleviewer.secrets import _metrics as secrets_metrics
from candleviewer.secrets.service import (
    GATE_REASON,
    STRANDED_GATE_REASON,
    STRANDED_REMEDIATION,
    SecretsService,
)
from tests.unit.api import position_writes_world as pw
from tests.unit.api import test_order_amend_route as am
from tests.unit.api import test_order_exits_route as er
from tests.unit.api import test_orders_route as orr
from tests.unit.api import test_position_leverage_route as lv
from tests.unit.api.test_order_acceptance import first_entry, read_entry, replay_of
from tests.unit.oms import submit_rig as sr
from tests.unit.oms.submit_rig import SubmitRig

_CODE = "kek_unavailable"
_DETAIL = OrderKekUnavailable.default_detail
_FOREIGN = orr.BODY | {"exchange_account_id": str(orr.FOREIGN)}  # outside the Manager's grants


@dataclass
class Latch:
    """`KekLatch`: the OMS read-only gate's reason as the routes read it."""

    reason_code: str | None = KEK_LATCH_REASON


def _refused_with_kek(answer: Any) -> None:
    """The fixed 403: the code and CandleViewer's own sentence, never the latch's remediation."""
    body = answer.json()
    assert (answer.status_code, body["code"], body["detail"]) == (403, _CODE, _DETAIL)
    assert "CV_KEK" not in answer.text and "reason" not in body


# --- the shared check ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("switched", "latch", "expected"),
    [
        (None, Latch(), OrderKekUnavailable),
        (OrderEntryRefused(orr.GATE), Latch(), OrderKekUnavailable),  # ahead of the gate
        (TradingDisabled(), Latch(), TradingDisabled),  # live off or the kill switch first
        (OmsNotReady(), Latch(), OmsNotReady),  # the lock's fence first
        (None, Latch(STRANDED_GATE_REASON), type(None)),
        (None, Latch("secrets.kek_rotation"), type(None)),
        (None, None, type(None)),
    ],
    ids=["latched", "before_gate", "after_kill", "after_fence", "stranded", "rotation", "none"],
)
def test_entry_refusal_slots_the_kek_after_the_switches_and_before_the_gate(
    switched: OmsError | None, latch: Latch | None, expected: type[object]
) -> None:
    assert type(entry_refusal(latch, switched)) is expected


def test_kek_refusal_reads_the_switches_only_while_latched_and_yields_to_a_switch() -> None:
    asked: list[int] = []

    def switches(answer: OmsError | None) -> Callable[[], OmsError | None]:
        def read() -> OmsError | None:
            asked.append(1)
            return answer

        return read

    assert kek_refusal(Latch(None), switches(None)) is None and asked == []
    assert isinstance(
        kek_refusal(Latch(), switches(OrderEntryRefused(orr.GATE))), OrderKekUnavailable
    )
    assert kek_refusal(Latch(), switches(TradingDisabled())) is None  # the service answers it
    assert len(asked) == 2


def test_the_pinned_reason_is_the_secrets_latchs_and_22s_example_is_the_fixed_detail() -> None:
    spec: Any = load_openapi_spec()
    example = spec["components"]["responses"]["Forbidden"]["content"]["application/problem+json"]
    value = example["examples"]["kekUnavailableOrderEntry"]["value"]
    assert KEK_LATCH_REASON == GATE_REASON
    assert (value["code"], value["detail"]) == (_CODE, _DETAIL)


# --- placeOrder ---------------------------------------------------------------------------------


@pytest.mark.parametrize("body", [orr.BODY, orr.BODY | {"reduce_only": True}], ids=["entry", "ro"])
async def test_place_order_latched_is_403_kek_unavailable_recorded_nothing_sent(
    body: dict[str, Any],
) -> None:
    """AC4: the degraded latch, then `POST /orders`: 403 `kek_unavailable`, its `orders.submit`
    record written ahead, no pipeline call and no task."""
    world = orr.World(kek=Latch())
    answer = await orr.post(world, body=body)
    _refused_with_kek(answer)
    er._PROBLEM.validate(answer.json())
    [record] = world.audit.written
    assert (record.action, record.outcome, record.reason) == ("orders.submit", "denied", _CODE)
    assert record.detail["step"] == "kek"
    assert (world.oms.submission.submitted, world.oms.tasks) == ([], [])
    assert world.rejected(_CODE) == 1


@pytest.mark.parametrize(
    ("switched", "code"),
    [(TradingDisabled(), "trading_disabled"), (OrderEntryRefused(orr.GATE), _CODE)],
    ids=["kill_switch_first", "gate_after"],
)
async def test_place_order_the_kill_switch_answers_before_the_kek_and_the_gate_after(
    switched: TradingDisabled, code: str
) -> None:
    world = orr.World(kek=Latch())
    world.oms.route.switches.refuses = switched
    answer = await orr.post(world)
    assert (answer.status_code, answer.json()["code"]) == (403, code)
    assert world.oms.submission.submitted == []


@pytest.mark.parametrize(
    ("who", "body", "code"),
    [("viewer", None, "forbidden"), ("manager", _FOREIGN, "account_scope_denied")],
    ids=["forbidden_role", "cross_account"],
)  # fmt: skip
async def test_place_order_latched_an_unauthorised_caller_still_meets_rbac_first(
    who: str, body: Any, code: str
) -> None:
    """The KEK state never reaches a caller outside scope (BQ-2)."""
    world = orr.World(kek=Latch())
    answer = await orr.post(world, who, body)
    assert (answer.status_code, answer.json()["code"]) == (403, code)
    assert world.audit.actions() == ["rbac.denied"]


async def test_place_order_latched_a_replay_of_an_accepted_key_is_its_stored_outcome() -> None:
    world, first = orr.World(kek=Latch()), first_entry()
    row, found = read_entry(first)
    world.oms.route.orders.rows[row.id], world.oms.route.groups.found = row, found
    orr._replay(world, replay_of(first))
    answer = await orr.post(world)
    assert (answer.status_code, answer.headers["idempotency-replayed"]) == (202, "true")
    assert world.oms.submission.submitted == []


async def test_place_order_latched_an_unwritable_refusal_record_is_503_audit_unavailable() -> None:
    world = orr.World(kek=Latch())
    world.audit.fail = True
    answer = await orr.post(world)
    assert (answer.status_code, answer.json()["code"]) == (503, "audit_unavailable")
    assert world.oms.submission.submitted == []


@pytest.fixture
def secrets_gauge() -> Iterator[None]:
    """`_latch` sets the process-wide KEK gauge: restored, so no other test reads it set."""
    yield None
    secrets_metrics.kek_degraded_state.set(0)


@pytest.mark.usefixtures("secrets_gauge")
@pytest.mark.parametrize("latched", ["unavailable", "stranded", "rotation"])
async def test_place_order_over_the_real_secrets_latch(latched: str) -> None:
    """BQ-3: the real `SecretsService._latch` on the real `ReadOnlyGate`, wired as `create_app`
    wires it. Unavailable is the route's `kek_unavailable`; stranded and rotation pass the route
    and the OMS validator answers them `trading_disabled`, as before #2331."""
    gate, service = ReadOnlyGate(), SecretsService(harden=lambda: True)
    ctx: Any = SimpleNamespace(oms_read_only_gate=gate)
    if latched == "unavailable":
        service._latch(ctx, "kek_unavailable")
    elif latched == "stranded":
        service._latch(
            ctx, "kek_rows_stranded", code=STRANDED_GATE_REASON, text=STRANDED_REMEDIATION
        )
    else:
        service._latch_rotation(gate)
    world = orr.World(kek=gate)
    try:  # the pipeline's own read-only check, the real validator's
        Validator(read_only_gate=gate).assert_order_placement_allowed()
    except OrderPlacementRefused as exc:
        world.oms.submission.error = exc
    answer = await orr.post(world)
    if latched == "unavailable":
        _refused_with_kek(answer)
        assert world.oms.submission.submitted == []
        return
    assert (answer.status_code, answer.json()["code"]) == (403, "trading_disabled")


# --- reversePosition, closePosition, closeAllPositions -----------------------------------------


async def test_reverse_position_latched_is_403_kek_unavailable_recorded_nothing_sent() -> None:
    world = pw.World(kek=Latch())
    answer = await pw.post(world, pw.on(REVERSE_PATH, pw.ON_A))
    _refused_with_kek(answer)
    [(record, sent)] = world.records.written
    assert (record.action, record.outcome, record.reason, sent) == (
        REVERSE_ACTION, "denied", _CODE, 0
    )  # fmt: skip
    assert record.detail["step"] == "kek"
    assert world.pipeline.submitted == []


async def test_reverse_position_latched_a_replay_of_an_accepted_key_is_its_stored_outcome() -> None:
    world, key = pw.World(), uuid4()
    path = pw.on(REVERSE_PATH, pw.ON_A)
    first = await pw.post(world, path, key=key)
    assert first.status_code == 202, first.text
    sent = len(world.pipeline.submitted)
    world.kek = Latch()
    again = await pw.post(world, path, key=key)
    assert (again.status_code, again.headers["idempotency-replayed"]) == (202, "true")
    assert again.json() == first.json() and len(world.pipeline.submitted) == sent


async def test_reverse_position_latched_an_unwritable_refusal_record_is_503_audit_unavailable() -> (
    None
):
    world = pw.World(kek=Latch())
    world.records.fail = True
    answer = await pw.post(world, pw.on(REVERSE_PATH, pw.ON_A))
    assert (answer.status_code, answer.json()["code"]) == (503, "audit_unavailable")
    assert world.pipeline.submitted == []


async def test_reverse_position_latched_a_foreign_position_is_404_as_before() -> None:
    world = pw.World(kek=Latch())
    answer = await pw.post(world, pw.on(REVERSE_PATH, pw.ON_B), "manager")
    assert (answer.status_code, answer.json()["code"]) == (404, "not_found")
    assert world.pipeline.submitted == [] and world.records.written == []


async def test_reverse_position_latched_the_forbidden_role_meets_rbac_first() -> None:
    world = pw.World(kek=Latch())
    answer = await pw.post(world, pw.on(REVERSE_PATH, pw.ON_A), "viewer")
    assert (answer.status_code, answer.json()["code"]) == (403, "forbidden")
    assert world.records.written == []


@pytest.mark.parametrize(
    ("path", "body", "status"),
    [(pw.on(CLOSE_PATH, pw.ON_A), {"order_type": "market", "pct": "100"}, 202),
     (CLOSE_ALL_PATH, {}, 200)],
    ids=["close", "close_all"],
)  # fmt: skip
async def test_close_and_close_all_latched_keep_their_answers(
    path: str, body: dict[str, Any], status: int
) -> None:
    """C-2.6: under the same latch a close and the panic flatten go as before."""
    world = pw.World(kek=Latch())
    answer = await pw.post(world, path, body=body)
    assert answer.status_code == status, answer.text
    assert world.pipeline.submitted and all(r.reduce_only for r in world.submitted())


def test_the_protective_routers_take_no_kek_latch() -> None:
    """C-2.6: cancel-all, the closes and the preview are composed with no latch to read."""
    for factory in (
        make_cancel_all_router,
        make_position_close_router,
        make_trade_group_preview_router,
    ):
        assert "kek" not in inspect.signature(factory).parameters


# --- setPositionLeverage ------------------------------------------------------------------------


async def test_set_position_leverage_latched_is_403_kek_unavailable_recorded_nothing_sent() -> None:
    world = lv.World(kek=Latch())
    answer = await lv.put(world, "owner")
    _refused_with_kek(answer)
    [(record, calls)] = world.records.written
    assert (record.action, record.outcome, record.reason, calls) == (
        LEVERAGE_ACTION, "denied", _CODE, 0
    )  # fmt: skip
    assert world.sent() == []


async def test_set_position_leverage_latched_the_kill_switch_still_answers_first() -> None:
    world = lv.World(kek=Latch())
    world.switches.refusal_of = TradingDisabled()
    answer = await lv.put(world, "owner")
    assert (answer.status_code, answer.json()["code"]) == (403, "trading_disabled")
    assert world.sent() == []


async def test_set_position_leverage_latched_a_replayed_key_is_its_stored_outcome() -> None:
    world, key = lv.World(), uuid4()
    first = await lv.put(world, "owner", key=key)
    assert first.status_code == 200, first.text
    sent = len(world.sent())
    world.kek = Latch()
    again = await lv.put(world, "owner", key=key)
    assert (again.status_code, again.headers["idempotency-replayed"]) == (200, "true")
    assert again.json() == first.json() and len(world.sent()) == sent


async def test_set_position_leverage_latched_an_unwritable_refusal_record_is_503() -> None:
    world = lv.World(kek=Latch())
    world.records.fail = True
    answer = await lv.put(world, "owner")
    assert (answer.status_code, answer.json()["code"]) == (503, "audit_unavailable")
    assert world.sent() == []


async def test_set_position_leverage_latched_a_foreign_position_is_404_as_before() -> None:
    world = lv.World(kek=Latch())
    answer = await lv.put(world, "scoped", lv.ON_B)
    assert (answer.status_code, answer.json()["code"]) == (404, "not_found")
    assert world.sent() == [] and world.records.written == []


async def test_set_position_leverage_latched_a_manager_is_forbidden() -> None:
    world = lv.World(kek=Latch())
    answer = await lv.put(world, "manager")
    assert (answer.status_code, answer.json()["code"]) == (403, "forbidden")
    assert world.records.written == []


# --- amendOrder and cancelOrder -----------------------------------------------------------------


@pytest.fixture
async def rig() -> AsyncIterator[SubmitRig]:
    async with sr.rigged() as built:
        built.store.seed_owner(am.OWNER)
        yield built


async def _amendable(rig: SubmitRig) -> tuple[er.World, Any]:
    world, row = await am.amendable(rig)
    world.kek, world.oms.route.switches = Latch(), orr.Switches()
    return world, row


async def test_amend_order_latched_a_raise_is_403_kek_unavailable_recorded_nothing_sent(
    rig: SubmitRig,
) -> None:
    world, row = await _amendable(rig)
    answer = await am.patch(world, row.id, am._RAISE)
    _refused_with_kek(answer)
    assert (world.actions()[-1], world.steps()[-1]) == (("orders.amend", _CODE), "kek")
    assert am.amends(rig) == []


@pytest.mark.parametrize(
    "body",
    [am._CUT, {"take_profit": {"unit": "price", "value": "64500"}},
     {"stop_loss": {"unit": "price", "value": "58500"}}],
    ids=["reduce", "tp_only", "sl_tighten"],
)  # fmt: skip
async def test_amend_order_latched_a_protective_amend_keeps_its_answer(
    rig: SubmitRig, body: dict[str, Any]
) -> None:
    """C-2.6: a reducing amend, a take-profit move and a tighter stop never meet the latch."""
    world, row = await _amendable(rig)
    answer = await am.patch(world, row.id, body)
    assert answer.status_code == 202, answer.text
    assert len(am.amends(rig)) == 1


async def test_amend_order_latched_a_viewer_is_forbidden(rig: SubmitRig) -> None:
    world, row = await _amendable(rig)
    answer = await am.patch(world, row.id, am._RAISE, who="viewer")
    assert (answer.status_code, answer.json()["code"]) == (403, "forbidden")
    assert am.amends(rig) == []


async def test_amend_order_latched_a_replay_of_an_accepted_key_is_its_stored_outcome(
    rig: SubmitRig,
) -> None:
    world, row = await _amendable(rig)
    world.kek = None
    first = await am.patch(world, row.id, am._RAISE)
    assert first.status_code == 202, first.text
    world.kek = Latch()
    again = await am.patch(world, row.id, am._RAISE)
    assert (again.status_code, again.headers["idempotency-replayed"]) == (202, "true")
    assert len(am.amends(rig)) == 1


async def test_amend_order_latched_an_unwritable_refusal_record_is_503_audit_unavailable(
    rig: SubmitRig,
) -> None:
    world, row = await _amendable(rig)
    rig.port.audits.refuse = RuntimeError("the audit WAL refused the record")
    answer = await am.patch(world, row.id, am._RAISE)
    assert (answer.status_code, answer.json()["code"]) == (503, "audit_unavailable")
    assert am.amends(rig) == []


async def test_amend_order_latched_an_ungranted_manager_meets_its_scope_answer_first(
    rig: SubmitRig,
) -> None:
    world, row = await _amendable(rig)
    answer = await am.patch(world, row.id, am._RAISE, who="ungranted")
    assert (answer.status_code, answer.json()["code"]) == (404, "not_found")
    assert am.amends(rig) == []


async def test_cancel_order_latched_keeps_its_answer() -> None:
    """C-2.6: a cancel never reads the latch."""
    world, _, row, _ = await er.scripted_world("submitted", "cancelled")
    world.kek = Latch()
    answer = await er.delete(world, row.id, key=uuid4())
    assert answer.status_code == 202, answer.text
