"""E37-X01 (#1073): the presentation block carries no meaning to the runtime (E35-FR-05's test).

The block is a rule's `graph_layout` and `editor` (`PRESENTATION_KEYS`; `24-internal-schemas.md`
section 11.4, guarantees 3 and 4). For the ticket's scenario 2 there are four proofs: every rule of
the corpus evaluates the same with any block and a flipped `editor`; no module that decides what
runs reads the block; an account key inside it makes a Manager's save refuse; and it adds no
runtime target. The clocks are injected and hypothesis runs one fixed seed.
"""

from __future__ import annotations

import ast
import hashlib
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest
from hypothesis import HealthCheck, example, given, seed, settings
from hypothesis import strategies as st

from candleviewer.rules.evaluator import (
    EvaluationResult,
    Evaluator,
    MetricValue,
    SnapshotBuilder,
    metric_key,
)
from candleviewer.rules.evaluator.engine import scope_instance
from candleviewer.rules.ir import MetricRef, Rule, parse_ir_json
from candleviewer.rules.ir.canonical import PRESENTATION_KEYS
from candleviewer.rules.manager import (
    Actor,
    EvaluableRule,
    InMemoryRuleStore,
    RuleError,
    RulesManager,
)
from candleviewer.rules.runner import EvalTick, PushedMetricSource, RuleEvaluationRunner
from candleviewer.rules.vocabulary import default_registry
from tests.rules.roundtrip.chain import COMPILER_LAYOUT_KEYS

_API: Final = Path(__file__).resolve().parents[3]
_CV: Final = _API / "candleviewer"
#: What decides what runs: the runtime that schedules, evaluates, resolves, gates and executes a
#: stored rule, the manager's work list and arming facts, the validator the arming gate reads, the
#: store, the bridge to the OMS and the alert path. A directory is read whole, subpackages too.
_RUNTIME: Final = """
    rules/evaluator rules/executor rules/runner.py rules/service.py rules/scope.py
    rules/scope_state.py rules/limits.py rules/lifecycle.py rules/arming.py rules/manager.py
    rules/validator.py rules_store_pg.py rules_oms_wiring.py alerts/compiler.py alerts/evaluator.py
""".split()
#: The modules the scan reads, pinned: one added under, moved out of or dropped from `_RUNTIME`'s
#: places fails the scan until it is named here.
_SCANNED: Final = {
    f"rules/{name}.py"
    for name in """
        evaluator/__init__ evaluator/engine evaluator/nodes evaluator/snapshot executor/__init__
        executor/dispatch executor/engine executor/handlers executor/keys executor/metrics
        executor/ports executor/results executor/writeahead runner service scope scope_state
        limits lifecycle arming manager validator
    """.split()
} | {"rules_store_pg.py", "rules_oms_wiring.py", "alerts/compiler.py", "alerts/evaluator.py"}
#: The calls that read the key they are given: `getattr(r, k)`, `r.get(k)`, `attrgetter(k)`...
_READERS: Final = frozenset(
    {"getattr", "hasattr", "get", "pop", "setdefault", "attrgetter", "itemgetter", "__getitem__"}
)
_CORPUS: Final = tuple(
    parse_ir_json(path.read_text(encoding="utf-8"))
    for path in sorted((_API / "tests/fixtures/rule_corpus").glob("[0-9][0-9]_*.json"))
)
_A, _B = str(uuid.UUID(int=10)), str(uuid.UUID(int=12))  # the Manager is granted A, never B
_MANAGER: Final = Actor("u2", "s2", frozenset({"rules:read", "rules:write"}), frozenset({_A}))
#: Account keys as the account walker reads them (`ir/accounts.py`), each naming B.
_KEYED: Final[tuple[dict[str, Any], ...]] = (
    {"account_id": _B},
    {"account_ids": [_B]},
    {"exchange_account_ids": [_B]},
    {"notes": [{"accountId": _B}]},
    {"by_account_ids": {_B: "kept"}},
)
#: Keys a reader of the block might act on: the walker's account keys and the server's own keys.
_TRAPS: Final = (*(key for keyed in _KEYED for key in keyed), "accountId", *COMPILER_LAYOUT_KEYS)
#: Values past what a reader of the block might trust: past 2^53, 2^61 and a signed 64-bit
#: integer, a finite float, a null, a 64 KiB string and a nested object.
_EXTREMES: Final = (2**53 + 1, 2**61, -(2**61), 10**19, -(10**19), 0.1, None, "x" * 65_536)
_EXTREME: Final = {f"x{n}": v for n, v in enumerate(_EXTREMES)} | {key: [_B] for key in _TRAPS}
_START_MS: Final = 1_767_225_600_000  # 2026-01-01T00:00:00Z
_STEP_MS: Final = 60_000
_TICKS: Final = 4
_INSTANCE: Final = scope_instance("BTCUSDT", _A)

