"""E27-T04 (#837): the `wallet` topic (`accounts/wallet_topic.py`) on the real gateway parts:
what a snapshot holds for the caller's scope (C-12.4), the health-only delta of a transition, the
balance delta of a refresh and of a turn to stale, and a delta or an item that fails. Fake clock;
every frame a subscriber gets is validated against 23-ws-protocol.md §15.4."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.accounts.health import AccountHealth, HealthState, epoch_ms
from candleviewer.accounts.status import HealthViews
from candleviewer.accounts.wallet import WalletSnapshot
from candleviewer.accounts.wallet_topic import LOG_INTERVAL_S, WalletTopic
from candleviewer.auth.generated_permissions import Permission
from candleviewer.ws.sequencing import SnapshotBody
from tests.unit.accounts._fakes import ACC, ACC_B, T0
from tests.unit.accounts._runtime_rig import snapshot
from tests.unit.accounts._wallet_ws import WalletWorld, manager, owner

_ACC_C = UUID(int=3)
_ACC_D = UUID(int=4)
_ECHO = "echoed exchange text: key abc123"  # what a failing collaborator's message may carry


@dataclass(frozen=True)
class _Sub:
    accounts: frozenset[UUID]


class _Published(list[tuple[str, dict[str, Any], UUID]]):
    """A hub's `publish` that records each delta, or raises `error`."""

    error: BaseException | None = None

    def __call__(self, ch: str, body: Mapping[str, Any], *, account: UUID) -> int:
        if self.error is not None:
            raise self.error
        self.append((ch, dict(body), account))
        return 1


class _Views:
    """A monitor's `view` as it is, until `error` is set: then every read raises it."""

    error: BaseException | None = None

    def __init__(self, inner: HealthViews) -> None:
        self._inner = inner

    def view(self, account_id: UUID) -> AccountHealth | None:
        if self.error is not None:
            raise self.error
        return self._inner.view(account_id)


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [entry["exchange_account_id"] for entry in entries]


def _recorded(world: WalletWorld) -> tuple[WalletTopic[SnapshotBody], _Published]:
    published = _Published()
    topic = WalletTopic(published, SnapshotBody, clock=world.clock.monotonic)
    topic.attach(world.monitor, world.wallets)
    return topic, published


def _breakable() -> tuple[WalletTopic[SnapshotBody], _Views, _Published]:
    """The topic with ACC's balance out fresh and its turn to stale come; what its reads and its
    hub raise is for the test to set."""
    world = WalletWorld()
    views, published = _Views(world.monitor), _Published()
    topic = WalletTopic(published, SnapshotBody, clock=world.clock.monotonic)
    topic.attach(views, world.wallets)
    topic.balance_refreshed(ACC)  # out fresh: it owes a turn to stale
    world.clock.advance(11)  # and the turn has come
    published.clear()
    return topic, views, published


def _unbuildable(world: WalletWorld) -> WalletSnapshot:
    """A balance the snapshot type refuses (an exponent out of range), as one that got past the type
    would be: `model_copy` validates nothing."""
    return snapshot(world.clock.now()).model_copy(update={"equity": Decimal("1E+41")})


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
    with capture_logs() as logs:
        conn.sub(ACC_B, _ACC_D, _ACC_C, ACC)  # D is not monitored
    [(_, body)] = conn.take()
    view = world.monitor.view(_ACC_C)
    assert view is not None and body["health"][0] == view.ws_entry(_ACC_C)
    assert _ids(body["health"]) == [str(_ACC_C), str(ACC), str(ACC_B)]
    assert _ids(body["balances"]) == [str(ACC), str(ACC_B)]
    assert logs == []  # no wallet snapshot is not a failure: a guard that is gone would log it


def test_a_snapshot_lists_its_accounts_in_account_order_not_the_order_of_the_scope() -> None:
    world = WalletWorld()
    late, early = UUID(int=9), UUID(int=2)
    for account in (late, early):
        world.monitor.track(account)
        world.wallets.track(account)
        world.wallets.apply(account, snapshot(T0))
    scope = frozenset({late, early})
    assert list(scope) == [late, early]  # a set's own order is not the account order
    body = world.topic.build(_Sub(scope))
    assert body is not None
    wanted = [str(early), str(late)]
    assert _ids(body.structured["health"]) == _ids(body.structured["balances"]) == wanted


