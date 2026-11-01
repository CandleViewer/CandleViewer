"""A rule's variable store (24 §11.5 "Variables"; E35-T13 slice 4a).

Per rule, at most `limits.VARIABLES_PER_RULE` variables, each value at most
`limits.VARIABLE_VALUE_MAX_BYTES` of canonical JSON, held in memory only: a restart clears the
store, as it drops queued fires. `ttl_ms` is optional: a variable expires once it has passed on the
injected monotonic clock, and one without it lives until its rule leaves `armed` (`retain`, at the
first evaluation after) or the process stops. A set past either bound is refused and never evicts
another variable; setting a name the rule holds replaces its value, and an expired variable frees
its place. No IR operand reads the store yet (a read operand is an IR change, contract first).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Literal
from uuid import UUID

from candleviewer.rules.executor.handlers import Capability, HandlerAnswer, Prepared, prepared
from candleviewer.rules.ir.canonical import dec_str
from candleviewer.rules.limits import VARIABLE_VALUE_MAX_BYTES, VARIABLES_PER_RULE
from candleviewer.rules.scope import ActionRequest

#: What a set did: stored, refused at the store's bound, or refused as a value over its size.
Put = Literal["set", "store_full", "too_large"]


def canonical_json(value: Any) -> str:
    """`value` as canonical JSON: keys sorted, no whitespace, UTF-8, and every number as its plain
    decimal text, the IR's own canonical form (`dec_str`), so `1.0` and `1.00` are one value. A
    `ValueError` for anything JSON cannot hold: a non-finite number, a key that is not a string, a
    type of no JSON form."""
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, float):  # an untyped `params` place holds one: its own shortest decimal
        value = Decimal(float.__repr__(value))
    if isinstance(value, int | Decimal):
        number = Decimal(value)
        if not number.is_finite():
            raise ValueError("a number with no finite value")
        return dec_str(number)
    if isinstance(value, dict | MappingProxyType):
        if not all(isinstance(k, str) for k in value):
            raise ValueError("a key that is not a string")
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    raise ValueError(f"a {type(value).__name__} has no JSON form")


@dataclass(slots=True)
class _Held:
    text: str  # the value's canonical JSON
    expires_at: float | None  # on the store's clock; `None` without a `ttl_ms`


class VariableStore:
    """Each rule's variables, by name, on `clock` (seconds, monotonic)."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        *,
        per_rule: int = VARIABLES_PER_RULE,
        max_bytes: int = VARIABLE_VALUE_MAX_BYTES,
    ) -> None:
        self._clock, self._per_rule, self._max_bytes = clock, per_rule, max_bytes
        self._rules: dict[str, dict[str, _Held]] = {}

    def put(self, rule_id: str, name: str, text: str, ttl_ms: int | None) -> Put:
        """Set `name` to `text` (canonical JSON) for `ttl_ms`, or for good when it is `None`."""
        if len(text.encode()) > self._max_bytes:
            return "too_large"
        now = self._clock()
        held = self._live(rule_id, now)
        if name not in held and len(held) >= self._per_rule:
            return "store_full"
        held[name] = _Held(text, None if ttl_ms is None else now + ttl_ms / 1000)
        return "set"

    def get(self, rule_id: str, name: str) -> str | None:
        """The value's canonical JSON while it lives; `None` once it expired or was never set."""
        held = self._live(rule_id, self._clock()).get(name) if rule_id in self._rules else None
        return None if held is None else held.text

    def names(self, rule_id: str) -> frozenset[str]:
        return (
            frozenset(self._live(rule_id, self._clock())) if rule_id in self._rules else frozenset()
        )

    def retain(self, rule_ids: Collection[str]) -> None:
        """Drop every rule's variables but those of `rule_ids`, the rules still armed."""
        for rule_id in [r for r in self._rules if r not in rule_ids]:
            del self._rules[rule_id]

    def clear(self) -> None:
        self._rules.clear()

    def _live(self, rule_id: str, now: float) -> dict[str, _Held]:
        """The rule's variables, each expired one dropped first, so it frees its place."""
        held = self._rules.setdefault(rule_id, {})
        for name in [
            n for n, h in held.items() if h.expires_at is not None and now >= h.expires_at
        ]:
            del held[name]
        return held


class SetVariableHandler:
    """`set_variable` (24 §11.5): `ok` once the variable is set, `failed` when the store is full
    (`variable_store_full`), the value is over its size (`variable_too_large`) or a parameter is
    not of its type (`invalid_params`: `name` a non-empty string, `ttl_ms` a positive integer or
    absent, `value` any JSON)."""

    capability: Capability = "variables"

    def __init__(self, store: VariableStore) -> None:
        self._store = store

    def prepare(
        self, req: ActionRequest, account_id: UUID | None, *, max_notional_usd: Decimal | None
    ) -> Prepared:
        params = req.payload.params
        name, ttl_ms = params.get("name"), params.get("ttl_ms")
        try:
            text: str | None = canonical_json(params.get("value"))
        except ValueError:
            text = None
        typed = isinstance(ttl_ms, int) and not isinstance(ttl_ms, bool) and ttl_ms > 0
        if not isinstance(name, str) or not name or text is None or not (ttl_ms is None or typed):
            return prepared({"invalid": True})
        return prepared({"rule_id": req.rule_id, "name": name, "value": text, "ttl_ms": ttl_ms})

    async def send(self, prepared: Prepared, *, client_ref: str) -> HandlerAnswer:
        request = prepared.request
        if request.get("invalid"):
            return HandlerAnswer("refused", error_code="invalid_params")
        put = self._store.put(
            request["rule_id"], request["name"], request["value"], request["ttl_ms"]
        )
        return (
            HandlerAnswer("done") if put == "set" else HandlerAnswer("refused", f"variable_{put}")
        )
