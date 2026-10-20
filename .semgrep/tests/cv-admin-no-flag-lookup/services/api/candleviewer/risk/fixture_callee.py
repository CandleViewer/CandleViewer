"""Fixtures for cv-admin-no-flag-lookup in risk/: a call naming a flag (AC-ADM-14)."""


def cap(limits, store) -> int:
    if get_flag(store, "maintenance.keep_recorder"):  # ruleid: cv-admin-no-flag-lookup
        return 0
    service = FlagService(store)  # ruleid: cv-admin-no-flag-lookup
    return limits.daily_cap(service)  # ok: cv-admin-no-flag-lookup
