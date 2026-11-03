"""E35-T13 (#5005) slice 4a: a rule's variable store (24 §11.5 "Variables"; BQ-6).

The store on a frozen clock, through `SetVariableHandler` as the executor drives a handler
(`prepare` once, then `send`), and once through `EngineRig`, where an armed fire's `set_variable`
lands in the service's store and the store drops a rule's variables once it leaves `armed`.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from candleviewer.rules.executor.handlers import HandlerAnswer
from candleviewer.rules.executor.variables import SetVariableHandler, VariableStore, canonical_json
from candleviewer.rules.ir.models import Action, RuleScope
from candleviewer.rules.limits import VARIABLE_VALUE_MAX_BYTES, VARIABLES_PER_RULE
from candleviewer.rules.scope import ScopeInstanceRef
from tests.rules.executor.engine_rig import EngineRig, engine, set_var
from tests.rules.executor.request_builders import action_request
from tests.rules.test_scope_wiring import OWNER

__all__ = ["engine"]  # the rig's fixture, used by name

RULE, ELSE = str(uuid.UUID(int=7)), str(uuid.UUID(int=9))


class Seconds:
    """A frozen monotonic clock, in seconds, moved by hand."""

    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


async def _set(
    store: VariableStore, name: Any, value: Any = 1, *, rule_id: str = RULE, **params: Any
) -> HandlerAnswer:
    action = Action.model_validate(
        {"node_id": "v1", "type": "set_variable",
         "params": {"name": name, "value": value, **params}}
    )  # fmt: skip
    req = action_request(
        RuleScope(level="account"), OWNER, ScopeInstanceRef("*@*", None, None),
        action_type="set_variable", payload=action, rule_id=rule_id,
    )  # fmt: skip
    handler = SetVariableHandler(store)
    return await handler.send(handler.prepare(req, None, max_notional_usd=None), client_ref="k")


async def test_set_variable_expires_after_ttl() -> None:
    """Scenario: A variable expires after its TTL and the store is bounded (edge case). With a
    `ttl_ms` on a frozen clock, the variable lives until the TTL has passed, then it is gone; one
    set without a `ttl_ms` stays."""
    clock = Seconds()
    store = VariableStore(clock)
    assert (await _set(store, "brief", "x", ttl_ms=500)).answer == "done"
    assert (await _set(store, "kept", "y")).answer == "done"
    clock.t += 0.499
    assert store.get(RULE, "brief") == '"x"'
    clock.t += 0.001  # the TTL has passed
    assert store.get(RULE, "brief") is None and store.get(RULE, "kept") == '"y"'
    assert store.names(RULE) == {"kept"}


async def test_variable_store_is_bounded_per_rule() -> None:
    """Scenario: A variable expires after its TTL and the store is bounded (edge case). The
    thirty-third variable of a rule is refused (`variable_store_full`) and evicts none; another
    rule's store is its own; a name the rule holds is replaced in place; an expired variable frees
    its place."""
    assert VARIABLES_PER_RULE == 32
    clock = Seconds()
    store = VariableStore(clock)
    for n in range(VARIABLES_PER_RULE - 1):
        assert (await _set(store, f"v{n}")).answer == "done"
    assert (await _set(store, "brief", ttl_ms=1_000)).answer == "done"  # the thirty-second
    full = await _set(store, "one-more")
    assert (full.answer, full.error_code) == ("refused", "variable_store_full")
    assert len(store.names(RULE)) == VARIABLES_PER_RULE and store.get(RULE, "one-more") is None
    assert (await _set(store, "v0", 2)).answer == "done" and store.get(RULE, "v0") == '"2"'
    assert (await _set(store, "elsewhere", rule_id=ELSE)).answer == "done"
    clock.t += 1.0  # `brief` expires and frees its place
    assert (await _set(store, "one-more")).answer == "done"
    assert len(store.names(RULE)) == VARIABLES_PER_RULE


async def test_a_value_over_its_size_bound_is_refused() -> None:
    """A value of at most 1 KiB of canonical JSON is set, its UTF-8 bytes counted; one byte more
    is refused (`variable_too_large`) and leaves the variable as it was."""
    assert VARIABLE_VALUE_MAX_BYTES == 1024
    store = VariableStore(Seconds())
    fits = "é" * ((VARIABLE_VALUE_MAX_BYTES - 2) // 2)  # two bytes each, plus the two quotes
    assert len(canonical_json(fits).encode()) == VARIABLE_VALUE_MAX_BYTES
    assert (await _set(store, "note", fits)).answer == "done"
    over = await _set(store, "note", fits + "x")
    assert (over.answer, over.error_code) == ("refused", "variable_too_large")
    assert store.get(RULE, "note") == canonical_json(fits)


def test_a_value_is_held_as_canonical_json() -> None:
    """Keys sorted, no whitespace, every number its plain decimal (`1.0` and `1` are one)."""
    assert canonical_json({"b": [1.0, True, None], "a": "x"}) == '{"a":"x","b":["1",true,null]}'
    assert canonical_json(1.0) == canonical_json(1) and canonical_json(10) == '"10"'
    for bad in (float("nan"), {1: "x"}, object()):
        with pytest.raises(ValueError):
            canonical_json(bad)


async def test_a_float_is_held_as_its_shortest_decimal() -> None:
    """The IR's rule for a float: its shortest decimal text, never its binary expansion, and in
    plain notation, never an exponent; `0.1` set through the handler is held as "0.1" too."""
    assert canonical_json(0.1) == '"0.1"'
    assert (canonical_json(1e22), canonical_json(1e-7)) == (
        '"10000000000000000000000"', '"0.0000001"',
    )  # fmt: skip
    store = VariableStore(Seconds())
    assert (await _set(store, "step", 0.1)).answer == "done"
    assert store.get(RULE, "step") == '"0.1"'


@pytest.mark.parametrize(
    ("name", "params"),
    [("", {}), (7, {}), ("n", {"ttl_ms": 0}), ("n", {"ttl_ms": -1}), ("n", {"ttl_ms": True}),
     ("n", {"ttl_ms": "500"}), ("n", {"value": float("inf")})],
    ids=str,
)  # fmt: skip
async def test_a_mistyped_set_variable_fails(name: Any, params: dict[str, Any]) -> None:
    store = VariableStore(Seconds())
    answer = await _set(store, name, **params)
    assert (answer.answer, answer.error_code) == ("refused", "invalid_params")
    assert store.names(RULE) == frozenset()


async def test_an_armed_fires_variable_lives_until_the_rule_leaves_armed(engine: EngineRig) -> None:
    """Through the executor: an armed fire's `set_variable` is `ok` and lands in the service's
    store; once the rule is no longer armed, the store drops its variables at the next evaluation,
    and a stop clears the store."""
    rid = await engine.add(actions=[set_var("v1", "level", {"at": 1.5})])
    other = await engine.add(actions=[set_var("v1", "level", 2)])
    await engine.fire()
    await engine.settle()
    assert engine.results(rid) == [("set_variable", "ok", None)]
    variables = engine.svc._variables
    assert variables.get(rid, "level") == '{"at":"1.5"}' and variables.get(other, "level") == '"2"'
    (await engine.row(rid)).mode = "simulate"
    await engine.fire()
    await engine.settle()
    assert variables.get(rid, "level") is None and variables.get(other, "level") == '"2"'
    await engine.svc.stop(1.0)
    assert variables.get(other, "level") is None
