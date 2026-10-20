"""`/indicator-presets` audit and metrics (E13-T03, #427; C-2.9, IR-19, O1): every write is
recorded ahead of the row, the record carries the code and a content digest but never the
parameters, a refused record stores nothing, and the two series follow the writes (the gauge is
read at startup too)."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
from typing import Any

import pytest
from _presets_env import (
    EMA9,
    SID,
    USER_A,
    USER_B,
    Audit,
    Env,
    FakePresetRepo,
    Metrics,
    body,
    new_ids,
    principal,
)
from sqlalchemy.exc import OperationalError
from structlog.testing import capture_logs

from candleviewer.api.indicator_presets_models import PresetInput
from candleviewer.api.indicator_presets_service import (
    IndicatorPresetService,
    IndicatorPresetsGaugePrimer,
    content_sha256,
)
from candleviewer.audit.redact import redact
from candleviewer.audit.writer import AuditUnavailable, AuditWriterStopped
from candleviewer.orderflow.indicators.catalogue import default_catalogue
from candleviewer.storage.repositories.indicator_presets import (
    Occupancy,
    PresetFields,
    PresetNotFoundError,
)


def _ordered(env: Env) -> list[str]:
    """One log of audit actions and store writes, in the order they happened."""
    log: list[str] = []
    emit, call = env.audit.emit, env.repo._call

    async def audited(action: str, **kw: Any) -> None:
        log.append(f"audit:{action}")
        await emit(action, **kw)

    def stored(name: str, **kw: Any) -> None:
        if name in ("create", "update", "soft_delete"):
            log.append(f"store:{name}")
        call(name, **kw)

    env.audit.emit = audited  # type: ignore[method-assign]  # the test's spy
    env.repo._call = stored  # type: ignore[method-assign]  # the test's spy
    return log


def test_every_write_is_audited_ahead_of_its_row() -> None:
    env = Env()
    log = _ordered(env)
    made = env.create()
    env.c.put(f"/indicator-presets/{made['id']}", json=body(name="Renamed"))
    env.c.delete(f"/indicator-presets/{made['id']}")
    assert log == [
        "audit:indicator_preset.created", "store:create",
        "audit:indicator_preset.updated", "store:update",
        "audit:indicator_preset.deleted", "store:soft_delete",
    ]  # fmt: skip


def test_records_name_the_preset_and_carry_the_code_and_digest_only() -> None:
    env = Env()
    made = env.create()
    env.c.put(f"/indicator-presets/{made['id']}", json=body(name="Renamed", params={"n": 20}))
    env.c.delete(f"/indicator-presets/{made['id']}")
    created, updated, deleted = env.audit.calls
    expected = PresetFields("atr", "ATR 14", {"n": 14}, {}, "subpane", False)
    renamed = dataclasses.replace(expected, name="Renamed", params={"n": 20})
    assert created["after_state"] == {"indicator_code": "atr",
                                      "content_sha256": content_sha256(expected)}  # fmt: skip
    assert updated["before_state"] == created["after_state"]
    assert updated["after_state"]["content_sha256"] == content_sha256(renamed)
    assert deleted["before_state"] == updated["after_state"] and "after_state" not in deleted
    for record in (created, updated, deleted):
        assert (record["object_kind"], record["object_id"]) == ("indicator_preset", made["id"])
        assert (record["actor_user_id"], record["session_id"], record["actor_ip"]) == (
            USER_A, SID, "10.0.0.9",
        )  # fmt: skip
        text = json.dumps(record, default=str)
        assert '"n"' not in text and "Renamed" not in text and "ATR 14" not in text


def test_the_digest_is_sha256_of_the_canonical_preset_and_survives_the_audit_redaction() -> None:
    fields = PresetFields("ema", "Fast", {"n": 9}, {}, "overlay", True)
    canonical = json.dumps(dataclasses.asdict(fields), sort_keys=True, separators=(",", ":"))
    assert content_sha256(fields) == hashlib.sha256(canonical.encode()).hexdigest()
    state = {"indicator_code": "ema", "content_sha256": content_sha256(fields)}
    assert redact(state) == state  # a `*hash*` key would be dropped by the redaction


@pytest.mark.parametrize("error", [AuditUnavailable("down"), AuditWriterStopped()])
@pytest.mark.parametrize("op", ["create", "update", "delete"])
def test_a_refused_audit_record_is_503_audit_unavailable_and_nothing_is_stored(
    op: str, error: Exception
) -> None:
    env = Env()
    made = env.create()
    before = dict(env.repo.rows)
    env.audit.fail = error
    with capture_logs() as logs:
        if op == "create":
            r = env.c.post("/indicator-presets", json=body(name="Other"))
        elif op == "update":
            r = env.c.put(f"/indicator-presets/{made['id']}", json=body(name="Other"))
        else:
            r = env.c.delete(f"/indicator-presets/{made['id']}")
    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert r.headers["retry-after"] == "5"
    assert env.repo.rows == before and not env.repo.deleted
    assert [e["event"] for e in logs] == ["indicator_presets_audit_unavailable"]


def test_a_409_after_the_record_is_the_race_the_pre_check_lost() -> None:
    """The store decides `ux_ip_name` again: a concurrent create can take the name between the
    pre-check and the insert, so that 409 follows a `created` record (a known false positive)."""
    env = Env()
    env.create(name="Fast")

    async def stale(owner: str, name_key: Any = None, *, exclude_id: Any = None) -> Occupancy:
        return Occupancy(1, False)  # the pre-check's read, before the concurrent insert

    env.repo.occupancy = stale  # type: ignore[method-assign]  # simulates the lost race
    r = env.c.post("/indicator-presets", json=body(name="FAST"))
    assert (r.status_code, r.json()["errors"][0]["rule"]) == (409, "name_taken")
    assert env.audit.actions().count("indicator_preset.created") == 2


def test_pre_checked_conflicts_write_no_record() -> None:
    env = Env()
    env.create(name="Fast")
    calls = len(env.audit.calls)
    assert env.c.post("/indicator-presets", json=body(name="fast")).status_code == 409
    assert len(env.audit.calls) == calls


def test_the_gauge_follows_creates_deletes_and_counts_all_owners() -> None:
    env = Env()
    first = env.create(name="a")
    env.create(name="b")
    assert env.metrics.presets.values == {("true",): 18, ("false",): 2}
    env.user = USER_B
    env.create(name="c")
    env.user = USER_A
    env.c.delete(f"/indicator-presets/{first['id']}")
    assert env.metrics.presets.values == {("true",): 18, ("false",): 2}


def test_a_store_outage_while_the_gauge_is_read_never_fails_the_committed_write() -> None:
    env = Env()

    async def down() -> dict[bool, int]:
        raise OperationalError("SELECT 1", {}, ConnectionError("gone"))

    env.repo.count_live_by_builtin = down  # type: ignore[method-assign]  # store gone after write
    with capture_logs() as logs:
        r = env.c.post("/indicator-presets", json=body())
    assert r.status_code == 201 and len(env.mine()) == 1
    assert {"event": "indicator_presets_gauge_stale", "error": "OperationalError",
            "log_level": "warning"} in logs  # fmt: skip


def test_denials_are_logged_with_actor_target_and_reason() -> None:
    env = Env()
    theirs = env.repo.seed(USER_B)
    with capture_logs() as logs:
        env.c.delete(f"/indicator-presets/{theirs}")
        env.c.delete(f"/indicator-presets/{EMA9}")
    denials = [e for e in logs if e["event"] == "indicator_preset_denied"]
    assert [(e["user_id"], e["preset_id"], e["reason"]) for e in denials] == [
        (str(USER_A), theirs, "not_owner"), (str(USER_A), EMA9, "builtin_immutable"),
    ]  # fmt: skip
    assert env.metrics.denied.values == {("not_owner",): 1, ("builtin_immutable",): 1}


async def test_without_metrics_a_denial_and_a_write_record_nothing_and_still_answer() -> None:
    repo, audit = FakePresetRepo(), Audit()
    service = IndicatorPresetService(lambda: repo, default_catalogue(), audit, new_id=new_ids())
    made = await service.create(principal(), PresetInput.model_validate(body()))
    assert made.owner_user_id == str(USER_A)
    theirs = repo.seed(USER_B)
    with pytest.raises(PresetNotFoundError):
        await service.soft_delete(principal(), theirs)
    assert [c["reason"] for c in audit.denied()] == ["not_owner:workspaces:write:self"]


async def test_a_gauge_read_that_fails_for_a_bug_is_not_swallowed() -> None:
    repo, metrics = FakePresetRepo(), Metrics()
    service = IndicatorPresetService(lambda: repo, default_catalogue(), Audit(),
                                     new_id=new_ids(), metrics=metrics)  # fmt: skip

    async def broken() -> dict[bool, int]:
        raise RuntimeError("bug")

    repo.count_live_by_builtin = broken  # type: ignore[method-assign]  # a bug, not an outage
    with pytest.raises(RuntimeError):
        await service.create(principal(), PresetInput.model_validate(body()))


# --- the gauge at startup ---------------------------------------------------------------------

_PRIMER_TASK = "indicator-presets-gauge"


def _primer_tasks() -> list[asyncio.Task[Any]]:
    return [t for t in asyncio.all_tasks() if t.get_name() == _PRIMER_TASK]


def _hanging(entered: asyncio.Event) -> Any:
    """A `count_live_by_builtin` whose store never answers."""

    async def hangs() -> dict[bool, int]:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("never answered")

    return hangs


async def test_the_gauge_is_read_at_startup_before_any_write() -> None:
    """Both series are exported from the start, not only after the first create, delete or
    import; a user class with no live preset reads 0."""
    repo, metrics = FakePresetRepo(), Metrics()
    await IndicatorPresetsGaugePrimer(lambda: repo, metrics).prime()
    assert metrics.presets.values == {("true",): 18, ("false",): 0}
    assert [name for name, _ in repo.calls] == ["count_live_by_builtin"]


async def test_start_reads_the_gauge_once_in_a_task_of_its_own() -> None:
    repo, metrics = FakePresetRepo(), Metrics()
    primer = IndicatorPresetsGaugePrimer(lambda: repo, metrics)
    primer.start()
    primer.start()  # the lifespan starts it once; a second start reads nothing more
    (task,) = _primer_tasks()
    await task
    assert metrics.presets.values == {("true",): 18, ("false",): 0}
    assert [name for name, _ in repo.calls] == ["count_live_by_builtin"]
    await primer.stop()  # a finished read: nothing left to cancel


async def test_stop_cancels_a_read_still_in_flight() -> None:
    repo, metrics, entered = FakePresetRepo(), Metrics(), asyncio.Event()
    repo.count_live_by_builtin = _hanging(entered)  # type: ignore[method-assign]  # store hangs
    primer = IndicatorPresetsGaugePrimer(lambda: repo, metrics)
    primer.start()
    await entered.wait()
    await primer.stop()
    await primer.stop()  # a second stop has nothing to cancel
    assert _primer_tasks() == [] and metrics.presets.values == {}


async def test_a_store_that_does_not_answer_in_time_leaves_the_gauge_unset() -> None:
    repo, metrics, entered = FakePresetRepo(), Metrics(), asyncio.Event()
    repo.count_live_by_builtin = _hanging(entered)  # type: ignore[method-assign]  # store hangs
    with capture_logs() as logs:
        await IndicatorPresetsGaugePrimer(lambda: repo, metrics, timeout_s=0).prime()
    assert entered.is_set() and metrics.presets.values == {}
    assert {"event": "indicator_presets_gauge_stale", "error": "TimeoutError",
            "log_level": "warning"} in logs  # fmt: skip


async def test_a_store_outage_at_startup_leaves_the_gauge_unset_and_is_logged() -> None:
    repo, metrics = FakePresetRepo(), Metrics()
    repo.fail = OperationalError("SELECT 1", {}, ConnectionError("gone"))
    with capture_logs() as logs:
        await IndicatorPresetsGaugePrimer(lambda: repo, metrics).prime()
    assert metrics.presets.values == {}
    assert {"event": "indicator_presets_gauge_stale", "error": "OperationalError",
            "log_level": "warning"} in logs  # fmt: skip


async def test_a_bug_at_startup_is_logged_and_never_leaves_the_task_failed() -> None:
    repo, metrics = FakePresetRepo(), Metrics()
    repo.fail = RuntimeError("bug")
    with capture_logs() as logs:
        await IndicatorPresetsGaugePrimer(lambda: repo, metrics).prime()
    assert metrics.presets.values == {}
    assert [(e["event"], e["log_level"]) for e in logs] == [
        ("indicator_presets_gauge_failed", "error")
    ]


async def test_without_a_store_the_primer_reads_and_sets_nothing() -> None:
    metrics = Metrics()
    await IndicatorPresetsGaugePrimer(lambda: None, metrics).prime()
    assert metrics.presets.values == {}
