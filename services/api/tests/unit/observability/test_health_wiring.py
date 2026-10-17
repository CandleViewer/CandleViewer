"""QA #1668: event writer, WS publisher, real probes. E42-T05: the writer redacts `details`
through the injected audit serializer and materialises an `error` or `critical` event's incident
in the event's own unit of work."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from candleviewer.app import build_auth_service, create_app
from candleviewer.audit.redact import REDACTION_MARKER, redact
from candleviewer.bus.models import Topic
from candleviewer.db.models import incidents, system_events
from candleviewer.health_wiring import (
    HealthSystemPublisher,
    PgSystemEventWriter,
    register_real_probes,
)
from candleviewer.observability.health_probes import (
    ComponentState,
    HealthRegistry,
    SystemEvent,
)
from candleviewer.settings import Settings
from candleviewer.storage.repositories.incident_grouping import (
    incident_signature,
    normalise_message,
)

#: What the database stamps on the event row (`event_ts DEFAULT now()`), returned by the insert.
EVENT_TS = datetime(2026, 10, 17, 9, 30, tzinfo=UTC)


class _Session:
    def __init__(self, log: list[Any], fail_at: int | None = None) -> None:
        self.log = log
        self._fail_at = fail_at

    async def execute(self, stmt: Any) -> Any:
        if self._fail_at == len(self.log):
            raise OSError("down")
        self.log.append(stmt)
        return SimpleNamespace(scalar_one=lambda: EVENT_TS)


class _Uow:
    def __init__(self, log: list[Any], fail_at: int | None = None) -> None:
        self.session = _Session(log, fail_at)
        self.committed = False

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *a: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


class _Repo:
    def __init__(self, fail: bool = False, fail_at: int | None = None) -> None:
        self.log: list[Any] = []
        self.fail = fail
        self.fail_at = fail_at
        self.uows: list[_Uow] = []

    def unit_of_work(self) -> _Uow:
        if self.fail:
            raise OSError("down")
        u = _Uow(self.log, self.fail_at)
        self.uows.append(u)
        return u


class _Bus:
    def __init__(self) -> None:
        self.sent: list[tuple[Topic, Any]] = []

    async def publish(self, topic: Topic, event: Any) -> None:
        self.sent.append((topic, event))


def _writer(repo: _Repo) -> PgSystemEventWriter:
    return PgSystemEventWriter(repo, redact_details=redact)


def _values(stmt: Any) -> dict[str, Any]:
    return dict(stmt.compile().params)


@pytest.mark.parametrize("severity", ["debug", "info", "warning"])
async def test_writer_inserts_a_lower_severity_event_alone_and_commits(severity: str) -> None:
    repo = _Repo()
    await _writer(repo).write(SystemEvent("auth", "totp_clock_skew", severity, "m", {"a": "b"}))
    assert [s.table for s in repo.log] == [system_events] and repo.uows[0].committed


async def test_writer_passes_details_through_the_audit_serializer() -> None:
    repo = _Repo()
    details = {"probe": "x", "api_key": "k", "body": '{"token": "t", "n": 1}'}
    await _writer(repo).write(SystemEvent("db", "health_degraded", "warning", "m", details))
    assert _values(repo.log[0])["details"] == {
        "probe": "x",
        "api_key": REDACTION_MARKER,
        "body": f'{{"token":"{REDACTION_MARKER}","n":1}}',  # embedded JSON is walked too
    }
    assert details["api_key"] == "k"  # the event itself is never mutated


def _real_settings() -> Settings:
    return Settings(  # test-only values, not credentials
        storage_backend="real",
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
        auth_pepper=SecretStr("pepper"),
    )


def _auth_service_writer() -> object:
    return build_auth_service(_real_settings())._system_events


def _health_registry_writer() -> object:
    registry: HealthRegistry = create_app(_real_settings()).state.health_registry
    return registry._events


@pytest.mark.parametrize(
    "build",
    [_auth_service_writer, _health_registry_writer],
    ids=["auth_service", "health_registry"],
)
def test_each_production_writer_is_built_with_the_audit_serializer(
    build: Callable[[], object],
) -> None:
    # `redact_details` has no default, but a no-op passed at a construction site type-checks.
    writer = build()
    assert isinstance(writer, PgSystemEventWriter)
    assert writer._redact_details({"api_key": "k"}) == {"api_key": REDACTION_MARKER}


@pytest.mark.parametrize("severity", ["error", "critical"])
async def test_an_incident_event_upserts_its_incident_in_the_same_unit_of_work(
    severity: str,
) -> None:
    repo = _Repo()
    message = "parquet write failed for BTCUSDT segment 41"
    await _writer(repo).write(SystemEvent("recorder", "parquet_write", severity, message, {}))
    event, upsert = repo.log
    assert (event.table, upsert.table) == (system_events, incidents) and len(repo.uows) == 1
    assert repo.uows[0].committed  # once, after both statements
    values = _values(upsert)
    title = normalise_message(message)
    assert {k: values[k] for k in ("component", "signature", "severity", "title", "detail")} == {
        "component": "recorder",
        "signature": incident_signature("recorder", "parquet_write", title),
        "severity": severity,
        "title": title,
        "detail": message,
    }
    assert values["first_seen_at"] == values["last_seen_at"] == EVENT_TS  # the row's own time


@pytest.mark.parametrize("fail_at", [0, 1], ids=["event", "incident"])
async def test_a_failed_statement_commits_neither_row(fail_at: int) -> None:
    repo = _Repo(fail_at=fail_at)
    with pytest.raises(OSError):
        await _writer(repo).write(SystemEvent("db", "health_degraded", "error", "m", {}))
    assert not repo.uows[0].committed  # the unit of work rolls the event back with the incident


async def test_transition_writes_event_and_publishes_snapshot() -> None:
    repo, bus = _Repo(), _Bus()
    reg = HealthRegistry(
        events=_writer(repo),
        on_snapshot=HealthSystemPublisher(bus, "demo"),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )
    state = {"s": ComponentState.HEALTHY}

    class P:
        name = "bybit_public_ws"
        timeout = 1.0

        async def check(self):  # type: ignore[no-untyped-def]  # nested probe stub; protocol-typed at registration
            from candleviewer.observability.health_probes import ProbeResult

            return ProbeResult(state["s"])

    reg.register(P())
    await reg.refresh()
    assert repo.log == []
    state["s"] = ComponentState.DOWN
    await reg.refresh()
    state["s"] = ComponentState.HEALTHY
    await reg.refresh()
    assert [s.table for s in repo.log] == [system_events, incidents, system_events]  # down: error
    assert len(bus.sent) == 3
    topic, payload = bus.sent[1]
    assert topic.domain == "system"
    assert payload["kind"] == "health" and payload["health"] == "down"
    assert payload["exchange"]["public_ws"] == "down"  # type: ignore[index]  # payload is dict[str, object]; test narrows by key


async def test_real_probes_replace_placeholders_and_report_failure(tmp_path: Any) -> None:
    reg = HealthRegistry()
    reg.register_placeholders()
    register_real_probes(
        reg,
        pg_repo=_Repo(fail=True),
        questdb_host="127.0.0.1",
        questdb_port=1,
        parquet_root=str(tmp_path),
        disk_path=str(tmp_path),
    )
    snap = await reg.refresh()
    st = {c.name: c.state for c in snap.components}
    assert st["postgres"] is ComponentState.DOWN
    assert st["questdb"] is ComponentState.DOWN
    assert st["parquet_store"] is ComponentState.HEALTHY
    assert st["disk"] in (ComponentState.HEALTHY, ComponentState.WARNING, ComponentState.DOWN)
    assert st["oms"] is ComponentState.NOT_DEPLOYED


async def test_disk_probe_uses_absolute_path(tmp_path: Any) -> None:
    reg = HealthRegistry()
    register_real_probes(
        reg,
        pg_repo=object(),  # type: ignore[arg-type]  # unused by the disk probe under test
        questdb_host="127.0.0.1",
        questdb_port=1,
        parquet_root=str(tmp_path),
        disk_path=".",
    )
    await reg.refresh()
    disk = next(c for c in reg.snapshot().components if c.name == "disk")
    assert disk.state is not ComponentState.DOWN
