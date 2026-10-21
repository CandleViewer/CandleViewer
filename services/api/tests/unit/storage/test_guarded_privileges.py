"""#3998: the boot check of the runtime role's guarded privileges (`storage.guarded_privileges`),
its read (`repositories.guarded_privileges_sqlalchemy`) and where it runs: `StorageService.start()`
on the real backend, with the gauge `create_app` attaches. No database: the read is faked at its
unit of work; the real statement runs in `tests/integration/storage/test_guarded_privileges_pg.py`
(CI only). The pinned table's tripwire: `tests/unit/migrations/test_guarded_privileges_tripwire.py`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from structlog.testing import capture_logs

from candleviewer.app import create_app
from candleviewer.observability.redaction import redact_structure
from candleviewer.settings import Environment, Settings
from candleviewer.storage import real_tiers
from candleviewer.storage.errors import GuardedPrivilegesHeld
from candleviewer.storage.guarded_privileges import (
    GUARDED_PAIRS,
    HeldPrivilege,
    PrivilegeReport,
    check_guarded_privileges,
)
from candleviewer.storage.real_tiers import RealTier, RealTiers
from candleviewer.storage.repositories import guarded_privileges_sqlalchemy as sql_mod
from candleviewer.storage.service import StorageService
from candleviewer.storage.testing import (
    FakeColdTierRepository,
    FakeMarketDataRepository,
    FakeRelationalRepository,
)

#: What a driver error may carry: a host and a login. Neither may reach a log line or an error.
_LEAKY = 'connection to "db.internal" port 5432 refused for user "cv_app"'
_NONE = PrivilegeReport(False, ())
_RUNTIME = PrivilegeReport(False, (HeldPrivilege("api_keys", "DELETE", False),))
_SUPERUSER = PrivilegeReport(True, tuple(HeldPrivilege(t, p, True) for t, p in GUARDED_PAIRS))
_OWNER = PrivilegeReport(False, tuple(HeldPrivilege(t, p, True) for t, p in GUARDED_PAIRS))
_MIXED = PrivilegeReport(
    False, (HeldPrivilege("api_keys", "DELETE", True), HeldPrivilege("backups", "DELETE", False))
)
_ALL = len(GUARDED_PAIRS)


class _Gauge:
    def __init__(self) -> None:
        self.values: list[float] = []

    def set(self, value: float) -> None:
        self.values.append(value)


def _reader(report: PrivilegeReport | BaseException | None) -> Callable[[], Awaitable[Any]]:
    """A read that returns `report`, raises it, or (None) never answers."""

    async def read() -> PrivilegeReport:
        if report is None:
            await asyncio.Event().wait()
        if isinstance(report, BaseException):
            raise report
        assert isinstance(report, PrivilegeReport)
        return report

    return read


async def _check(
    report: PrivilegeReport | BaseException | None, *, live: bool
) -> tuple[list[float], list[MutableMapping[str, Any]], GuardedPrivilegesHeld | None]:
    """Run the check once: the gauge's values, the log lines and the error it raised, if any."""
    gauge = _Gauge()
    refused: GuardedPrivilegesHeld | None = None
    with capture_logs() as logs:
        try:
            await check_guarded_privileges(
                _reader(report), live=live, gauge=cast(Any, gauge), timeout_s=0.05
            )
        except GuardedPrivilegesHeld as exc:
            refused = exc
    return gauge.values, logs, refused


def _events(logs: list[MutableMapping[str, Any]]) -> list[tuple[str, str]]:
    return [(line["event"], line["log_level"]) for line in logs]


_CHECKED = ("storage_guarded_privileges_checked", "info")
_HELD = ("storage_guarded_privileges_held", "error")
_PRIVILEGED = ("storage_guarded_privileges_privileged_role", "warning")


