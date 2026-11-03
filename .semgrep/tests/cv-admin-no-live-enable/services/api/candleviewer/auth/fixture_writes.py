"""Fixtures for cv-admin-no-live-enable-py: no server module turns the live gate on, by the
literal key or the catalogue's constant, with any value but a literal off; and the key keeps its
spellings, so another name for it (a binding, an aliased import, a container) is a finding too."""

from candleviewer.admin.flags import LIVE_ENABLED, catalogue
from candleviewer.admin.flags.registry import LIVE_ENABLED as GATE  # ruleid: cv-admin-no-live-enable
from candleviewer.admin.flags.store import FlagWrite, StoredFlag

KEY = "trading.live_enabled"  # ruleid: cv-admin-no-live-enable


async def turns_it_on(
    writer, store, principal, view, rows, at, actor, on, request, decide, current
):
    await writer.set("trading.live_enabled", principal, value=True)  # ruleid: cv-admin-no-live-enable
    await writer.set(LIVE_ENABLED, principal, reason="r", value=True)  # ruleid: cv-admin-no-live-enable
    await writer.set(catalogue.LIVE_ENABLED, principal, value=True)  # ruleid: cv-admin-no-live-enable
    FlagWrite(key=LIVE_ENABLED, value=True, expected_updated_at=at, actor=actor)  # ruleid: cv-admin-no-live-enable
    store.put(GATE, True)  # ruleid: cv-admin-no-live-enable
    store.put(KEY, "true")  # ruleid: cv-admin-no-live-enable
    rows["trading.live_enabled"] = True  # ruleid: cv-admin-no-live-enable
    rows[LIVE_ENABLED] = StoredFlag(True)  # ruleid: cv-admin-no-live-enable
    await view.on_change(LIVE_ENABLED, None, StoredFlag(value=True))  # ruleid: cv-admin-no-live-enable
    await store.execute("UPDATE", {"key": LIVE_ENABLED, "value": "true"})  # ruleid: cv-admin-no-live-enable
    await writer.set(LIVE_ENABLED, principal, value=on)  # ruleid: cv-admin-no-live-enable
    await writer.set(catalogue.LIVE_ENABLED, principal, value=request.on)  # ruleid: cv-admin-no-live-enable
    await writer.set("trading." + "live_enabled", principal, value=decide())  # ruleid: cv-admin-no-live-enable
    FlagWrite(value=on, expected_updated_at=at, key=LIVE_ENABLED)  # ruleid: cv-admin-no-live-enable
    store.put(True, LIVE_ENABLED)  # ruleid: cv-admin-no-live-enable
    rows[LIVE_ENABLED] = on  # ruleid: cv-admin-no-live-enable
    await store.execute("UPDATE", {"value": request.on, "key": LIVE_ENABLED})  # ruleid: cv-admin-no-live-enable
    await view.on_change(LIVE_ENABLED, None, current)  # ruleid: cv-admin-no-live-enable
    return {"trading.live_enabled": on}  # ruleid: cv-admin-no-live-enable


def renames_it():
    gate = LIVE_ENABLED  # ruleid: cv-admin-no-live-enable
    other: str = catalogue.LIVE_ENABLED  # ruleid: cv-admin-no-live-enable
    keys = (LIVE_ENABLED,)  # ruleid: cv-admin-no-live-enable
    names = [catalogue.LIVE_ENABLED]  # ruleid: cv-admin-no-live-enable
    by_role = {"live": "trading.live_enabled"}  # ruleid: cv-admin-no-live-enable
    return gate, other, keys, names, by_role


async def leaves_it_off(writer, store, principal, flags, rows, settings, view, current):
    await writer.set(LIVE_ENABLED, principal, value=False)  # ok: cv-admin-no-live-enable
    await writer.set("trading.one_click", principal, value=True)  # ok: cv-admin-no-live-enable
    live = await flags.value(LIVE_ENABLED)  # ok: cv-admin-no-live-enable
    view = flags.FlagView(flags, LIVE_ENABLED)  # ok: cv-admin-no-live-enable
    rows[LIVE_ENABLED] = StoredFlag(False)  # ok: cv-admin-no-live-enable
    flags.require(LIVE_ENABLED, requires_evidence=True)  # ok: cv-admin-no-live-enable
    on = settings.trading_live_enabled  # ok: cv-admin-no-live-enable
    note = "trading.live_enabled = True only through E44-T04"  # ok: cv-admin-no-live-enable
    await store.execute("SELECT", {"key": LIVE_ENABLED, "visible": True})  # ok: cv-admin-no-live-enable
    await writer.set(LIVE_ENABLED, principal, value=None)  # ok: cv-admin-no-live-enable
    await store.execute("SELECT", {"key": LIVE_ENABLED})  # ok: cv-admin-no-live-enable
    return {"trading.one_click": True, LIVE_ENABLED: False}  # ok: cv-admin-no-live-enable
