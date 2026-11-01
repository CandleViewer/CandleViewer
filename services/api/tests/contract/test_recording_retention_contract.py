"""#492 S4 provider contract: `listRetentionPolicies` and `setRetentionPolicies` through the real
`create_app()` (the RBAC pack's world, so the real step-up guard). Bodies validate against the
schema 22 declares for their status; every status the routes answer is declared; the examples
validate. The PUT always needs the `recorder` step-up (`403 step_up_required`) and is Owner-only
(`admin:write`, the E16 threat model's R-T1 class): with the step-up the Owner replaces the set,
while a Manager or a Viewer gets 403 and an `rbac.denied` record and the set is unchanged.

E16-S03 (#485) BQ-2: the 200 body carries `job_id`, the id of the `retention_sweep` job that
`apply_now=true` started (a uuid), and null without it. BQ-4: `Job.result` is documented per
served kind as the server sends it: each runner's own result builder is run and its output must
validate against the schema 22 names for that kind, with exactly the keys that schema lists."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, get_args

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.recorder_admin import IMPORT_JOB_KIND, JOB_KIND, Job
from candleviewer.api.recorder_purge import PURGE_JOB_KIND
from candleviewer.domain.archive import ArchiveChecksumFailed, ArchiveError, ArchiveParseFailed
from candleviewer.recorder.importer import MAX_SKIPPED_REPORTED, ImportSummary
from candleviewer.recorder.retention import Protected, PruneItem, Reason, RunReport, day_key
from candleviewer.storage.cold.compaction_run import CompactionSummary, compact_all
from candleviewer.storage.cold.compactor import Compactor
from candleviewer.storage.cold.layout import DatasetRegistry
from tests.contract._admin_support import example_cases, text, validate_example
from tests.contract.rbac.rbac_harness import World, bearer, build_world
from tests.unit.api import test_recorder_purge as purge_tests
from tests.unit.api.test_recording_retention import (
    _OWNER,
    _Env,
    _item,
    _settle,
    _Store,
    _Sweeper,
    _whole,
)
from tests.unit.recorder._retention_fakes import T, day

_SPEC: Any = load_openapi_spec()
_PATH = "/recording/retention-policies"
_ANSWERED = {"get": ("200", "401", "403", "503"),
             "put": ("200", "401", "403", "409", "422", "503")}  # fmt: skip
_CASES = [(m, s) for m in _ANSWERED for s in _ANSWERED[m]]
_EXAMPLES = example_cases([(_PATH, "get"), (_PATH, "put")])
_PROBLEMS = {"401": "Unauthorized", "403": "Forbidden", "409": "Conflict"}
_PROBLEMS |= {"422": "UnprocessableEntity", "503": "ServiceUnavailable"}
_OK = "/paths/~1recording~1retention-policies/{}/responses/200/content/application~1json/schema"


@pytest.fixture(scope="module")
def world() -> Iterator[World]:
    mp = pytest.MonkeyPatch()
    try:
        w = build_world(mp)
        mp.setattr(w.app.state, "retention_policies", _Store([]), raising=False)
        yield w
    finally:
        mp.undo()


@pytest.fixture
def store(world: World) -> _Store:
    world.step_up.elevated = True
    world.audit.records.clear()
    fresh = _Store([])
    fresh.seed("trades", 30)
    world.app.state.retention_policies = fresh
    return fresh


def _put(world: World, actor: str, items: Any, **params: Any) -> Any:
    return world.client.put(
        _PATH, json={"items": _whole(items)}, params=params, headers=bearer(actor)
    )


@pytest.mark.parametrize(("case", "pointer", "value"), _EXAMPLES, ids=[c[0] for c in _EXAMPLES])
def test_every_documented_example_validates(case: str, pointer: str, value: Any) -> None:
    validate_example(pointer, value)


@pytest.mark.parametrize(("method", "status"), _CASES)
def test_the_operation_declares_every_status_the_route_answers(method: str, status: str) -> None:
    assert status in _SPEC["paths"][_PATH][method]["responses"]


def test_a_put_without_the_recorder_step_up_is_refused_before_the_handler(
    world: World, store: _Store
) -> None:
    world.step_up.elevated = False
    resp = _put(world, "owner", [_item(days=60)])
    assert (resp.status_code, resp.json()["code"]) == (403, "step_up_required")
    assert store.replaced == 0


def test_with_the_step_up_the_owner_replaces_the_set(world: World, store: _Store) -> None:
    resp = _put(world, "owner", [_item(days=60)])
    assert resp.status_code == 200 and store.replaced == 1
    validate_example(_OK.format("put"), resp.json())
    listed = world.client.get(_PATH, headers=bearer("viewer"))
    assert listed.status_code == 200 and listed.json() == {"items": resp.json()["items"]}
    validate_example(_OK.format("get"), listed.json())
    assert [r["action"] for r in world.audit.records] == ["retention.change"]


@pytest.mark.parametrize("actor", ["manager_with_grant", "manager_without_grant"])
def test_a_manager_with_the_step_up_gets_403_an_rbac_denied_record_and_the_set_unchanged(
    world: World, store: _Store, actor: str
) -> None:
    """AC-03 of the E16 threat model (R-T1), through the real app and its step-up guard."""
    kept = list(store.rows)
    resp = _put(world, actor, [_item(days=60)])
    assert (resp.status_code, resp.json()["code"]) == (403, "forbidden")
    validate_example(
        "/components/responses/Forbidden/content/application~1problem+json/schema", resp.json()
    )
    assert [r["action"] for r in world.audit.records] == ["rbac.denied"]
    assert store.replaced == 0 and store.rows == kept


def test_a_viewer_with_the_step_up_gets_403_and_an_rbac_denied_record(
    world: World, store: _Store
) -> None:
    resp = _put(world, "viewer", [_item(days=60)])
    assert (resp.status_code, resp.json()["code"]) == (403, "forbidden")
    assert [r["action"] for r in world.audit.records] == ["rbac.denied"]
    assert store.replaced == 0


def test_each_problem_body_is_its_declared_response(world: World, store: _Store) -> None:
    answers = {
        "401": world.client.get(_PATH, headers=bearer("unauthenticated")),
        "403": _put(world, "viewer", [_item()]),
        "409": _put(world, "owner", [_item()], apply_now="true"),  # the scheduler is off
        "422": _put(world, "owner", [_item(action="pin")]),
    }
    world.app.state.retention_policies = None  # no store: 503
    answers["503"] = world.client.get(_PATH, headers=bearer("owner"))
    for status, resp in answers.items():
        assert (str(resp.status_code), resp.headers["content-type"]) == (
            status, "application/problem+json")  # fmt: skip
        response = f"/components/responses/{_PROBLEMS[status]}/content/application~1problem+json"
        validate_example(f"{response}/schema", resp.json())
    assert store.replaced == 0


# -- E16-S03 BQ-2: the PUT answers the id of the sweep `apply_now=true` started -------------------

_PUT_200 = _SPEC["paths"][_PATH]["put"]["responses"]["200"]["content"]["application/json"]


def test_the_put_declares_job_id_a_required_nullable_uuid_beside_items() -> None:
    body = _PUT_200["schema"]
    assert body["required"] == ["items", "job_id"]
    job_id = body["properties"]["job_id"]
    assert (job_id["type"], job_id["format"]) == (["string", "null"], "uuid")
    said = text(job_id["description"])
    assert "`apply_now=true`" in said and said.endswith(".") and ". " not in said  # one sentence


def test_the_put_documents_both_of_its_answers_as_examples() -> None:
    examples = _PUT_200["examples"]
    assert examples["scheduled"]["value"]["job_id"] is None
    started = examples["appliedNow"]["value"]["job_id"]
    assert str(uuid.UUID(started)) == started


def test_a_put_without_apply_now_answers_a_null_job_id_through_the_real_app(
    world: World, store: _Store
) -> None:
    resp = _put(world, "owner", [_item(days=60)])
    assert resp.status_code == 200 and resp.json()["job_id"] is None
    validate_example(_OK.format("put"), resp.json())


async def test_apply_now_answers_the_uuid_of_the_sweep_it_started_in_the_declared_body() -> None:
    env = _Env(*_OWNER)
    resp = await env.put([_item(days=60)], apply_now="true")
    assert resp.status_code == 200
    validate_example(_OK.format("put"), resp.json())
    (job,) = await _settle(env.jobs)
    assert resp.json()["job_id"] == job.id and str(uuid.UUID(job.id)) == job.id


# -- E16-S03 BQ-4: `Job.result` per served kind, as the server sends it --------------------------

_JOB = "/components/schemas/Job"
_SCHEMAS = _SPEC["components"]["schemas"]
_RESULTS = ["RetentionSweepResult", "CompactionRunResult", "RetentionPurgeResult"]
_RESULTS += ["ArchiveImportResult"]
_T = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def _view(kind: str, result: dict[str, object]) -> dict[str, Any]:
    """A succeeded job as `getJob` serves it (`Job.view()`) over a runner's `result`."""
    job = Job(id=str(uuid.uuid4()), kind=kind, status="succeeded", progress_pct=100.0,
              started_at=_T, finished_at=_T, result=result)  # fmt: skip
    return job.view()


