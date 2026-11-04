"""CC-9 at dispatch (#1130 slice 3, closes #1869): the owner's mute, quiet hours and desktop master
applied per channel by the `alert.deliver` poller, over the in-memory store (no database, no
network, a fake clock; C-13.5). The Gherkin of E40-S02 Part B, server side: "Muting a symbol
silences without losing the record" and "Quiet hours suppress the optional channels only"."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from _dispatch_env import USER, Clock, MemStore
from test_alert_dispatcher import FailingRelay, Metrics

from candleviewer.alerts.dispatcher import AlertDispatcher, default_adapters
from candleviewer.alerts.owners import OwnerGate
from candleviewer.alerts.preferences import DeliveryPrefs, StoredPrefs
from tests.alerts._owners_env import Directory

OTHER = "00000000-0000-4000-8000-00000000000b"
ETH = {"trigger_type": "crosses_above", "symbol": "ETHUSDT"}
QH = {"enabled": True, "start": "22:00", "end": "07:00", "tz": "Europe/Berlin"}


class _Row(SimpleNamespace):
    key: str
    value: object


class Settings:
    """`UserSettings.read` fake: each user's leaves; `reads`, the users asked; `fail` raises."""

    def __init__(self, leaves: dict[str, dict[str, object]], *, fail: bool = False) -> None:
        self.leaves, self.fail, self.reads = leaves, fail, list[uuid.UUID]()

    async def read(self, user_id: uuid.UUID) -> list[_Row]:
        self.reads.append(user_id)
        if self.fail:
            raise ConnectionError("settings store down")
        return [_Row(key=k, value=v) for k, v in self.leaves.get(str(user_id), {}).items()]


def _world(settings: Settings | None, *, at: datetime | None = None, prefs: Any = None) -> Any:
    clock, changed = Clock(), list[int]()
    if at is not None:
        clock.t = at
    store, relay = MemStore(clock), FailingRelay(fail=0)

    async def on_change(ids: Any) -> None:
        changed.extend(ids)

    disp = AlertDispatcher(
        store, default_adapters(relay), worker="w", now=clock, rng=lambda: 1.0,
        owners=OwnerGate(Directory(everyone=True)), metric=Metrics(), on_change=on_change,
        prefs=prefs if settings is None else StoredPrefs(settings),
    )  # fmt: skip
    return SimpleNamespace(store=store, disp=disp, relay=relay, changed=changed)


def _state(w: Any) -> list[tuple[str, str, str | None, Any]]:
    return [(r.channel, r.status, r.error_message, r.context.get("silenced"))
            for r in w.store.rows.values()]  # fmt: skip


NOON = datetime(2026, 11, 4, 11, 0, tzinfo=UTC)
AT_23_BERLIN = datetime(2026, 11, 4, 22, 0, tzinfo=UTC)


async def test_dispatch_muted_symbol_records_in_app_silenced_and_suppresses_desktop() -> None:
    w = _world(Settings({USER: {"notifications.muted_symbols": [{"symbol": "ETHUSDT"}]}}), at=NOON)
    ids = w.store.fire(["in_app", "desktop"], context=ETH)
    await w.disp.run_once()
    assert _state(w) == [("in_app", "sent", None, "muted_symbol"),
                         ("desktop", "suppressed", "muted_symbol", None)]  # fmt: skip
    assert w.store.rows[2].context["suppression_reason"] == "muted_symbol"
    assert sorted(w.changed) == ids  # both announced: the record is visible in the centre
    assert all(o.processed for o in w.store.outbox.values())


async def test_dispatch_quiet_hours_hold_optional_channels_and_email_is_untouched() -> None:
    w = _world(Settings({USER: {"notifications.quiet_hours": QH}}), at=AT_23_BERLIN)
    w.store.fire(["in_app", "desktop", "email"], context=ETH)
    await w.disp.run_once()
    assert _state(w) == [("in_app", "sent", None, "quiet_hours"),
                         ("desktop", "suppressed", "quiet_hours", None),
                         ("email", "sent", None, None)]  # fmt: skip
    assert len(w.relay.keys) == 1


