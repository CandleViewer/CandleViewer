"""Contract (E42-T05, BK-0): what the backup routes answer before they ship (C-6.1).

Every backup route answers `501 not_implemented` until a backup engine is wired, and the routes
that spend a `backups` grant answer it before any challenge. This pins the statuses each operation
declares, the catalogue order and cursor binding, the run and verify records and their codes,
delete keeping its row and refusing the last verified backup of a kind, the challenge templates,
the token-addressed download that needs no bearer header, `Backup.deleted_at`, the backup job
results, `job_unknown` on `getJob`, the statuses `acknowledgeIncident` answers, and
`backup.deleted` in every audit vocabulary (the coordinator's rulings on #966: Q4, Q5, Q8, Q9,
Q10, Q11). Every change is additive (C-6.3). It reads the contract and the plan docs and drives
no route; `test_admin_ops_contract.py` validates every example of these operations.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from candleviewer.api._generated import openapi_models as api
from tests.contract._admin_support import ROOT, SPEC, text

_PATHS: dict[str, Any] = SPEC["paths"]
_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_REGISTRY: dict[str, int] = {entry["code"]: entry["status"] for entry in SPEC["x-error-codes"]}
#: The dangerous-route registry's sweep (`test_dangerous_route_registry.py`): an operation whose
#: text matches is read as a step-up candidate, so the ungated ones must never match it.
_STEP_UP_TEXT = re.compile(r"step[-_ ]up", re.IGNORECASE)
_FETCH_PATH = "/admin/backups/{backupId}/download/{token}"

#: The statuses each operation declares, exactly (C-6.3: declaring one is additive).
_DECLARED: dict[str, frozenset[int]] = {
    "listBackups": frozenset({200, 400, 401, 403, 422, 501, 503}),
    "getBackup": frozenset({200, 401, 403, 404, 501, 503}),
    "createBackup": frozenset({202, 401, 403, 409, 422, 429, 501, 503}),
    "verifyBackup": frozenset({202, 401, 403, 404, 409, 429, 501, 503}),
    "deleteBackup": frozenset({204, 401, 403, 404, 409, 501, 503}),
    "issueBackupDownload": frozenset({200, 401, 403, 404, 409, 429, 501, 503}),
    "downloadBackup": frozenset({200, 401, 403, 404, 409, 410, 429, 501, 503}),
    "getJob": frozenset({200, 401, 403, 404}),
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
        "ordered by `started_at` descending with `id` as the tie-break",
        "an opaque keyset cursor bound to the `kind` and `status` filters it was issued for",
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
    for rule in ("backup_not_usable", "verify_running"):
        assert f"`409 conflict` with rule `{rule}`" in verify, rule
    # Q6: one admission lock, so a verification never runs beside a restore.
    assert "while a restore is running, with rule `backup_or_restore_running`" in verify


def test_delete_keeps_the_row_and_names_its_conflicts() -> None:
    delete = _desc("deleteBackup")
    for clause in (
        "the catalogue row is kept, since the catalogue is kept forever",
        "the row gains `deleted_at` and records who deleted it, its `status` is unchanged",
        "a later verify, link or restore of it is `409 conflict` with rule `backup_not_usable`",
        "After the grant is spent, and in this order",
        "a second `backup.deleted` record with `outcome: failure` follows and the answer is "
        "`503 store_unavailable`, the row unchanged",
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


def test_backup_schema_gains_optional_deleted_at() -> None:
    backup = _SCHEMAS["Backup"]
    deleted_at = backup["properties"]["deleted_at"]
    assert (deleted_at["type"], deleted_at["format"]) == (["string", "null"], "date-time")
    assert "the catalogue row is kept" in text(deleted_at["description"])
    assert "required" not in backup  # every member optional, so adding one is additive (C-6.3)
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
    token is `404` and unspent."""
    fetch = _operation("downloadBackup")
    assert fetch["security"] == [{}, {"bearerAuth": []}]
    assert fetch["x-rbac"] == {"permissions": ["backups:read"], "scope": "none"}
    served = _desc("downloadBackup")
    for clause in (
        "the token is the credential, so the `GET` needs no `Authorization` header",
        "the fetch acts as the user the link was issued to",
        "issued for the backup in the path and, when the request does carry a bearer token, to "
        "that token's user",
        "any other token, and a malformed one, is `404 not_found` (never `422`) and nothing is "
        "spent",
        "the user it was issued to must still hold `backups:read`, else `403 forbidden`",
        "an unknown token or another user's is `404 not_found`, so a token cannot be probed",
    ):
        assert clause in served, clause
    assert "`downloadBackup` needs no `Authorization` header" in _desc("issueBackupDownload")


def test_download_reads_a_single_regular_file_inside_the_backup_root() -> None:
    served = _desc("downloadBackup")
    for clause in (
        "A matching token is spent before anything else is checked, so a refused fetch spends it "
        "too",
        "only once that path resolves, without following a symbolic link, to a regular file "
        "inside the configured backup root",
        "is no longer `ok`, `verified` or `restored` since the link was issued, the answer is "
        "`409 conflict` with rule `backup_not_usable`",
        "`Content-Disposition` names the file `cv-backup-<kind>-<backupId>.age`, never the stored "
        "path",
        "counts towards the hourly limit of the user it was issued to, refused ones included",
        "is written before the first byte; when it cannot be written the answer is "
        "`503 audit_unavailable` and the link stays spent",
    ):
        assert clause in served, clause
    # Q8: only a single-file artefact can be linked.
    assert "or whose artefact is not a single file is not usable" in _desc("issueBackupDownload")


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
