"""Which operations the view-as guard lets through (#3085; 22-api-openapi.yaml "View-as session").

A request of a session that holds a view-as context is refused unless it reads in a live context
or its operation is one of these:

- The viewer's own operations (`OWN_OPERATIONS`). They act on the viewer's own session, as the
  viewer, so none of the view-as rules applies to them, and leaving view-as is one call that
  nothing refuses. The contract lists them in prose only; a test reads that list from its text.
- The protective writes (C-2.6, `PROTECTIVE_WRITES`). Their handlers decide after validation, by
  the classification of 24-internal-schemas.md section 8.10, or need none for a cancel, which is
  protective in whole; so the guard passes them on once a handler has registered
  (`ProtectiveWrites`). Until then it refuses them as any write: fail closed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Final

#: The viewer's own operations, (METHOD, contract path template): the start, reading and ending
#: the context, the session's own read, refresh, logout, extension and unlock, and the bucket
#: counts of `POST /telemetry/frontend`.
OWN_OPERATIONS: Final = frozenset(
    {
        ("POST", "/admin/view-as"),
        ("GET", "/auth/session/view-as"),
        ("DELETE", "/auth/session/view-as"),
        ("GET", "/auth/session"),
        ("POST", "/auth/refresh"),
        ("POST", "/auth/logout"),
        ("POST", "/auth/session/extend"),
        ("POST", "/auth/unlock"),
        ("POST", "/telemetry/frontend"),
    }
)

#: The protective writes, by operationId: (METHOD, contract path template), and the ticket that
#: mounts the handler. The app's contract subset carries no operationIds, so each is named twice; a
#: test pins the pairs to the contract.
PROTECTIVE_WRITES: Final[Mapping[str, tuple[tuple[str, str], str]]] = MappingProxyType(
    {
        "setKillSwitch": (("POST", "/trading/kill-switch"), "E39-S03"),
        "amendOrder": (("PATCH", "/orders/{orderId}"), "E29-T04"),
        "amendTradeGroup": (("POST", "/trade-groups/{tradeGroupId}/amend"), "E34-S03"),
        "setPositionTpSl": (("PUT", "/positions/{positionId}/tpsl"), "E29-T07"),
        "cancelOrder": (("DELETE", "/orders/{orderId}"), "E29-T04"),
        "cancelAllOrders": (("POST", "/orders/cancel-all"), "E29-T04"),
    }
)


class ProtectiveWrites:
    """The protective writes' registry and its tripwire.

    Three of the six handlers are registered, `cancelAllOrders`, `cancelOrder` and `amendOrder`
    (E29-T04, #913 slice 4); E39-S03 mounts `setKillSwitch`, E29-T07 `setPositionTpSl` and E34-S03
    `amendTradeGroup`. Each handler registers its operation as it is mounted (`register`). It then
    decides view-as itself, after validation and before it asks for a step-up (#3223 item 4,
    option a), by the classification of 24 Sec.8.10 (`oms.exits.protective_amend` for an amend).
    A request with any non-protective component is refused `view_as_read_only`, or
    `view_as_expired` in a hold, before any effect, binds no key and writes its refusal record
    (`ViewAsRefusalRecorder.refuse_operation`, through `view_as_guard.refuse_component`); a cancel
    has none, as every cancel is a risk-reducing exit (C-2.6; 22 "View-as session", Protective
    writes). The write runs as the viewer and is admitted only when both the viewer's own RBAC and
    the target's allow it; in the hold it runs in the viewer's own scope.

    The contract makes engaging the kill switch on an account set (`engaged: true`,
    `scope: accounts`) protective, and refuses its release and `scope: global`. Any default
    beyond that is the owner's decision for E39 (#3223 item 3).

    Until an operation is registered, the guard refuses it as any write: the tripwire."""

    def __init__(self, operations: Iterable[tuple[str, str]]) -> None:
        """*operations*: the contract's declared operations, which must hold every protective
        write."""
        self._ids = {operation: id_ for id_, (operation, _) in PROTECTIVE_WRITES.items()}
        if missing := sorted(self._ids.keys() - frozenset(operations)):
            raise ValueError(f"undeclared protective writes: {missing}")
        self._registered: set[str] = set()

    def register(self, operation_id: str) -> None:
        """Its handler decides view-as from now on (the class docstring)."""
        if operation_id not in PROTECTIVE_WRITES:
            raise ValueError(f"{operation_id!r} is not a protective write")
        self._registered.add(operation_id)

    def is_registered(self, operation: tuple[str, str]) -> bool:
        return self._ids.get(operation) in self._registered
