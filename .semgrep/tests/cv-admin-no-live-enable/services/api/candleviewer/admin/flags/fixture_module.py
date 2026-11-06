"""Fixtures for cv-admin-no-live-enable-py: a new module of the flag service is in scope."""

from candleviewer.admin.flags.registry import LIVE_ENABLED


async def seed(store):
    await store.put(LIVE_ENABLED, True)  # ruleid: cv-admin-no-live-enable
