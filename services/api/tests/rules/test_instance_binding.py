"""E35-T15 PR 1 (#5745): the scope instance binds the refs a rule leaves open; a tick carries its
timeframe.

24 §11.2: a `MetricRef` with `symbol: None` reads the scope symbol, so each instance of a
multi-symbol rule reads its own key (E6), and the key a producer writes (`metric_key`) never changes
shape. A bar close names its timeframe, so it reaches only the `on_bar_close` rules of it.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.rules.evaluator import Evaluator, MetricValue, SnapshotBuilder, metric_key
from candleviewer.rules.evaluator.engine import EvaluationResult, parse_instance, scope_instance
from candleviewer.rules.evaluator.snapshot import ScopeBindingError, bound_ref
from candleviewer.rules.ir.models import MetricRef, Rule
from candleviewer.rules.manager import EvaluableRule
from candleviewer.rules.runner import EvalTick, PushedMetricSource, RuleEvaluationRunner
from candleviewer.rules.scope import instance_ref
from candleviewer.rules.service import RulesService
from candleviewer.rules.vocabulary.metrics import DEFAULT_DESCRIPTORS
from tests.rules.test_evaluator import Clock

#: The production scope table: `RulesService` builds it from the same registry descriptors.
SCOPES = {d.name: d.scope for d in DEFAULT_DESCRIPTORS}
A = uuid.UUID(int=0xA)
B = uuid.UUID(int=0xB)
NOW = 1_000_000


def ref(metric: str, **kw: Any) -> MetricRef:
    return MetricRef.model_validate({"metric": metric, **kw})


def rule(
    metric: dict[str, Any],
    *,
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT"),
    accounts: tuple[uuid.UUID, ...] = (),
    trigger: dict[str, Any] | None = None,
    rid: int = 7,
) -> Rule:
    scope: dict[str, Any] = {"level": "symbol", "symbols": list(symbols)}
    if accounts:
        scope = {**scope, "level": "account", "account_ids": [str(a) for a in accounts]}
    return Rule.model_validate(
        {
            "rule_id": str(uuid.UUID(int=rid)), "version": 1, "name": f"r{rid}", "enabled": True,
            "mode": "simulate", "scope": scope,
            "trigger": trigger or {"type": "on_price_update"},
            "conditions": {"node_id": "c", "op": "gt", "left": metric, "right": {"const": 100}},
            "actions": [{"node_id": "a1", "type": "send_notification", "params": {}}],
            "limits": {"cooldown_ms": 0},
        }
    )  # fmt: skip


def evaluator(r: Rule, src: PushedMetricSource) -> Evaluator:
    clk = Clock()
    clk.t = NOW
    return Evaluator(r, SnapshotBuilder(src, SCOPES), clk, clk)


# --- bound_ref ----------------------------------------------------------------------------------


def test_bound_ref_symbol_scope_without_symbol_takes_instance_symbol() -> None:
    assert bound_ref(ref("price"), "ETHUSDT", str(A), SCOPES) == ref("price", symbol="ETHUSDT")


def test_bound_ref_authored_symbol_is_kept() -> None:
    authored = ref("price", symbol="BTCUSDT")
    assert bound_ref(authored, "ETHUSDT", None, SCOPES) is authored


def test_bound_ref_account_scope_takes_instance_account_only() -> None:
    assert bound_ref(ref("account_equity"), "BTCUSDT", str(A), SCOPES) == ref(
        "account_equity", account_id=str(A)
    )


def test_bound_ref_position_scope_takes_symbol_and_account() -> None:
    assert bound_ref(ref("position_qty"), "BTCUSDT", A, SCOPES) == ref(
        "position_qty", symbol="BTCUSDT", account_id=str(A)
    )


def test_bound_ref_authored_same_account_is_kept() -> None:
    authored = ref("account_equity", account_id=str(A))
    assert bound_ref(authored, None, str(A), SCOPES) is authored


@pytest.mark.parametrize("metric", ["account_equity", "position_qty", "price", "replay_speed"])
def test_bound_ref_authored_foreign_account_fails_closed(metric: str) -> None:
    """IDOR: an instance of account A never reads a ref the rule pinned to account B (C-12.4)."""
    with pytest.raises(ScopeBindingError):
        bound_ref(ref(metric, account_id=str(B)), "BTCUSDT", str(A), SCOPES)


@pytest.mark.parametrize("account", [None, "*"])
def test_bound_ref_pinned_account_without_instance_account_fails_closed(
    account: str | None,
) -> None:
    """With a scope table, an instance with no open account has none a pinned ref can match."""
    with pytest.raises(ScopeBindingError):
        bound_ref(ref("account_equity", account_id=str(B)), "BTCUSDT", account, SCOPES)


@pytest.mark.parametrize("account", [None, "*"])
def test_bound_ref_pinned_account_without_scope_table_is_kept(account: str | None) -> None:
    """The alert evaluator's reads (no scope table) bind nothing and compare no absent account."""
    authored = ref("account_equity", account_id=str(B))
    assert bound_ref(authored, "BTCUSDT", account, {}) is authored


