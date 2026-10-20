"""Fixtures for cv-admin-no-flag-lookup: the WS permission checks (AC-ADM-14), relative imports too."""

import importlib
from .. import flags_wiring  # ruleid: cv-admin-no-flag-lookup
from ..admin.flags import catalogue  # ruleid: cv-admin-no-flag-lookup
from ..oms import errors  # ok: cv-admin-no-flag-lookup
from ..admin import flags  # ruleid: cv-admin-no-flag-lookup
from ..admin import flags as gates  # ruleid: cv-admin-no-flag-lookup
from ...admin import flags as deep  # ruleid: cv-admin-no-flag-lookup
from ... import flags_wiring as fw  # ruleid: cv-admin-no-flag-lookup
from ..admin import errors as admin_errors  # ok: cv-admin-no-flag-lookup
from candleviewer.admin import http  # ok: cv-admin-no-flag-lookup

WIRING = importlib.import_module("candleviewer.flags_wiring")  # ruleid: cv-admin-no-flag-lookup


def may_subscribe(principal, flag_service) -> bool:
    return flag_service.value("trading.one_click")  # ruleid: cv-admin-no-flag-lookup


def decide(principal, topic) -> bool:
    return topic in principal.topics  # ok: cv-admin-no-flag-lookup
