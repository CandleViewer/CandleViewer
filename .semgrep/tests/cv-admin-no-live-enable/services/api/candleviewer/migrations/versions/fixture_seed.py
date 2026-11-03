"""Fixtures for cv-admin-no-live-enable-py: a migration is no way around the gate either."""


def upgrade(op, flags):
    op.bulk_insert(flags, [{"key": "trading.live_enabled", "default_value": True}])  # ruleid: cv-admin-no-live-enable
    op.bulk_insert(flags, [{"key": "trading.live_enabled", "default_value": False}])  # ok: cv-admin-no-live-enable