@pytest.mark.parametrize(
    ("report", "live", "gauge", "events"),
    [
        pytest.param(_NONE, False, 0, [_CHECKED], id="none-held-demo"),
        pytest.param(_NONE, True, 0, [_CHECKED], id="none-held-live"),
        pytest.param(_RUNTIME, False, 1, [_HELD], id="runtime-holds-demo"),
        pytest.param(_RUNTIME, True, 1, [_HELD], id="runtime-holds-live"),
        pytest.param(_SUPERUSER, False, 0, [_PRIVILEGED, _CHECKED], id="superuser-demo"),
        pytest.param(_SUPERUSER, True, _ALL, [_HELD], id="superuser-live"),
        pytest.param(_OWNER, False, 0, [_PRIVILEGED, _CHECKED], id="owner-demo"),
        pytest.param(_MIXED, False, 1, [_PRIVILEGED, _HELD], id="owner-and-grant-demo"),
    ],
)
async def test_check_refuses_only_in_live_and_never_counts_ownership_outside_it(
    report: PrivilegeReport, live: bool, gauge: int, events: list[tuple[str, str]]
) -> None:
    values, logs, refused = await _check(report, live=live)
    assert values == [gauge]
    assert _events(logs) == events
    assert (refused is not None) == (live and gauge > 0)


async def test_held_line_names_each_table_and_privilege_and_the_role_kind_only() -> None:
    _, logs, refused = await _check(_MIXED, live=False)
    assert refused is None
    privileged, held = logs
    assert privileged["role"] == "owner"
    assert {k: held[k] for k in ("held", "role", "refused")} == {
        "held": ["backups.DELETE"],
        "role": "owner",
        "refused": False,
    }
    _, logs, refused = await _check(_SUPERUSER, live=True)
    (line,) = logs
    assert line["role"] == "superuser" and len(line["held"]) == _ALL and line["refused"] is True
    assert str(refused) == "the runtime role holds guarded privileges: " + ", ".join(line["held"])
    assert redact_structure(line) == line  # readable as written: nothing secret-shaped in it


@pytest.mark.parametrize(
    ("failure", "error"),
    [(OSError(_LEAKY), "OSError"), (None, "TimeoutError")],
    ids=["driver-error", "no-answer"],
)
@pytest.mark.parametrize("live", [False, True])
async def test_a_check_that_cannot_run_counts_every_pair_and_refuses_live(
    failure: BaseException | None, error: str, live: bool
) -> None:
    values, logs, refused = await _check(failure, live=live)
    assert values == [_ALL]
    assert logs == [
        {
            "event": "storage_guarded_privileges_unchecked",
            "log_level": "error",
            "error": error,
            "refused": live,
        }
    ]
    assert (refused is not None) == live
    assert "db.internal" not in f"{logs} {refused}" and "cv_app" not in f"{logs} {refused}"


async def test_a_cancellation_is_not_judged() -> None:
    task = asyncio.create_task(_check(None, live=True))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_a_check_with_no_gauge_attached_still_refuses_live() -> None:
    with pytest.raises(GuardedPrivilegesHeld):
        await check_guarded_privileges(_reader(_RUNTIME), live=True, gauge=None, timeout_s=0.05)


