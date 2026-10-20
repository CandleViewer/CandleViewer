"""E35-T04: semantic validator scenarios and the compile/validate endpoints."""

from __future__ import annotations

import gc
import json
import statistics
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.rules import make_rules_router
from candleviewer.rules.compiler import compile_form, compile_graph, to_form_model, to_graph_model
from candleviewer.rules.ir import Rule, ir_hash
from candleviewer.rules.limits import LIMIT_CAPS
from candleviewer.rules.validator import estimate_evaluations_per_minute, validate_rule
from candleviewer.rules.vocabulary import default_registry

FIX = Path(__file__).parents[1] / "fixtures/rule_ir"
RULE_ID = "00000000-0000-4000-8000-000000000001"
REG = default_registry()
PRICE = {"metric": "price"}


def _rule(name: str = "form_simple_0.json", **over: Any) -> Rule:
    raw = json.loads((FIX / name).read_text(encoding="utf-8"), parse_float=str)
    return Rule.model_validate({**raw, **over})


def _codes(issues: list[Any]) -> list[str]:
    return [i.code for i in issues]


def _notify() -> dict[str, Any]:
    return {
        "node_id": "a1",
        "type": "send_notification",
        "params": {"channel": "ui", "severity": "info", "template": "x"},
    }


def _cmp(left: dict[str, Any], right: dict[str, Any], op: str = "gt") -> dict[str, Any]:
    return {"node_id": "c1", "op": op, "left": left, "right": right}


def _doc(cond: dict[str, Any], actions: list[dict[str, Any]] | None = None, **over: Any) -> Rule:
    return _rule(conditions=cond, actions=actions or [_notify()], **over)


def _jsonable(model: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(model, default=str))  # type: ignore[no-any-return]


def test_unit_incoherent_comparison_is_a_type_mismatch() -> None:
    """Scenario: Unit-incoherent comparison is a compile error"""
    res = validate_rule(_doc(_cmp({"metric": "atr", "params": {"n": 14}}, {"const": "5%"})), REG)
    assert not res.valid
    (e,) = [i for i in res.errors if i.code == "type_mismatch"]
    assert e.path == "conditions"
    assert "price" in e.message
    assert "pct" in e.message


def test_valid_rule_and_references() -> None:
    res = validate_rule(_doc(_cmp(PRICE, {"const": 5})), REG)
    assert res.valid
    assert res.referenced_variables == ["price"]
    assert res.referenced_actions == ["send_notification"]


def test_unknown_metric_and_operator_applicability() -> None:
    res = validate_rule(_doc(_cmp({"metric": "no_such_metric"}, {"const": 1})), REG)
    assert _codes(res.errors) == ["unknown_metric"]
    res = validate_rule(_doc(_cmp(PRICE, {"const": 1}, "is_true")), REG)
    assert "operator_not_applicable" in _codes(res.errors)
    res = validate_rule(_doc(_cmp(PRICE, {"metric": "rsi"})), REG)
    assert "type_mismatch" in _codes(res.errors)


def test_arithmetic_unit_mixing_and_set_membership() -> None:
    ar = {"node_id": "m1", "op": "add", "operands": [PRICE, {"metric": "rsi"}]}
    assert "type_mismatch" in _codes(validate_rule(_doc(_cmp(ar, {"const": 1})), REG).errors)
    no_set = {"node_id": "c1", "op": "in_set", "left": {"metric": "market_regime"}}
    assert "missing_action_param" in _codes(validate_rule(_doc(no_set), REG).errors)


def test_unreachable_branches() -> None:
    consts = validate_rule(_doc(_cmp({"const": 1}, {"const": 2})), REG)
    assert "unreachable_branch" in _codes(consts.warnings)
    btw = {
        "node_id": "c1",
        "op": "between",
        "left": PRICE,
        "right": {"const": 9},
        "right2": {"const": 1},
    }
    assert "unreachable_branch" in _codes(validate_rule(_doc(btw), REG).errors)
    nof = {"node_id": "g", "op": "n_of", "n": 3, "children": [_cmp(PRICE, {"const": 1})]}
    assert "unreachable_branch" in _codes(validate_rule(_doc(nof), REG).errors)


def test_missing_action_param() -> None:
    bad = {"node_id": "a1", "type": "send_notification", "params": {"channel": "ui"}}
    res = validate_rule(_doc(_cmp(PRICE, {"const": 1}), [bad]), REG)
    assert {i.path for i in res.errors} == {
        "actions[0].params.severity",
        "actions[0].params.template",
    }


