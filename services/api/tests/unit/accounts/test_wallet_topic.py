"""E27-T04 (#837) W4b: the `wallet` topic (`accounts/wallet_topic.py`) on the real gateway parts:
what a snapshot holds for the caller's scope (C-12.4), the health-only delta of a transition, the
balance delta of a refresh and of a turn to stale, and a delta that fails. Fake clock; every frame a
subscriber gets is validated against 23-ws-protocol.md §15.4."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.accounts.health import HealthState, epoch_ms
from candleviewer.accounts.wallet_topic import WalletTopic
from candleviewer.auth.generated_permissions import Permission
from candleviewer.ws.sequencing import SnapshotBody
from tests.unit.accounts._fakes import ACC, ACC_B, T0
from tests.unit.accounts._runtime_rig import snapshot
from tests.unit.accounts._wallet_ws import WalletWorld, manager, owner

_ACC_C = UUID(int=3)
_ACC_D = UUID(int=4)


@dataclass(frozen=True)
class _Sub:
    accounts: frozenset[UUID]


class _Published(list[tuple[str, dict[str, Any], UUID]]):
    """A hub's `publish` that records each delta, or raises `error`."""

    error: Exception | None = None

    def __call__(self, ch: str, body: Mapping[str, Any], *, account: UUID) -> int:
        if self.error is not None:
            raise self.error
        self.append((ch, dict(body), account))
        return 1


class _BrokenViews:
    """A monitor or wallet cache whose every read raises."""

    def view(self, account_id: UUID) -> None:
        raise RuntimeError("echoed exchange text: key abc123")


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [entry["exchange_account_id"] for entry in entries]


def _recorded(world: WalletWorld) -> tuple[WalletTopic[SnapshotBody], _Published]:
    published = _Published()
    topic = WalletTopic(published, SnapshotBody)
    topic.attach(world.monitor, world.wallets)
    return topic, published


def test_a_manager_snapshot_holds_only_its_granted_accounts() -> None:
    world = WalletWorld()
    conn = world.conn(manager(ACC))
    result = conn.sub(ACC, ACC_B)  # B is monitored and has a balance, but is not granted
    [(kind, body)] = conn.take()
    assert result["effective"]["exchange_account_ids"] == [str(ACC)] and kind == "snap"
    assert _ids(body["health"]) == _ids(body["balances"]) == [str(ACC)]


def test_an_owner_snapshot_lists_each_monitored_account_asked_for_and_each_balance() -> None:
    world = WalletWorld()
    world.monitor.track(_ACC_C)
    world.wallets.track(_ACC_C)  # monitored, never connected, no wallet snapshot yet
    conn = world.conn(owner())
    conn.sub(ACC_B, _ACC_D, _ACC_C, ACC)  # D is not monitored
    [(_, body)] = conn.take()
    view = world.monitor.view(_ACC_C)
    assert view is not None and body["health"][0] == view.ws_entry(_ACC_C)
    assert _ids(body["health"]) == [str(_ACC_C), str(ACC), str(ACC_B)]
    assert _ids(body["balances"]) == [str(ACC), str(ACC_B)]


def test_a_caller_without_accounts_read_gets_no_snapshot_and_no_frame() -> None:
    world = WalletWorld()
    conn = world.conn(manager(ACC, permissions=frozenset({Permission.ORDERS_READ})))
    result = conn.sub(ACC)
    world.monitor.ws_dropped(ACC)
    world.topic.health_changed(ACC)
    world.topic.balance_refreshed(ACC)
    assert (result["ok"], result["error"]["code"]) == (False, "forbidden") and conn.take() == []


def test_a_delta_never_reaches_a_subscriber_whose_principal_lost_accounts_read() -> None:
    world = WalletWorld()
    conn = world.conn(manager(ACC))
    conn.sub(ACC)
    conn.take()
    conn.authz.principal = manager(ACC, permissions=frozenset())  # §9.5 swaps it in first
    world.monitor.ws_dropped(ACC)
    world.topic.health_changed(ACC)
    world.topic.balance_refreshed(ACC)
    assert conn.take() == []


def test_a_transition_is_one_health_only_delta_and_reaches_only_its_accounts_scope() -> None:
    world = WalletWorld()
    on_a, on_b = world.conn(manager(ACC)), world.conn(manager(ACC_B))
    on_a.sub(ACC)
    on_b.sub(ACC_B)
    on_a.take()
    on_b.take()
    world.clock.advance(1)
    moved = world.monitor.ws_dropped(ACC)
    world.topic.health_changed(ACC)
    view = world.monitor.view(ACC)
    assert moved is not None and view is not None and view.state is HealthState.DEGRADED
    assert on_a.take() == [("d", {"balances": [], "health": [view.ws_entry(ACC)]})]
    assert on_b.take() == []