def test_bound_ref_pinned_foreign_account_without_scope_table_fails_closed() -> None:
    with pytest.raises(ScopeBindingError):
        bound_ref(ref("account_equity", account_id=str(B)), "BTCUSDT", str(A), {})


def test_bound_ref_non_uuid_instance_account_fails_closed() -> None:
    with pytest.raises(ScopeBindingError):
        bound_ref(ref("account_equity"), "BTCUSDT", "acct-3f2a", SCOPES)


def test_bound_ref_non_uuid_instance_account_symbol_ref_binds_symbol() -> None:
    assert bound_ref(ref("price"), "BTCUSDT", "acct-3f2a", SCOPES) == ref("price", symbol="BTCUSDT")


@pytest.mark.parametrize("metric", ["replay_speed", "replay_position_ms", "replay_integrity_ok"])
def test_bound_ref_global_scope_binds_nothing(metric: str) -> None:
    authored = ref(metric)
    assert bound_ref(authored, "BTCUSDT", str(A), SCOPES) is authored


@pytest.mark.parametrize("metric", ["price", "account_equity", "position_qty"])
def test_bound_ref_wildcard_instance_binds_nothing(metric: str) -> None:
    authored = ref(metric)
    assert bound_ref(authored, "*", "*", SCOPES) is authored
    assert bound_ref(authored, None, None, SCOPES) is authored


def test_bound_ref_unregistered_metric_binds_nothing() -> None:
    authored = ref("not_a_registry_metric")
    assert bound_ref(authored, "BTCUSDT", str(A), SCOPES) is authored


_NAMES = st.sampled_from([d.name for d in DEFAULT_DESCRIPTORS])
_SYMS = st.sampled_from([None, "BTCUSDT", "ETHUSDT"])
_ACCTS = st.sampled_from([None, A, B])
_TFS = st.sampled_from([None, "1m", "1h"])
_PARAMS = st.dictionaries(
    st.sampled_from(["n", "source", "window_ms"]),
    st.one_of(st.integers(-5, 500), st.sampled_from(["last", "mark", "0.5"])),
    max_size=2,
)


def _old_key(r: MetricRef) -> str:
    """The key format on main before E35-T15, spelled out so a change to it fails here."""
    params = json.dumps(r.params, sort_keys=True, separators=(",", ":"), default=str)
    return f"{r.metric}{params}|{r.symbol or ''}|{r.account_id or ''}|{r.timeframe or ''}"


@given(_NAMES, _PARAMS, _SYMS, _ACCTS, _TFS)
def test_metric_key_existing_refs_byte_identical(
    name: str, params: dict[str, Any], sym: str | None, acct: uuid.UUID | None, tf: str | None
) -> None:
    r = MetricRef.model_validate(
        {"metric": name, "params": params, "symbol": sym, "account_id": acct, "timeframe": tf}
    )
    assert metric_key(r) == _old_key(r)
    if acct is not None:  # a pinned account no instance account can match: refused (m-3)
        with pytest.raises(ScopeBindingError):
            bound_ref(r, None, None, SCOPES)
        r = r.model_copy(update={"account_id": None})
    assert bound_ref(r, None, None, SCOPES) is r  # no instance: the authored key, as before
    snap = SnapshotBuilder(PushedMetricSource(), SCOPES).build([r], NOW)
    assert list(snap.values) == [_old_key(r)] and not snap.bound
    unscoped = SnapshotBuilder(PushedMetricSource()).build([r], NOW)  # the alert evaluator's
    assert list(unscoped.values) == [_old_key(r)] and not unscoped.bound


def test_metric_key_format_pinned() -> None:
    r = ref("price", params={"n": 14, "source": "mark"}, symbol="BTCUSDT", timeframe="1m")
    assert metric_key(r) == 'price{"n":14,"source":"mark"}|BTCUSDT||1m'


# --- the snapshot remembers its binding -------------------------------------------------------


