"""Fixtures for cv-admin-no-flag-lookup in audit/: no catalogue key (AC-ADM-14)."""

LIVE = "trading.live_enabled"  # ruleid: cv-admin-no-flag-lookup
ORDER_KILL = "killswitch.order_entry"  # ruleid: cv-admin-no-flag-lookup


def engaged(read) -> bool:
    return read("maintenance.mode")  # ruleid: cv-admin-no-flag-lookup


# ADR-0037 decision 12's key is refused here too; the flag reaches audit/ only as the callable the
# composition root injects (D3, the AD-F09 residual), which the next lines stand for.
JOURNAL_FIRST = "audit.lane_journal_first"  # ruleid: cv-admin-no-flag-lookup
PROSE = "maintenance.mode is read by the composition root"  # ok: cv-admin-no-flag-lookup
ACTION = "maintenance.enabled"  # ok: cv-admin-no-flag-lookup


def lane(journal_first) -> bool:
    return journal_first()  # ok: cv-admin-no-flag-lookup
