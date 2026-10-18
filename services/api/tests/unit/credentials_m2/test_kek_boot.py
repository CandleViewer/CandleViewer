"""KEK boot (#2266 PR C): the previous KEK is verified before a new KCV is enrolled, an enrolment
commits with its `security.kek_enrolled` record, and unrevoked rows at a KEK version the process
did not load degrade it while it keeps the broker (decision 3 of the #2266 ruling), on M2's
in-memory store."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Iterator
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.observability.health import HealthStatus
from candleviewer.secrets import _metrics as m
from candleviewer.secrets.errors import CredentialUnavailable, KekUnavailable
from candleviewer.secrets.service import (
    REASONS,
    STRANDED_GATE_REASON,
    STRANDED_REMEDIATION,
    SecretsService,
)
from candleviewer.secrets.store import InMemoryCredentialStore
from tests.unit.credentials_m2._service_fakes import (
    KEK_V3,
    _borrow,
    _ctx,
    _Src,
    _store_one,
    _svc,
    _zeroed,
)
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2, AuditLog, kek

_LOADED, _STRANDED = "security.kek_loaded", "security.kek_rows_stranded"
_SYSTEM = {"actor_kind": "system", "actor_role": "secrets", "env": "demo"}


async def _start(
    store: InMemoryCredentialStore, *srcs: _Src, audit: AuditLog | None = None
) -> tuple[SecretsService, Any]:
    svc, ctx = _svc(*srcs, store=store, audit=audit), _ctx()
    await svc.start(ctx)
    return svc, ctx


async def _mid_rotation() -> tuple[InMemoryCredentialStore, UUID, UUID]:
    """A key stored under v1, the rotation boot (v2 beside v1), a key stored under v2 and no
    re-wrap: the first key is still at v1."""
    store = InMemoryCredentialStore()
    old = await _store_one((await _start(store, _Src(KEK_V1, 1)))[0])
    new = await _store_one((await _start(store, _Src(KEK_V2, 2), _Src(KEK_V1, 1)))[0])
    return store, old.key_id, new.key_id


async def _stranded() -> tuple[SecretsService, Any, AuditLog]:
    """The boot with only v2 loaded, not started yet: the key stored under v1 is stranded."""
    store, _, _ = await _mid_rotation()
    audit = AuditLog()
    return _svc(_Src(KEK_V2, 2), store=store, audit=audit), _ctx(), audit


@contextlib.contextmanager
def _short_bounds_fire_at_once() -> Iterator[list[float]]:
    """The running loop's `call_at` as the fake clock (C-13.7) for the boot's short bounds (under
    10 s): such a timer fires at the next turn of the loop and its delay is recorded; longer ones
    run as they are. A bound around an await that never suspends is cancelled before it can fire."""
    loop = asyncio.get_running_loop()
    real, fired = loop.call_at, list[float]()

    def timer(when: float, callback: Callable[..., object], *args: object, **kw: Any) -> Any:
        delay = when - loop.time()
        if delay >= 10:
            return real(when, callback, *args, **kw)

        def fire(*called: object) -> None:
            fired.append(delay)
            callback(*called)

        return real(loop.time(), fire, *args, **kw)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(loop, "call_at", timer)
        yield fired


class _NoStrandedRecord(AuditLog):
    async def __call__(self, action: str, fields: dict[str, str]) -> None:
        if action == _STRANDED:
            raise RuntimeError("audit down")
        await super().__call__(action, fields)


class _Outraced(InMemoryCredentialStore):
    """Another boot enrolled `(env, version)` with a different KCV after this boot's read: the
    insert conflicts and hands back the winner's."""

    async def record_kcv(
        self, env: str, version: int, kcv: bytes, *, audit: tuple[str, dict[str, str]]
    ) -> tuple[bytes, bool]:
        winner = kek(KEK_V2, version, env).kcv()
        self.kcvs[(env, version)] = winner
        return winner, False


async def test_a_wrong_previous_kek_is_refused_before_the_new_kcv_is_enrolled() -> None:
    """#2266 item 6: verified first, a wrong previous KEK never pins v(n+1)."""
    store = InMemoryCredentialStore()
    await _start(store, _Src(KEK_V1, 1))
    enrolled, audit = list(store.kcv_audit), AuditLog()
    svc, _ = await _start(store, _Src(KEK_V2, 2), _Src(KEK_V3, 1), audit=audit)
    assert svc.health().detail == "kek_mismatch" and ("demo", 2) not in store.kcvs
    assert store.kcv_audit == enrolled and audit.actions() == ["security.kek_load_failed"]