def test_a_snapshot_still_serves_the_others_when_one_balance_cannot_be_built() -> None:
    world = WalletWorld()
    assert world.wallets.apply(ACC, _unbuildable(world))
    conn = world.conn(owner())
    with capture_logs() as logs:
        conn.sub(ACC, ACC_B)
    [(kind, body)] = conn.take()
    shape = (kind, _ids(body["health"]), _ids(body["balances"]))
    assert shape == ("snap", [str(ACC), str(ACC_B)], [str(ACC_B)])  # ACC's health, not its balance
    assert [(e["path"], e["failed_in"], e["error"]) for e in logs] == [
        ("build", "read_model", "ValueError")
    ]


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
    world.topic.balance_refreshed(ACC)  # each is out fresh and owes a turn to stale, to its scope
    world.topic.balance_refreshed(ACC_B)
    on_a.take()
    on_b.take()
    world.clock.advance(1)
    moved = world.monitor.ws_dropped(ACC)
    world.topic.health_changed(ACC)
    view = world.monitor.view(ACC)
    assert moved is not None and view is not None and view.state is HealthState.DEGRADED
    assert on_a.take() == [("d", {"balances": [], "health": [view.ws_entry(ACC)]})]
    assert on_b.take() == []
    world.monitor.ws_dropped(ACC_B)  # and the other way round: B's entry, not under A's account
    world.topic.health_changed(ACC_B)
    view_b = world.monitor.view(ACC_B)
    assert view_b is not None and view_b.state is HealthState.DEGRADED
    assert on_b.take() == [("d", {"balances": [], "health": [view_b.ws_entry(ACC_B)]})]
    assert on_a.take() == []


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


def test_a_balance_delta_and_a_retried_turn_go_out_only_in_their_own_accounts_scope() -> None:
    """SR-152 (04-security-program.md section 6.16), cross-account: with two accounts owed, the
    delta of one is published under that account alone (C-12.4), never batched or scoped under
    the other."""
    world = WalletWorld()
    topic, published = _recorded(world)
    topic.balance_refreshed(ACC)
    topic.balance_refreshed(ACC_B)  # both out fresh: each owes its turn to stale
    world.clock.advance(11)
    published.error = RuntimeError(_ECHO)
    with capture_logs():
        topic.stale_check()  # both turns fail
    published.error = None
    topic.stale_check()  # the next tick sends each again
    sent = [(account, _ids(body["balances"])) for _, body, account in published]
    assert sent == [(account, [str(account)]) for account in (ACC, ACC_B, ACC, ACC_B)]


def test_a_manager_never_receives_another_accounts_balance_from_a_refresh_or_a_turn() -> None:
    world = WalletWorld()
    on_a, on_b = world.conn(manager(ACC)), world.conn(manager(ACC_B))
    on_a.sub(ACC)
    on_b.sub(ACC_B)
    on_a.take()
    on_b.take()
    world.topic.balance_refreshed(ACC)
    world.topic.balance_refreshed(ACC_B)
    world.clock.advance(11)
    world.topic.stale_check()
    seen_by_a = [(kind, _ids(body["balances"])) for kind, body in on_a.take()]
    seen_by_b = [(kind, _ids(body["balances"])) for kind, body in on_b.take()]
    assert seen_by_a == [("d", [str(ACC)])] * 2  # its refresh, then its turn to stale
    assert seen_by_b == [("d", [str(ACC_B)])] * 2


def test_each_delta_names_its_account_to_the_hub() -> None:
    topic, published = _recorded(WalletWorld())
    topic.health_changed(ACC)
    topic.balance_refreshed(ACC_B)
    assert [(ch, account) for ch, _, account in published] == [("wallet", ACC), ("wallet", ACC_B)]


def test_an_account_that_is_not_monitored_publishes_nothing_and_logs_no_failure() -> None:
    world = WalletWorld()
    topic, published = _recorded(world)
    topic.balance_refreshed(ACC)
    world.wallets.untrack(ACC)
    world.clock.advance(11)
    with capture_logs() as logs:  # a guard that is gone would fail on its None and log it
        topic.stale_check()  # the balance it sent is gone with the account, not turned stale
        topic.health_changed(_ACC_C)
        topic.balance_refreshed(_ACC_C)
    assert [account for _, _, account in published] == [ACC] and logs == []


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


_PATHS: dict[str, Callable[[WalletTopic[SnapshotBody]], None]] = {
    "health_changed": lambda topic: topic.health_changed(ACC),
    "balance_refreshed": lambda topic: topic.balance_refreshed(ACC),
    "stale_check": lambda topic: topic.stale_check(),
}
#: What the monitor's reads and what the hub raise, and the side the log line names.
_SIDES = [
    pytest.param(RuntimeError(_ECHO), None, "read_model", id="read-model"),
    pytest.param(None, RuntimeError(_ECHO), "hub", id="hub"),
]