def _same_keys(value: Any, schema: Any) -> None:
    """Every object in `value` has exactly the keys its schema lists. The contract is open to
    readers, so only this catches a key the runner adds that 22 never names, or 22 names that the
    runner never sends."""
    if "$ref" in schema:
        schema = _SCHEMAS[schema["$ref"].rsplit("/", 1)[1]]
    if isinstance(value, dict):
        assert set(value) == set(schema["properties"]), schema.get("description", "")[:60]
        for key, member in value.items():
            _same_keys(member, schema["properties"][key])
    elif isinstance(value, list):
        for member in value:
            _same_keys(member, schema["items"])


def _documented(view: dict[str, Any], kind: str, schema: str) -> None:
    """The job validates as a `Job` of `kind`, its `result` as `schema`, with exactly its keys."""
    assert (view["kind"], view["status"]) == (kind, "succeeded")
    validate_example(_JOB, view)
    validate_example(f"/components/schemas/{schema}", view["result"])
    _same_keys(view["result"], {"$ref": f"#/components/schemas/{schema}"})


def test_job_result_names_each_served_shape_and_stays_open() -> None:
    result = _SCHEMAS["Job"]["properties"]["result"]
    refs = [m["$ref"].rsplit("/", 1)[1] for m in result["anyOf"] if "$ref" in m]
    assert refs == ["AuditExportResult", *_RESULTS]
    assert {"type": "object", "additionalProperties": True} in result["anyOf"]
    assert {"type": "null"} in result["anyOf"]
    described = text(result["description"])
    for phrase in ("`kind: retention_sweep`", "`RetentionSweepResult`", "`CompactionRunResult`",
                   "`kind: retention_purge`", "`RetentionPurgeResult`", "`kind: archive_import`",
                   "`ArchiveImportResult`"):  # fmt: skip
        assert phrase in described, phrase


