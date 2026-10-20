"""Fixtures for cv-admin-no-flag-lookup: ws/ outside `permissions.py` is out of its scope."""


def push(flag_service) -> object:
    return flag_service.value("trading.one_click")  # ok: cv-admin-no-flag-lookup