async def test_dispatch_outside_quiet_hours_delivers_as_before() -> None:
    w = _world(Settings({USER: {"notifications.quiet_hours": QH}}), at=NOON)
    w.store.fire(["in_app", "desktop"], context=ETH)
    await w.disp.run_once()
    assert _state(w) == [("in_app", "sent", None, None), ("desktop", "queued", None, None)]


async def test_dispatch_desktop_off_suppresses_the_desktop_row_only() -> None:
    w = _world(Settings({USER: {"notifications.desktop_enabled": False}}), at=NOON)
    w.store.fire(["in_app", "desktop"], context=ETH)
    await w.disp.run_once()
    assert _state(w) == [("in_app", "sent", None, None),
                         ("desktop", "suppressed", "desktop_off", None)]  # fmt: skip


async def test_dispatch_reads_the_delivery_owners_settings_never_another_users() -> None:
    """RBAC/IDOR: OTHER's mute of ETHUSDT never silences USER's ETHUSDT alert, and each owner's
    settings are read for that owner's rows only."""
    settings = Settings({OTHER: {"notifications.muted_symbols": [{"symbol": "ETHUSDT"}]}})
    w = _world(settings, at=NOON)
    w.store.fire(["in_app", "desktop"], context=ETH, user=USER)
    w.store.fire(["in_app"], context=ETH, user=OTHER)
    await w.disp.run_once()
    assert _state(w) == [("in_app", "sent", None, None), ("desktop", "queued", None, None),
                         ("in_app", "sent", None, "muted_symbol")]  # fmt: skip
    assert settings.reads == [uuid.UUID(USER), uuid.UUID(OTHER)]  # one read per owner per batch


async def test_dispatch_unreadable_settings_deliver_unsuppressed() -> None:
    """A mute is a comfort and a delivery is safe: a failed read never holds or drops a row."""
    w = _world(Settings({}, fail=True), at=AT_23_BERLIN)
    w.store.fire(["in_app", "desktop"], context=ETH)
    await w.disp.run_once()
    assert _state(w) == [("in_app", "sent", None, None), ("desktop", "queued", None, None)]


async def test_dispatch_settings_are_read_afresh_each_batch() -> None:
    settings = Settings({})
    w = _world(settings, at=NOON)
    w.store.fire(["in_app"], context=ETH)
    await w.disp.run_once()
    settings.leaves[USER] = {"notifications.muted_symbols": [{"symbol": "ETHUSDT"}]}
    w.store.fire(["in_app"], context=ETH)
    await w.disp.run_once()
    assert [s for *_, s in _state(w)] == [None, "muted_symbol"]


async def test_dispatch_a_disarm_notice_of_a_muted_symbol_is_not_held() -> None:
    w = _world(Settings({USER: {"notifications.muted_symbols": [{"symbol": "ETHUSDT"}],
                                "notifications.quiet_hours": QH}}), at=AT_23_BERLIN)  # fmt: skip
    w.store.fire(["in_app"], context={"disarmed": True, "symbol": "ETHUSDT"})
    await w.disp.run_once()
    assert _state(w) == [("in_app", "sent", None, None)]


async def test_dispatch_without_a_prefs_source_holds_nothing() -> None:
    w = _world(None, at=AT_23_BERLIN)
    w.store.fire(["in_app", "desktop"], context=ETH)
    await w.disp.run_once()
    assert _state(w) == [("in_app", "sent", None, None), ("desktop", "queued", None, None)]


async def test_dispatch_lost_settle_race_on_a_held_desktop_row_is_not_announced() -> None:
    class Prefs:
        async def prefs(self, user_id: str) -> DeliveryPrefs:
            return DeliveryPrefs(desktop_enabled=False)

    w = _world(None, at=NOON, prefs=Prefs())

    async def lost(job: Any, *, reason: str) -> bool:
        return False  # another worker settled it first

    w.store.settle_suppressed = lost
    w.store.fire(["desktop"], context=ETH)
    await w.disp.run_once()
    assert w.changed == []
