"""Fixtures for cv-admin-no-flag-lookup: api/ outside the RBAC check is out of its scope."""

from candleviewer.admin.flags import default_registry  # ok: cv-admin-no-flag-lookup


async def get_flag(flags, key: str) -> object:
    return await flags.value(key)  # ok: cv-admin-no-flag-lookup
