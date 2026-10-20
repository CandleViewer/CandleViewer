"""Fixtures for cv-admin-no-flag-lookup: the admin RBAC guard (AC-ADM-14), relative imports too."""

import importlib
from . import flags  # ruleid: cv-admin-no-flag-lookup
from .flags import default_registry  # ruleid: cv-admin-no-flag-lookup
from . import errors  # ok: cv-admin-no-flag-lookup

REGISTRY = importlib.import_module("candleviewer.admin.flags")  # ruleid: cv-admin-no-flag-lookup


async def enter(principal, flags) -> bool:
    if await flags.value("maintenance.mode"):  # ruleid: cv-admin-no-flag-lookup
        return True
    return principal.has("admin:read")  # ok: cv-admin-no-flag-lookup
