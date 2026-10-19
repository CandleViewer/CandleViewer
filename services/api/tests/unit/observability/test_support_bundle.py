"""E04-S02 support bundle: contents, canary secret scan, cap, RBAC, 409, chaos."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from candleviewer.api.support_bundle import make_support_bundle_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.observability import support_bundle as bundle_module
from candleviewer.observability.bundle_scan import scan_text
from candleviewer.observability.support_bundle import (
    BundleError,
    BundleJob,
    BundleSources,
    SupportBundleService,
    build_bundle,
    filter_config,
    truncate_newest_first,
    validate_window,
)

T1 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
T0 = T1 - timedelta(hours=2)
# Assembled at runtime so no secret-shaped literal sits in the repo.
CANARY = "api_secret=" + "Zq9" + "x" * 20 + "AbCd"


def _sources(logs: list[str] | None = None, config: dict[str, Any] | None = None) -> BundleSources:
    return BundleSources(
        logs=lambda a, b: list(logs if logs is not None else ["l3", "l2", "l1"]),
        metrics=lambda: "up 1\n",
        health=lambda: {"overall": "healthy"},
        system_events=lambda a, b: [{"kind": "x"}],
        alerts=lambda: [],
        build_info=lambda: {"version": "1.0.0"},
        config=lambda: config or {"CV_ENV": "demo", "CV_DB_PASSWORD": "hunter2hunter2"},
    )


def _build(tmp: Path, src: BundleSources, **kw: Any) -> Any:
    return build_bundle(src, tmp, T0, T1, free_bytes=lambda p: 10**12, **kw)


def test_bundle_contents_and_manifest_hashes(tmp_path: Path) -> None:
    res = _build(tmp_path, _sources())
    with zipfile.ZipFile(res.path) as zf:
        names = set(zf.namelist())
        assert names == {
            "health.json", "system_events.json", "alerts.json", "build_info.json",
            "config.json", "metrics.prom", "logs.ndjson", "manifest.json",
        }  # fmt: skip
        manifest = json.loads(zf.read("manifest.json"))
        for art in manifest["artefacts"]:
            assert hashlib.sha256(zf.read(art["name"])).hexdigest() == art["sha256"]
        cfg = json.loads(zf.read("config.json"))
    assert cfg == {"CV_ENV": "demo", "CV_DB_PASSWORD": "<omitted>"}
    assert [p.name for p in tmp_path.iterdir()] == [res.path.name]
    if os.name == "posix":
        assert (res.path.stat().st_mode & 0o777) == 0o600


def test_unknown_secret_config_key_omitted_by_default() -> None:
    assert filter_config({"CV_NEW_THING_KEY": "abc", "CV_FLAG_X": True})["CV_NEW_THING_KEY"] == (
        "<omitted>"
    )


def test_canary_secret_in_logs_fails_and_leaves_nothing(tmp_path: Path) -> None:
    with pytest.raises(BundleError) as ei:
        _build(tmp_path, _sources(logs=["ok", f"boom {CANARY}"]))
    assert ei.value.code == "BUNDLE_SECRET_DETECTED"
    assert [(f.file, f.rule) for f in ei.value.findings] == [("logs.ndjson", "labelled-secret")]
    assert CANARY.split("=")[1] not in str(ei.value)
    assert list(tmp_path.iterdir()) == []


def test_canary_in_alerts_also_detected(tmp_path: Path) -> None:
    src = _sources()
    src.alerts = lambda: [{"msg": "-----BEGIN PRIVATE KEY-----"}]
    with pytest.raises(BundleError) as ei:
        _build(tmp_path, src)
    assert ei.value.findings[0].rule == "private-key-block"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "text",
    [
        "ghp_" + "a" * 36,
        "AKIA" + "A" * 16,
        "sk-" + "a" * 24,
        "Authorization: Bearer " + "a" * 24,
        "x.y".join(["a" * 12, "b" * 12]) + "." + "c" * 12,
    ],
)
def test_scan_rules_hit(text: str) -> None:
    assert list(scan_text(text))


@pytest.mark.parametrize(
    "text",
    ['access_token="' + "a" * 24 + '"', "GET /ws?token=" + "a" * 24 + " HTTP/1.1"],
    ids=["access_token", "token"],
)
def test_scan_labelled_secret_rule_covers_the_access_token_and_token_key_names(text: str) -> None:
    """The rule is built from the redaction key names, so their widening is deliberate."""
    assert list(scan_text(text)) == ["labelled-secret"]


def test_scan_ignores_redacted_placeholders() -> None:
    assert not list(scan_text('{"api_secret": "[redacted:key-name]"}'))
    assert not list(scan_text("password=<omitted>"))


def test_truncation_preserves_newest_and_manifest_says_so(tmp_path: Path) -> None:
    kept, dropped = truncate_newest_first(["n3", "n2", "n1", "n0"], 6)
    assert kept == ["n2", "n3"] and dropped == 2
    lines = [f"line-{i:06d}" + "x" * 90 for i in range(5000, 0, -1)]
    res = _build(tmp_path, _sources(logs=lines), cap_bytes=70 * 1024 + 4000)
    assert res.truncated
    with zipfile.ZipFile(res.path) as zf:
        m = json.loads(zf.read("manifest.json"))
        logs = zf.read("logs.ndjson").decode()
    assert m["truncated"][0]["artefact"] == "logs.ndjson"
    assert m["truncated"][0]["policy"] == "newest-first"
    assert "line-005000" in logs.splitlines()[-1]


def test_window_validation() -> None:
    with pytest.raises(BundleError) as ei:
        validate_window(T1 - timedelta(hours=25), T1)
    assert ei.value.code == "BUNDLE_WINDOW_TOO_LARGE"
    with pytest.raises(BundleError):
        validate_window(T1, T0)
    with pytest.raises(BundleError):
        validate_window(datetime(2026, 1, 1), T1)


def test_disk_insufficient_precheck(tmp_path: Path) -> None:
    with pytest.raises(BundleError) as ei:
        build_bundle(_sources(), tmp_path, T0, T1, cap_bytes=100, free_bytes=lambda p: 199)
    assert ei.value.code == "BUNDLE_DISK_INSUFFICIENT"
    assert list(tmp_path.iterdir()) == []


def test_disk_full_mid_generation_cleans_up(tmp_path: Path) -> None:
    src = _sources()

    def boom() -> str:
        raise OSError(28, "No space left on device")

    src.metrics = boom
    with pytest.raises(BundleError) as ei:
        _build(tmp_path, src)
    assert ei.value.code == "BUNDLE_DISK_INSUFFICIENT"
    assert list(tmp_path.iterdir()) == []


class _Audit:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.calls.append((action, kw))


class _Resolver:
    def __init__(self, perms: set[str] | None) -> None:
        self.p = (
            None
            if perms is None
            else AuditPrincipal(uuid.uuid4(), "own", frozenset(perms), request_id=uuid.uuid4())
        )

    async def resolve(self, request: Any) -> AuditPrincipal | None:
        return self.p


BODY = {"from": T0.isoformat(), "to": T1.isoformat()}


def _listing(p: Path) -> list[str]:
    return os.listdir(p)


def _exists(p: str) -> bool:
    return Path(p).exists()


def _aclient(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def _app(
    tmp: Path, perms: set[str] | None, src: BundleSources | None = None, *, is_async: bool = False
) -> tuple[Any, _Audit, SupportBundleService]:
    svc = SupportBundleService(src or _sources(), tmp)
    a = _Audit()
    app = FastAPI()
    app.include_router(make_support_bundle_router(svc, a, _Resolver(perms)))
    return (_aclient(app) if is_async else TestClient(app)), a, svc


def test_manager_denied_403_audited_no_bundle(tmp_path: Path) -> None:
    c, a, _ = _app(tmp_path, {"audit:read"})
    assert c.post("/admin/support-bundle", json=BODY).status_code == 403
    assert a.calls[0][0] == "health.diagnostics_exported"
    assert a.calls[0][1]["outcome"].value == "denied"
    assert list(tmp_path.iterdir()) == []


def test_fail_closed_without_resolver_or_session(tmp_path: Path) -> None:
    svc = SupportBundleService(_sources(), tmp_path)
    app = FastAPI()
    app.include_router(make_support_bundle_router(svc, _Audit(), None))
    assert TestClient(app).post("/admin/support-bundle", json=BODY).status_code == 501
    c, _, _ = _app(tmp_path, None)
    assert c.post("/admin/support-bundle", json=BODY).status_code == 401
    assert c.get(f"/admin/support-bundle/{uuid.uuid4()}").status_code == 401


def test_bad_requests(tmp_path: Path) -> None:
    c, _, _ = _app(tmp_path, {"admin:read"})
    assert c.post("/admin/support-bundle", json={"x": 1}).status_code == 400
    wide = {"from": (T1 - timedelta(hours=30)).isoformat(), "to": T1.isoformat()}
    r = c.post("/admin/support-bundle", json=wide)
    assert r.status_code == 400 and r.json()["code"] == "BUNDLE_WINDOW_TOO_LARGE"
    assert c.get(f"/admin/support-bundle/{uuid.uuid4()}").status_code == 404


async def test_owner_flow_audited_and_second_request_409(tmp_path: Path) -> None:
    gate = asyncio.Event()
    src = _sources()
    loop = asyncio.get_running_loop()
    inner = src.metrics

    def slow() -> str:
        asyncio.run_coroutine_threadsafe(gate.wait(), loop).result(5)
        return inner()

    src.metrics = slow
    c, a, svc = _app(tmp_path, {"admin:read"}, src, is_async=True)
    first = await c.post("/admin/support-bundle", json=BODY)
    assert first.status_code == 202
    second = await c.post("/admin/support-bundle", json=BODY)
    assert second.status_code == 409 and second.json()["code"] == "BUNDLE_ALREADY_RUNNING"
    gate.set()
    job = svc.get(first.json()["job_id"])
    assert job is not None and job._task is not None
    await job._task
    assert job.status == "succeeded" and job.path and _exists(job.path)
    assert a.calls[-1][0] == "health.diagnostics_exported"
    assert a.calls[-1][1]["after_state"]["size_bytes"] == job.size_bytes
    st = await c.get(f"/admin/support-bundle/{job.id}")
    assert st.json()["status"] == "succeeded"
    # runner is free again
    assert svc.start(T0, T1)._task is not None
    await asyncio.sleep(0)
    for t in asyncio.all_tasks():
        if t is not asyncio.current_task():
            await t


async def test_secret_failure_no_archive_event_and_failure_audit(tmp_path: Path) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    svc = SupportBundleService(
        _sources(logs=[CANARY]), tmp_path, on_event=lambda r, d: events.append((r, d))
    )
    a = _Audit()
    app = FastAPI()
    app.include_router(make_support_bundle_router(svc, a, _Resolver({"admin:read"})))
    r = await _aclient(app).post("/admin/support-bundle", json=BODY)
    job = svc.get(r.json()["job_id"])
    assert job is not None and job._task is not None
    await job._task
    assert job.error_code == "BUNDLE_SECRET_DETECTED" and job.path is None
    assert events[0][0] == "secret_detected"
    assert CANARY.split("=")[1] not in json.dumps(events) + json.dumps(job.view())
    assert a.calls[-1][1]["outcome"].value == "failure"
    assert _listing(tmp_path) == []


async def test_timeout_and_unexpected_error_codes(tmp_path: Path) -> None:
    svc = SupportBundleService(_sources(), tmp_path, timeout_s=0.0)
    job = svc.start(T0, T1)
    assert job._task is not None
    await job._task
    assert job.error_code == "BUNDLE_TIMEOUT"
    src = _sources()

    def bad_health() -> dict[str, Any]:
        raise RuntimeError("x")

    src.health = bad_health
    svc2 = SupportBundleService(src, tmp_path)
    job2 = svc2.start(T0, T1)
    assert job2._task is not None
    await job2._task
    assert job2.error_code == "BUNDLE_FAILED"


async def test_a_job_that_dies_after_a_failed_audit_is_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The audit failed, so the export must go (C-2.9); when that fails too, no one awaits it."""

    async def audit_down(job: BundleJob) -> None:
        raise RuntimeError("audit down")

    def locked(self: Path, *, missing_ok: bool = False) -> None:
        raise PermissionError("export is locked")

    monkeypatch.setattr(Path, "unlink", locked)
    svc = SupportBundleService(_sources(), tmp_path)
    with capture_logs() as logs:
        job = svc.start(T0, T1, on_complete=audit_down)
        assert job._task is not None
        await asyncio.wait({job._task})
    assert [(e["event"], e["log_level"], e["error"]) for e in logs] == [
        ("support_bundle_job_failed", "error", "PermissionError")
    ]


