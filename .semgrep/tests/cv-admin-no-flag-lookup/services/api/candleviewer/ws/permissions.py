"""Fixtures for cv-admin-no-flag-lookup: the WS permission checks (AC-ADM-14), relative imports too."""

import importlib
from .. import flags_wiring  # ruleid: cv-admin-no-flag-lookup
from ..admin.flags import catalogue  # ruleid: cv-admin-no-flag-lookup
from ..oms import errors  # ok: cv-admin-no-flag-lookup

WIRING = importlib.import_module("candleviewer.flags_wiring")  # ruleid: cv-admin-no-flag-lookup


def may_subscribe(principal, flag_service) -> bool:
    return flag_service.value("trading.one_click")  # ruleid: cv-admin-no-flag-lookup


def decide(principal, topic) -> bool:
    return topic in principal.topics  # ok: cv-admin-no-flag-lookup
