"""Fixtures for cv-admin-no-live-enable-py: tests are out of its scope; they turn the flag on
in memory to prove the gate refuses without the setting."""

from candleviewer.admin.flags import LIVE_ENABLED, StoredFlag


async def test_flag_on_alone(flags):
    await flags.live_enabled.on_change(LIVE_ENABLED, None, StoredFlag(True))  # ok: cv-admin-no-live-enable
