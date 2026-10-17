"""oms module (M14).

Order state machine, fan-out, brackets, emulated OCO/iceberg/TWAP/chase,
reconciliation, SL invariant.

Public interface only — internal implementation modules are not re-exported.
Allowed dependencies (CONSTITUTION.md C-3.1): M1, M3, M4, M5, M10, M13, M17.

Built so far (the rest lands in the epic that owns this module, see
docs/plan/20-architecture.md Sec.3 and the module table in CONSTITUTION.md Sec.3):

- `Validator`/`ReadOnlyCheck` (E09-T04), always-on ahead of the rest of OMS: it is the
  boundary every future order-placement path must call before accepting a
  position-opening command, so the read-only degradation invariant exists from day one
  rather than being retrofitted once OMS lands.
- The `order_link_id` id path (E29-T02, docs/plan/24-internal-schemas.md Sec.8.3):
  generator and parser (`order_link`), collision-checked allocation
  (`order_link_allocator`), success-after-lookup and history retention
  (`order_link_resolution`), the typed errors (`errors`) and the in-memory lookup fake
  (`fakes`). The submission pipeline that calls them is E29-T04.
- The persistence (E29-T01): `OrderRepository`, `OrderEventRepository`,
  `ExecutionRepository`, `PositionRepository` and `PositionSnapshotRepository`
  (`repository`) over the driver-free stores of M10, the `WriteTimer` behind
  `oms_db_write_seconds{table}`, and `DuplicateOrderLinkId`.

`service.py` (the lifecycle contract) and `models.py` are still the E02-T05 scaffold: the
supervisor can construct and sequence the module, and `start()` builds the `Validator`, but
no other order logic runs yet.
"""

from __future__ import annotations

from .errors import DuplicateOrderLinkId
from .repository import (
    ExecutionRepository,
    OrderEventRepository,
    OrderRepository,
    PositionRepository,
    PositionSnapshotRepository,
    WriteTimer,
)
from .validator import OrderPlacementRefused, ReadOnlyCheck, Validator

__all__: list[str] = [
    "DuplicateOrderLinkId",
    "ExecutionRepository",
    "OrderEventRepository",
    "OrderPlacementRefused",
    "OrderRepository",
    "PositionRepository",
    "PositionSnapshotRepository",
    "ReadOnlyCheck",
    "Validator",
    "WriteTimer",
]