def test_feedback_loop_guard() -> None:
    """Scenario: A self-retriggering rule is refused at save time"""
    place = {
        "node_id": "a1",
        "type": "place_order",
        "params": {"side": "buy", "order_type": "market", "qty_mode": "fixed"},
    }
    rule = _doc(_cmp(PRICE, {"const": 1}), [place], trigger={"type": "on_order_fill"})
    res = validate_rule(rule, REG, {"orders:write"})
    (e,) = [i for i in res.errors if i.code == "feedback_loop"]
    assert e.klass == "safety"
    assert "loop" in e.message
    me = {"node_id": "a1", "type": "enable_rule", "params": {"rule_id": RULE_ID}}
    assert "feedback_loop" in _codes(
        validate_rule(_doc(_cmp(PRICE, {"const": 1}), [me]), REG).errors
    )
    sig = {"node_id": "a1", "type": "emit_signal", "params": {"signal_name": "s"}}
    rule = _doc(_cmp(PRICE, {"const": 1}), [sig], trigger={"type": "on_signal"})
    assert "feedback_loop" in _codes(validate_rule(rule, REG).errors)


def test_warnings_do_not_block_saving_but_safety_blocks_arming() -> None:
    """Scenario: Warnings inform but do not block saving"""
    res = validate_rule(_doc(_cmp(PRICE, {"const": 1})), REG)
    (w,) = [i for i in res.warnings if i.code == "guard_missing"]
    assert res.valid
    assert w.path == "guards.cooldown_seconds"
    assert w.klass == "safety"
    assert res.blocks_arming
    ok = _doc(_cmp(PRICE, {"const": 1}), limits={"cooldown_ms": 5000})
    assert not validate_rule(ok, REG).blocks_arming


def test_require_native_stop_invariant() -> None:
    """Dedicated safety test: removing the native SL is never allowed."""
    for extra in ({"remove": True}, {"cancel": True}):
        a = {
            "node_id": "a1",
            "type": "modify_stop_loss",
            "params": {"mode": "absolute", "value": 1, **extra},
        }
        res = validate_rule(_doc(_cmp(PRICE, {"const": 1}), [a]), REG, {"*"})
        assert "native_stop_violation" in _codes(res.errors)
    params = {"side": "buy", "order_type": "market", "qty_mode": "x", "require_native_stop": False}
    po = {"node_id": "a1", "type": "place_order", "params": params}
    res = validate_rule(_doc(_cmp(PRICE, {"const": 1}), [po]), REG, {"*"})
    assert "native_stop_violation" in _codes(res.errors)


def test_only_tighten_false_needs_loosen_stop_permission() -> None:
    """Dedicated safety test: loosening a stop is permission gated."""
    params = {"mode": "absolute", "value": 1, "only_tighten": False}
    a = {"node_id": "a1", "type": "modify_stop_loss", "params": params}
    rule = _doc(_cmp(PRICE, {"const": 1}), [a])
    res = validate_rule(rule, REG, {"orders:write"})
    (e,) = [i for i in res.errors if i.code == "permission_required"]
    assert e.klass == "safety"
    granted = validate_rule(rule, REG, {"rules.loosen_stop"})
    assert "permission_required" not in _codes(granted.errors)
    tighten = {**a, "params": {"mode": "absolute", "value": 1}}
    assert validate_rule(_doc(_cmp(PRICE, {"const": 1}), [tighten]), REG).valid


def test_trigger_metric_validated() -> None:
    rule = _doc(_cmp(PRICE, {"const": 1}), trigger={"type": "on_metric_change", "metric": "ghost"})
    assert "unknown_metric" in _codes(validate_rule(rule, REG).errors)


@pytest.mark.parametrize(
    ("trigger", "expected"),
    [
        ({"type": "on_price_update"}, 600),
        ({"type": "on_price_update", "debounce_ms": 1000}, 60),
        ({"type": "on_bar_close", "timeframe": "1m"}, 1),
        ({"type": "on_timer", "interval_ms": 5000}, 12),
        ({"type": "on_schedule", "cron": "* * * * *"}, 1),
        ({"type": "on_order_fill"}, 60),
        ({"type": "on_order_fill", "debounce_ms": 2000}, 30),
    ],
)
def test_estimated_evaluations_per_minute(trigger: dict[str, Any], expected: int) -> None:
    assert estimate_evaluations_per_minute(_rule(trigger=trigger)) == expected


