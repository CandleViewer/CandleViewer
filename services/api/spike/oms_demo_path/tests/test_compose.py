# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""The composition (#843 A4 brief items 1 and 2), over the in-memory stores: the harness's M2
start only opens what the stack's boot made, its audit writer keeps a WAL of its own and loads no
lane key, and a KEK the stack never enrolled stops it before anything starts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import AccountRef
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.secrets.store import InMemoryCredentialStore
from spike.oms_demo_path import compose as composition
from spike.oms_demo_path.compose import Stores, app_context, close, compose
from spike.oms_demo_path.config import BUCKET_UID
from spike.oms_demo_path.offline import (
    Corpus,
    CorpusVenue,
    MemoryAuditRepository,
    as_audit_repository,
    default_accounts_fixture,
    default_corpus,
    offline_settings,
    offline_stack,
)
from spike.oms_demo_path.run import offline_m2, offline_proof
from spike.oms_demo_path.safety import WAL_MARKER, Refused, check_audit_dir


def _exists(path: Path) -> bool:
    return path.exists()


@pytest.fixture
async def booted(tmp_path: Path) -> AsyncIterator[tuple[Any, Any, MemoryAuditRepository]]:
    """The stack's boot and key import, then the harness's composition over the same store."""
    settings = offline_settings(tmp_path / "state")
    stack = await offline_stack(
        settings, app_context(settings, ReadOnlyGate()), accounts_fixture=default_accounts_fixture()
    )
    repo = MemoryAuditRepository()
    stores = Stores(stack.store, stack.store, None, as_audit_repository(repo))
    enrolments = len(stack.store.kcv_audit)
    venue = CorpusVenue(Corpus(default_corpus()))
    composed = await compose(
        settings,
        stores,
        rest_transport=httpx.MockTransport(venue.handle),
        private_ws_connect=venue.connect,
        clock_offset_ms=lambda: None,
        build_m2=offline_m2,
        prove=offline_proof,
    )
    assert len(stack.store.kcv_audit) == enrolments  # nothing enrolled by the harness's start
    yield composed, stack, repo
    await close(composed)


async def test_the_harness_audit_writer_keeps_its_own_wal_and_loads_no_lane(
    booted: tuple[Any, Any, MemoryAuditRepository], tmp_path: Path
) -> None:
    composed, _, _ = booted
    wal = Path(composed.settings.audit_wal_path)
    assert wal.parent == tmp_path / "state" / "spike-audit" / "spike"
    assert _exists(wal) and _exists(wal.parent / "breakglass" / "instance.lock")
    assert not _exists(wal.parent / "lane") and not _exists(wal.parent.parent / "lane")
    writer, lane, facade = composed.audit.lane_parts()
    assert writer is not None and facade is not None
    assert lane is None  # no key loaded: no lane.lock taken, no lane built or booted
    assert composed.audit.lane_lock_failures == composed.audit.lane_link_failures == 0
    assert composed.kek_version == 1 and not composed.gate.is_read_only


async def test_m2_start_writes_only_its_kek_loaded_record_and_signs_audited(
    booted: tuple[Any, Any, MemoryAuditRepository],
) -> None:
    composed, stack, repo = booted
    await composed.audit.writer.flush(5.0)
    assert repo.actions() == ["security.kek_loaded"]
    port = composed.port
    account = AccountRef(
        account_id=AccountId(stack.account_id),
        uid=BUCKET_UID,
        environment="demo",
        key_ref=stack.key_ref,
    )
    await port.wallet(account)
    await composed.audit.writer.flush(5.0)
    assert repo.actions() == ["security.kek_loaded", "security.credential_borrowed"]