def test_snapshot_get_authored_ref_finds_bound_key() -> None:
    src = PushedMetricSource()
    src.push(ref("price", symbol="ETHUSDT"), Decimal(42), NOW)
    authored = ref("price")
    snap = SnapshotBuilder(src, SCOPES).build([authored], NOW, symbol="ETHUSDT", account=str(A))
    assert snap.get(authored).value == Decimal(42)
    assert list(snap.values) == [metric_key(ref("price", symbol="ETHUSDT"))]
    assert dict(snap.bound) == {metric_key(authored): metric_key(ref("price", symbol="ETHUSDT"))}


def test_snapshot_builder_without_scopes_binds_nothing() -> None:
    """The alert evaluator's builder takes no scope table: its refs are read as authored."""
    authored = ref("price")
    snap = SnapshotBuilder(PushedMetricSource()).build([authored], NOW, symbol="BTCUSDT")
    assert list(snap.values) == [metric_key(authored)] and not snap.bound


def test_snapshot_build_two_instances_reads_each_key_once() -> None:
    src = PushedMetricSource()
    builder = SnapshotBuilder(src, SCOPES)
    authored = ref("price")
    builder.build([authored], NOW, symbol="BTCUSDT")
    builder.build([authored], NOW, symbol="ETHUSDT")
    builder.build([authored], NOW, symbol="BTCUSDT")
    assert builder.computations == 2 and builder.cache_hits == 1


# --- the evaluator binds its instance (E6) ------------------------------------------------------


def _push_prices(src: PushedMetricSource, **by_symbol: int) -> None:
    for sym, price in by_symbol.items():
        src.push(ref("price", symbol=sym), Decimal(price), NOW)


def test_evaluator_symbolless_ref_two_symbols_each_reads_own_symbol() -> None:
    """Scenario: Each scope instance reads its own symbol."""
    src = PushedMetricSource()
    _push_prices(src, BTCUSDT=150, ETHUSDT=50)
    ev = evaluator(rule({"metric": "price"}), src)
    btc = ev.on_trigger(scope_instance("BTCUSDT", None), "on_price_update")
    eth = ev.on_trigger(scope_instance("ETHUSDT", None), "on_price_update")
    assert btc.fired and btc.metric_values == {"price": Decimal(150)}
    assert not eth.fired and eth.metric_values == {"price": Decimal(50)}


def test_evaluator_symbolless_ref_shared_key_not_read_by_instances() -> None:
    """The old shared read: before E35-T15 both instances read the one symbol-less key (150) and
    both fired; now the instances read their own keys and only BTCUSDT's 150 fires."""
    src = PushedMetricSource()
    src.push(ref("price"), Decimal(150), NOW)  # the key every instance read before the binding
    _push_prices(src, BTCUSDT=150, ETHUSDT=50)
    ev = evaluator(rule({"metric": "price"}), src)
    fired = {
        sym: ev.on_trigger(scope_instance(sym, None), "on_price_update").fired
        for sym in ("BTCUSDT", "ETHUSDT")
    }
    assert fired == {"BTCUSDT": True, "ETHUSDT": False}


def test_evaluator_unpushed_instance_symbol_skips_stale() -> None:
    src = PushedMetricSource()
    _push_prices(src, BTCUSDT=150)
    res = evaluator(rule({"metric": "price"}), src).on_trigger("ETHUSDT@*", "on_price_update")
    assert not res.fired and res.skipped_reason == "stale_data"


def test_evaluator_authored_symbol_ref_reads_authored_key() -> None:
    src = PushedMetricSource()
    _push_prices(src, BTCUSDT=150, ETHUSDT=50)
    ev = evaluator(rule({"metric": "price", "symbol": "BTCUSDT"}), src)
    assert ev.on_trigger("ETHUSDT@*", "on_price_update").fired  # pinned to BTCUSDT


def test_evaluator_account_scoped_ref_binds_instance_account() -> None:
    src = PushedMetricSource()
    src.push(ref("account_equity", account_id=str(A)), Decimal(500), NOW)
    src.push(ref("account_equity", account_id=str(B)), Decimal(5), NOW)
    ev = evaluator(rule({"metric": "account_equity"}, symbols=("BTCUSDT",), accounts=(A, B)), src)
    assert ev.on_trigger(scope_instance("BTCUSDT", str(A)), "on_price_update").fired
    assert not ev.on_trigger(scope_instance("BTCUSDT", str(B)), "on_price_update").fired


