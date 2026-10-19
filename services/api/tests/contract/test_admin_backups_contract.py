"""Contract (E42-T05, BK-0): what the backup routes answer before they ship (C-6.1).

Every backup route answers `501 not_implemented` until a backup engine is wired, and the routes
that spend a `backups` grant answer it before any challenge. This pins the statuses each operation
declares, the catalogue order and cursor binding, the run and verify records and their codes,
delete keeping its row and refusing the last verified backup of a kind, the challenge templates,
the token-addressed download that needs no bearer header and ends with its session family's
events, its limits, the records that name each link and tell a bearer-less fetch apart,
`Backup.deleted_at`, the backup job results, `job_unknown` on `getJob`, the statuses
`acknowledgeIncident` answers, and `backup.deleted` in every audit vocabulary (the coordinator's
rulings on #966: Q4, Q5, Q8, Q9, Q10, Q11, and on the BK-0 reviews). Every change is additive
(C-6.3). It reads the contract and the plan docs and drives no route;
`test_admin_ops_contract.py` validates every example of these operations.

It also pins what an admission answers when it cannot take the backups admission lock in time, and
what that costs a delete or a restore (SR-BK7A-03 and SEC-LW-01, from the BK-7a and lock-wait
reviews), what a verification does to its row when it passes or cannot read the artefact (BK-3 m4,
BK-6b D-1), and how long a spent or expired download link is remembered (SR-3456-01). It pins the
run's refusal of a plan that is not encrypted under a key alias, what it records (stage `refused`),
answers (`backup_engine_invalid`, or `audit_unavailable` when its record cannot be written) and
costs (a start against the hourly limit), the idempotency exception for every refusal to start,
the job's audit marker and the client's rule to take a run's outcome from its row (BK-8 rulings,
SEC-EI-01 to SEC-EI-05), and what a download-link issue answers and records when it is refused
(SR-BK10A-03, SR-BK10B-04). The contract-C review (wf_2a96af04-e90) added the reason of every
refusal after a link's spend, the link store's bounds, the ceiling on a link's memory, the issued
record that cannot be written, the order a run is refused in, and what `Backup.error` holds.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from candleviewer.api._generated import openapi_models as api
from candleviewer.ws._generated.error_codes import ERROR_META, WS_ERROR_CODES, ErrorCode
from tests.contract._admin_support import ROOT, SPEC, text, validate_example

_PATHS: dict[str, Any] = SPEC["paths"]
_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_REGISTRY: dict[str, int] = {entry["code"]: entry["status"] for entry in SPEC["x-error-codes"]}
#: The dangerous-route registry's sweep (`test_dangerous_route_registry.py`): an operation whose
#: text matches is read as a step-up candidate, so the ungated ones must never match it.
_STEP_UP_TEXT = re.compile(r"step[-_ ]up", re.IGNORECASE)
#: The sweep's pattern plus the inflections a sentence about a spent grant uses ("steps up again"),
#: which `_STEP_UP_TEXT` misses: the text of an operation that spends no grant never matches it.
_STEP_UP_ANY = re.compile(r"step(?:s|ped|ping)?[-_ ]up", re.IGNORECASE)
_FETCH_PATH = "/admin/backups/{backupId}/download/{token}"

#: The statuses each operation declares, exactly (C-6.3: declaring one is additive). A malformed
#: `backupId` is the shared `422`, except on the token-addressed fetch, where it is `404`.
_DECLARED: dict[str, frozenset[int]] = {
    "listBackups": frozenset({200, 400, 401, 403, 422, 501, 503}),
    "getBackup": frozenset({200, 401, 403, 404, 422, 501, 503}),
    "createBackup": frozenset({202, 401, 403, 409, 422, 429, 501, 503}),
    "verifyBackup": frozenset({202, 401, 403, 404, 409, 422, 429, 501, 503}),
    "deleteBackup": frozenset({204, 401, 403, 404, 409, 422, 501, 503}),
    "issueBackupDownload": frozenset({200, 401, 403, 404, 409, 422, 429, 501, 503}),
    "downloadBackup": frozenset({200, 401, 403, 404, 409, 410, 429, 501, 503}),
    "getJob": frozenset({200, 401, 403, 404, 501, 503}),
    "acknowledgeIncident": frozenset({200, 401, 403, 404, 409, 422, 501, 503}),
}
#: The shared response (`components.responses`) each failure status reuses ...
_SHARED = {
    401: "Unauthorized",
    403: "Forbidden",
    404: "NotFound",
    409: "Conflict",
    422: "UnprocessableEntity",
    429: "RateLimited",
    501: "NotImplemented",
    503: "ServiceUnavailable",
}
#: ... except these, declared in place: the list's `invalid_cursor`, the fetch's `410 gone`
#: (with its `no-store` headers) and the job poll's `job_unknown`.
_INLINE = frozenset({("listBackups", 400), ("downloadBackup", 410), ("getJob", 404)})
_READS = ("listBackups", "getBackup")
_ACTIONS = ("createBackup", "verifyBackup", "deleteBackup", "issueBackupDownload", "downloadBackup")


def _operation(operation_id: str) -> dict[str, Any]:
    (operation,) = [
        operation
        for item in _PATHS.values()
        for operation in item.values()
        if isinstance(operation, dict) and operation.get("operationId") == operation_id
    ]
    return operation


def _desc(operation_id: str) -> str:
    return text(_operation(operation_id).get("description", ""))


def _assert_declared(operation_id: str) -> None:
    responses: dict[str, Any] = _operation(operation_id)["responses"]
    assert {int(status) for status in responses} == _DECLARED[operation_id]
    for status, response in responses.items():
        if int(status) < 400:
            continue
        if (operation_id, int(status)) in _INLINE:
            (media,) = response["content"]
            assert media == "application/problem+json"
            schema = response["content"][media]["schema"]
            assert schema == {"$ref": "#/components/schemas/Problem"}
        else:
            assert response == {"$ref": f"#/components/responses/{_SHARED[int(status)]}"}


@pytest.mark.parametrize("operation_id", _READS)
def test_backup_reads_declare_the_statuses_they_answer(operation_id: str) -> None:
    _assert_declared(operation_id)


@pytest.mark.parametrize("operation_id", _ACTIONS)
def test_backup_actions_declare_the_statuses_they_answer(operation_id: str) -> None:
    _assert_declared(operation_id)


def test_backup_list_order_and_cursor_binding_are_normative() -> None:
    listed = _desc("listBackups")
    for clause in (
        "ordered by `started_at` descending with `id` descending as the tie-break",
        "an opaque keyset cursor bound to the `kind` and `status` filters it was issued for and "
        "valid for one hour",
        "`location` is the artefact's path on the backup volume and `error` a stable code",
        "the encryption key alias is never returned",
        "A backup whose artefact was deleted is listed with `deleted_at` set",
        'never an empty page that would read as "no backups"',
        "cannot be read within its budget is `503 store_unavailable`",
    ):
        assert clause in listed, clause
    bad = text(_operation("listBackups")["responses"]["400"]["description"])
    assert "`code: invalid_cursor` signals a malformed, foreign or expired `cursor`" in bad
    assert "(one issued for different `kind` or `status` filters)" in bad
    one = _desc("getBackup")
    assert "One catalogue row (E42-T05) as `listBackups` serves it" in one
    assert "a deleted artefact's row included (`deleted_at` set)" in one


@pytest.mark.parametrize(
    ("operation_id", "clause"),
    [
        ("listBackups", "the operation answers `501 not_implemented`, never an empty page"),
        ("getBackup", "`501 not_implemented` and `503 store_unavailable` as on `listBackups`"),
        ("createBackup", "answers `501 not_implemented`, writes no record and starts nothing"),
        ("verifyBackup", "answers `501 not_implemented` and schedules nothing"),
        ("deleteBackup", "answers `501 not_implemented` before any challenge"),
        ("issueBackupDownload", "operation answers `501 not_implemented` before any challenge"),
        ("downloadBackup", "store are wired the operation answers `501 not_implemented`"),
    ],
)
def test_backup_actions_answer_501_before_any_challenge(operation_id: str, clause: str) -> None:
    """Until the engine is wired nothing runs and, where a `backups` grant is spent, the `501`
    comes before the challenge, so no code is spent on a route that cannot act."""
    assert clause in _desc(operation_id)


def test_unknown_backup_and_the_link_limit_are_decided_before_any_challenge() -> None:
    assert "An unknown backup is `404` before any challenge" in _desc("deleteBackup")
    issue = _desc("issueBackupDownload")
    early = "an unknown backup (`404`) and the hourly limit (`429`) are decided before any"
    assert early + " challenge" in issue
    assert "and `backup_not_usable` after the grant is spent, as on `restoreBackup`" in issue


def test_run_and_verify_records_name_their_stages_and_bind_the_digest() -> None:
    create, verify = _desc("createBackup"), _desc("verifyBackup")
    for clause in (
        "`backup.run` is written with `after_state.stage: requested` before the `202`",
        "(when it cannot be written the answer is `503 audit_unavailable` and nothing starts)",
        "again with `stage: finished` when the run ends, carrying the outcome, `size_bytes` and "
        "`checksum_sha256`",
        "the catalogue row becomes `ok` only after that record is written",
        "`note` is kept in the `requested` record's `reason` and nowhere else",
        "the row records `triggered_by: manual` and the caller",
        "A user may start at most 4 runs in a rolling hour, else `429 rate_limited`",
    ):
        assert clause in create, clause
    for clause in (
        "`backup.verified` is written with `after_state.stage: requested` before the `202`",
        "(when it cannot be written the answer is `503 audit_unavailable` and nothing is "
        "scheduled)",
        "with `stage: finished`, the outcome and the `error` code when the job ends, before the "
        "row changes",
        "A user may start at most 12 verifications in a rolling hour, else `429 rate_limited`",
    ):
        assert clause in verify, clause


#: The run's own refusal for an engine plan that is not encrypted (BK-8 ruling, READY-30, #966).
_ENGINE_CODE = "backup_engine_invalid"


def test_a_run_planned_unencrypted_is_refused_503_backup_engine_invalid() -> None:
    """BK-8 ruling (READY-30, #966; C-6.1, C-2.9; SEC-EI-01): a plan that is not encrypted under a
    key alias, whether `encrypted: false` or no alias named, breaks "always encrypted", so the run
    is refused fail closed with a code of its own, not the retryable `store_unavailable`: the
    failure record (stage `refused`) is written first, nothing starts, and the refusal stands
    until the configuration is fixed. No alias value is named (class S). `createBackup` already
    declares `503`. The sentence comes before the hourly-limit one and the `501` one (CR-6a), and
    it defines the plan it speaks of instead of restating the word (code F4c)."""
    _assert_declared("createBackup")
    refused = "A run whose backup engine plan (what the engine reports for the run: the artefact's "
    refused += "location, whether it is encrypted and under which key alias) is not encrypted "
    refused += "under a key alias (`encrypted: false`, or no alias named) breaks the rule that "
    refused += "backups are always encrypted, so it is refused fail closed: its failure record "
    refused += "(`backup.run`, `stage: refused`, `outcome: failure`) is written first, then the "
    refused += f"answer is `503 {_ENGINE_CODE}`, nothing starts, and runs stay refused this way "
    refused += "until the engine configuration is fixed."
    create = _desc("createBackup")
    assert refused in create
    limit = "A user may start at most 4 runs in a rolling hour"
    unwired = "Until a backup engine is wired the operation answers `501 not_implemented`"
    assert create.index(refused) < create.index(limit) < create.index(unwired)


def test_an_unwritable_refusal_record_is_a_503_audit_unavailable_and_nothing_starts() -> None:
    """SEC-EI-02 / CR-1 (C-2.9, as SEC-LW-01 on `deleteBackup`): the refusal's failure record is
    written first, so when it cannot be written the answer is `503 audit_unavailable`, in place of
    `503 backup_engine_invalid`, and nothing starts. A run has no grant, so nothing is spent."""
    create = _desc("createBackup")
    unwritten = "When that failure record cannot be written, the answer is `503 audit_unavailable` "
    unwritten += "and nothing starts."
    assert unwritten in create
    # "that failure record" is the refusal's, which the sentence before it writes first.
    refused = "and runs stay refused this way until the engine configuration is fixed."
    assert create.index(refused) < create.index(unwritten)


def test_a_refusal_counts_as_a_start_and_the_limit_is_checked_before_the_plan() -> None:
    """SEC-EI-04 / CR-2b (BK-8b, `runs.py`: the limit is checked before the plan, and `record_start`
    follows the refusal's record): a run refused as `backup_engine_invalid` counts toward the hourly
    limit like a start, once its record is written, so past the limit the answer is
    `429 rate_limited`, not the engine's `503`, and a retry loop cannot flood the trail."""
    create = _desc("createBackup")
    counted = "A run refused as `backup_engine_invalid` counts as a start, once its record is "
    counted += "written, and the limit is checked before the plan, so past it the answer is "
    counted += "`429 rate_limited`, not `503 backup_engine_invalid`."
    assert counted in create
    # "the limit" is the one the sentence before it states.
    limit = "A user may start at most 4 runs in a rolling hour, else `429 rate_limited` with "
    assert create.index(limit + "`Retry-After`.") < create.index(counted)


def test_a_refused_run_writes_one_record_with_the_stage_refused() -> None:
    """CR-2c (BK-8b, `runs.py`: the refusal record's `after_state.stage` is `refused`): `refused`
    is a third `backup.run` stage, named where the contract names `requested` and `finished`; a
    refused run writes that one record instead of the other two. The sentence follows the refusal
    it names and precedes the unwritable-record one (code F4b)."""
    create = _desc("createBackup")
    refused = "A run refused as `backup_engine_invalid` writes one record, with `stage: refused`, "
    refused += "instead of the `requested` and `finished` ones."
    assert refused in create
    finished = "carrying the outcome, `size_bytes` and `checksum_sha256`"
    fixed = "and runs stay refused this way until the engine configuration is fixed."
    unwritten = "When that failure record cannot be written, the answer is `503 audit_unavailable`"
    assert create.index(finished) < create.index(fixed) < create.index(refused)
    assert create.index(refused) < create.index(unwritten)


def test_a_run_is_decided_in_the_plans_order() -> None:
    """Code F3 (BK-8b, `runs.py`, the plan's order; SEC-EI-04): the first refusal that applies
    answers, so a client and BK-8 can rely on the order: no engine (`501`), the hourly limit
    (`429`, checked again under the lock, still ahead of the `409`), the admission lock (`503` on a
    lock wait), a running backup or restore (`409`), the engine's plan (`503 backup_engine_invalid`
    whatever else it breaks, or `store_unavailable` when it cannot plan), then the `requested`
    record and the start. Nothing is recorded before the plan."""
    create = _desc("createBackup")
    order = "Order (E42-T05): the first of these that applies answers, and no record is written "
    order += "before the plan: no backup engine wired, `501 not_implemented`; the hourly limit, "
    order += "`429 rate_limited` (checked before the lock and again once it is held, so it still "
    order += "comes ahead of the `409`); the backups admission lock, `503 store_unavailable`; a "
    order += "running backup or restore, `409 conflict`; the engine's plan, "
    order += "`503 backup_engine_invalid` when it is not encrypted under a key alias, whatever "
    order += "else it breaks, or `503 store_unavailable` when the engine cannot plan the run; then "
    order += "the `requested` record and the start."
    assert order in create
    steps = (
        "`501 not_implemented`",
        "`429 rate_limited`",
        "the backups admission lock, `503 store_unavailable`",
        "`409 conflict`",
        "`503 backup_engine_invalid`",
        "`503 store_unavailable` when the engine cannot plan",
        "the `requested` record and the start",
    )
    places = [order.index(step) for step in steps]
    assert places == sorted(places)
    # It follows the two sentences it orders (the `409` and the lock wait) and precedes the records.
    assert "before any record, and starts nothing. Order (E42-T05)" in create
    assert create.index(order) < create.index("Records (E42-T05)")


def test_backup_engine_invalid_is_registered_rest_only_and_not_retryable() -> None:
    """The refusal holds until the configuration changes, so a retry cannot clear it: it is the
    one 503 of the run that is not retryable. Every enumeration of the registry carries it: the
    YAML, the Python enum and its meta, and both TypeScript tables (all generated from the YAML)."""
    (entry,) = [e for e in SPEC["x-error-codes"] if e["code"] == _ENGINE_CODE]
    assert (entry["status"], entry["retryable"]) == (503, False)
    assert entry.get("surface", ["rest"]) == ["rest"]
    meta = ERROR_META[ErrorCode(_ENGINE_CODE)]
    assert (meta.surfaces, meta.retryable, meta.title) == (("rest",), False, entry["title"])
    assert ErrorCode(_ENGINE_CODE) not in WS_ERROR_CODES
    tables = (ROOT / "packages/protocol/src/errorCodes.ts").read_text(encoding="utf-8")
    assert f'\n  "{_ENGINE_CODE}",\n' in tables  # `ERROR_CODES`
    meta_row = rf'^  {_ENGINE_CODE}: \{{ surfaces: \["rest"\], scope: null, retryable: false, '
    assert re.search(meta_row, tables, re.MULTILINE)  # `ERROR_META`


def test_a_succeeded_job_over_an_unwritten_finished_record_carries_the_audit_marker() -> None:
    """BK-8 ruling (READY-30, #966): the row is the truth. A `stage: finished` record that cannot
    be written leaves the row `failed` with `audit_unavailable`, never `ok`; the job is polled
    apart and may still read `succeeded`, but only with `audit: "unavailable"` in its free-form
    `result`. The `Job` schema is unchanged: it already admits any object for a `backup` job."""
    marker = "When the run's `stage: finished` record cannot be written, the row ends `failed` "
    marker += "with `error: audit_unavailable`, and the job may read `succeeded` only if its "
    marker += '`result` then also carries `audit: "unavailable"`: the row is the truth.'
    create = _desc("createBackup")
    poll = "poll `GET /admin/jobs/{Backup.id}`, which reports `kind: backup`."
    audited = "The run is audited as `backup.run` ahead of the response."
    assert create.index(poll) < create.index(marker) < create.index(audited)
    job = _SCHEMAS["Job"]
    assert {"type": "object", "additionalProperties": True} in job["properties"]["result"]["anyOf"]
    assert "audit" not in job["properties"]  # the marker is a member of the open `result` object
    succeeded = {
        "id": "18000000-0000-4000-8000-000000000001",
        "kind": "backup",
        "status": "succeeded",
        "result": {"backup_id": "18000000-0000-4000-8000-000000000001", "audit": "unavailable"},
    }
    validate_example("/components/schemas/Job", succeeded)
    assert api.Job.model_validate(succeeded).model_dump(mode="json", exclude_none=True) == succeeded


def test_a_client_takes_a_runs_outcome_from_its_row_and_the_job_names_the_marker() -> None:
    """SEC-EI-03 / CR-4: the job store sets `succeeded` before the run's end record is written, so
    a `succeeded` job is not proof of an `ok` row. A client takes a run's outcome from its row
    (`getBackup`), not from the job's `status`, and a `succeeded` job is final only once the row
    has left `running`. `Job.result` for a `backup` job and `getJob` name the
    `audit: "unavailable"` marker the job may carry when the finished record could not be
    written."""
    create = _desc("createBackup")
    outcome = "A client takes a run's outcome from its row (`getBackup`), not from the job's "
    outcome += "`status`: a `succeeded` job is final only once the row has left `running`."
    assert outcome in create
    # It builds on the marker sentence before it and comes ahead of the audit sentence.
    audited = "The run is audited as `backup.run` ahead of the response."
    assert create.index("the row is the truth.") < create.index(outcome) < create.index(audited)
    result = text(_SCHEMAS["Job"]["properties"]["result"]["description"])
    carried = 'For `kind: backup` it is `{backup_id}`, plus `audit: "unavailable"` when the '
    carried += "run's `stage: finished` record could not be written (`createBackup`), and for "
    assert carried in result
    named = "A `backup` job's `result` carries `audit: \"unavailable\"` when the run's "
    named += "`stage: finished` record could not be written (`createBackup`), and a run's outcome "
    named += "is its row's (`getBackup`), not the job's `status`."
    assert named in _desc("getJob")


def test_any_refusal_to_start_is_not_stored_under_the_idempotency_key() -> None:
    """SEC-EI-05 / CR-2d (from SEC-LW-02; the cache stores only a 2xx, `api/idempotency.py`): the
    exception to replay covers any answer but a `2xx` with which `createBackup` or `restoreBackup`
    refuses to start (a `409`, `422`, `429`, `501` or `503`), so a run refused for the lock wait,
    the hourly limit, an unwired engine, an unwritten record or an engine plan that is not
    encrypted is evaluated afresh under the same key once the cause clears, never answered from the
    cache. The engine's refusal is the registered `backup_engine_invalid`, not an unavailable
    engine."""
    exception = "Exception (E42-T05): any answer but a `2xx` with which `createBackup` or "
    exception += "`restoreBackup` refuses to start (a precondition, another backup or restore "
    exception += "still running, the hourly limit, a dependency that is unavailable, or a backup "
    exception += "engine that is not wired or is invalid) is not stored under the key, so the same "
    exception += "key and body are evaluated afresh once the cause clears."
    assert exception in text(SPEC["info"]["description"])


def test_verify_hashes_before_any_decrypt_and_names_its_codes() -> None:
    verify = _desc("verifyBackup")
    first = "compares its SHA-256 with `checksum_sha256` and with the digest the run's "
    assert first + "`backup.run` record bound, before anything is decrypted or restored" in verify
    for code in ("checksum_mismatch", "checksum_unbound", "artefact_missing", "verify_failed"):
        assert f"`{code}`" in verify, code
    # Q8: only a single-file artefact is digest-checked here; the engine checks the others.
    assert "when the backup's kind produces a single-file artefact" in verify
    assert "is checked by the backup engine's own verifier instead" in verify
    assert "without following a symbolic link, to a regular file inside the backup root" in verify
    assert "whose artefact was deleted or that is recorded with `encrypted: false` is" in verify
    for rule in ("backup_not_usable", "verify_running"):
        assert f"`409 conflict` with rule `{rule}`" in verify, rule
    # Q6: one admission lock, so a verification never runs beside a restore.
    assert "while a restore is running, with rule `backup_or_restore_running`" in verify


def test_an_unreadable_artefact_fails_the_verification_and_leaves_the_row_unchanged() -> None:
    """BK-6b security lens D-1 (C-6.1): an artefact that exists but cannot be read (BK-6's
    `ArtefactUnreadable`) is the job's `store_unavailable`. The job ends `failed` and its finished
    record is still written, but the row keeps its `status`, `error` and `verified_at`: an
    unreadable store leaves the verification inconclusive, which is no evidence against the backup.
    That is the one exception to recording a failure on the row, so the sentence that records it
    names the exception instead of contradicting it."""
    verify = _desc("verifyBackup")
    unreadable = "An artefact that exists but cannot be read (for instance an I/O error on the "
    unreadable += "backup volume) is `store_unavailable`: the job ends `failed` and "
    unreadable += "`backup.verified` (`stage: finished`, `outcome: failure`, "
    unreadable += "`error: store_unavailable`) is still written, but the row keeps its `status`, "
    unreadable += "`error` and `verified_at`, since an unreadable store makes the verification "
    unreadable += "inconclusive, not evidence against the backup."
    assert unreadable in verify
    recorded = "records the failed verification on the backup row (`status: failed`, `error`), "
    assert recorded + "except for `store_unavailable`, which leaves the row unchanged." in verify


def test_a_passing_verification_makes_any_status_verified_and_the_latest_outcome_wins() -> None:
    """BK-3 m4 (C-6.1): the contract gave only the failed re-verify. A passing one sets `status:
    verified` and `verified_at` and clears `error` (as BK-3's store does) whatever the status was
    before, a `restored` backup included, as a failing one sets `failed`: the latest outcome
    wins."""
    verify = _desc("verifyBackup")
    passing = "ends `succeeded` and sets `status: verified` and `verified_at` and clears `error`, "
    passing += "whatever the status was before (`restored` included: the latest outcome wins)"
    assert passing in verify
    failing = "A failed re-verify leaves `verified_at` at the last successful verification."
    assert failing in verify


def test_delete_keeps_the_row_and_names_its_conflicts() -> None:
    delete = _desc("deleteBackup")
    for clause in (
        "the catalogue row is kept, since the catalogue is kept forever",
        "the row gains `deleted_at` and records who deleted it (not exposed), its `status` is "
        "unchanged",
        "a later verify, link or restore of it is `409 conflict` with rule `backup_not_usable`",
        "After the grant is spent, and in this order",
        "one that is `running`, or that a running verification or restore uses, is "
        "`409 conflict` with rule `backup_in_use`",
        "a second `backup.deleted` record with `outcome: failure` follows, the row is unchanged, "
        "and the answer is `503 store_unavailable`, a code that here also covers the backup "
        "volume",
        # pinned since #2957
        "Audited as `backup.deleted` (actor, backup id, `before_state.status`) ahead of the `204`",
    ):
        assert clause in delete, clause
    rules = ["`backup_deleted`", "`backup_in_use`", "`last_usable_backup`"]
    assert [delete.index(r) for r in rules] == sorted(delete.index(r) for r in rules)
    # Q4: the last verified, undeleted backup of a kind is never deleted.
    last = "the last backup of its `kind` that is verified and not deleted (`status` `verified` or "
    assert last + "`restored` with `verified_at` set, no `deleted_at`)" in delete
    assert "with rule `last_usable_backup`, so no kind loses its last verified backup" in delete
    # SR-BK0-07: two senses of "usable"; an `ok` backup never verified protects no kind.
    narrower = "this rule counts only a verified backup as usable, a narrower sense than in "
    narrower += "`backup_not_usable`, which also admits an `ok` backup that was never verified"
    assert narrower in delete
    # SR-BK0-08: two concurrent deletes cannot both pass `last_usable_backup`.
    locked = "The three conflicts are evaluated and the row marked under the backups admission "
    assert locked + "lock, one delete at a time." in delete
    lock = "The backups admission lock is the one process-wide lock that admits a run, a "
    members = "verification, a restore, a delete and a download-link issue one at a time"
    assert lock + members in delete


def test_an_admission_that_cannot_take_the_lock_is_a_503_and_a_spent_grant_stays_spent() -> None:
    """SR-BK7A-03 (C-6.1): an admission waits a bounded time for the backups lock, then is refused
    `503 store_unavailable` with `Retry-After`. A run or a verification has written nothing and
    started nothing; a delete or a restore is refused after its grant is spent, so the grant is
    gone, its failure record is written ahead of the `503` and the operator steps up again. A run
    spends no grant, so its sentence never speaks of a step-up, which the registry sweep would read
    as a gated route. A download-link issue is refused the same way, and `deleteBackup` points to
    its sentence, so the lock's classes are not read as the four named here (code F4a, sec F6)."""
    create, delete = _desc("createBackup"), _desc("deleteBackup")
    run = "A run that cannot take the backups admission lock (`deleteBackup`) within its wait is "
    run += "`503 store_unavailable` with `Retry-After`, before any record, and starts nothing."
    assert run in create
    admission = "An admission that cannot take that lock within its wait is "
    admission += "`503 store_unavailable` with `Retry-After`. A run or a verification then writes "
    admission += "no record and starts nothing; a delete or a restore is refused after its grant "
    admission += "is spent, so the grant is gone, its failure record (`backup.deleted` or "
    admission += "`backup.restore`, `outcome: failure`) is written ahead of the `503`, and the "
    admission += "operator steps up again to retry."
    assert admission in delete
    # "that lock" is the one the sentence before it names.
    named = "The backups admission lock is the one process-wide lock"
    assert delete.index(named) < delete.index(admission)
    link = "A download-link issue is refused the same way after its grant is spent, with a record "
    link += "of its own (`issueBackupDownload`)."
    assert delete.index(admission) < delete.index(link)
    # A run's text, whole, never speaks of a step-up: the sweep's pattern (`_STEP_UP_TEXT`) plus the
    # inflection the delete sentence uses, so that sentence pasted into `createBackup` fails too.
    assert not _STEP_UP_ANY.search(create)


def test_a_verification_that_cannot_take_the_lock_is_a_503_and_schedules_nothing() -> None:
    """SR-BK7A-03 (C-6.1), mirrored from `createBackup`: a verification waits a bounded time for
    the backups lock too, then is refused `503 store_unavailable` with `Retry-After`, before any
    record, and schedules nothing. It spends no grant, so its text, whole, never speaks of a
    step-up in any inflection, which the registry sweep would read as a gated route."""
    verify = _desc("verifyBackup")
    sentence = "A verification that cannot take the backups admission lock (`deleteBackup`) within "
    sentence += "its wait is `503 store_unavailable` with `Retry-After`, before any record, and "
    sentence += "schedules nothing."
    assert sentence in verify
    assert not _STEP_UP_ANY.search(verify)


def test_an_unwritable_failure_record_after_the_spend_is_a_503_audit_unavailable() -> None:
    """SEC-LW-01 (C-2.9), from the lock-wait review: the failure record of a refusal after the
    grant is spent is written ahead of the answer, so when it cannot be written the answer is
    `503 audit_unavailable` and the grant, spent before the service ran, stays spent. One sentence
    covers the lock-wait `503` and the `409` refusals of a delete, which have the same gap; it says
    "a delete's" so it is not read as covering a restore, whose own text is #3084's (code F4a)."""
    delete = _desc("deleteBackup")
    unwritten = "When a delete's failure record cannot be written, for this `503` or for any "
    unwritten += "`409 conflict` after the grant is spent, the answer is `503 audit_unavailable` "
    unwritten += "and the grant stays spent."
    assert unwritten in delete
    # "a delete's failure record" is the one the sentences before it write ahead of the `503`.
    ahead = "is written ahead of the `503`, and the operator steps up again to retry."
    assert delete.index(ahead) < delete.index(unwritten)
    # "first of what?": the lock-wait text says ahead of the answer, never "first".
    lock_wait = _clause(delete, "An admission that cannot take that lock", "The challenge's")
    assert "is written first" not in lock_wait


def test_backup_schema_gains_optional_deleted_at() -> None:
    backup = _SCHEMAS["Backup"]
    deleted_at = backup["properties"]["deleted_at"]
    assert (deleted_at["type"], deleted_at["format"]) == (["string", "null"], "date-time")
    assert "the catalogue row is kept" in text(deleted_at["description"])
    assert "required" not in backup  # every member optional, so adding one is additive (C-6.3)


def test_backup_error_names_the_latest_conclusive_verification() -> None:
    """Sec F6 (2), code F5 (C-6.1): a verification that cannot read the artefact is inconclusive and
    leaves `error` as it was, and a passing one clears it, so `Backup.error` holds why the run or
    its latest conclusive verification failed (`verifyBackup`; BK-3 m4, BK-6b D-1)."""
    error = text(_SCHEMAS["Backup"]["properties"]["error"]["description"])
    lead = "Why the run or its latest conclusive verification failed, as a stable code such as "
    assert error.startswith(lead + "`checksum_mismatch`")
    cleared = "A passing verification clears it and an inconclusive one (`store_unavailable`) "
    cleared += "leaves it as it was (`verifyBackup`)."
    assert cleared in error
    assert not api.Backup.model_fields["deleted_at"].is_required()
    assert api.Backup.model_validate({"kind": "pg_dump"}).deleted_at is None


@pytest.mark.parametrize(
    ("operation_id", "clause"),
    [
        ("deleteBackup", "the `backup.deleted` record names the `challenge_id` of the grant"),
        ("issueBackupDownload", "every record names the `challenge_id` of the grant it spent"),
    ],
)
def test_gated_backup_records_name_the_spent_challenge(operation_id: str, clause: str) -> None:
    assert clause in _desc(operation_id)


@pytest.mark.parametrize(
    ("operation_id", "template"),
    [
        ("deleteBackup", "Delete the artefact of backup '<backupId>' (<kind>)"),
        ("issueBackupDownload", "Issue a 5-minute download link for backup '<backupId>' (<kind>)"),
    ],
)
def test_gated_backup_summaries_use_fixed_templates(operation_id: str, template: str) -> None:
    """The id is quoted, as `Problem.action_summary` quotes identifiers; the kind is an enum
    value, so it stays bare. Neither action asks for a typed confirmation."""
    assert f"`action_summary` template is `{template}` and `target` is null" in _desc(operation_id)


def test_issue_link_response_is_no_store() -> None:
    issued = _operation("issueBackupDownload")["responses"]["200"]
    no_store = {"schema": {"type": "string", "const": "no-store"}}
    assert issued["headers"] == {"Cache-Control": no_store}
    issue = _desc("issueBackupDownload")
    assert "The token carries 256 bits from a CSPRNG (43 base64url characters)" in issue
    assert "The `200` is sent with `Cache-Control: no-store`" in issue
    url = issued["content"]["application/json"]["examples"]["issued"]["value"]["download_url"]
    pattern = _PATHS[_FETCH_PATH]["parameters"][1]["schema"]["pattern"]
    assert re.fullmatch(pattern, url.rsplit("/", 1)[1])
    assert len(url.rsplit("/", 1)[1]) == 43


def test_download_is_token_addressed_and_needs_no_bearer() -> None:
    """Q9: a plain browser link saves the file, so the fetch needs no `Authorization` header.
    The bearer stays optional: a request that carries one keeps the rule that another user's
    token is `404` and unspent, and one that does not resolve gets the standard `401`."""
    fetch = _operation("downloadBackup")
    assert fetch["security"] == [{}, {"bearerAuth": []}]
    assert fetch["x-rbac"] == {"permissions": ["backups:read"], "scope": "none"}
    served = _desc("downloadBackup")
    for clause in (
        "the token is the credential, so the `GET` needs no `Authorization` header",
        "the fetch acts as the user the link was issued to",
        # SR-BK0-05, R2-05: the standard `401`, as on every other route.
        "A bearer token that is sent but does not resolve to a usable session gets the standard "
        "`401` (`unauthenticated`, or `session_idle_locked` for an idle-locked session, as "
        "everywhere), and nothing is spent",
        "issued for the backup in the path and, when the request does carry a bearer token, to "
        "that token's user",
        # R2-07: a malformed `backupId` is a miss too.
        "any other token, a malformed one and a malformed `backupId` are `404 not_found` (never "
        "`422`), and nothing is spent",
        "The user it was issued to must still hold `backups:read`, else `403 forbidden`",
        # SR-BK0-04: a spent token is `410` without a bearer; the 256 bits keep it unguessable.
        # Sec F3: it is `410` only while the link is remembered.
        "An expired or already used token is `410 gone` while the link is remembered, whether or "
        "not the request carries a bearer token, and `404 not_found` when it carries another "
        "user's; an unknown token is `404 not_found`",
        "Telling a used token from an unknown one discloses nothing, since a token cannot be "
        "guessed (256 bits, `issueBackupDownload`)",
    ):
        assert clause in served, clause
    for old in ("so a token cannot be probed", "issued to the calling user"):  # F1, N2
        assert old not in served, old
    issue = _desc("issueBackupDownload")
    assert "`downloadBackup` needs no `Authorization` header" in issue
    # SR-BK0-06: the token authenticates the fetch; "same user" holds only with a bearer.
    authenticates = "fetching it is a `GET` that the token itself authenticates, served as the "
    assert authenticates + "issuing user (`downloadBackup`)" in issue
    assert "never a bearer credential" not in issue
    assert "authenticated `GET` by the same user" not in issue


def test_download_reads_a_single_regular_file_inside_the_backup_root() -> None:
    served = _desc("downloadBackup")
    for clause in (
        # N3, R2-01: a lookup, then the one check before the spend; a dead token counts nowhere.
        "Matching is a lookup, not a spend",
        "A matching token that was spent or has expired is `410 gone` and counts against no limit",
        "then meets the hourly limit of the user it was issued to, the one check before the spend: "
        "over it, the answer is `429 rate_limited`, nothing is spent and nothing is recorded",
        "The token is then spent, so a refused fetch spends it too",
        "only once that path resolves, without following a symbolic link, to a regular file "
        "inside the configured backup root",
        "is no longer `ok`, `verified` or `restored` since the link was issued, the answer is "
        "`409 conflict` with rule `backup_not_usable`",
        "`Content-Disposition` names the file `cv-backup-<kind>-<backupId>.age`, never the stored "
        "path",
        "Every fetch that spends a token counts towards the hourly limit of the user it was issued "
        "to, refused ones included, and nothing else does",
        "is written before the first byte; when it cannot be written the answer is "
        "`503 audit_unavailable` and the link stays spent",
    ):
        assert clause in served, clause
    # Q8: only a single-file artefact can be linked.
    unusable = "a backup whose artefact was deleted, that is recorded with `encrypted: false`, or "
    unusable += "whose artefact is not a single file is not usable"
    assert unusable in _desc("issueBackupDownload")


def test_a_fetch_refused_after_the_spend_is_recorded_before_the_answer() -> None:
    """SR-BK0-01 (C-2.9): issue and delete record their refusals after the spend, so the fetch
    does too, and a record that cannot be written refuses the fetch without reviving the link."""
    refused = "A fetch refused after the token is spent is audited as `backup.downloaded` with "
    refused += "`stage: served`, `outcome: failure` and `reason` naming the refusal "
    refused += "(`user_disabled` if the user was disabled, else `session_ended` for those session "
    refused += "events; `forbidden`; `backup_not_usable`), before the answer; when that record "
    refused += "cannot be written the answer is `503 audit_unavailable` and the link stays spent."
    assert refused in _desc("downloadBackup")


def test_link_records_name_the_link_and_whether_a_bearer_came() -> None:
    """SR-BK0-02: the served record is the control left against a forwarded link (Q9), so it
    names the link the issued record names and tells a bearer-less fetch from the Owner's own."""
    issue = _desc("issueBackupDownload")
    failed = "A refusal after the grant is spent is audited as `backup.downloaded` with "
    assert failed + "`stage: issued` and `outcome: failure`" in issue
    issued = "the record of an issued link also names its `after_state.link_id`, an id minted "
    assert issued + "with the link that the fetch's records repeat, never the token or" in issue
    fetched = "Every record of a fetch with a matching token names the link by its "
    fetched += "`after_state.link_id`, never the token or its hash, and records in "
    fetched += "`after_state.bearer` whether the request carried the issuing user's bearer token "
    fetched += "(`matched`) or none (`absent`)."
    assert fetched in _desc("downloadBackup")


#: What ends the link (SR-BK0-03, N1): the events that end the no-grace grant that minted it
#: (logout, idle lock, read-only, at `authStepUp`), a revocation of its session family other than a
#: rotation, the family's expiry, and a disabled user. A rotation does not end it.
_LINK_ENDS = (
    "logged out",
    "idle-locked",
    "turned read-only",
    "revoked other than by a rotation",
    "expired",
    "its user was disabled",
)


def _clause(description: str, start: str, end: str) -> str:
    """The text between `start` and the first `end` after it; both markers must be there."""
    _, found, rest = description.partition(start)
    clause, ended, _ = rest.partition(end)
    assert found and ended, (start, end)
    return clause


def test_a_link_dies_with_its_session_or_its_user() -> None:
    """SR-BK0-03 (C-12.4): the link follows its session family across rotation and ends with the
    events that end the grant that minted it, not with the grant's 60-second expiry or its use.
    Each of the five session events and a disabled user make the fetch `410`; a rotation does
    not, and neither an unlock nor the end of the read-only window revives the link."""
    grant = "it also ends when the session turns read-only, when it idle-locks (#2301) and at "
    assert grant + "logout" in _desc("authStepUp")
    issue, fetch = _desc("issueBackupDownload"), _desc("downloadBackup")
    gone = text(_operation("downloadBackup")["responses"]["410"]["description"])
    assert "into its successors (its family): a rotation does not end the link" in issue
    # R3-F1: the binding itself (to the session and to that session's user), not only its effects.
    bound = "The link is bound to the session that issued it and to that session's user, and "
    assert bound + "follows that session across the rotations a refresh or a step-up makes" in issue
    assert "family across rotation (`issueBackupDownload`), so a rotation does not end it" in fetch
    ends = "with the events that end the grant that minted it, not with the grant's 60-second "
    ends += "expiry or its use: after the family's session "
    for description, end in (
        (issue, ", a fetch is `410 gone` (`downloadBackup`)"),
        (fetch, ", a fetch is `410 gone`, and neither an unlock"),
        (gone, " (`code: gone`)"),
    ):
        clause = _clause(description, ends, end)
        for event in _LINK_ENDS:
            assert event in clause, (end, event)
    assert "neither an unlock nor the end of the read-only window revives the link" in fetch
    # The coordinator's case: the session rotates, then its family is revoked.
    rotated = "A link whose session rotated and whose family was then revoked other than by a "
    rotated += "rotation is such a refusal: `410 gone`, the link spent, and "
    assert rotated + "`reason: session_ended`." in fetch
    assert "lives no longer than" not in issue + fetch + gone


def test_a_410_names_no_cause_and_a_replayed_link_is_recorded_once() -> None:
    """R2-02: whatever the cause, a `410` carries the `used` body. R2-03 (confirmed by the
    coordinator): the first return of a spent link is recorded, by its link id, once per link.
    Sec F3: the response, like the operation, says a `410` holds only while the link is
    remembered; after that its token is unknown."""
    response = _operation("downloadBackup")["responses"]["410"]
    gone = text(response["description"])
    # R3-F2: the expiry and use causes lead the description, and `used` is its only example.
    assert gone.startswith("The link expired or was already used, or it ended with the events")
    assert "Every cause gets the same body, the `used` example; only the record's `reason`" in gone
    assert list(response["content"]["application/problem+json"]["examples"]) == ["used"]
    remembered = "A link is `410 gone` only while it is remembered (`downloadBackup`); after that "
    remembered += "its token is unknown and the fetch is `404 not_found`."
    assert gone.endswith(remembered)
    served = _desc("downloadBackup")
    assert "Every `410` has the same body (the `used` example) whatever its cause" in served
    replay = "the first time a spent token is presented again, a `backup.downloaded` record with "
    replay += "`stage: served`, `outcome: failure` and `reason: link_reused`, naming its "
    replay += "`after_state.link_id`, precedes the `410`, and no later presentation or expired "
    assert replay + "link writes one" in served


def test_misses_spend_a_per_source_budget_that_never_limits_a_matching_token() -> None:
    """SR-BK0-09 (the coordinator's ruling): non-matching fetches spend a per-source budget
    shaped like the sign-in limiter's. A 256-bit token cannot be guessed, so the budget bounds
    log and audit volume and flags a scanner."""
    assert _operation("authLogin")["x-rate-limit"] == "10 requests / minute / source IP"
    limit = _operation("downloadBackup")["x-rate-limit"]
    assert limit == "10 non-matching fetches / minute / source IP"
    budget = "past 10 in a minute, a further miss is `429 rate_limited` with `Retry-After` instead "
    budget += "of `404`, counted in `cv_backup_download_source_rate_limited_total`, and the first "
    budget += "such refusal per address and minute is audited as `backup.downloaded` with "
    budget += "`stage: served`, `outcome: denied` and `reason: rate_limited`"
    served = _desc("downloadBackup")
    assert budget in served
    # SR-BK0-R3-01 (C-12.6, C-12.8): the path of a miss is the sender's, so none of it is recorded.
    assert "naming the address and no backup or link taken from the path" in served
    guess = "A token cannot be guessed, so this budget only bounds log and audit volume and "
    assert guess + "flags a scanner; it never limits a matching token" in served


def test_a_spent_link_first_presented_after_its_expiry_is_still_recorded_as_reused() -> None:
    """R3-F3: the link was spent first, so a spent token first presented again after its 5 minutes
    is a spent token presented again (`link_reused`); only a link that expired unspent writes
    none."""
    unspent = "The expired link that writes none is one that expired unspent: a token that was "
    unspent += "spent and is first presented again after its 5 minutes writes the record, since "
    assert unspent + "the link was spent first." in _desc("downloadBackup")


def test_a_link_is_remembered_for_at_most_an_hour_and_a_restart_forgets_every_link() -> None:
    """SR-3456-01, BK-10's open question 3 (C-6.1): the `410` answers and the `link_reused` record
    hold only while a link is remembered, at most 1 hour after its spend (or after its expiry, if it
    was never spent). After that, and after a restart of the one API process that holds every link,
    the token is unknown: `404 not_found` and no `link_reused` record, and a link lost to a restart
    shows as an `issued` record with no `served` record (BK-10 review, Q10). The sentence names the
    rules it bounds, so the `link_reused` sentence before it reads as holding within that window,
    and it keeps the rule whole (sec F3): a spent link presented again for the first time is
    recorded once, as above, so a holder of a spent token cannot write a record per request."""
    served = _desc("downloadBackup")
    horizon = "A spent or expired link is remembered for at most 1 hour after its spend, or after "
    horizon += "its expiry if it was never spent: while it is remembered, an expired or used token "
    horizon += "is `410 gone` and a spent one presented again for the first time is recorded once "
    horizon += "as `link_reused`, as above; after that its token is unknown, so a fetch is "
    horizon += "`404 not_found` and no `link_reused` record is written."
    assert horizon in served
    # It follows the rule it bounds, which stays whole (`test_a_410_names_no_cause_...` quotes it).
    assert served.index("`reason: link_reused`") < served.index(horizon)
    restart = "Links are held in the memory of the one API process (ADR-0004), as jobs are "
    restart += "(`getJob`), so a restart forgets every link, live or spent: one issued before it "
    restart += "is unknown, a fetch is `404 not_found`, and the link shows as an `issued` record "
    restart += "with no `served` record."
    assert restart in served


def test_a_link_issue_that_cannot_take_the_lock_is_a_503_after_the_spend() -> None:
    """BK-10 review (SR-BK10A-03, C-6.1): the backups admission lock admits a download-link issue
    too, so an issue that cannot take it within its wait is `503 store_unavailable` with
    `Retry-After`, after its grant is spent: the grant is gone, its failure record is written ahead
    of the `503` and the operator steps up again, in the wording `deleteBackup` settled (SEC-LW-01).
    When that record cannot be written, for any of these `503`s or for the `409`, the answer is
    `503 audit_unavailable` and the grant stays spent (sec F1: every `503`, not two of three)."""
    lock = "admits a run, a verification, a restore, a delete and a download-link issue one at "
    assert lock + "a time" in _desc("deleteBackup")
    issue = _desc("issueBackupDownload")
    wait = "An issue that cannot take the backups admission lock (`deleteBackup`) within its wait "
    wait += "is `503 store_unavailable` with `Retry-After`, after the grant is spent, so the grant "
    wait += "is gone, its failure record (`backup.downloaded`, `stage: issued`, "
    wait += "`outcome: failure`, `reason: store_unavailable`) is written ahead of the `503`, and "
    wait += "the operator steps up again to retry."
    assert wait in issue
    unwritten = "When that failure record cannot be written, for any of these `503`s or for the "
    unwritten += "`409`, the answer is `503 audit_unavailable` and the grant stays spent."
    assert unwritten in issue
    # "that failure record" is the one the lock-wait sentence writes ahead of the `503`.
    assert issue.index(wait) < issue.index(unwritten)


def test_an_issue_failure_record_names_its_reason_and_a_full_link_store_is_a_503() -> None:
    """BK-10 review (SR-BK10B-04, C-6.1): the failure record of a refused issue carries a `reason`:
    `backup_not_usable` for the `409`, `links_full` for a full link store, which answers
    `503 store_unavailable` with `Retry-After` like the lock wait, and `store_unavailable` for any
    other `503 store_unavailable` after the spend (the lock wait, or a catalogue or artefact store
    that fails or is too slow), as BK-10a's `_reason` gives it (sec F1, code F1). The store is full
    at 1024 live links and no other count (sec F2, code F2), stated once, with the link's memory
    (`downloadBackup`)."""
    issue = _desc("issueBackupDownload")
    reasons = "`outcome: failure` and a `reason`: `backup_not_usable` for the `409`, "
    reasons += "`links_full` for a full link store and `store_unavailable` for any other "
    reasons += "`503 store_unavailable` after the spend (the lock wait, or a catalogue or artefact "
    reasons += "store that fails or is too slow);"
    assert reasons in issue
    full = "An issue that finds the link store full (1024 links live; `downloadBackup` states the "
    full += "bounds) is refused the same way: `503 store_unavailable` with `Retry-After`, "
    full += "`reason: links_full`, a code that here also covers the in-process link store."
    assert full in issue


def test_a_store_that_fails_inside_the_lock_ends_an_issue_like_the_lock_wait() -> None:
    """Sec F1, code F1 (BK-10a, `downloads.py`: `_usable` makes a catalogue read or an artefact
    resolve that fails or is too slow an `OpsUnavailable`, and `_reason` gives every one the reason
    `store_unavailable`): an issue whose catalogue or artefact store fails inside the lock is
    `503 store_unavailable` after the spend, with the lock wait's failure record, so the reason
    does not belong to the lock wait alone."""
    issue = _desc("issueBackupDownload")
    inside = "A catalogue or artefact store that fails or is too slow once the lock is held ends "
    inside += "the same way, with the same record."
    assert inside in issue
    wait = "and the operator steps up again to retry."
    full = "An issue that finds the link store full"
    assert issue.index(wait) < issue.index(inside) < issue.index(full)


def test_a_full_link_store_is_1024_live_links_and_the_oldest_ended_are_forgotten_first() -> None:
    """Sec F2, code F2 (BK-10a, `links.py`: `LinksFull` only at 1024 live links; past 1024 ended
    links the oldest issued is dropped at the next issue, before its hour): the store is full when
    1024 links are live, no other count, and the ended links are kept as a history of the newest
    1024, so a token can be `404` with no record before its hour is up. The memory's hour is a
    ceiling (`test_a_link_is_remembered_for_at_most_an_hour_and_a_restart_forgets_every_link`)."""
    served = _desc("downloadBackup")
    bounds = "At most 1024 links are live at once, every user's together; an issue that finds 1024 "
    bounds += "live is refused (`issueBackupDownload`). The spent or expired ones are kept as "
    bounds += "well, the newest 1024 issued, and the oldest issued are forgotten first, so a token "
    bounds += "can be `404 not_found` with no record before its hour is up."
    assert bounds in served
    # It follows the restart sentence, and the issue's own text defers to it for the bounds.
    assert served.index("with no `served` record.") < served.index(bounds)
    assert "(1024 links live; `downloadBackup` states the bounds)" in _desc("issueBackupDownload")


def test_an_unwritable_issued_record_means_the_link_is_never_sent() -> None:
    """Sec F4 (c), C-2.9 (BK-10a, `downloads.py`: an `issued` record that is not written discards
    the link, and the route answers `503 audit_unavailable` with the grant spent): the record is
    written before the response, so when it cannot be written no link is sent, the answer is
    `503 audit_unavailable` and the grant stays spent. The failure record's own sentence is pinned
    by `test_a_link_issue_that_cannot_take_the_lock_is_a_503_after_the_spend`."""
    issue = _desc("issueBackupDownload")
    unwritten = "when that record cannot be written, the link is never sent: the answer is "
    unwritten += "`503 audit_unavailable` and the grant stays spent."
    assert unwritten in issue
    # "that record" is the issued record the sentence before it writes before the response.
    written = "Issuing is audited as `backup.downloaded` with `after_state.stage: issued` at "
    written += "severity `error` before the response; "
    assert written + unwritten in issue


def test_a_replay_or_source_record_that_cannot_be_written_is_a_503_and_not_used_up() -> None:
    """SR-BK0-R3-02, R3-F3 (C-2.9): both records are written before the answer, so one that cannot
    be written answers `503 audit_unavailable` in place of the `410` or the per-source `429`,
    and does not use up the one record per link, or per address and minute."""
    unwritten = "When the `link_reused` record or the per-source `rate_limited` record cannot be "
    unwritten += "written (write-ahead, C-2.9), the answer is `503 audit_unavailable` instead of "
    unwritten += "the `410` or of the per-source `429`, and a record that was not written does not "
    unwritten += "use up the one record per link (or per address and minute): the next "
    unwritten += "presentation of that link, or the next refused miss from that address in the "
    assert unwritten + "minute, writes it." in _desc("downloadBackup")


@pytest.mark.parametrize(
    "operation_id",
    [*_READS, "createBackup", "verifyBackup", "downloadBackup", "getJob", "acknowledgeIncident"],
)
def test_ungated_operations_never_mention_a_step_up(operation_id: str) -> None:
    """The registry sweep would read any of these as a step-up candidate (#3083, #3210): create
    and verify are allow-listed as needing none, and the reads, the fetch, the job poll and the
    acknowledge need none."""
    operation = _operation(operation_id)
    summary, description = operation.get("summary", ""), operation.get("description", "")
    assert not _STEP_UP_TEXT.search(f"{summary}\n{description}")


def test_a_vanished_job_is_404_with_rule_job_unknown_and_the_loss_is_counted() -> None:
    """Q10: the code stays `not_found` (additive, C-6.3); the rule names why the job is gone."""
    _assert_declared("getJob")
    poll = _desc("getJob")
    for clause in (
        "An unknown or evicted job id is `404 not_found`",
        "a restart loses every job, finished ones included",
        "Every `404` here carries rule `job_unknown` (E42-T05), whatever the cause",
        "so it never tells a lost or evicted job from one that was never issued",
        "a client whose job vanished reads the object it acted on instead",
        "Jobs a restart loses are counted by `cv_admin_jobs_lost_on_restart_total`",
    ):
        assert clause in poll, clause
    gone = _operation("getJob")["responses"]["404"]
    assert "rule `job_unknown`" in text(gone["description"])
    example = gone["content"]["application/problem+json"]["examples"]["jobUnknown"]["value"]
    problem = api.Problem.model_validate(example)
    assert (problem.status, problem.code) == (404, "not_found")
    assert [error.rule for error in problem.errors or []] == ["job_unknown"]


def test_job_poll_declares_its_unwired_501_and_its_guard_503() -> None:
    """The served route already answers `501` without a principal resolver, and behind the
    audited admin-area guard (Q15) a guard record that cannot be written is `503` (C-2.9)."""
    _assert_declared("getJob")
    clause = "The operation answers `501 not_implemented` while no principal resolver is wired, "
    clause += "and `503 audit_unavailable` when the admin-area guard (E42-T01) cannot write its "
    assert clause + "`admin.area_entered` record." in _desc("getJob")


def test_backup_job_results_name_the_backup() -> None:
    result = _SCHEMAS["Job"]["properties"]["result"]
    described = text(result["description"])
    assert "For `kind: backup` it is `{backup_id}`" in described
    assert "for `kind: backup_verify` it is `{backup_id, verify_method}`" in described
    methods = ("restore_smoke", "checksum", "pg_verifybackup", "duckdb_scan")
    assert all(f"`{method}`" in described for method in methods)
    ddl = (ROOT / "docs/plan/21-database-schema.md").read_text(encoding="utf-8")
    assert "verify_method IN ('restore_smoke','checksum','pg_verifybackup','duckdb_scan')" in ddl
    # Still open for every other kind, so documenting these shapes tightens nothing (C-6.3).
    assert {"type": "object", "additionalProperties": True} in result["anyOf"]


def test_acknowledge_declares_the_statuses_its_route_answers() -> None:
    """#966 slice E: the route also answers a malformed id (`422`), the unwired backend (`501`)
    and a write-ahead record that cannot be written (`503`)."""
    _assert_declared("acknowledgeIncident")
    sentence = (
        "An `incident.acknowledged` record that cannot be written leaves the incident `open` and "
        "answers `503 audit_unavailable`."
    )
    assert sentence in _desc("acknowledgeIncident")


def test_every_vocabulary_lists_backup_deleted() -> None:
    """Q11: the action is `backup.restore` (never `backup.restored`), and `backup.deleted` joins
    the other backup actions in every audit vocabulary the docs keep."""
    plan = ROOT / "docs/plan"
    security = (plan / "04-security-program.md").read_text(encoding="utf-8")
    (data,) = [line for line in security.splitlines() if line.startswith("| Data ")]
    schema = (plan / "21-database-schema.md").read_text(encoding="utf-8")
    must_audit = schema.split("Actions that MUST be audited", 1)[1].split("\n\n", 1)[0]
    internal = (plan / "24-internal-schemas.md").read_text(encoding="utf-8")
    closed = internal[internal.index("### 15.5 Audited action vocabulary") :]
    closed = closed[: closed.index("\n### ")]
    table = internal.split("| **Backup & restore**", 1)[1].split("\n| **", 1)[0]
    actions = ("run", "restore", "verified", "downloaded", "deleted")
    for vocabulary in (data, must_audit, closed, table):
        assert all(f"`backup.{action}`" in vocabulary for action in actions)
        assert "`backup.restored`" not in vocabulary
    assert "Audited as `backup.deleted`" in _desc("deleteBackup")


def test_internal_schemas_gate_the_three_backup_actions_by_handler() -> None:
    internal = text((ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8"))
    assert "exporting the audit log, restoring, downloading or deleting a backup" in internal
    because = "a no-grace grant binds the request its handler validated, which a path cannot name"
    assert because in internal


@pytest.mark.parametrize("operation_id", sorted(_DECLARED))
def test_every_status_and_code_the_text_names_is_registered(operation_id: str) -> None:
    """Every refusal named as `<status> <code>` uses a code registered with that status."""
    pairs = re.findall(r"`(\d{3}) ([a-z_]+)`", _desc(operation_id))
    assert all(_REGISTRY.get(code) == int(status) for status, code in pairs), pairs
