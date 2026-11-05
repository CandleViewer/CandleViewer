"""The E29-X02 world (#982): the RBAC pack's real `create_app()` (`build_world`, no network, C-13.5)
with the OMS composed as `create_app()` composes it, on in-memory stores: the OMS runtime
(`OmsRuntime`, the order lane inline on the app's loop, its venue a `FakeTradingPort`, its stores
`InMemoryOrderStore`'s, `test_oms_runtime`'s world) handed the app's own `orders`, `executions`
and `positions` topics, and the OMS reads (`OmsReads`) over an in-memory read store that scopes as
the SQL does (`oms_reads_world`). Every request runs on one loop, the runtime's, so a route's task
is the runtime's own (CR-S3C2-01).

The two accounts are the pack's: `GRANTED`, granted to `manager_with_grant` with trade, and
`FOREIGN`, granted to no one; both demo. Each holds a final order (an exit admitted past its scope
then meets the order's state and sends nothing), a flat position for the writes, an open one and a
fill for the lists. `ABSENT` is an id nothing holds. The granted order is `manager_with_grant`'s
own (ruling Q6), the foreign one the Owner's.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, cast

import pytest
from anyio.from_thread import start_blocking_portal

import candleviewer.app as appmod
from candleviewer.oms.fakes import InMemoryOrderStore
from candleviewer.oms.reads import OmsReads
from candleviewer.oms_wiring import GroupStores, OmsStores
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.repositories.accounts import AccountScope, GrantScope
from candleviewer.storage.repositories.idempotency_anchors import NewAnchor
from candleviewer.storage.repositories.orders import OrderRow, settle_accounts
from candleviewer.storage.repositories.trading_accounts import TradingAccountRow
from tests.contract.rbac.rbac_harness import ABSENT, FOREIGN, GRANTED, World, build_world
from tests.contract.rbac.rbac_harness import user_id_of as uid
from tests.unit.api import oms_reads_world as rw
from tests.unit.oms import test_oms_runtime as rt

ENVIRONMENT: Final = {GRANTED: "demo", FOREIGN: "demo"}
#: The situations a cell is run in, by the account its path or body names.
SITUATIONS: Final[dict[str, tuple[uuid.UUID, ...]]] = {
    "granted": (GRANTED,), "foreign": (FOREIGN,), "absent": (ABSENT,), "mixed": (GRANTED, FOREIGN),
    "-": (),
}  # fmt: skip
#: Each account's final order, flat position (the writes' object), open position and fill.
ORDER: Final = {GRANTED: rw.order(1, GRANTED), FOREIGN: rw.order(2, FOREIGN)}
FLAT: Final = {GRANTED: rw.position(1, GRANTED), FOREIGN: rw.position(2, FOREIGN)}
OPEN: Final = {GRANTED: rw.position(3, GRANTED), FOREIGN: rw.position(4, FOREIGN)}
FILL: Final = {
    a: rw.fill(n, a, ORDER[a].id, closed_pnl=Decimal("1.5"))
    for n, a in ((1, GRANTED), (2, FOREIGN))
}
#: An id nothing holds, for each object a path names.
MISSING: Final = uuid.UUID(int=0xAB5E)
_KEY: Final = uuid.UUID(int=0xBEEF)


def _final(account: uuid.UUID) -> OrderRow:
    row = ORDER[account]
    return dataclasses.replace(row, state="filled", lifecycle_state="filled", leaves_qty=Decimal(0))


class Reads(rw.Store):
    """The read store of `oms_reads_world`, its accounts this world's two (both demo)."""

    def _reach(self, scope: AccountScope, env: str, requested: Any) -> set[uuid.UUID]:
        self.calls.append("settle")
        live = sorted(a for a, e in ENVIRONMENT.items() if e == env)
        if isinstance(scope, GrantScope):
            live = [a for a in live if a in scope.account_ids]
        return set(settle_accounts(live, tuple(requested)))

    def _viewable(self, scope: AccountScope, env: str, account: uuid.UUID) -> bool:
        held = not isinstance(scope, GrantScope) or account in scope.account_ids
        return ENVIRONMENT.get(account) == env and held


def _reads() -> Reads:
    """Each account's final order, its fill, its flat position and its open one (no group)."""
    flat = [dataclasses.replace(FLAT[a], size=Decimal(0), side="None") for a in FLAT]
    reads = Reads(positions=[*flat, *OPEN.values()])
    reads.orders.extend((_final(a), None) for a in ORDER)
    reads.fills.extend((f, None) for f in FILL.values())
    return reads


def _orders() -> InMemoryOrderStore:
    """The exit routes' scoped store: the two final orders, their creators and the grants."""
    store = InMemoryOrderStore(lambda: rt.T0)
    owner, manager = uid("owner"), uid("manager_with_grant")
    store.seed_owner(owner)
    store.seed_access(manager, GRANTED, trade=True)
    for n, (account, creator) in enumerate(((GRANTED, manager), (FOREIGN, owner)), start=1):
        store._environments[account] = "demo"
        row = _final(account)
        anchor = NewAnchor(
            id=uuid.UUID(int=0xA0 + n), created_by=creator, operation="placeOrder",
            client_ref=str(uuid.UUID(int=0xC0 + n)), request_sha256="0" * 64, order_id=row.id,
        )  # fmt: skip
        store._commit_rows(row, store._new_anchor(anchor))
        store._fills[(account, FILL[account].exec_id)] = FILL[account]
    return store