async def test_close_drains_the_writer_and_reports_its_depth(tmp_path: Path) -> None:
    settings = offline_settings(tmp_path / "state")
    stack = await offline_stack(
        settings, app_context(settings, ReadOnlyGate()), accounts_fixture=default_accounts_fixture()
    )
    venue = CorpusVenue(Corpus(default_corpus()))
    closed: list[str] = []

    async def closer() -> None:
        closed.append("pool")

    stores = Stores(stack.store, stack.store, None, as_audit_repository(MemoryAuditRepository()))
    stores.closers.append(closer)
    composed = await compose(
        settings,
        stores,
        rest_transport=httpx.MockTransport(venue.handle),
        private_ws_connect=venue.connect,
        clock_offset_ms=lambda: None,
        build_m2=offline_m2,
        prove=offline_proof,
    )
    report = await close(composed)
    assert report == {"written": 1, "buffer_depth": 0}
    assert closed == ["pool"]
    assert composed.bundle.lifecycle.health().status.value == "stopped"


async def test_a_kek_the_stack_never_enrolled_refuses_before_anything_starts(
    tmp_path: Path,
) -> None:
    settings = offline_settings(tmp_path / "state")
    store = InMemoryCredentialStore()  # no boot of the stack: no check value enrolled
    stores = Stores(store, store, None, as_audit_repository(MemoryAuditRepository()))
    venue = CorpusVenue(Corpus(default_corpus()))
    with pytest.raises(Refused, match="kek_not_enrolled"):
        await compose(
            settings,
            stores,
            rest_transport=httpx.MockTransport(venue.handle),
            private_ws_connect=venue.connect,
            clock_offset_ms=lambda: None,
            build_m2=offline_m2,
            prove=offline_proof,
        )
    assert store.kcvs == {} and not _exists(Path(settings.audit_wal_path))


async def test_a_previous_kek_handle_refuses(tmp_path: Path) -> None:
    settings = offline_settings(tmp_path / "state").model_copy(
        update={"kek_prev_handle": "/run/secrets/cv_kek_prev"}
    )
    store = InMemoryCredentialStore()
    stores = Stores(store, store, None, as_audit_repository(MemoryAuditRepository()))
    venue = CorpusVenue(Corpus(default_corpus()))
    with pytest.raises(Refused, match="previous KEK"):
        await compose(
            settings,
            stores,
            rest_transport=httpx.MockTransport(venue.handle),
            private_ws_connect=venue.connect,
            clock_offset_ms=lambda: None,
            build_m2=offline_m2,
            prove=offline_proof,
        )


async def test_a_latched_m2_refuses_and_stops_what_started(tmp_path: Path) -> None:
    settings = offline_settings(tmp_path / "state")
    stack = await offline_stack(
        settings, app_context(settings, ReadOnlyGate()), accounts_fixture=default_accounts_fixture()
    )
    stack.store.rows[next(iter(stack.store.rows))]["kek_version"] = 7  # a stranded row
    stores = Stores(stack.store, stack.store, None, as_audit_repository(MemoryAuditRepository()))
    venue = CorpusVenue(Corpus(default_corpus()))
    with pytest.raises(Refused, match="M2 did not come up clean"):
        await compose(
            settings,
            stores,
            rest_transport=httpx.MockTransport(venue.handle),
            private_ws_connect=venue.connect,
            clock_offset_ms=lambda: None,
            build_m2=offline_m2,
            prove=offline_proof,
        )


def test_production_m2_never_passes_the_export_signing_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def capture(*args: Any, **kwargs: Any) -> str:
        seen.update(kwargs)
        return "bundle"

    monkeypatch.setattr(composition, "build_secrets_service", capture)
    marker: Any = object()
    built: object = composition.production_m2(marker, marker, marker, marker)
    assert built == "bundle"
    assert seen == {"auth_keys": marker, "export_keys": None}


def test_the_offline_wal_directory_is_marked_as_the_harness_s(tmp_path: Path) -> None:
    settings = offline_settings(tmp_path / "state")
    directory = check_audit_dir(
        settings.audit_wal_path,
        stack_wal="/var/lib/candleviewer/audit/audit.wal",
        stack_volume="cv-audit-data",
        mountinfo="",
    )
    assert (directory / WAL_MARKER).read_text().startswith("the E29-K01 harness")
