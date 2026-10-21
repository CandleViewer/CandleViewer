"""Fixtures for cv-admin-no-flag-lookup in audit/: no catalogue key (AC-ADM-14)."""

LIVE = "trading.live_enabled"  # ruleid: cv-admin-no-flag-lookup
ORDER_KILL = "killswitch.order_entry"  # ruleid: cv-admin-no-flag-lookup


def engaged(read) -> bool:
    return read("maintenance.mode")  # ruleid: cv-admin-no-flag-lookup


PROSE = "maintenance.mode is read by the composition root"  # ok: cv-admin-no-flag-lookup
ACTION = "maintenance.enabled"  # ok: cv-admin-no-flag-lookup