class _Groups:
    """The trade-group store as the runtime reads it here: no open group, no anchor."""

    async def list_open_groups(self) -> tuple[()]:
        return ()

    async def find_anchor(self, *_args: Any) -> None:
        return None


@dataclasses.dataclass
class Runtime(rt.World):
    """`test_oms_runtime`'s world: its stores the order store above and `_Groups`."""

    def stores(self) -> OmsStores:
        return dataclasses.replace(super().stores(), groups=cast(GroupStores, _Groups()))


@dataclasses.dataclass
class OmsWorld:
    pack: World
    oms: Runtime
    runtime: Any
    topics: Any  # the app's `orders`, `executions` and `positions` topics, the runtime's
    reads: Reads
    portal: Any
    by_request: dict[str, list[dict[str, Any]]]  # every audit record, both writers, by request id

    @property
    def app(self) -> Any:
        return self.pack.app

    @property
    def client(self) -> Any:
        return self.pack.client

    def count(self) -> int:
        """Every record both writers took: the serving loop's and the order lane's."""
        return len(self.pack.audit.records) + len(self.oms.writer.records)

    def stores(self) -> dict[str, Any]:
        """Every store the world has, whichever route the author expected to touch."""
        p, o = self.pack, self.oms
        return {
            "orders": o.store, "venue": [port.__dict__ for port in o.venue.ports],
            "reads": {k: v for k, v in vars(self.reads).items() if k != "calls"},  # a read log
            "users": p.users, "access": p.access, "rules": p.rule_store,
            "purge": p.purge_backend, "step_up": p.step_up, "grants": p.grants,
            "resolver": (p.resolver.revoked, p.resolver.extra),  # its contract is read-only
            "standing": self.runtime._standing,
        }  # fmt: skip

    def reset(self) -> None:
        self.by_request.clear()

    def call(self, fn: Any, *args: Any) -> Any:
        return self.portal.call(fn, *args)


def tally(source: Any, name: str, **labels: str) -> float:
    """The sum of `source`'s samples named `name` whose labels hold `labels` (a registry or one
    collector)."""
    if hasattr(source, "restricted_registry"):  # a whole registry: collect `name`'s alone
        source = source.restricted_registry([name])
    return float(sum(
        s.value for family in source.collect() for s in family.samples
        if s.name == name and all(s.labels.get(k) == v for k, v in labels.items())
    ))  # fmt: skip


async def _until_ready(runtime: Any, oms: rt.World) -> None:
    await runtime.start()
    for mark_read in [flag.read for flag in oms.flags]:  # a fake flag view's first read, no body
        mark_read()
    await rt.until(lambda: runtime.state == "ok")


@contextmanager
def oms_world(bars_state_root: Path) -> Iterator[OmsWorld]:
    """The world, its bars builders' state under `bars_state_root` (pytest's temporary directory);
    its patches are undone and its runtime stopped however the caller ends."""
    with pytest.MonkeyPatch.context() as mp, start_blocking_portal() as portal:
        oms, reads = Runtime(store=_orders()), _reads()
        oms.accounts.extend(TradingAccountRow(a, "demo", "1001", False, _KEY) for a in ENVIRONMENT)
        built: list[Any] = []

        def runtime(*_a: Any, topics: Any = None, **_kw: Any) -> Any:
            built.extend((oms.runtime(topics=topics), topics))
            return built[0]

        mp.setattr(appmod, "build_oms_runtime", runtime)
        mp.setattr(appmod, "oms_reads", lambda _settings: OmsReads(rw.ReadStore(reads), "demo"))
        pack = build_world(mp, bars_state_root=bars_state_root)
        pack.client.portal = portal  # one loop for every request: the runtime's (CR-S3C2-01)
        index: dict[str, list[dict[str, Any]]] = {}
        for sink in (pack.audit, oms.writer):
            _indexed(mp, sink, index)
        saved, b01._ATTEMPTS = b01._ATTEMPTS, OrderedDict()
        run, topics = built
        try:
            portal.call(_until_ready, run, oms)
            yield OmsWorld(pack, oms, run, topics, reads, portal, index)
        finally:
            portal.call(run.stop)
            b01._ATTEMPTS = saved
            pack.client.portal = None


def _indexed(mp: pytest.MonkeyPatch, sink: Any, index: dict[str, list[dict[str, Any]]]) -> None:
    """Each record `sink` takes, indexed by its request id as it lands."""
    real = sink.emit

    async def emit(action: str, **kw: Any) -> None:
        await real(action, **kw)
        index.setdefault(str(kw.get("request_id")), []).append({"action": action, **kw})

    mp.setattr(sink, "emit", emit)
