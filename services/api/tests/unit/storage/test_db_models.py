"""Tests for `candleviewer.db.models` (E07-T02): the SQLAlchemy 2.0 Core
`MetaData` mirroring `0001_identity_rbac_sessions_mfa`'s hand-written SQL.
No database needed — these assert the metadata's shape only.
"""

from __future__ import annotations

from candleviewer.db.models import NAMING_CONVENTION, metadata


def test_metadata_has_naming_convention_matching_schema_doc() -> None:
    assert metadata.naming_convention == NAMING_CONVENTION
    assert NAMING_CONVENTION["ix"] == "ix_%(table_name)s_%(column_0_N_name)s"
    assert NAMING_CONVENTION["uq"] == "ux_%(table_name)s_%(column_0_N_name)s"
    assert NAMING_CONVENTION["ck"] == "ck_%(table_name)s_%(constraint_name)s"
    assert NAMING_CONVENTION["fk"] == "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
    assert NAMING_CONVENTION["pk"] == "pk_%(table_name)s"


def test_metadata_declares_every_table_from_0001() -> None:
    expected = {
        "users",
        "roles",
        "permissions",
        "role_permissions",
        "user_roles",
        "user_account_access",
        "sessions",
        "sessions_rotation",
        "mfa_methods",
        "mfa_challenges",
        "recovery_codes",
        # E09-T02 (0003_audit_log)
        "audit_log",
        "audit_checkpoints",
        # E08-S01 (0004_instruments)
        "instruments",
        "instrument_versions",
        # E09-S06 (0012_onboarding_dismissals)
        "onboarding_dismissals",
        # E09-S05 (0010_user_invites)
        "user_invites",
        # E04-T04 (0008_system_events)
        "system_events",
        # E16-T01 (0011_recorder)
        "recorded_symbols",
        "recording_sessions",
        "recording_gaps",
        "retention_policies",
        "rules",
        "rule_versions",
        "rule_runs",
        "rule_events",
        "alerts",
        "alert_deliveries",
        "outbox",
        # E27-T01 (0017_exchange_accounts_api_keys)
        "exchange_accounts",
        "api_keys",
        "api_key_rotations",
    }
    actual = {t.name for t in metadata.sorted_tables}
    assert actual == expected


def test_users_table_has_expected_primary_key_and_required_columns() -> None:
    users = metadata.tables["users"]
    assert [c.name for c in users.primary_key.columns] == ["id"]
    for column in ("email", "username", "password_hash", "status", "mfa_required"):
        assert column in users.columns, f"missing column {column!r} on users"
        assert users.columns[column].nullable is False
