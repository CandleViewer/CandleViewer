"""`0014_alerts`: models mirror the SQL, DDL renders, outbox keys, SECRET allow-list (E40-T01)."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from candleviewer.alerts.outbox import (
    ALERT_OUTBOX_TOPICS,
    alert_deliver_dedup_key,
    webhook_post_dedup_key,
)
from candleviewer.db import models
from candleviewer.storage.repositories.alerts_sqlalchemy import (
    ALERT_COLUMNS,
    AlertRow,
    array_literal,
    decode_cursor,
    encode_cursor,
)
from candleviewer.storage.retention import policy
from candleviewer.storage.retention.schedule import RetentionSchedule

_ROOT = Path(__file__).resolve().parents[3]


def _render(*args: str) -> str:
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", *args, "--sql"],
        cwd=_ROOT,
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _checks(table: object) -> set[str]:
    return {
        str(c.name)
        for c in table.constraints  # type: ignore[attr-defined]
        if c.__class__.__name__ == "CheckConstraint"
    }


def test_check_constraint_names_match_sql() -> None:
    assert _checks(models.alerts) == {
        f"ck_alerts_{n}" for n in ("al_cooldown", "al_channels", "al_webhook", "al_disarm_reason")
    }
    assert _checks(models.alert_deliveries) == {"ck_alert_deliveries_ad_attempt"}


def test_index_names_match_sql() -> None:
    names = {ix.name for t in (models.alerts, models.alert_deliveries) for ix in t.indexes}
    assert names == {
        "ux_alerts_name",
        "ix_alerts_live",
        "ix_alerts_snooze",
        "ix_alerts_expiry",
        "ix_ad_alert_time",
        "ix_ad_pending",
        "ix_ad_user_unack",
    }


def test_upgrade_sql_has_tables_constraints_and_trigger() -> None:
    sql = _render("upgrade", "0013_rules:0014_alerts")
    for table in ("alerts", "alert_deliveries", "outbox"):
        assert f"CREATE TABLE {table}" in sql
    for enum in ("alert_channel", "alert_trigger_mode", "delivery_status"):
        assert f"CREATE TYPE {enum}" in sql
    for name in ("al_cooldown", "al_channels", "al_webhook", "ad_attempt", "ob_attempts"):
        assert f"CONSTRAINT {name}" in sql
    assert "cooldown_seconds BETWEEN 0 AND 86400" in sql
    assert "array_length(channels,1) BETWEEN 1 AND 5" in sql
    assert "CREATE TRIGGER trg_ad_append BEFORE DELETE ON alert_deliveries" in sql
    assert "session_user = 'cv_owner'" in sql
    assert "UPDATE" not in sql.split("trg_ad_append")[1].split(";")[0]


def test_downgrade_refuses_populated_and_drops_everything() -> None:
    sql = _render("downgrade", "0014_alerts:0013_rules")
    assert "downgrade refused" in sql
    for obj in (
        "TABLE IF EXISTS outbox",
        "TABLE IF EXISTS alert_deliveries",
        "TABLE IF EXISTS alerts",
        "TYPE IF EXISTS delivery_status",
        "TYPE IF EXISTS alert_channel",
        "TYPE IF EXISTS alert_trigger_mode",
    ):
        assert f"DROP {obj}" in sql


def test_outbox_topics_and_dedup_keys() -> None:
    assert ALERT_OUTBOX_TOPICS == {"alert.deliver", "webhook.post"}
    assert alert_deliver_dedup_key(42) == "42"
    assert webhook_post_dedup_key("a1", 1700000000000, 2) == "a1:1700000000000:2"


def test_read_allow_list_never_selects_secret_columns() -> None:
    assert "webhook_url_enc IS NOT NULL" in ALERT_COLUMNS
    stripped = ALERT_COLUMNS.replace("(webhook_url_enc IS NOT NULL) AS has_webhook", "")
    assert "webhook_url_enc" not in stripped and "webhook_secret_enc" not in stripped
    fields = set(AlertRow.__dataclass_fields__)
    assert not {"webhook_url_enc", "webhook_secret_enc", "webhook_url", "webhook_secret"} & fields


def test_cursor_roundtrip_and_rejects_garbage() -> None:
    ts = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    assert decode_cursor(encode_cursor(ts, 7)) == (ts, "7")
    with pytest.raises(ValueError):
        decode_cursor("not-a-cursor")


def test_array_literal() -> None:
    assert array_literal(("in_app", "webhook")) == "{in_app,webhook}"


def test_alert_deliveries_retention_registered_only_when_enabled() -> None:
    assert RetentionSchedule.from_env({}).alert_jobs() == {}
    on = RetentionSchedule.from_env({"CV_RETENTION_ENABLED": "true"}).alert_jobs()
    assert on == {"alert_deliveries_purge": "0 3 * * *"}
    assert (policy.ALERT_DELIVERIES_HOT_DAYS, policy.ALERT_DELIVERIES_COLD_MONTHS) == (180, 24)
    assert policy.ALERT_DELIVERIES_ACTION == "archive_parquet"