class _Busy(_Sweeper):
    """A pass that removed a partition, kept one at delete time and failed on one."""

    async def run_nightly(self) -> RunReport:
        item = PruneItem("cold", "trades", ("BTCUSDT",), "trades/symbol=BTCUSDT/dt=2026-09-01",
                         0, 1, 40, 2_048)  # fmt: skip
        return RunReport(dry_run=False, deleted=[item], skipped=[Protected(item, "leased")],
                         failed=[(item, "OSError")], next_run_us=1)  # fmt: skip


async def test_an_apply_now_sweep_reports_a_retention_sweep_result() -> None:
    env = _Env(*_OWNER)
    env.sweeper = _Busy()
    assert (await env.put([_item()], apply_now="true")).status_code == 200
    (job,) = await _settle(env.jobs)
    assert job.result == {"deleted": 1, "freed_bytes": 2048, "skipped": 1, "failed": 1,
                          "skipped_locked": False}  # fmt: skip
    _documented(job.view(), JOB_KIND, "RetentionSweepResult")


async def test_a_sweep_that_found_the_volume_locked_reports_zero_counts_and_the_flag() -> None:
    env = _Env(*_OWNER)
    env.sweeper.locked = True
    assert (await env.put([_item()], apply_now="true")).status_code == 200
    (job,) = await _settle(env.jobs)
    assert job.result == {"deleted": 0, "freed_bytes": 0, "skipped": 0, "failed": 0,
                          "skipped_locked": True}  # fmt: skip
    _documented(job.view(), JOB_KIND, "RetentionSweepResult")