def test_high_frequency_performance_warning() -> None:
    res = validate_rule(_doc(_cmp(PRICE, {"const": 1})), REG)
    assert any(w.klass == "performance" for w in res.warnings)


class _P:
    def __init__(self, *perms: str) -> None:
        self.perms = set(perms)

    def has(self, p: str) -> bool:
        return p in self.perms


class _R:
    def __init__(self, p: _P) -> None:
        self.p = p

    def resolve(self, request: object) -> _P:
        return self.p


def _client(p: _P | None = None, empty: bool = False) -> TestClient:
    app = FastAPI()
    reg = None if empty else REG
    principal = _P("rules:read") if p is None else p
    app.include_router(make_rules_router(lambda: reg, principal_resolver=_R(principal)))
    return TestClient(app)


def _cycle_graph() -> tuple[dict[str, Any], list[str]]:
    g = _jsonable(to_graph_model(_rule("form_all_of_any_of.json")))
    b = [n["id"] for n in g["nodes"] if n["type"] == "boolean"]
    g["edges"] += [
        {"from": b[0], "to": b[1], "port": "in"},
        {"from": b[1], "to": b[0], "port": "in"},
    ]
    return g, b


def test_compile_endpoint_hash_equality_between_editors() -> None:
    ir = _rule("form_all_of_any_of.json")
    c, url = _client(), f"/rules/{RULE_ID}/compile"
    f = c.post(url, json={"editor": "form", "model": _jsonable(to_form_model(ir))})
    g = c.post(url, json={"editor": "graph", "model": _jsonable(to_graph_model(ir))})
    assert f.status_code == g.status_code == 200
    assert f.json()["ir_hash"] == g.json()["ir_hash"] == ir_hash(ir)
    assert isinstance(f.json()["issues"], list)


def test_compile_endpoint_cycle_is_422_rule_ir_invalid() -> None:
    g, b = _cycle_graph()
    r = _client().post(f"/rules/{RULE_ID}/compile", json={"editor": "graph", "model": g})
    body = r.json()
    assert r.status_code == 422
    assert body["code"] == "rule_ir_invalid"
    assert "ir" not in body
    assert body["errors"][0]["rule"] == "cycle_detected"
    assert body["errors"][0]["field"]
    assert set(b) <= set(body["errors"][0]["node_ids"])


def test_validate_endpoint_shapes_and_examples() -> None:
    ir = json.loads(_rule().model_dump_json())
    ir["limits"] = {}
    ir["actions"] = [_notify()]
    body = _client().post("/rules/validate", json={"ir": ir}).json()
    assert body["valid"] is True
    assert body["warnings"][0]["code"] == "guard_missing"
    assert body["warnings"][0]["path"] == "guards.cooldown_seconds"
    for key in (
        "errors",
        "referenced_variables",
        "referenced_actions",
        "estimated_evaluations_per_minute",
    ):
        assert key in body
    ir["conditions"]["left"] = {"metric": "atr"}
    ir["conditions"]["right"] = {"const": "5%"}
    bad = _client().post("/rules/validate", json={"ir": ir}).json()
    assert bad["valid"] is False
    assert bad["errors"][0]["code"] == "type_mismatch"
    broken = _client().post("/rules/validate", json={"ir": {"nope": 1}}).json()
    assert broken["valid"] is False
    assert broken["errors"][0]["code"] == "schema_error"


def test_endpoints_rbac_and_bad_requests() -> None:
    for path in ("/rules/validate", f"/rules/{RULE_ID}/compile"):
        assert _client(_P("orders:read")).post(path, json={}).status_code == 403
        assert _client().post(path, content=b"not json").status_code == 400
        assert _client().post(path, json={}).status_code == 400
        assert _client(empty=True).post(path, json={}).status_code == 503
    bad = {"editor": "x", "model": {}}
    assert _client().post(f"/rules/{RULE_ID}/compile", json=bad).status_code == 400


