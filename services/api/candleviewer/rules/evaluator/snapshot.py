"""Immutable MetricSnapshot with cross-rule memoisation (11.5 E2/E3/E7, 7.3)."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Final, Protocol
from uuid import UUID

from candleviewer.rules.ir.models import MetricRef

Value = Decimal | bool | str | None

DEFAULT_MAX_DATA_AGE_MS = 5_000
STALE_CADENCE_FACTOR = 3


@dataclass(frozen=True, slots=True)
class MetricValue:
    """One metric reading. ``value is None`` means unavailable; ``reason`` says why."""

    value: Value
    ts_ms: int
    cadence_ms: int = 0
    reason: str | None = None  # warmup | no_position | stale_data | ...

    def max_age_ms(self) -> int:
        return max(DEFAULT_MAX_DATA_AGE_MS, STALE_CADENCE_FACTOR * self.cadence_ms)


class MetricSource(Protocol):
    """Synchronous read of a memoised metric value (no await may interleave, E2)."""

    def read(self, ref: MetricRef) -> MetricValue: ...


def metric_key(ref: MetricRef) -> str:
    """Canonical, deterministic key for a metric reference (metric + params + scope)."""
    params = json.dumps(ref.params, sort_keys=True, separators=(",", ":"), default=str)
    return f"{ref.metric}{params}|{ref.symbol or ''}|{ref.account_id or ''}|{ref.timeframe or ''}"


#: Metric name -> registry scope (`MetricDescriptor.scope`, 24 §7.1). Injected, not imported:
#: `alerts` imports this module and may not reach `orderflow` through the registry (M22).
MetricScopes = Mapping[str, str]
NO_SCOPES: Final[MetricScopes] = MappingProxyType({})
_SYMBOL_SCOPES: Final = frozenset({"symbol", "position"})
_ACCOUNT_SCOPES: Final = frozenset({"account", "position"})


class ScopeBindingError(ValueError):
    """A ref the instance may not read: the instance account is not a UUID, or the rule authored
    an account other than the instance's. The evaluator skips the instance as ``scope``."""


def _open(part: str | UUID | None) -> bool:
    return part is not None and part != "*"


def _account(account: str | UUID) -> UUID:
    if isinstance(account, UUID):
        return account
    try:
        return UUID(account)
    except ValueError:
        raise ScopeBindingError("instance account is not a UUID") from None


def bound_ref(
    ref: MetricRef, symbol: str | None, account: str | UUID | None, scopes: MetricScopes
) -> MetricRef:
    """The ref a source is asked for in one scope instance (E6, 24 §11.2 "None = scope symbol").

    A ref with no symbol whose registry scope is ``symbol`` or ``position`` takes the instance's
    symbol; one with no ``account_id`` whose scope is ``account`` or ``position`` takes the
    instance's account. An instance part of ``*`` (or None), an authored symbol, a ``global``
    metric and a name outside ``scopes`` bind nothing. Pure; the same ref back when nothing
    binds, so ``metric_key`` is unchanged for every ref a rule pins.

    Fails closed (`ScopeBindingError`) when the ref is pinned to an account other than the
    instance's (no cross-account read before the grant fence, C-12.4): with a scope table, an
    instance with no open account has none a pin can match; without one (the alert evaluator),
    only an open instance account is compared. It fails closed too when an account-scoped ref
    meets an instance account that is not a UUID."""
    scope = scopes.get(ref.metric)
    update: dict[str, object] = {}
    if ref.symbol is None and scope in _SYMBOL_SCOPES and _open(symbol):
        update["symbol"] = symbol
    open_account = account if account is not None and _open(account) else None
    if ref.account_id is not None:
        if open_account is None:
            if scopes:
                raise ScopeBindingError("ref account is not the instance account")
        elif ref.account_id != _account(open_account):
            raise ScopeBindingError("ref account is not the instance account")
    elif open_account is not None and scope in _ACCOUNT_SCOPES:
        update["account_id"] = _account(open_account)
    return ref.model_copy(update=update) if update else ref


@dataclass(frozen=True, slots=True)
class MetricSnapshot:
    taken_at_ms: int
    values: Mapping[str, MetricValue]
    #: authored key -> bound key, for the refs the instance bound (`SnapshotBuilder.build`).
    bound: Mapping[str, str] = MappingProxyType({})

    def get(self, ref: MetricRef) -> MetricValue:
        key = metric_key(ref)
        return self.values[self.bound.get(key, key)]

    def stale_keys(self) -> tuple[str, ...]:
        return tuple(
            k for k, v in self.values.items() if self.taken_at_ms - v.ts_ms > v.max_age_ms()
        )


class SnapshotBuilder:
    """Reads every referenced metric once; memoises across rules within one tick (7.3)."""

    def __init__(self, source: MetricSource, scopes: MetricScopes = NO_SCOPES) -> None:
        self._source = source
        self._scopes = scopes  # empty: no ref is ever bound (the alert evaluator's reads)
        self._cache: dict[str, MetricValue] = {}
        self.computations = 0
        self.cache_hits = 0

    def new_tick(self) -> None:
        """Invalidate the memo; call once per market update, not per rule."""
        self._cache.clear()

    def build(
        self,
        refs: Iterable[MetricRef],
        now_ms: int,
        *,
        symbol: str | None = None,
        account: str | UUID | None = None,
    ) -> MetricSnapshot:
        """Read each ref bound to the instance (``symbol``, ``account``; `bound_ref`) once."""
        values: dict[str, MetricValue] = {}
        bound: dict[str, str] = {}
        for authored in refs:
            ref = bound_ref(authored, symbol, account, self._scopes)
            key = metric_key(ref)
            if ref is not authored:
                bound[metric_key(authored)] = key
            if key in values:
                continue
            cached = self._cache.get(key)
            if cached is None:
                cached = self._source.read(ref)
                self._cache[key] = cached
                self.computations += 1
            else:
                self.cache_hits += 1
            values[key] = cached
        return MetricSnapshot(now_ms, MappingProxyType(values), MappingProxyType(bound))