async def test_a_compaction_reports_the_retention_sweep_kind_and_a_compaction_run_result(
    tmp_path: Path,
) -> None:
    empty = (await compact_all(DatasetRegistry(tmp_path), Compactor())).as_result()
    assert empty == {"compacted": 0, "skipped": 0, "deferred": [], "failed": []}
    busy = CompactionSummary(
        compacted=3, skipped=1, deferred=["trades/symbol=BTCUSDT/dt=2026-10-16"],
        failed=["trades/symbol=ETHUSDT/dt=2026-10-15"],
    ).as_result()  # fmt: skip
    for result in (empty, busy):
        _documented(_view(JOB_KIND, result), JOB_KIND, "CompactionRunResult")
    said = text(_SPEC["paths"]["/admin/recorder/compact"]["post"]["description"])
    assert JOB_KIND == "retention_sweep" and "`kind: retention_sweep`" in said
    assert "`CompactionRunResult`" in said


async def test_a_purge_reports_a_retention_purge_result_listing_what_it_kept() -> None:
    env = purge_tests._Env()
    env.w.add_hot(T, 3, {"BTCUSDT": 4})  # alone when planned, shared before it is deleted
    env.w.add_hot(T, 4, {"BTCUSDT": 4, "ETHUSDT": 2})  # shared when planned
    env.backend.gate.clear()
    started = await env.post(purge_tests.BODY)
    assert started.status_code == 202
    env.w.hot[T][day(3)]["ETHUSDT"] = 2
    env.backend.gate.set()
    view = await env.wait(started.json()["job_id"])
    kept = [{"partition": day_key(day(n)), "reason": "shared_partition"} for n in (3, 4)]
    result = view["result"]
    assert (result["deleted"], result["skipped"], result["protected"], result["failed"]) == (
        2, kept[:1], kept[1:], 0)  # fmt: skip
    assert result["freed_bytes"] > 0
    _documented(view, PURGE_JOB_KIND, "RetentionPurgeResult")


def test_an_import_reports_an_archive_import_result() -> None:
    first = int(datetime(2026, 6, 20, tzinfo=UTC).timestamp()) * 1_000_000
    summary = ImportSummary(
        "BTCUSDT", date(2026, 6, 1), date(2026, 6, 30), files_total=30, files_processed=27,
        files_already_imported=1, rows_written=648, rows_discarded_overlap=264,
        rows_discarded_duplicate=2, bytes_downloaded=1_048_576, prior_rows_written=24,
        overlap=[(first, first + 11 * 86_400_000_000)],
        skipped=[("BTCUSDT2026-06-07.csv.gz", ArchiveChecksumFailed.code),
                 ("BTCUSDT2026-06-09.csv.gz", ArchiveParseFailed.code)],
    )  # fmt: skip
    result = summary.as_result()
    assert result["streams"] == ["trades"] and result["source"] == "archive"
    _documented(_view(IMPORT_JOB_KIND, result), IMPORT_JOB_KIND, "ArchiveImportResult")


def test_the_documented_reasons_are_the_ones_the_code_names() -> None:
    kept = _SCHEMAS["RetentionHold"]["properties"]["reason"]["enum"]
    assert set(kept) == set(get_args(Reason))
    skipped = _SCHEMAS["ArchiveImportResult"]["properties"]["files_skipped"]
    assert set(skipped["items"]["properties"]["reason"]["enum"]) == {
        c.code for c in ArchiveError.__subclasses__()
    }
    assert MAX_SKIPPED_REPORTED == 400 and "400" in text(skipped["description"])
