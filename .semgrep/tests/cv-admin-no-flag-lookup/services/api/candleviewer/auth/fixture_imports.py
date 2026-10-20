"""Fixtures for cv-admin-no-flag-lookup in auth/: no import reaches the flag API (AC-ADM-14)."""

import candleviewer.admin.flags  # ruleid: cv-admin-no-flag-lookup
import candleviewer.admin.flags.service as flag_service  # ruleid: cv-admin-no-flag-lookup
from candleviewer import flags_wiring  # ruleid: cv-admin-no-flag-lookup
from candleviewer.admin import flags  # ruleid: cv-admin-no-flag-lookup
from candleviewer.admin.flags import default_registry  # ruleid: cv-admin-no-flag-lookup
from candleviewer.admin.flags.catalogue import LIVE_ENABLED  # ruleid: cv-admin-no-flag-lookup
from candleviewer.flags_wiring import build_feature_flags  # ruleid: cv-admin-no-flag-lookup
from candleviewer.admin.http import admin_router  # ok: cv-admin-no-flag-lookup
from candleviewer.audit.actions import validate_action  # ok: cv-admin-no-flag-lookup