async def test_a_cancelled_job_is_not_logged_as_a_failure(tmp_path: Path) -> None:
    svc = SupportBundleService(_sources(), tmp_path)
    task = svc.start(T0, T1)._task
    assert task is not None
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    with capture_logs() as logs:
        svc._settled(task)  # a cancelled task has no exception to read: reading it raises
    assert logs == []


async def test_drain_with_no_job_in_flight_returns_zero_at_once(tmp_path: Path) -> None:
    assert await SupportBundleService(_sources(), tmp_path).drain() == 0  # `wait` of nothing raises


def test_the_drain_default_is_the_five_second_bound_main_relies_on() -> None:
    assert bundle_module.DRAIN_TIMEOUT_S == 5.0  # `main.py` calls `drain()` with no argument
    assert SupportBundleService.drain.__defaults__ == (bundle_module.DRAIN_TIMEOUT_S,)


async def test_drain_waits_for_the_running_job_and_its_closing_record(tmp_path: Path) -> None:
    release = asyncio.Event()

    async def on_complete(job: BundleJob) -> None:
        await release.wait()

    svc = SupportBundleService(_sources(), tmp_path)
    job = svc.start(T0, T1, on_complete=on_complete)
    try:
        drain = asyncio.ensure_future(svc.drain())
        done, _ = await asyncio.wait({drain}, timeout=0)
        assert not done
        with capture_logs() as logs:
            release.set()
            assert await drain == 0
        assert job._task is not None and job._task.done()  # its closing record has run
        assert svc._tasks == set()  # and the finished job is released
        assert "support_bundle_job_failed" not in {e["event"] for e in logs}  # it succeeded
    finally:
        release.set()  # a failed assertion must not leave the job waiting


async def test_drain_gives_up_at_its_bound_logs_the_job_and_never_cancels_it(
    tmp_path: Path,
) -> None:
    release = asyncio.Event()

    async def on_complete(job: BundleJob) -> None:
        await asyncio.wait_for(release.wait(), 5)  # only bounds the test, if the drain waits on it

    svc = SupportBundleService(_sources(), tmp_path)
    job = svc.start(T0, T1, on_complete=on_complete)
    assert job._task is not None
    try:
        with capture_logs() as logs:
            assert await svc.drain(grace_s=0) == 1
        assert [(e["event"], e["log_level"], e["jobs"]) for e in logs] == [
            ("support_bundle_left_running", "warning", 1)
        ]
    finally:
        release.set()
    await job._task  # raises if the drain had cancelled it: its closing record is audited work
    assert job.status == "succeeded"
