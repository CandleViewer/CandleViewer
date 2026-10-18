"""The M2 audit-row builder `admin.wiring` injects into the M10 credential store (#2266)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

import candleviewer.app as app_module
from candleviewer.admin.wiring import secrets_audit_row, secrets_audit_sink
from candleviewer.audit.actions import UnknownAuditAction
from candleviewer.audit.redact import REDACTION_MARKER
from candleviewer.settings import Environment, Settings

T0 = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
ACTION = "security.credential_rewrapped"
FIELDS = {
    "run_id": "r-1", "key_id": str(uuid.UUID(int=7)), "from": "1", "to": "2",
    "actor_kind": "user", "actor_role": "owner", "actor_user_id": str(uuid.UUID(int=9)),
}  # fmt: skip


async def test_the_row_builder_writes_the_columns_the_wal_sink_writes() -> None:
    emitted: list[tuple[str, dict[str, Any]]] = []

    async def emit(action: str, **columns: Any) -> None:
        emitted.append((action, columns))

    writer = SimpleNamespace(emit=emit)
    await secrets_audit_sink(cast(Any, SimpleNamespace(writer=writer)))(ACTION, FIELDS)
    build = secrets_audit_row("testnet", clock=lambda: T0)
    row, again = build(ACTION, FIELDS), build(ACTION, FIELDS)
    [(action, columns)] = emitted
    assert row["action"] == action and {k: row[k] for k in columns} == columns
    assert (row["object_kind"], row["env"], row["outcome"]) == ("api_key", "testnet", "success")
    assert datetime.fromisoformat(row["event_ts"]) == T0 and row["record_id"] != again["record_id"]


def test_the_row_builder_refuses_an_unregistered_action() -> None:
    with pytest.raises(UnknownAuditAction):
        secrets_audit_row("demo")("security.not_registered", FIELDS)


def test_the_row_builder_redacts_the_state() -> None:
    row = secrets_audit_row("demo")(ACTION, {**FIELDS, "api_secret": "plain"})
    assert row["after_state"]["api_secret"] == REDACTION_MARKER


def test_the_real_backend_injects_a_row_builder_bound_to_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: dict[str, Any] = {}

    def store(relational: Any, **kwargs: Any) -> Any:
        built.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(app_module, "SqlAlchemyCredentialStore", store)
    settings = Settings(environment=Environment.TESTNET, storage_backend="real")
    app_module._build_secrets(settings, app_module._build_audit(settings))
    assert built["audit_row"](ACTION, FIELDS)["env"] == "testnet"


@pytest.mark.parametrize(
    ("action", "severity"),
    [("security.kek_enrolled", "info"), ("security.kek_rows_stranded", "error")],
)
def test_the_boot_records_are_about_the_kek_at_their_severity(action: str, severity: str) -> None:
    """#2266 PR C: an enrolment commits with its KCV row; stranded rows page at error."""
    row = secrets_audit_row("demo")(action, {"env": "demo", "kcv": "00", "stranded": "1"})
    assert (row["action"], row["object_kind"], row["severity"]) == (action, "kek", severity)


@pytest.mark.parametrize(
    "action", ["security.kek_loaded", "security.kek_enrolled", "security.kek_rows_stranded"]
)
def test_a_kek_boot_record_is_stored_without_its_kek_version(action: str) -> None:
    """Pins today's behaviour (#3577): the redactor drops every field named `*kek*`, so a boot
    record keeps its environment and count but not the KEK version. Change this test when the
    redactor keeps `kek_version`."""
    fields = {"env": "demo", "kek_version": "2", "stranded": "1"}
    stored = secrets_audit_row("demo")(action, fields)["after_state"]
    assert stored == {**fields, "kek_version": REDACTION_MARKER}