class _Recording(PushedMetricSource):
    """A pushed source that records the key of every read."""

    def __init__(self) -> None:
        super().__init__()
        self.asked: list[str] = []

    def read(self, ref: MetricRef) -> MetricValue:
        self.asked.append(metric_key(ref))
        return super().read(ref)


def test_evaluator_foreign_authored_account_skips_scope() -> None:
    """IDOR: a rule scoped to A that pins B's equity reads nothing and is not an error (C-12.4):
    the pinned key is never asked of the source, and the skip is a binding refusal."""
    src = _Recording()
    pinned_ref = ref("account_equity", account_id=str(B))
    src.push(pinned_ref, Decimal(500), NOW)
    pinned = {"metric": "account_equity", "account_id": str(B)}
    ev = evaluator(rule(pinned, symbols=("BTCUSDT",), accounts=(A,)), src)
    res = ev.on_trigger(scope_instance("BTCUSDT", str(A)), "on_price_update")
    assert not res.fired and res.skipped_reason == "scope" and res.error is None
    assert res.binding_refused and res.metric_values == {} and ev.stats.errors == 0
    assert metric_key(pinned_ref) not in src.asked and src.asked == []


def test_evaluator_gate_scope_skip_is_not_a_binding_refusal() -> None:
    clk = Clock()
    clk.t = NOW
    r = rule({"metric": "price"}, symbols=("BTCUSDT",), accounts=(A,))
    ev = Evaluator(r, SnapshotBuilder(_Recording(), SCOPES), clk, clk, scope_gate=lambda _: "x")
    res = ev.on_trigger(scope_instance("BTCUSDT", str(A)), "on_price_update")
    assert res.skipped_reason == "scope" and not res.binding_refused


def test_evaluator_non_uuid_instance_account_skips_scope_not_error() -> None:
    src = PushedMetricSource()
    ev = evaluator(rule({"metric": "account_equity"}, symbols=("BTCUSDT",), accounts=(A,)), src)
    res = ev.on_trigger("BTCUSDT@acct-3f2a", "on_price_update")
    assert res.skipped_reason == "scope" and res.error is None and ev.stats.errors == 0


def test_evaluator_global_scope_ref_reads_unbound_key() -> None:
    src = PushedMetricSource()
    src.push(ref("replay_speed"), Decimal(200), NOW)
    ev = evaluator(rule({"metric": "replay_speed"}, symbols=("BTCUSDT",), accounts=(A,)), src)
    assert ev.on_trigger(scope_instance("BTCUSDT", str(A)), "on_price_update").fired


def test_evaluator_wildcard_instance_reads_unbound_key() -> None:
    src = PushedMetricSource()
    src.push(ref("price"), Decimal(150), NOW)
    ev = evaluator(rule({"metric": "price"}, symbols=()), src)
    assert ev.on_trigger(scope_instance(None, None), "on_price_update").fired


# --- the instance string ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("symbol", "account"), [("BTCUSDT", str(A)), ("BTCUSDT", None), (None, str(A)), (None, None)]
)
def test_parse_instance_round_trips_scope_instance(symbol: str | None, account: str | None) -> None:
    key = scope_instance(symbol, account)
    assert parse_instance(key) == (symbol, account)
    assert scope_instance(*parse_instance(key)) == key


@pytest.mark.parametrize(
    ("key", "symbol", "account"),
    [
        (scope_instance("BTCUSDT", str(A)), "BTCUSDT", A),
        (scope_instance(None, str(A)), None, A),
        (scope_instance("BTCUSDT", None), "BTCUSDT", None),
        ("BTCUSDT@", "BTCUSDT", None),  # never produced: an empty part is no account
    ],
)
def test_instance_ref_parses_the_instance_key(
    key: str, symbol: str | None, account: uuid.UUID | None
) -> None:
    got = instance_ref(key)
    assert (got.key, got.symbol, got.account_id) == (key, symbol, account)


def test_instance_ref_non_uuid_account_raises() -> None:
    """As the hand-split did: a key `scope_instance` never builds from a rule's account ids."""
    with pytest.raises(ValueError):
        instance_ref("BTCUSDT@acct-3f2a")


# --- a tick carries its timeframe ---------------------------------------------------------------


def _bar_rule(tf: str, rid: int) -> EvaluableRule:
    r = rule(
        {"metric": "price"}, symbols=("BTCUSDT",),
        trigger={"type": "on_bar_close", "timeframe": tf}, rid=rid,
    )  # fmt: skip
    return EvaluableRule(r, "simulate", None, f"v{rid}", f"h{rid}")


