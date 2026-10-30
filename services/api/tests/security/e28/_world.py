"""The E28-X03 world (#976): the RBAC pack's real `create_app()` (`build_world`, no network,
C-13.5) with every E28 route over an in-memory store, so each cell can see a write it was not
expected to make. The profile reads and writes are `_profile_writes_world`'s; the trade-group reads
the unit `Store` faked as Postgres scopes it; the definition reads and writes the S2d unit world;
the preview the S3c unit world's ports; the `trade_groups` topic is the app's own, captured.

`trading.trade_groups` is on, as in a world where the routes act: the flag is no RBAC control
(C-4.14), and off it would answer the Owner before any scope check. The preview's per-user bucket
never runs dry here (its 429 is `test_trade_group_preview_route.py`'s).
"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, cast

import pytest

import candleviewer.app as appmod
from candleviewer.accounts.errors import AccountNotFoundError
from candleviewer.accounts.models import ExchangeAccount
from candleviewer.api.preview_limiter import PreviewLimiter
from candleviewer.api.trade_group_definition_writes import DefinitionWrites
from candleviewer.api.trade_group_preview import PreviewReads, make_trade_group_preview_router
from candleviewer.api.trade_groups_gate import TradeGroupsGate
from candleviewer.storage.repositories.accounts import GrantScope
from candleviewer.ws_wiring import trade_groups_topic
from tests.contract._profile_writes_world import Writes, build
from tests.contract.rbac.rbac_harness import FOREIGN, GRANTED
from tests.unit.api import test_trade_group_definition_reads as def_reads
from tests.unit.api import test_trade_group_preview_route as preview
from tests.unit.api import test_trade_group_routes as groups
from tests.unit.api.test_trade_group_definition_update import World as DefinitionsWorld
from tests.unit.oms.submit_rig import instrument as btcusdt

#: The situations a cell is run in, by the accounts they name: one granted to
#: `manager_with_grant`, one granted to no one, and both (a group with a leg on each).
SITUATIONS: dict[str, tuple[uuid.UUID, ...]] = {
    "granted": (GRANTED,), "foreign": (FOREIGN,), "mixed": (GRANTED, FOREIGN), "-": (),
}  # fmt: skip
GROUP = {
    at: uuid.UUID(int=0x5000 + n) for n, at in ((11, "granted"), (12, "foreign"), (13, "mixed"))
}
DEFINITION = {at: uuid.UUID(int=0xDE00 + n) for n, at in enumerate(("granted", "foreign", "mixed"))}
_NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
LIVE = uuid.UUID(int=0x11BE)  # a live account the preview's accounts know, for case 5
_LISTED = frozenset({"BTCUSDT", "ETHUSDT"})
#: The fields that log a read, not a write: a 404 reads (in the caller's scope) and writes nothing.
READ_LOGS = frozenset({"seen", "reads", "listed", "asked", "read", "profiled", "calls", "texts"})
_OPAQUE = ("fastapi", "starlette", "httpx", "anyio", "asyncio", "threading", "prometheus_client")


class Preview(preview.World):
    """The S3c world's ports, its accounts the harness's two, both demo, and `LIVE`; ETHUSDT is
    listed too, so a symbol off an account's allow-list reaches its check."""

    async def instrument(self, symbol: str) -> Any:
        return btcusdt(symbol=symbol, base_coin=symbol[:3]) if symbol in _LISTED else None

    async def get_account(self, scope: Any, account_id: uuid.UUID) -> ExchangeAccount:
        self.read.append(account_id)
        if account_id not in (GRANTED, FOREIGN, LIVE) or (
            isinstance(scope, GrantScope) and account_id not in scope.account_ids
        ):  # missing or outside the scope: M13's one answer
            raise AccountNotFoundError("account")
        env = "live" if account_id == LIVE else "demo"
        row = {"id": account_id, "env": env, "kind": "main", "exchange_uid": "1001"}
        row |= {"label": f"E28-{str(account_id)[-1]}", "created_at": _NOW, "updated_at": _NOW}
        return ExchangeAccount.model_validate(row)


class Definitions(DefinitionsWorld):
    """The S2d world, which also knows the harness's two accounts (demo, live, BTCUSDT allowed)."""

    def __init__(self) -> None:
        super().__init__()
        self.symbols |= {GRANTED: ("BTCUSDT",), FOREIGN: ("BTCUSDT",)}
        self.live |= {GRANTED, FOREIGN}

    async def get_account(self, scope: Any, account_id: uuid.UUID) -> ExchangeAccount:
        if account_id not in (GRANTED, FOREIGN):
            return await super().get_account(scope, account_id)
        row = {"id": account_id, "env": "demo", "kind": "main", "exchange_uid": "1001"}
        row |= {"label": f"E28-{str(account_id)[-1]}", "created_at": _NOW, "updated_at": _NOW}
        return ExchangeAccount.model_validate(row)


