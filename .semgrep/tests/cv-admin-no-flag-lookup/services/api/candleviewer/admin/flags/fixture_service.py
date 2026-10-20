"""Fixtures for cv-admin-no-flag-lookup: the flag module itself is out of its scope."""

from candleviewer.admin.flags.catalogue import LIVE_ENABLED  # ok: cv-admin-no-flag-lookup


async def live(flags) -> bool:
    return await flags.value("trading.live_enabled")  # ok: cv-admin-no-flag-lookup
