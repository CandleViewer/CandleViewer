"""Fixtures for cv-admin-no-flag-lookup: the deny-by-default route check (AC-ADM-14)."""

from ..admin import flags  # ruleid: cv-admin-no-flag-lookup
from ..admin import errors  # ok: cv-admin-no-flag-lookup
from candleviewer.admin import flags as admin_flags  # ruleid: cv-admin-no-flag-lookup
from candleviewer import flags_wiring  # ruleid: cv-admin-no-flag-lookup


def declared(route, flags) -> bool:
    return flags.is_enabled(route)  # ruleid: cv-admin-no-flag-lookup
