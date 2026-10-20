"""Fixtures for cv-admin-no-flag-lookup: the deny-by-default route check (AC-ADM-14)."""


def declared(route, flags) -> bool:
    return flags.is_enabled(route)  # ruleid: cv-admin-no-flag-lookup