def test_compile_round_trip_match_and_divergence_reported_never_reconciled() -> None:
    ir = _rule("form_all_of_any_of.json")
    seen: list[tuple[str, int]] = []
    app = FastAPI()
    app.include_router(
        make_rules_router(
            lambda: REG,
            principal_resolver=_R(_P("rules:read")),
            on_divergence=lambda e, n: seen.append((e, n)),
        )
    )
    c, url = TestClient(app), f"/rules/{RULE_ID}/compile"
    form, graph = _jsonable(to_form_model(ir)), _jsonable(to_graph_model(ir))
    ok = c.post(url, json={"editor": "form", "model": form, "counterpart_model": graph}).json()
    assert ok["round_trip"] == {"match": True, "diff": []}
    other = _rule("form_simple_0.json")
    bad = c.post(
        url,
        json={
            "editor": "form",
            "model": form,
            "counterpart_model": _jsonable(to_graph_model(other)),
        },
    ).json()
    assert bad["round_trip"]["match"] is False and bad["round_trip"]["diff"]
    assert bad["ir_hash"] == ir_hash(ir)  # the submitted model is untouched, never reconciled
    assert seen and seen[0][0] == "form"


def test_compile_blocks_arming_flag_end_to_end() -> None:
    ir = _rule("form_simple_0.json")
    r = (
        _client()
        .post(
            f"/rules/{RULE_ID}/compile",
            json={"editor": "form", "model": _jsonable(to_form_model(ir))},
        )
        .json()
    )
    assert r["blocks_arming"] == any(
        i["severity"] == "error" or i["class"] == "safety" for i in r["issues"]
    )