def test_a_refresh_is_one_balance_delta_with_plain_decimals_and_no_health() -> None:
    world = WalletWorld()
    conn = world.conn(manager(ACC))
    conn.sub(ACC)
    conn.take()
    world.clock.advance(1)
    tiny = snapshot(world.clock.now()).model_copy(update={"account_mm_rate": Decimal("1E-7")})
    assert world.wallets.apply(ACC, tiny)
    world.topic.balance_refreshed(ACC)
    item: dict[str, Any] = {"exchange_account_id": str(ACC), "coin": "USDT", "equity": "1000.50"}
    item |= {"wallet_balance": "1000", "available_balance": "800.25", "unrealised_pnl": "0.50"}
    item |= {"account_im_rate": "0.0125", "account_mm_rate": "0.0000001", "stale": False}
    item |= {"stale_since_ms": None, "updated_at_ms": epoch_ms(T0 + timedelta(seconds=1))}
    assert conn.take() == [("d", {"balances": [item]})]


def test_a_refreshed_balance_turning_stale_is_one_more_delta_and_no_other_check_sends_one() -> None:
    world = WalletWorld()  # refreshed at T0
    conn = world.conn(manager(ACC))
    conn.sub(ACC)
    world.topic.balance_refreshed(ACC)
    conn.take()
    world.clock.advance(10)
    world.topic.stale_check()  # exactly 10 s old is not stale yet
    assert conn.take() == []
    world.clock.advance(0.001)
    for _ in range(20):  # ten seconds of the runtime's tick
        world.topic.stale_check()
        world.clock.advance(0.5)
    [(kind, body)] = conn.take()
    [item] = body["balances"]
    since = epoch_ms(T0 + timedelta(seconds=10))
    assert (kind, item["stale"], item["stale_since_ms"]) == ("d", True, since)


def test_a_balance_already_stale_when_its_refresh_goes_out_is_not_sent_again() -> None:
    world = WalletWorld()  # refreshed at T0; its delta goes out late, after the stale window
    conn = world.conn(manager(ACC))
    conn.sub(ACC)
    conn.take()
    world.clock.advance(11)
    world.topic.balance_refreshed(ACC)
    world.clock.advance(1)
    world.topic.stale_check()
    [(_, body)] = conn.take()
    assert [item["stale"] for item in body["balances"]] == [True]


def test_each_delta_names_its_account_to_the_hub() -> None:
    topic, published = _recorded(WalletWorld())
    topic.health_changed(ACC)
    topic.balance_refreshed(ACC_B)
    assert [(ch, account) for ch, _, account in published] == [("wallet", ACC), ("wallet", ACC_B)]


def test_an_account_that_is_not_monitored_publishes_nothing() -> None:
    world = WalletWorld()
    topic, published = _recorded(world)
    topic.balance_refreshed(ACC)
    world.wallets.untrack(ACC)
    world.clock.advance(11)
    topic.stale_check()  # the balance it sent is gone with the account, not turned stale
    topic.health_changed(_ACC_C)
    topic.balance_refreshed(_ACC_C)
    assert [account for _, _, account in published] == [ACC]


def test_until_it_is_attached_the_topic_builds_nothing_and_it_attaches_once() -> None:
    world = WalletWorld()
    topic = WalletTopic(_Published(), SnapshotBody)
    sub = _Sub(frozenset({ACC}))
    assert topic.build(sub) is None
    topic.attach(world.monitor, world.wallets)
    assert topic.build(sub) is not None
    assert topic.generation(sub) == 0 and topic.continuity(sub, 1) is False
    with pytest.raises(ValueError, match="attached"):
        topic.attach(world.monitor, world.wallets)


@pytest.mark.parametrize("broken", ["publish", "read"])
def test_a_delta_that_fails_is_logged_by_its_type_and_reaches_no_caller(broken: str) -> None:
    world = WalletWorld()
    published = _Published()
    topic = WalletTopic(published, SnapshotBody)
    if broken == "publish":
        published.error = RuntimeError("echoed exchange text: key abc123")
        topic.attach(world.monitor, world.wallets)
    else:
        topic.attach(_BrokenViews(), _BrokenViews())
    with capture_logs() as logs:
        topic.health_changed(ACC)
        topic.balance_refreshed(ACC)
    failed = ("wallet_topic.publish_failed", "error", "RuntimeError")
    assert [(e["event"], e["log_level"], e["error"]) for e in logs] == [failed] * 2
    assert "abc123" not in repr(logs) and published == []
