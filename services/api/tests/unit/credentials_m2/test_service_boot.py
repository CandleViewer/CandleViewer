"""SecretsService boot edge cases: handoff ack ordering, fake backend, latch-first, bounds."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from candleviewer.observability.health import HealthStatus
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets._source import KekSources
from candleviewer.secrets.service import SecretsService
from candleviewer.secrets.store import InMemoryCredentialStore
from candleviewer.settings import Environment
from tests.unit.credentials_m2._service_fakes import (
    _boot,
    _ctx,
    _Src,
    _svc,
)
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2, AuditLog


async def test_ack_written_once_after_all_handles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Order pinned: handoff read before any FIFO opens; one ack after the *last* handle."""
    from candleviewer.secrets import _kek

    store = InMemoryCredentialStore()
    await _boot(store, _Src(KEK_V1, 1))
    h = tmp_path / "h"
    h.mkdir()
    (h / "handoff").write_text("nonce-1234abcd")
    (h / "handoff").chmod(0o400)
    os.mkfifo(h / "cv_kek", 0o600)  # the configured handle is a FIFO (lstat, never opened here)
    order: list[str] = []
    real_read, real_write = _kek.read_handoff, _kek.write_ack

    def read(d: Path) -> str:
        order.append("handoff")
        return real_read(d)

    def write(nonce: str, path: Path) -> None:
        order.append("ack")
        real_write(nonce, path)

    monkeypatch.setattr(_kek, "read_handoff", read)
    monkeypatch.setattr(_kek, "write_ack", write)
    cur, prev = _Src(KEK_V2, 2, fifo=True), _Src(KEK_V1, 1, fifo=True)
    for src in (cur, prev):
        real = src.load

        def load(real: Callable[[], LoadedKek] = real, src: _Src = src) -> LoadedKek:
            order.append(f"load{src.version}")
            if src.version == 2:  # launcher: write → close → unlink handoff + dir
                (h / "handoff").chmod(0o600)
                (h / "handoff").unlink()
            return real()

        src.load = load  # type: ignore[method-assign]
    ack = tmp_path / "ack"
    svc = _svc(cur, prev, store=store, ack=ack)
    await svc.start(_ctx(kek_handle=str(h / "cv_kek"), kek_version=2))
    assert order == ["handoff", "load2", "load1", "ack"]
    assert ack.read_text() == "nonce-1234abcd\n"
    assert svc.health().status is HealthStatus.OK


async def test_live_fifo_on_previous_handle_only_needs_the_ack() -> None:
    store = InMemoryCredentialStore()
    await _boot(store, _Src(KEK_V1, 1))
    svc = _svc(_Src(KEK_V2, 2), _Src(KEK_V1, 1, fifo=True), store=store)
    await svc.start(_ctx(environment=Environment.LIVE, kek_source="none", kek_version=2))
    assert svc.health().detail == "kek_handle_permissions"


async def test_no_store_fake_backend_not_latched_reports_stopped() -> None:
    svc, ctx = SecretsService(harden=lambda: True), _ctx(kek_source="none")
    await svc.start(ctx)
    assert not ctx.oms_read_only_gate.is_read_only
    assert svc.health().status is HealthStatus.STOPPED


async def test_no_store_in_live_latches_and_reports_degraded() -> None:
    svc = SecretsService(harden=lambda: True)
    ctx = _ctx(environment=Environment.LIVE, kek_source="none")
    await svc.start(ctx)
    assert ctx.oms_read_only_gate.is_read_only and svc.health().status is HealthStatus.DEGRADED


async def test_degrade_latches_even_if_metric_and_log_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from candleviewer.secrets import _metrics

    class _Boom:
        def labels(self, **k: Any) -> Any:
            raise RuntimeError("metric")

        def set(self, v: Any) -> None:
            raise RuntimeError("metric")

    monkeypatch.setattr(_metrics, "kek_load_failures_total", _Boom())
    svc, ctx = _svc(_Src(None, 1)), _ctx()
    with pytest.raises(RuntimeError, match="metric"):
        await svc.start(ctx)
    assert ctx.oms_read_only_gate.is_read_only  # enforcement happened first


async def test_generator_exit_during_boot_closes_and_latches() -> None:
    src = _Src(KEK_V1, 1, exc=GeneratorExit())
    svc, ctx = _svc(src), _ctx()
    with pytest.raises(GeneratorExit):
        await svc.start(ctx)
    assert ctx.oms_read_only_gate.is_read_only


async def test_kcv_versions_that_never_return_degrade_within_bound() -> None:
    store = InMemoryCredentialStore()

    async def hang() -> list[Any]:
        await asyncio.Event().wait()
        return []

    store.kcv_versions = hang  # type: ignore[method-assign]
    svc, ctx = _svc(_Src(KEK_V1, 1), store=store), _ctx()
    await asyncio.wait_for(svc.start(ctx), timeout=10)
    assert svc.health().detail == "kcv_store_unavailable"


async def test_systemd_regular_file_with_ack_path_does_not_read_handoff(tmp_path: Path) -> None:
    """An ack path set (e.g. from a shared env file) is ignored for a non-FIFO handle."""
    k = tmp_path / "kek"
    k.write_bytes(KEK_V1)
    svc = _svc(_Src(KEK_V1, 1), ack=tmp_path / "ack")
    await svc.start(_ctx(kek_handle=str(k)))
    assert svc.health().status is HealthStatus.OK and not (tmp_path / "ack").exists()


@pytest.mark.parametrize("stage", ["harden", "read_handoff", "write_ack"])
async def test_boot_thread_offloads_are_bounded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stage: str
) -> None:
    """Each boot-time thread offload has a bound: a hang degrades instead of stalling boot."""
    import threading

    from candleviewer.secrets import _kek

    gate = threading.Event()

    def hang(*a: Any) -> Any:
        gate.wait(5)
        raise RuntimeError("released")

    h = tmp_path / "h"
    h.mkdir()
    (h / "handoff").write_text("nonce-1234abcd")
    (h / "handoff").chmod(0o400)
    os.mkfifo(h / "cv_kek", 0o600)
    harden = hang if stage == "harden" else (lambda: True)
    if stage in ("read_handoff", "write_ack"):
        monkeypatch.setattr(_kek, stage, hang)
    st = InMemoryCredentialStore()
    svc = SecretsService(
        store=st, kcv_store=st, audit=AuditLog(), harden=harden, load_timeout_s=0.1,
        sources=lambda s: KekSources(_Src(KEK_V1, 1, fifo=True), None, tmp_path / "ack"),
    )  # fmt: skip
    try:
        await asyncio.wait_for(svc.start(_ctx(kek_handle=str(h / "cv_kek"))), timeout=3)
    finally:
        gate.set()
    assert svc.health().detail == "kek_unavailable"
