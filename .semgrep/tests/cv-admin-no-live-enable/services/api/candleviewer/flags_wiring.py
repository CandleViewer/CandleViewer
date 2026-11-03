"""Fixtures for cv-admin-no-live-enable-py: the flag wiring names the key to read it, and any
write of it there with a value that is not a literal off, by position or by any keyword that may
carry one, is a finding; a change hook is a write."""

from candleviewer.admin.flags import LIVE_ENABLED, StoredFlag


async def wiring(self, store, view, writer, principal, on, current, turn_on, f):
    await store.put(LIVE_ENABLED, on)  # ruleid: cv-admin-no-live-enable
    await store.write(LIVE_ENABLED, turn_on)  # ruleid: cv-admin-no-live-enable
    await store.write(LIVE_ENABLED, lambda row: StoredFlag(row.value))  # ruleid: cv-admin-no-live-enable
    await view.on_change(LIVE_ENABLED, current, StoredFlag(on))  # ruleid: cv-admin-no-live-enable
    await view.on_change(LIVE_ENABLED, None, current)  # ruleid: cv-admin-no-live-enable
    await store.write(LIVE_ENABLED, prepare=turn_on)  # ruleid: cv-admin-no-live-enable
    await writer.set(LIVE_ENABLED, principal, enabled=on)  # ruleid: cv-admin-no-live-enable
    await writer.set(LIVE_ENABLED, principal, value=False, user_overrides=on)  # ruleid: cv-admin-no-live-enable
    await writer.set(key=LIVE_ENABLED, principal=principal, after=on)  # ruleid: cv-admin-no-live-enable
    await writer.set(flag=LIVE_ENABLED, principal=principal)  # ruleid: cv-admin-no-live-enable
    self.live_enabled = FlagView(self, LIVE_ENABLED)  # ok: cv-admin-no-live-enable
    await view.on_change(LIVE_ENABLED, None, StoredFlag(False))  # ok: cv-admin-no-live-enable
    await view.on_change(LIVE_ENABLED, None, False)  # ok: cv-admin-no-live-enable
    await writer.set(LIVE_ENABLED, principal, value=False, reason="r", fingerprint=f)  # ok: cv-admin-no-live-enable
    await store.put(LIVE_ENABLED, False)  # ok: cv-admin-no-live-enable
    return await store.get(LIVE_ENABLED)  # ok: cv-admin-no-live-enable