@dataclasses.dataclass
class E28World:
    writes: Writes
    groups: groups.Store
    definitions: Definitions
    preview: Preview
    topic: Any  # the app's `trade_groups` topic
    by_request: dict[str, list[dict[str, Any]]]  # the audit records, by `request_id`
    kept: dict[uuid.UUID, Any]  # the definitions as seeded

    @property
    def app(self) -> Any:
        return self.writes.world.app

    @property
    def records(self) -> list[dict[str, Any]]:
        return self.writes.world.audit.records

    def stores(self) -> dict[str, Any]:
        """Every store the world has, whichever route the author expected to touch."""
        world, w = self.writes.world, self.writes
        return {
            "profiles": w.rows, "invalidated": w.invalidated, "armed": w.rules,
            "replays": w.replays, "minted": w.minted, "groups": self.groups,
            "definitions": self.definitions, "preview": self.preview, "users": world.users,
            "access": world.access, "rules": world.rule_store, "purge": world.purge_backend,
            "step_up": world.step_up, "grants": world.grants, "resolver": world.resolver,
        }  # fmt: skip

    def reset(self) -> None:
        self.writes.reset()  # the profile rows and the audit log
        self.by_request.clear()
        self.definitions.records = dict(self.kept)
        self.definitions.deleted.clear()


def state(value: Any, *, skip: frozenset[str] = frozenset(), depth: int = 0) -> Any:
    """A comparable copy of `value`, walked whole: a write anywhere in it changes the copy. A
    value object (a dataclass, a model, a scalar) is kept by its `repr`; a callable, a framework
    object or a field named in `skip` is left out."""
    if depth > 8:
        return "<deep>"
    if value is None or isinstance(value, str | int | float | uuid.UUID | Decimal | datetime):
        return value
    if isinstance(value, Enum | bytes) or dataclasses.is_dataclass(value):
        return repr(value)
    if hasattr(value, "model_dump"):  # a pydantic model
        return repr(value)
    if isinstance(value, Mapping):
        return sorted(
            (repr(k), state(v, skip=skip, depth=depth + 1))
            for k, v in value.items()
            if k not in skip
        )
    if isinstance(value, list | tuple):
        return [state(v, skip=skip, depth=depth + 1) for v in value]
    if isinstance(value, set | frozenset):
        return sorted(repr(state(v, skip=skip, depth=depth + 1)) for v in value)
    if callable(value) or type(value).__module__.split(".")[0] in _OPAQUE:
        return None
    fields = getattr(value, "__dict__", {})
    return sorted(
        (k, state(v, skip=skip, depth=depth + 1)) for k, v in fields.items() if k not in skip
    )


def request_id(cell: str) -> str:
    """A canonical UUIDv4 named by `cell` (the middleware binds only those, #3990)."""
    return str(uuid.UUID(bytes=hashlib.sha256(cell.encode()).digest()[:16], version=4))


def _definitions() -> Definitions:
    store = Definitions()
    for at, key in DEFINITION.items():
        store.records[key] = def_reads.record(key, f"E28 {at}", *SITUATIONS[at])
    return store


@contextmanager
def e28_world() -> Iterator[E28World]:
    """The world; its patches are undone however the caller's module ends."""
    with pytest.MonkeyPatch.context() as mp:
        made = [groups.group(n, "BTCUSDT", "open", n, *SITUATIONS[at]) for n, at in (
            (11, "granted"), (12, "foreign"), (13, "mixed"))]  # fmt: skip
        reads, defs, pv, topics = groups.Store(*made), _definitions(), Preview(), list[Any]()
        mp.setattr(appmod, "group_reads", lambda _settings: reads)
        mp.setattr(appmod, "definition_store", lambda _settings: defs)
        own = cast(Any, defs)  # its accounts, profiles, listing and readiness
        mp.setattr(
            appmod, "definition_writes", lambda *_a: DefinitionWrites(own, own, own, own, own)
        )
        mp.setattr(appmod, "TradeGroupsGate", lambda _f, **kw: TradeGroupsGate(lambda: True, **kw))
        real_router, real_topic = make_trade_group_preview_router, trade_groups_topic

        def preview_router(principals: Any, _runtime: Any, **kw: Any) -> Any:
            kw |= {"reads": PreviewReads(pv, cast(Any, pv), pv, "demo")}
            kw |= {"limiter": PreviewLimiter(10**6, clock=lambda: 0.0)}
            return real_router(principals, lambda: pv, **kw)

        def topic(*args: Any) -> Any:
            topics.append(real_topic(*args))
            return topics[-1]

        mp.setattr(appmod, "make_trade_group_preview_router", preview_router)
        mp.setattr(appmod, "trade_groups_topic", topic)
        w = build(mp)
        index: dict[str, list[dict[str, Any]]] = {}
        sink, real_emit = w.world.audit, w.world.audit.emit

        async def emit(action: str, **kw: Any) -> None:  # the records, indexed as they land
            await real_emit(action, **kw)
            index.setdefault(str(kw.get("request_id")), []).append(sink.records[-1])

        mp.setattr(sink, "emit", emit)
        yield E28World(w, reads, defs, pv, topics[0], index, dict(defs.records))