def _big_rule(n: int) -> Rule:
    """~n leaf comparisons spread over groups of 25 (the all_of fan-out cap is 32)."""
    groups = [
        {
            "node_id": f"g{g}",
            "op": "any_of",
            "children": [
                {**_cmp(PRICE, {"const": g * 25 + i + 1}), "node_id": f"c{g}_{i}"}
                for i in range(25)
            ],
        }
        for g in range(n // 25)
    ]
    return _doc({"node_id": "root", "op": "all_of", "children": groups})


# SCR-081: compile + round-trip diff within 500 ms p95 for a 100-node rule. A budget held by one
# shot measures a runner's worst moment, not the code: merge-group run 39406730343 read 834 ms for
# a compile that takes a few ms on a laptop. Each budget below is held by the median of this many
# timed calls; the count is odd and large enough that three stalled samples cannot move it.
_PERF_SAMPLES = 7


def _sample_ms(
    work: Callable[[], object],
    samples: int = _PERF_SAMPLES,
    clock: Callable[[], float] = time.perf_counter,
) -> list[float]:
    """The wall time in ms of each of `samples` calls to `work`, after one untimed warm-up call.

    The cyclic GC is off while timing, as `timeit` does it. In the `py-perf` job pytest holds over
    a million tracked objects from collecting the whole tree; a full GC pass over them costs about
    a second on a laptop and lands in whichever call crosses the collector's threshold. Collecting
    first pays that pass outside the timed calls instead of leaving it pending for the next test.
    """
    work()
    gc.collect()
    was_enabled = gc.isenabled()
    gc.disable()
    timings: list[float] = []
    try:
        for _ in range(samples):
            started = clock()
            work()
            timings.append((clock() - started) * 1000)
    finally:
        if was_enabled:
            gc.enable()
    return timings


def _assert_median_within(
    work: Callable[[], object],
    budget_ms: float,
    clock: Callable[[], float] = time.perf_counter,
) -> None:
    """The median of the timed calls is inside the budget: one stalled sample (a runner pause)
    cannot fail it, a slowdown that holds for most samples does."""
    timings = _sample_ms(work, clock=clock)
    median = statistics.median(timings)
    message = (
        f"median {median:.1f} ms of {len(timings)} runs, budget {budget_ms} ms: {sorted(timings)}"
    )
    assert median < budget_ms, message


@pytest.mark.perf
def test_perf_100_node_compile_and_validate_budget() -> None:
    rule = _big_rule(100)
    g, f = _jsonable(to_graph_model(rule)), _jsonable(to_form_model(rule))

    def compile_both() -> None:
        compile_graph(g)
        compile_form(f)

    _assert_median_within(compile_both, budget_ms=500)
    _assert_median_within(lambda: validate_rule(rule, REG, set()), budget_ms=100)


class _StepClock:
    """A fake `perf_counter`: the two reads around each timed call are `durations_ms[i]` apart."""

    def __init__(self, durations_ms: Sequence[float]) -> None:
        self._durations_ms = iter(durations_ms)
        self._now = 0.0
        self._closing = False

    def __call__(self) -> float:
        if self._closing:
            self._now += next(self._durations_ms) / 1000
        self._closing = not self._closing
        return self._now


def _samples_with(stalled: int) -> _StepClock:
    """`_PERF_SAMPLES` durations: `stalled` of them 834 ms (the CI reading), the rest 6 ms."""
    return _StepClock([834.0] * stalled + [6.0] * (_PERF_SAMPLES - stalled))


def _set_gc(enabled: bool) -> None:
    if enabled:
        gc.enable()
    else:
        gc.disable()


@pytest.fixture
def gc_spy(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """`gc.collect` recorded in the yielded list instead of run (a real pass over the lane's heap
    costs far more than these tests), and the collector left on or off as the test found it."""
    events: list[str] = []

    def collect(*_: int) -> int:
        events.append("collect")
        return 0

    monkeypatch.setattr(gc, "collect", collect)
    was_enabled = gc.isenabled()
    yield events
    _set_gc(was_enabled)


@pytest.mark.usefixtures("gc_spy")
@pytest.mark.parametrize("stalled", [0, 1, _PERF_SAMPLES // 2])
def test_median_budget_holds_while_a_minority_of_samples_stall(stalled: int) -> None:
    _assert_median_within(lambda: None, budget_ms=500, clock=_samples_with(stalled))


@pytest.mark.usefixtures("gc_spy")
@pytest.mark.parametrize("stalled", [_PERF_SAMPLES // 2 + 1, _PERF_SAMPLES])
def test_median_budget_fails_once_most_samples_exceed_it(stalled: int) -> None:
    failure = rf"median 834\.0 ms of {_PERF_SAMPLES} runs, budget 500 ms"
    with pytest.raises(AssertionError, match=failure):
        _assert_median_within(lambda: None, budget_ms=500, clock=_samples_with(stalled))


@pytest.mark.usefixtures("gc_spy")
def test_sample_ms_leaves_the_warm_up_call_untimed() -> None:
    calls: list[None] = []

    def work() -> None:
        calls.append(None)

    timings = _sample_ms(work, samples=3, clock=_StepClock([5, 6, 7]))

    assert len(calls) == 4
    assert timings == pytest.approx([5, 6, 7])


@pytest.mark.parametrize("was_enabled", [True, False])
def test_sample_ms_warms_up_then_collects_then_times_with_the_gc_off(
    gc_spy: list[str], was_enabled: bool
) -> None:
    _set_gc(was_enabled)

    def work() -> None:
        gc_spy.append("work, gc on" if gc.isenabled() else "work, gc off")

    _sample_ms(work, samples=2, clock=_StepClock([1, 1]))

    warm_up = "work, gc on" if was_enabled else "work, gc off"
    assert gc_spy == [warm_up, "collect", "work, gc off", "work, gc off"]
    assert gc.isenabled() is was_enabled


def test_sample_ms_puts_the_gc_back_when_a_timed_call_raises(gc_spy: list[str]) -> None:
    _set_gc(True)

    def work() -> None:
        gc_spy.append("work")
        if gc_spy.count("work") == 2:  # the first timed call; the warm-up call was the first
            raise RuntimeError("timed call failed")

    with pytest.raises(RuntimeError, match="timed call failed"):
        _sample_ms(work, samples=3, clock=_StepClock([1, 1, 1]))

    assert gc.isenabled()


def test_validate_and_compile_report_a_limit_above_its_cap() -> None:
    """#3232: the editors see the action-budget cap before a save refuses it."""
    hour = "max_fires_per_hour"
    rule = _rule(limits={hour: LIMIT_CAPS[hour] + 1}, actions=[_notify()])
    body = _client().post("/rules/validate", json={"ir": _jsonable(rule.model_dump())}).json()
    assert body["valid"] is False
    assert [e["path"] for e in body["errors"]] == ["limits.max_fires_per_hour"]
    model = _jsonable(to_form_model(rule))
    out = _client().post(f"/rules/{RULE_ID}/compile", json={"editor": "form", "model": model})
    assert out.json()["blocks_arming"] is True
    errors = [i["path"] for i in out.json()["issues"] if i["severity"] == "error"]
    assert errors == ["limits.max_fires_per_hour"]
