"""#2188 S4b: `create_app` on the real backend (nothing connects at build): the recorder is
composed once, with one `PolicyConfig`, attached to the supervisor's service, and its readiness
is read live. The build starts no runtime and ticks nothing."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import SecretStr

from candleviewer.app import create_app
from candleviewer.recorder.runtime import RecorderRuntime
from candleviewer.settings import Environment, Settings


@pytest.fixture
def app(tmp_path: Path) -> Any:
    settings = Settings(
        environment=Environment.DEMO, storage_backend="real",
        parquet_root=str(tmp_path / "parquet"), audit_wal_path=str(tmp_path / "audit" / "a.wal"),
        auth_pepper=SecretStr("test-pepper"), auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32), auth_csrf_key_hex=SecretStr("33" * 32),
    )  # fmt: skip
    return create_app(settings)


def test_the_runtime_shares_the_policys_config_and_is_attached_to_the_service(app: Any) -> None:
    recorder = app.state.recorder
    control = app.state.recording_runtime
    assert control._config is cast(Any, recorder.policy)._cfg  # one PolicyConfig (SEC-m1)
    assert app.state.app_context.recorder._runtime is recorder.runtime
    assert app.state.recording_control is control and app.state.recording_writer is control


def test_readiness_follows_the_runtime_live_and_nothing_started_at_build(app: Any) -> None:
    runtime: RecorderRuntime = app.state.recorder.runtime
    assert runtime._task is None and app.state.recording_ready() is False
    runtime._done = True  # the startup has completed
    assert app.state.recording_ready() is True  # read per call, never captured once
    runtime._done = False
    assert app.state.recording_ready() is False


def test_no_request_path_starts_the_runtime_or_ticks() -> None:
    api = Path(create_app.__code__.co_filename).parent / "api"
    for path in api.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert ".tick(" not in text and "startup_reconcile" not in text, path.name
        assert "recorder.runtime" not in text and "recorder_runtime.start" not in text, path.name


def test_the_rolloff_job_holds_the_pg_advisory_lock_over_the_apps_relational_engine(
    app: Any,
) -> None:
    from candleviewer.storage.retention.locks import PgAdvisoryRunLock

    job = app.state.rolloff_job
    assert job is not None  # the real backend builds it (a `None` repo would build nothing)
    assert isinstance(job._lock, PgAdvisoryRunLock)
    assert job._lock._engine is app.state.kline_boundary_pg.engine


class _IngestionBooks:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def anchor(self, symbol: str) -> str:
        self.asked.append(symbol)
        return "not_live"


def test_the_apps_recorder_anchors_read_the_ingestion_books_lazily(app: Any) -> None:
    """#2223: the book stream is attached after the recorder is composed, so it is read per call."""
    ingestion = app.state.app_context.ingestion
    anchors_books = app.state.recorder.anchors._books
    ingestion.books = None
    assert anchors_books.anchor("BTCUSDT") == "no_book"  # nothing attached yet: counted, no error
    books = _IngestionBooks()
    ingestion.books = books  # attached after the build
    assert anchors_books.anchor("BTCUSDT") == "not_live" and books.asked == ["BTCUSDT"]