class _Rel:
    """A relational repository whose unit of work records each statement and returns `rows`."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: sa.TextClause, params: dict[str, Any]) -> Any:
            self.calls.append((stmt.text, params))
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: self.rows))

        yield SimpleNamespace(session=SimpleNamespace(execute=execute))


def test_statement_is_one_bound_has_table_privilege_query_on_current_user() -> None:
    text = sql_mod._HELD.text
    assert set(sql_mod._HELD.compile().params) == {"tables", "privileges"}
    assert "has_table_privilege(current_user, c.oid, g.priv)" in text
    assert "unnest(CAST(:tables AS text[]), CAST(:privileges AS text[]))" in text
    assert ";" not in text and "session_user" not in text


async def test_read_sends_every_pinned_pair_once_and_maps_the_held_rows() -> None:
    rel = _Rel(
        [
            {
                "table_name": "api_keys",
                "privilege": "DELETE",
                "via_owner": False,
                "superuser": False,
            },
            {"table_name": "backups", "privilege": "DELETE", "via_owner": True, "superuser": True},
        ]
    )
    report = await sql_mod.SqlAlchemyGuardedPrivileges(cast(Any, rel)).held()
    ((text, params),) = rel.calls
    assert text == sql_mod._HELD.text
    assert list(zip(params["tables"], params["privileges"], strict=True)) == list(GUARDED_PAIRS)
    assert report == PrivilegeReport(
        True, (HeldPrivilege("api_keys", "DELETE", False), HeldPrivilege("backups", "DELETE", True))
    )
    assert await sql_mod.SqlAlchemyGuardedPrivileges(cast(Any, _Rel([]))).held() == _NONE


async def test_build_real_tiers_reads_the_privileges_on_the_storage_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[Any] = []

    class _Relational(_Rel):
        def __init__(self, _dsn: str, suffix: str) -> None:
            super().__init__([])
            self.suffix = suffix
            made.append(self)

    monkeypatch.setattr(real_tiers, "SqlAlchemyRelationalRepository", _Relational)
    built = real_tiers.build_real_tiers(
        Settings(storage_backend="real", parquet_root=str(tmp_path))
    )
    assert built.guarded_privileges is not None
    assert await built.guarded_privileges() == _NONE
    (storage,) = made  # the tiers' one relational client: the app's own login
    assert storage.suffix == "storage"
    assert [text for text, _ in storage.calls] == [sql_mod._HELD.text]


class _Tiers:
    """Three tiers that answer, and the guarded read; `order` records probes and the read."""

    def __init__(self, report: PrivilegeReport) -> None:
        self.report = report
        self.order: list[str] = []

    def build(self, _settings: Settings) -> RealTiers:
        def tier(name: str) -> RealTier:
            async def probe() -> None:
                self.order.append(f"probe:{name}")

            async def close(_budget_s: float) -> None:
                self.order.append(f"close:{name}")

            return RealTier(cast(Any, name), probe, close)

        async def read() -> PrivilegeReport:
            self.order.append("guarded_privileges")
            return self.report

        return RealTiers(
            market_data=FakeMarketDataRepository(),
            relational=FakeRelationalRepository(),
            cold=FakeColdTierRepository(),
            tiers=(tier("postgres"), tier("questdb"), tier("cold")),
            guarded_privileges=read,
        )


def _ctx(environment: Environment) -> Any:
    return SimpleNamespace(settings=SimpleNamespace(environment=environment))


async def test_start_checks_once_the_tiers_answer_and_live_fails_closed() -> None:
    tiers, gauge = _Tiers(_RUNTIME), _Gauge()
    service = StorageService(backend="real", real_tiers=tiers.build)
    service.attach_privileges_gauge(cast(Any, gauge))
    with pytest.raises(GuardedPrivilegesHeld, match=r"api_keys\.DELETE"):
        await service.start(_ctx(Environment.LIVE))
    probes = ["probe:postgres", "probe:questdb", "probe:cold"]
    assert tiers.order == [
        *probes,
        "guarded_privileges",
        "close:cold",
        "close:questdb",
        "close:postgres",
    ]
    assert gauge.values == [1] and service.tier_health().tiers == ()


async def test_start_outside_live_counts_a_held_privilege_and_serves() -> None:
    tiers, gauge = _Tiers(_RUNTIME), _Gauge()
    service = StorageService(backend="real", real_tiers=tiers.build)
    service.attach_privileges_gauge(cast(Any, gauge))
    await service.start(_ctx(Environment.TESTNET))
    try:
        assert tiers.order[-1] == "guarded_privileges" and gauge.values == [1]
    finally:
        await service.stop(grace_s=1.0)


async def test_create_app_attaches_the_catalogue_gauge_that_the_start_sets(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            environment=Environment.DEMO, storage_backend="real", metrics_enabled=False,
            parquet_root=str(tmp_path / "parquet"), bars_state_root=str(tmp_path / "bars"),
            auth_pepper=SecretStr("test-pepper"), auth_totp_key_hex=SecretStr("11" * 32),
            auth_recovery_hmac_key_hex=SecretStr("22" * 32), auth_csrf_key_hex=SecretStr("33" * 32),
        )
    )  # fmt: skip
    ctx = app.state.app_context
    ctx.storage._build_real = _Tiers(_MIXED).build  # the tier clients, not the wiring, are faked
    await ctx.storage.start(ctx)
    try:
        sample = ctx.metrics.get_sample_value("cv_db_guarded_privileges_held", {"env": "demo"})
        assert sample == 1.0
    finally:
        await ctx.storage.stop(grace_s=1.0)
