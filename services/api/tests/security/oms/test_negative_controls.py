"""E29-X02 (#982), NC-1: the matrix's own credibility (the ticket's Test plan: "temporarily removing
a scope check ... and confirming the corresponding case fails each time"). Each scope layer is
removed in turn by a monkeypatch, and the cells it defends, run again through
`test_rbac_matrix` and `test_ws_scope`, must turn red, for the reason named (`match=`): the answer
the removal lets through. A control that stays green means the cell no longer tests its layer.

- the route's `enforce` (every E29 route module's, 24 Sec.8.4 step 2): a placeOrder on a foreign
  account, a viewer's cancel and a Manager's diagnostics read are admitted;
- the store's scope (the SQL's, as the world's stores hold it: the order store's `_reaches`, the
  read store's `_viewable` and `_reach`): a foreign order or position is found and a list leaks the
  foreign rows (absent-not-hidden fails), while the next layer, where one exists, refuses with
  another code (Q6's creator check, the position write's trade grant);
- the WS gateway's `_may_view` (23 Sec.6.2): a Manager's `orders` sub is not narrowed, and the
  foreign account's frames reach it;
- the fan-out's delivery filter (`ws.sequencing._routed`'s account clause, C-12.4): the sub is
  still narrowed, its `effective` the grant alone, yet each family's foreign frames reach it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Final

import pytest

from candleviewer.api import (
    oms_reads,
    order_cancel_all,
    order_exits,
    orders,
    position_admission,
    position_close,
    position_leverage,
)
from candleviewer.auth.generated_permissions import Scope
from candleviewer.oms.fakes import InMemoryOrderStore
from candleviewer.ws import sequencing
from candleviewer.ws.permissions import ConnectionAuthz
from tests.contract.rbac.rbac_harness import FOREIGN
from tests.security.oms import _cells as cells
from tests.security.oms import test_rbac_matrix as matrix
from tests.security.oms import test_ws_scope as ws
from tests.security.oms._world import ENVIRONMENT, OmsWorld, Reads

_ROUTES: Final = (
    orders, order_exits, order_cancel_all, oms_reads, position_admission, position_close,
    position_leverage,
)  # fmt: skip


def _no_route_enforce(mp: pytest.MonkeyPatch) -> None:
    async def admit(*_args: Any, **_kwargs: Any) -> None:
        return None

    for module in _ROUTES:
        mp.setattr(module, "enforce", admit)


def _no_store_scope(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(InMemoryOrderStore, "_reaches", lambda *_a, **_k: True)
    mp.setattr(Reads, "_viewable", lambda *_a: True)
    mp.setattr(Reads, "_reach", lambda *_a: set(ENVIRONMENT))


_LEAKED: Final = "the answer names what the caller may not see"
_CONTROLS: Final[list[tuple[Callable[[pytest.MonkeyPatch], None], str, str]]] = [
    (_no_route_enforce, "POST /orders|manager_with_grant|foreign", "'403 trading_disabled' =="),
    (_no_route_enforce, "DELETE /orders/{orderId}|viewer|granted", "'404 not_found' =="),
    (_no_route_enforce, "GET /orders/{orderId}/diagnostics|manager_with_grant|granted", "'200' =="),
    (_no_store_scope, "GET /orders/{orderId}|manager_with_grant|foreign", _LEAKED),
    (_no_store_scope, "GET /orders|manager_with_grant|-", _LEAKED),
    (_no_store_scope, "GET /positions|manager_with_grant|-", _LEAKED),
    (_no_store_scope, "DELETE /orders/{orderId}|manager_with_grant|foreign", "'403 forbidden' =="),
    (_no_store_scope, "POST /positions/{positionId}/close|manager_with_grant|foreign",
     "'403 account_scope_denied' =="),
]  # fmt: skip
_BY_ID: Final = {c.id: (c, n) for n, c in enumerate(cells.cells())}


@pytest.mark.parametrize(
    ("remove", "cell_id", "match"),
    _CONTROLS,
    ids=[f"{r.__name__}-{c}" for r, c, _ in _CONTROLS],
)
def test_negative_control_a_cell_fails_with_its_scope_layer_removed(
    world: OmsWorld,
    monkeypatch: pytest.MonkeyPatch,
    remove: Callable[[pytest.MonkeyPatch], None],
    cell_id: str,
    match: str,
) -> None:
    cell, n = _BY_ID[cell_id]
    assert cell.denied or cell.key in cells.LISTS, cell_id  # a refusal, or rows kept absent
    remove(monkeypatch)
    with pytest.raises(AssertionError, match=re.escape(match)):
        matrix.test_every_e29_cell_is_answered_as_the_matrix_and_the_scope_rule_say(world, cell, n)


def test_negative_control_a_sub_beyond_the_grants_is_served_without_may_view(
    world: OmsWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ConnectionAuthz, "_may_view", lambda *_a: True)
    with pytest.raises(AssertionError, match=re.escape(str(FOREIGN))):
        ws.test_a_private_sub_beyond_the_grants_is_narrowed_or_refused_and_never_echoed(
            world, "orders", "manager_with_grant"
        )


def _no_delivery_filter(mp: pytest.MonkeyPatch) -> None:
    """`_routed` without its account clause: an account family's delta reaches every one of its
    subscriptions, whatever accounts the subscription holds (the scope at `sub` untouched)."""
    real = sequencing._routed

    def routed(authz: Any, sub: Any, account: Any, user: Any) -> bool | None:
        answer = real(authz, sub, account, user)
        if answer is False and sub.topic.family.scope is Scope.GRANTED_ACCOUNTS:
            return account is not None
        return answer

    mp.setattr(sequencing, "_routed", routed)


@pytest.mark.parametrize("family", ws._FAMILIES)
def test_negative_control_a_narrowed_sub_is_sent_foreign_frames_without_the_delivery_filter(
    world: OmsWorld, monkeypatch: pytest.MonkeyPatch, family: str
) -> None:
    _no_delivery_filter(monkeypatch)
    with pytest.raises(AssertionError, match="a denied id was echoed"):
        ws.test_a_private_sub_beyond_the_grants_is_narrowed_or_refused_and_never_echoed(
            world, family, "manager_with_grant"
        )