_TEXT = st.text(st.characters(min_codepoint=0x20, max_codepoint=0x7E), max_size=24)
#: Keys a hostile block uses: the IR's own field names, a threshold, `_TRAPS` and any text.
_KEY = st.one_of(
    st.sampled_from(sorted({*Rule.model_fields, "threshold", *_TRAPS})), _TEXT.filter(bool)
)
#: A part of another corpus rule copied into the block: its conditions, actions, scope and so on.
_COPIED = st.builds(
    lambda rule, field: rule.model_dump(mode="json").get(field),
    st.sampled_from(_CORPUS),
    st.sampled_from(["conditions", "actions", "scope", "trigger", "limits"]),
)
_LEAF = st.one_of(
    st.integers(-(10**9), 10**9),
    st.floats(allow_nan=False, allow_infinity=False),
    st.sampled_from([*_EXTREMES, {"a": {"b": [1, {"c": {"d": None}}]}}]),
    st.booleans(),
    st.sampled_from(["armed", "simulate", "live"]),
    _TEXT,
    st.just([_B]),
    _COPIED,
)
_BLOCKS = st.dictionaries(
    _KEY,
    st.one_of(_LEAF, st.lists(_LEAF, max_size=3), st.dictionaries(_TEXT, _LEAF, max_size=3)),
    max_size=8,
)


class _Clock:
    """The evaluator's wall and monotonic clock: still within an evaluation, stepped between."""

    def __init__(self) -> None:
        self.ms = _START_MS

    def __call__(self) -> int:
        return self.ms


class _Feed:
    """A metric source whose every reading is a function of the seed, the metric and the time, so
    two evaluators of one rule read the same values: a number, a boolean or a missing value."""

    def __init__(self, feed_seed: int, clock: _Clock) -> None:
        self._seed, self._clock = feed_seed, clock

    def read(self, ref: MetricRef) -> MetricValue:
        now = self._clock.ms
        digest = hashlib.sha256(f"{self._seed}|{metric_key(ref)}|{now}".encode()).digest()
        n = int.from_bytes(digest[:8], "big")
        if n % 10 == 0:
            return MetricValue(None, now, 0, "warmup")
        if n % 10 < 4:
            return MetricValue(n % 20 < 10, now)
        return MetricValue(Decimal(n % 2_000_001 - 1_000_000) / 100, now)


def _evaluate(rule: Rule, feed_seed: int) -> list[EvaluationResult]:
    """`rule` evaluated on `_TICKS` ticks, a minute apart, by a fresh evaluator."""
    clock = _Clock()
    snapshots = SnapshotBuilder(_Feed(feed_seed, clock))
    evaluator = Evaluator(rule, snapshots, clock, clock)
    results = []
    for _ in range(_TICKS):
        snapshots.new_tick()
        results.append(evaluator.on_trigger(_INSTANCE, rule.trigger.type))
        clock.ms += _STEP_MS
    return results