async def test_a_previous_kek_that_was_never_enrolled_is_refused_and_enrols_nothing() -> None:
    """#2266 item 6, `must_exist`: no trust on first use for the previous KEK. A previous handle
    left set on a first boot names a version the lineage never recorded: it is refused before
    the current KEK is enrolled, and neither KCV is pinned."""
    store = InMemoryCredentialStore()
    svc, _ = await _start(store, _Src(KEK_V1, 1), _Src(KEK_V2, 7))
    assert svc.health().detail == "kek_mismatch" and store.kcvs == {} and store.kcv_audit == []


async def test_a_boot_that_lost_the_enrolment_race_to_another_kcv_is_refused() -> None:
    """The KCV the store holds after the insert decides, not the KEK's own."""
    src, audit = _Src(KEK_V1, 1), AuditLog()
    svc, ctx = await _start(_Outraced(), src, audit=audit)
    assert svc.health().detail == "kek_mismatch" and ctx.oms_read_only_gate.is_read_only
    assert _zeroed(src) and audit.actions() == ["security.kek_load_failed"]


async def test_an_enrolment_commits_its_record_with_the_kcv_row_not_through_the_sink() -> None:
    store, audit = InMemoryCredentialStore(), AuditLog()
    await _start(store, _Src(KEK_V1, 1), audit=audit)
    await _start(store, _Src(KEK_V1, 1))  # enrolled already: no second record
    fields = {**_SYSTEM, "kek_version": "1", "kcv": store.kcvs[("demo", 1)].hex()}
    assert store.kcv_audit == [("security.kek_enrolled", fields)] and audit.actions() == [_LOADED]


async def test_the_stranded_latch_comes_first_then_the_record_then_the_broker() -> None:
    """At the latch no broker is published and only `kek_loaded` is written (#2266 ruling,
    decision 3)."""
    svc, ctx, audit = await _stranded()
    at_latch: list[tuple[str | None, bool, list[str]]] = []
    ctx.oms_read_only_gate.subscribe(
        lambda _ro, code, _text: at_latch.append((code, svc._broker is None, audit.actions()))
    )
    await svc.start(ctx)
    assert at_latch == [("secrets.kek_rows_stranded", True, [_LOADED])]
    assert audit.actions() == [_LOADED, _STRANDED] and svc._broker is not None


async def test_the_stranded_record_carries_the_environment_the_version_and_the_count() -> None:
    """What M2 hands the audit sink. The stored state has `kek_version` redacted: the audit
    redactor drops every field named `*kek*` (#3577; `test_secrets_audit_row.py` pins it)."""
    svc, ctx, audit = await _stranded()
    await svc.start(ctx)
    assert audit.records[-1] == (_STRANDED, {**_SYSTEM, "kek_version": "2", "stranded": "1"})


async def test_a_stranded_boot_reports_degraded_with_its_reason() -> None:
    svc, ctx, _ = await _stranded()
    await svc.start(ctx)
    report = svc.health()
    assert (report.status, report.detail) == (HealthStatus.DEGRADED, "kek_rows_stranded")


async def test_the_stranded_gate_text_names_the_previous_handle_and_revocation() -> None:
    svc, ctx, _ = await _stranded()
    await svc.start(ctx)
    text = ctx.oms_read_only_gate.reason_text or ""
    assert "CV_KEK_PREV_HANDLE" in text and "revoke" in text


async def test_a_stranded_boot_counts_a_kek_rows_stranded_failure() -> None:
    failures = m.kek_load_failures_total.labels(reason="kek_rows_stranded")
    svc, ctx, _ = await _stranded()
    before = failures._value.get()
    await svc.start(ctx)
    assert failures._value.get() == before + 1


def test_the_stranded_failure_reason_is_preinitialised_at_zero() -> None:
    """`test_failure_reason_children_preinitialised` checks each entry of `REASONS`; this pins the
    entry, so the series starts at 0 and an `increase()` sees the first stranded boot."""
    assert STRANDED_GATE_REASON.removeprefix("secrets.") in REASONS


async def test_a_boot_counts_the_stranded_rows_of_its_own_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2.11: a testnet process counts testnet rows, never another environment's."""
    store, seen = InMemoryCredentialStore(), list[str]()
    count = store.count_stranded

    async def spy(env: str, *versions: int) -> int:
        seen.append(env)
        return await count(env, *versions)

    monkeypatch.setattr(store, "count_stranded", spy)
    await _svc(_Src(KEK_V1, 1), store=store).start(_ctx(environment="testnet"))
    assert seen == ["testnet"]


@pytest.mark.parametrize(
    ("gauge", "value"), [(m.kek_degraded_state, 1), (m.kek_version, 2)], ids=["degraded", "version"]
)
async def test_a_stranded_boot_pages_while_publishing_the_loaded_kek_version(
    gauge: Any, value: int
) -> None:
    svc, ctx, _ = await _stranded()
    gauge.set(0)
    await svc.start(ctx)
    assert gauge._value.get() == value