async def _evaluated(items: list[EvaluableRule], tick: EvalTick) -> list[str]:
    """The rule names the runner evaluated for `tick`."""
    seen: list[str] = []

    async def _rules() -> list[EvaluableRule]:
        return items

    def _on_result(res: EvaluationResult) -> None:
        seen.append(next(i.rule.name for i in items if str(i.rule.rule_id) == res.rule_id))

    src = PushedMetricSource()
    _push_prices(src, BTCUSDT=150)

    def _factory(r: Rule, snaps: SnapshotBuilder) -> Evaluator:
        clk = Clock()
        clk.t = NOW
        return Evaluator(r, snaps, clk, clk, on_result=_on_result)

    runner = RuleEvaluationRunner(_rules, SnapshotBuilder(src, SCOPES), _factory, _on_result)
    await runner.process(tick)
    return sorted(seen)


async def test_runner_bar_close_tick_evaluates_only_own_timeframe() -> None:
    """Scenario: A bar-close tick reaches only the rules of its timeframe."""
    items = [_bar_rule("1h", 1), _bar_rule("1m", 2)]
    assert await _evaluated(items, EvalTick("on_bar_close", "BTCUSDT", "1m")) == ["r2"]
    assert await _evaluated(items, EvalTick("on_bar_close", "BTCUSDT", "1h")) == ["r1"]


async def test_runner_bar_close_tick_without_timeframe_matches_nothing() -> None:
    """Fail closed: a bar close that names no timeframe runs no bar-close rule (missing ->
    skipped), whatever the rules' timeframes."""
    items = [_bar_rule("1h", 1), _bar_rule("1m", 2)]
    assert await _evaluated(items, EvalTick("on_bar_close", "BTCUSDT")) == []


async def test_runner_other_trigger_tick_without_timeframe_still_matches() -> None:
    items = [EvaluableRule(rule({"metric": "price"}, symbols=("BTCUSDT",)), "simulate", None, "v",
                           "h")]  # fmt: skip
    assert await _evaluated(items, EvalTick("on_price_update", "BTCUSDT")) == ["r7"]


async def test_runner_other_trigger_tick_with_timeframe_still_matches() -> None:
    items = [EvaluableRule(rule({"metric": "price"}, symbols=("BTCUSDT",)), "simulate", None, "v",
                           "h")]  # fmt: skip
    assert await _evaluated(items, EvalTick("on_price_update", "BTCUSDT", "1m")) == ["r7"]


class _Runner:
    def __init__(self) -> None:
        self.ticks: list[EvalTick] = []

    def submit(self, tick: EvalTick) -> None:
        self.ticks.append(tick)


@pytest.mark.parametrize(
    ("args", "tick"),
    [
        (("on_bar_close", "BTCUSDT", "1m"), EvalTick("on_bar_close", "BTCUSDT", "1m")),
        (("on_price_update", "BTCUSDT"), EvalTick("on_price_update", "BTCUSDT", None)),
    ],
)
def test_service_submit_tick_timeframe_reaches_runner(
    args: tuple[Any, ...], tick: EvalTick
) -> None:
    svc = RulesService()
    fake = _Runner()
    svc.runner = fake  # type: ignore[assignment]  # a recording stand-in for the runner
    assert svc.submit_tick(*args)
    assert fake.ticks == [tick]


def test_metric_value_unchanged_for_unpushed_bound_ref() -> None:
    """A bound ref nobody pushed reads warmup at ts 0, as an unbound one always did (E3)."""
    got = PushedMetricSource().read(bound_ref(ref("price"), "BTCUSDT", None, SCOPES))
    assert got == MetricValue(None, 0, 0, "warmup")


async def test_runner_rule_without_symbols_binds_ticking_symbol() -> None:
    """A rule that lists no symbol runs on the ticking symbol (`_instances`) and reads its key."""
    items = [EvaluableRule(rule({"metric": "price"}, symbols=()), "simulate", None, "v", "h")]
    assert await _evaluated(items, EvalTick("on_price_update", "BTCUSDT")) == ["r7"]


def test_runner_default_error_hook_logs_class_without_values() -> None:
    async def _rules() -> list[EvaluableRule]:
        return []

    def _factory(r: Rule, snaps: SnapshotBuilder) -> Evaluator:
        raise AssertionError("not reached")

    runner = RuleEvaluationRunner(_rules, SnapshotBuilder(PushedMetricSource()), _factory, print)
    with capture_logs() as logs:
        runner._on_error(RuntimeError("boom"))
    assert [e["event"] for e in logs] == ["rule evaluation failed"]