@pytest.mark.parametrize("path", _PATHS)
@pytest.mark.parametrize(("read_error", "hub_error", "failed_in"), _SIDES)
def test_a_delta_that_fails_is_logged_by_its_type_with_its_path_and_the_side_that_failed(
    path: str, read_error: BaseException | None, hub_error: BaseException | None, failed_in: str
) -> None:
    topic, views, published = _breakable()
    views.error, published.error = read_error, hub_error
    with capture_logs() as logs:
        _PATHS[path](topic)
    expected = {
        "event": "wallet_topic.publish_failed",
        "log_level": "error",
        "error": "RuntimeError",
        "path": path,
        "failed_in": failed_in,
        "suppressed": 0,
    }
    assert logs == [expected] and _ECHO not in repr(logs) and published == []


@pytest.mark.parametrize(
    ("read_error", "hub_error"),
    [(asyncio.CancelledError(), None), (None, asyncio.CancelledError())],
    ids=["read-model", "hub"],
)
def test_a_cancellation_is_not_contained_whichever_side_raises_it(
    read_error: BaseException | None, hub_error: BaseException | None
) -> None:
    topic, views, published = _breakable()
    views.error, published.error = read_error, hub_error
    with pytest.raises(asyncio.CancelledError):
        topic.health_changed(ACC)


def test_a_persistent_failure_logs_once_per_interval_and_counts_the_ones_it_held_back() -> None:
    world = WalletWorld()
    topic, published = _recorded(world)
    published.error = RuntimeError(_ECHO)
    with capture_logs() as logs:
        for _ in range(int(2 * LOG_INTERVAL_S) + 1):  # a failed delta a second, for two intervals
            topic.health_changed(ACC)
            world.clock.advance(1)
    held = int(LOG_INTERVAL_S) - 1
    assert [line["suppressed"] for line in logs] == [0, held, held]


def test_a_turn_to_stale_whose_publish_failed_is_sent_again_on_the_next_tick() -> None:
    world = WalletWorld()
    topic, published = _recorded(world)
    topic.balance_refreshed(ACC)  # out fresh: it owes a turn to stale
    world.clock.advance(11)
    published.error = RuntimeError(_ECHO)
    with capture_logs():
        topic.stale_check()  # the turn to stale: its publish fails
    published.error = None
    topic.stale_check()  # the next tick sends it
    topic.stale_check()  # once
    assert [item["stale"] for _, body, _ in published for item in body["balances"]] == [False, True]


def test_a_refresh_whose_publish_failed_still_owes_its_turn_to_stale() -> None:
    world = WalletWorld()
    topic, published = _recorded(world)
    published.error = RuntimeError(_ECHO)
    with capture_logs():
        topic.balance_refreshed(ACC)  # its publish fails: no item is out
    published.error = None
    world.clock.advance(11)
    topic.stale_check()
    assert [item["stale"] for _, body, _ in published for item in body["balances"]] == [True]


def test_an_account_that_lost_its_balance_is_forgotten_and_owes_no_turn_to_stale_later() -> None:
    world = WalletWorld()
    topic, published = _recorded(world)
    topic.balance_refreshed(ACC)  # out fresh: it owes a turn to stale
    world.wallets.untrack(ACC)
    topic.stale_check()  # its balance is gone: what it owed is forgotten
    world.wallets.track(ACC)
    world.wallets.apply(ACC, snapshot(world.clock.now()))  # a balance the topic was never told of
    world.clock.advance(11)
    topic.stale_check()
    assert [account for _, _, account in published] == [ACC]  # the first fresh item, nothing after


def test_an_item_that_cannot_be_built_is_forgotten_not_retried_at_every_tick() -> None:
    world = WalletWorld()
    topic, published = _recorded(world)
    topic.balance_refreshed(ACC)  # out fresh: it owes a turn to stale
    world.clock.advance(1)
    assert world.wallets.apply(ACC, _unbuildable(world))  # a refresh the topic is not told of
    world.clock.advance(11)  # the turn has come, with an item that cannot be built
    with capture_logs() as logs:
        for _ in range(3):  # a tick an interval apart: a retry would log each time
            topic.stale_check()
            world.clock.advance(LOG_INTERVAL_S)
    assert [line["path"] for line in logs] == ["stale_check"] and len(published) == 1


def test_a_refresh_whose_item_cannot_be_built_owes_no_turn_to_stale() -> None:
    world = WalletWorld()
    topic, published = _recorded(world)
    assert world.wallets.apply(ACC, _unbuildable(world))
    with capture_logs() as refreshed:
        topic.balance_refreshed(ACC)  # nothing goes out, so nothing is owed
    world.clock.advance(11 + LOG_INTERVAL_S)
    with capture_logs() as ticked:
        topic.stale_check()
    assert [line["path"] for line in refreshed] == ["balance_refreshed"]
    assert ticked == [] and published == []