async def test_a_stranded_boot_logs_the_count_the_version_and_the_remediation() -> None:
    svc, ctx, _ = await _stranded()
    with capture_logs() as logs:
        await svc.start(ctx)
    [line] = [e for e in logs if e["event"] == "secrets.kek_rows_stranded"]
    shown = (line["log_level"], line["stranded"], line["kek_version"], line["remediation"])
    assert shown == ("critical", 1, 2, STRANDED_REMEDIATION)


async def test_a_stranded_key_fails_closed_while_the_other_keys_sign() -> None:
    store, old, new = await _mid_rotation()
    svc, _ = await _start(store, _Src(KEK_V2, 2))
    with pytest.raises(CredentialUnavailable):
        await _borrow(svc, old)
    assert await _borrow(svc, new) == "ABCD1234"
    check = await svc.verify_kek_possession()
    assert (check.version, check.kcv_ok, check.reason) == (2, True, "kek_rows_stranded")


async def test_a_stranded_key_is_destroyed_with_its_record_and_the_next_boot_is_ok() -> None:
    """Recovery (b), v(n) lost: `destroy` needs no KEK, so the revoke path stays reachable."""
    store, old, _ = await _mid_rotation()
    audit = AuditLog()
    svc, _ = await _start(store, _Src(KEK_V2, 2), audit=audit)
    await svc._require().destroy(old)
    assert audit.actions()[-1] == "security.credential_destroyed" and store.rows[old]["revoked"]
    again, ctx = await _start(store, _Src(KEK_V2, 2))
    assert again.health().status is HealthStatus.OK and not ctx.oms_read_only_gate.is_read_only


@pytest.mark.parametrize(
    ("change", "loaded"),
    [({}, 2), ({"revoked": True}, 1), ({"status": "revoked"}, 1), ({"env": "live"}, 1)],
    ids=["previous_kek_loaded", "revoked_at", "status_revoked", "other_environment"],
)
async def test_no_row_is_stranded_that_the_boot_can_open_or_never_signs(
    change: dict[str, Any], loaded: int
) -> None:
    store, old, _ = await _mid_rotation()
    store.rows[old].update(change)
    svc, ctx = await _start(store, *[_Src(KEK_V2, 2), _Src(KEK_V1, 1)][:loaded])
    assert svc.health().status is HealthStatus.OK and not ctx.oms_read_only_gate.is_read_only
    assert (await svc.verify_kek_possession()).reason is None


async def _down(env: str, *loaded_versions: int) -> int:
    raise RuntimeError("db down")


async def _hang(env: str, *loaded_versions: int) -> int:
    await asyncio.Event().wait()
    return 0


async def _assert_degraded_fully(
    svc: SecretsService, ctx: Any, src: _Src, key: UUID, reason: str
) -> None:
    """No KEK is published: the gate is latched as unavailable, the KEK is zeroed and the broker
    is gone, so not even a key that is not stranded signs."""
    gate = ctx.oms_read_only_gate
    assert svc.health().detail == reason and gate.reason_code == "secrets.kek_unavailable"
    assert _zeroed(src)
    with pytest.raises(KekUnavailable):
        await _borrow(svc, key)


async def test_a_stranded_boot_whose_count_fails_degrades_fully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The count runs before `security.kek_loaded`; the KEK is published only after both."""
    store, _, new = await _mid_rotation()
    monkeypatch.setattr(store, "count_stranded", _down)
    src, audit = _Src(KEK_V2, 2), AuditLog()
    svc, ctx = await _start(store, src, audit=audit)
    assert audit.actions() == ["security.kek_load_failed"]
    await _assert_degraded_fully(svc, ctx, src, new, "kcv_store_unavailable")


async def test_a_stranded_count_that_never_returns_degrades_fully_within_its_two_second_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The count is not routed through the broker's `_io`: its own bound is the only one, and the
    one that fires on the fake clock is 2 s. A longer bound, or none, ends at the guard."""
    store, _, new = await _mid_rotation()
    monkeypatch.setattr(store, "count_stranded", _hang)
    src, audit = _Src(KEK_V2, 2), AuditLog()
    async with asyncio.timeout(5):  # ends a regression's hang
        with _short_bounds_fire_at_once() as fired:
            svc, ctx = await _start(store, src, audit=audit)
    assert fired == [pytest.approx(2.0, abs=0.1)]
    assert audit.actions() == ["security.kek_load_failed"]
    await _assert_degraded_fully(svc, ctx, src, new, "kcv_store_unavailable")


async def test_a_stranded_boot_whose_record_is_refused_degrades_fully() -> None:
    store, _, new = await _mid_rotation()
    src, audit = _Src(KEK_V2, 2), _NoStrandedRecord()
    svc, ctx = await _start(store, src, audit=audit)
    assert audit.actions() == [_LOADED, "security.kek_load_failed"]
    await _assert_degraded_fully(svc, ctx, src, new, "audit_unavailable")
