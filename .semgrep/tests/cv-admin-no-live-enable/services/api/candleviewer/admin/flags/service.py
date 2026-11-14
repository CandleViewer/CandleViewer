"""Fixtures for cv-admin-no-live-enable-py: the flag service's named modules are out of its
scope. The key is request data there, and the catalogue declares the flag off with its evidence.
Any other module of the flag service is in scope."""

from candleviewer.admin.flags.registry import LIVE_ENABLED, FlagSpec

SPEC = FlagSpec(LIVE_ENABLED, "boolean", "Master switch", None, False, "all", requires_evidence=True)  # ok: cv-admin-no-live-enable


async def write(store, value):
    return await store.put(LIVE_ENABLED, True)  # ok: cv-admin-no-live-enable
