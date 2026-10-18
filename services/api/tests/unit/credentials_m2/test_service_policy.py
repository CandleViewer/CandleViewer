"""KEK version policy, gate latch, and settings → sources (e27-kek.md §4-§6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.observability.health import HealthStatus
from candleviewer.secrets._kek import NoKekSource, PathKekSource
from candleviewer.secrets._source import sources_from_settings, validate_kek_settings
from candleviewer.secrets.errors import KekSourceNotPermitted
from candleviewer.secrets.service import REASONS
from candleviewer.secrets.store import InMemoryCredentialStore
from candleviewer.settings import Environment
from tests.unit.credentials_m2._service_fakes import (
    _PASS,
    KEK_V3,
    _boot,
    _borrow,
    _ctx,
    _settings,
    _Src,
    _store_one,
    _svc,
    _zeroed,
)
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2, AuditLog


def test_failure_reason_children_preinitialised() -> None:
    from prometheus_client import generate_latest

    text = generate_latest().decode()
    for reason in REASONS:
        assert f'cv_kek_load_failures_total{{reason="{reason}"}}' in text


async def test_latch_overrides_existing_mesh_trip_and_notifies() -> None:
    gate = ReadOnlyGate()
    seen: list[tuple[bool, str | None, str | None]] = []
    gate.subscribe(lambda ro, code, text: seen.append((ro, code, text)))
    gate.trip(reason_code="net.public_binding_detected", reason_text="mesh")
    gate.latch(reason_code="secrets.kek_unavailable", reason_text="kek")
    gate.clear(check_result=_PASS)
    gate.trip(reason_code="net.other", reason_text="x")
    assert gate.is_read_only and gate.reason_code == "secrets.kek_unavailable"
    assert gate.reason_text == "kek" and seen[-1] == (True, "secrets.kek_unavailable", "kek")


async def test_latched_gate_refuses_order_placement() -> None:
    from candleviewer.oms.validator import OrderPlacementRefused, Validator

    svc, ctx = _svc(_Src(None, 1)), _ctx()
    await svc.start(ctx)
    with pytest.raises(OrderPlacementRefused) as ei:
        Validator(read_only_gate=ctx.oms_read_only_gate).assert_order_placement_allowed()
    assert ei.value.reason_code == "secrets.kek_unavailable"


async def test_kcv_mismatch_degrades_and_zeroes() -> None:
    store = InMemoryCredentialStore()
    await _boot(store, _Src(KEK_V1, 1))
    src = _Src(KEK_V2, 1)
    svc = await _boot(store, src)
    assert svc.health().detail == "kek_mismatch" and _zeroed(src)


async def test_noop_rotation_same_kek_two_versions_degrades() -> None:
    store = InMemoryCredentialStore()
    await _boot(store, _Src(KEK_V1, 1))
    cur, prev = _Src(KEK_V1, 2), _Src(KEK_V1, 1)
    svc = await _boot(store, cur, prev)
    assert svc.health().detail == "kek_reused" and _zeroed(cur) and _zeroed(prev)


async def test_downgrade_to_retired_kek_degrades() -> None:
    store = InMemoryCredentialStore()
    await _boot(store, _Src(KEK_V1, 1))
    await _boot(store, _Src(KEK_V2, 2), _Src(KEK_V1, 1))
    store.retired.add(("demo", 1))
    assert (await _boot(store, _Src(KEK_V1, 1))).health().detail == "kek_retired"
    rot = await _boot(store, _Src(KEK_V3, 3), _Src(KEK_V1, 1))
    assert rot.health().detail in {"kek_retired", "kek_version_out_of_sequence"}


async def test_version_out_of_sequence_degrades() -> None:
    store = InMemoryCredentialStore()
    await _boot(store, _Src(KEK_V1, 1))
    assert (await _boot(store, _Src(KEK_V2, 3))).health().detail == "kek_version_out_of_sequence"
    jump = await _boot(store, _Src(KEK_V2, 2))  # max+1 without the previous KEK
    assert jump.health().detail == "kek_version_out_of_sequence"


async def test_prev_kek_mid_rotation_borrow_and_rewrap_records_owner() -> None:
    store = InMemoryCredentialStore()
    v1 = await _boot(store, _Src(KEK_V1, 1))
    meta = await _store_one(v1)
    audit = AuditLog()
    v2 = _svc(_Src(KEK_V2, 2), _Src(KEK_V1, 1), store=store, audit=audit)
    await v2.start(_ctx())
    assert v2.health().status is HealthStatus.OK
    assert await _borrow(v2, meta.key_id) == "ABCD1234"  # still at v1
    rep = await v2.rewrap_deks(2, environment="demo", actor_user_id="owner-1", actor_role="owner")
    assert (rep.rewrapped, rep.remaining) == (1, 0)
    assert audit.records[-1][1]["actor_user_id"] == "owner-1"


async def test_prev_kek_without_recorded_kcv_degrades() -> None:
    svc = await _boot(InMemoryCredentialStore(), _Src(KEK_V2, 2), _Src(KEK_V1, 1))
    assert svc.health().detail in {"kek_mismatch", "kek_version_out_of_sequence"}


def test_file_source_in_live_refused_by_settings_before_boot() -> None:
    with pytest.raises(ValueError, match="kek_source_not_permitted"):
        _settings(environment=Environment.LIVE, kek_source="file")


def test_validate_refuses_file_in_live() -> None:
    s = _settings(kek_source="file").model_copy(update={"environment": Environment.LIVE})
    with pytest.raises(KekSourceNotPermitted):
        validate_kek_settings(s)


def test_file_source_in_demo_warns(capsys: pytest.CaptureFixture[str]) -> None:
    validate_kek_settings(_settings(kek_source="file"))  # warns, does not raise


@pytest.mark.parametrize("src", ["handle", "host-keychain"])
def test_handle_source_allows_fifo(src: str) -> None:
    s = sources_from_settings(_settings(kek_source=src, kek_handle="/x", kek_ack_path="/a"))
    assert isinstance(s.current, PathKekSource) and s.current.allow_fifo
    assert s.ack_path == Path("/a") and s.previous is None


def test_none_source() -> None:
    assert isinstance(sources_from_settings(_settings(kek_source="none")).current, NoKekSource)


def test_previous_source_version() -> None:
    s = sources_from_settings(_settings(kek_source="file", kek_prev_handle="/p", kek_version=2))
    assert isinstance(s.previous, PathKekSource) and s.previous.version == 1
    assert s.ack_path is None


def test_sources_bind_the_process_environment() -> None:
    """#2338: every KEK is loaded for the process environment, current and previous alike."""
    s = sources_from_settings(
        _settings(environment="testnet", kek_source="file", kek_prev_handle="/p", kek_version=2)
    )
    assert isinstance(s.current, PathKekSource) and isinstance(s.previous, PathKekSource)
    assert (s.current.env_name, s.previous.env_name) == ("testnet", "testnet")


def test_live_flag_propagates() -> None:
    s = sources_from_settings(
        _settings(environment=Environment.LIVE, kek_source="handle", kek_ack_path="/a")
    )
    assert isinstance(s.current, PathKekSource) and s.current.live


def test_live_fifo_handle_without_ack_path_refused_before_any_read() -> None:
    """A live launcher-FIFO handle with no ack path is a pre-boot config error (fatal), so the
    read-once FIFO is never drained and the launcher never sees a false theft signal."""
    with pytest.raises(KekSourceNotPermitted):
        validate_kek_settings(_settings(environment=Environment.LIVE, kek_source="handle"))


def test_live_systemd_credential_needs_no_ack_path() -> None:
    s = _settings(
        environment=Environment.LIVE, kek_source="handle", kek_handle="/run/credentials/cv/kek"
    )
    validate_kek_settings(s)
    assert sources_from_settings(s).ack_path is None