def _runtime_modules() -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for part in _RUNTIME:
        path = _CV / part
        assert path.exists(), f"{part} moved: name its new place here"
        for module in sorted(path.rglob("*.py")) if path.is_dir() else [path]:
            modules[module.relative_to(_CV).as_posix()] = module
    return modules


def _key(node: ast.AST | None, aliases: frozenset[str]) -> bool:
    """`node` names a presentation key: the string itself, or a name bound to it."""
    if isinstance(node, ast.Constant):
        return node.value in PRESENTATION_KEYS
    return isinstance(node, ast.Name) and node.id in aliases


def _reads(tree: ast.AST) -> list[int]:
    """The lines where `tree` reads a presentation key: an attribute, a subscript, a call of
    `_READERS` or a `match` pattern naming one, as a string or through a name bound to one
    (`key = "editor"`). Docstrings, comments and the keys of a dict literal read none."""
    bound = [
        (target, node.value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
    ]
    aliases = frozenset(t.id for t, v in bound if isinstance(t, ast.Name) and _key(v, frozenset()))
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            hit = node.attr in PRESENTATION_KEYS
        elif isinstance(node, ast.Subscript):
            hit = _key(node.slice, aliases)
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            hit = name in _READERS and any(_key(arg, aliases) for arg in node.args)
        elif isinstance(node, ast.MatchMapping):
            hit = any(_key(key, aliases) for key in node.keys)
        elif isinstance(node, ast.MatchClass):
            hit = bool(PRESENTATION_KEYS.intersection(node.kwd_attrs))
        else:
            continue
        if hit:
            lines.append(node.lineno)
    return sorted(lines)


def _ir(**over: Any) -> dict[str, Any]:
    """A notification rule on BTCUSDT, scoped to account A."""
    path = _API / "tests/fixtures/rule_ir/form_simple_0.json"
    raw = json.loads(path.read_text(encoding="utf-8"), parse_float=str)
    raw["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x"}
    raw["scope"] = {"level": "account", "account_ids": [_A], "symbols": ["BTCUSDT"]}
    return {**raw, **over}


def test_evaluation_with_any_presentation_block_is_the_same() -> None:
    """Scenario: Presentation cannot carry semantics
    Given the graph_layout / comment / collapsed-state block
    When it is analysed against the evaluator's inputs
    Then it is demonstrated that no field in it reaches evaluation, or the finding is raised as a
    blocking gap against E35/E37-T01
    """
    seen = {"fired": 0, "traced": 0}

    @seed(20261103)
    @settings(
        max_examples=25,  # not the ci profile's 100: each example evaluates the whole corpus twice
        deadline=None,
        database=None,
        suppress_health_check=list(HealthCheck),
    )
    @example(block=_EXTREME, feed=0)
    @given(block=_BLOCKS, feed=st.integers(0, 2**31))
    def same(block: dict[str, Any], feed: int) -> None:
        for rule in _CORPUS:
            doc = rule.model_dump(mode="json")
            plain = Rule.model_validate({**doc, "graph_layout": None})
            flipped = "form" if rule.editor == "graph" else "graph"
            dressed = Rule.model_validate({**doc, "graph_layout": block, "editor": flipped})
            results = _evaluate(plain, feed)
            assert _evaluate(dressed, feed) == results, rule.name
            seen["fired"] += sum(result.fired for result in results)
            seen["traced"] += sum(bool(result.condition_trace) for result in results)

    same()
    assert len(_CORPUS) >= 30 and seen["fired"] and seen["traced"], "the corpus evaluated"


def test_no_runtime_module_reads_the_presentation_block() -> None:
    """Scenario: Presentation cannot carry semantics
    Given the graph_layout / comment / collapsed-state block
    When it is analysed against the evaluator's inputs
    Then it is demonstrated that no field in it reaches evaluation, or the finding is raised as a
    blocking gap against E35/E37-T01
    """
    assert {"graph_layout", "editor"} <= PRESENTATION_KEYS
    probe = (
        "r.graph_layout\nr['editor']\ngetattr(r, 'editor')\nr.get('graph_layout')\nk = 'editor'\n"
        "getattr(r, k)\noperator.attrgetter('editor')(r)\nitemgetter('graph_layout')(r)\n"
        "r.__getitem__(k)\nmatch r:\n    case {'editor': x}: pass\n"
        "    case R(graph_layout=y): pass\n{'editor': r.last_editor}\n"
    )
    assert _reads(ast.parse(probe)) == [1, 2, 3, 4, 6, 7, 8, 9, 11, 12]  # each form it refuses
    modules = _runtime_modules()
    assert set(modules) == _SCANNED, (
        sorted(set(modules) - _SCANNED),
        sorted(_SCANNED - set(modules)),
    )
    reads = {
        name: lines
        for name, path in modules.items()
        if (lines := _reads(ast.parse(path.read_text(encoding="utf-8"))))
    }
    assert reads == {}, "a runtime module reads the presentation block"


async def test_account_keys_in_the_presentation_block_refuse_a_managers_save() -> None:
    """Scenario: Presentation cannot carry semantics
    Given the graph_layout / comment / collapsed-state block
    When it is analysed against the evaluator's inputs
    Then it is demonstrated that no field in it reaches evaluation, or the finding is raised as a
    blocking gap against E35/E37-T01

    (An account key inside the block makes a Manager's create and update refuse, recorded.)
    """
    audits: list[tuple[str, dict[str, Any]]] = []

    async def audit(action: str, record: dict[str, Any]) -> None:
        audits.append((action, record))

    store = InMemoryRuleStore()
    rules = RulesManager(store, default_registry(), audit=audit, now_us=lambda: _START_MS * 1000)
    for block in _KEYED:
        with pytest.raises(RuleError) as refused:
            await rules.create(_ir(graph_layout=block), _MANAGER)
        assert (refused.value.status, refused.value.code) == (403, "forbidden"), block
    assert await store.all() == []
    await rules.create(_ir(graph_layout=None), _MANAGER)
    (row,) = await store.all()
    for block in _KEYED:
        with pytest.raises(RuleError) as refused:
            await rules.update(row.id, _ir(graph_layout=block), 1, _MANAGER)
        assert (refused.value.status, refused.value.code) == (403, "forbidden"), block
    assert [v["version"] for v in await rules.versions(row.id)] == [1]
    refusals = [record["reason"] for action, record in audits if action == "rule.scope_refused"]
    assert refusals == ["account_not_granted"] * 2 * len(_KEYED)


async def test_account_keys_in_the_presentation_block_add_no_runtime_target() -> None:
    """Scenario: Presentation cannot carry semantics
    Given the graph_layout / comment / collapsed-state block
    When it is analysed against the evaluator's inputs
    Then it is demonstrated that no field in it reaches evaluation, or the finding is raised as a
    blocking gap against E35/E37-T01

    (The Owner may store such a block, and the runtime still acts on the scope's account alone.)
    """
    block = {key: value for keyed in _KEYED for key, value in keyed.items()}
    rule = Rule.model_validate({**_ir(), "graph_layout": block})
    item = EvaluableRule(rule, "simulate", None, "v1", "h1")

    async def work_list() -> list[EvaluableRule]:
        return [item]

    clock = _Clock()
    targets: list[str] = []
    runner = RuleEvaluationRunner(
        work_list,
        SnapshotBuilder(PushedMetricSource()),
        lambda stored, snapshots: Evaluator(stored, snapshots, clock, clock),
        lambda _result: None,
        on_fire=lambda _item, result: targets.append(result.scope_instance),
    )
    await runner.process(EvalTick(rule.trigger.type))
    assert targets == [scope_instance("BTCUSDT", _A)]
