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
    assert lock + "verification, a restore and a delete one at a time" in delete  # R2-06


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
        "An expired or already used token is `410 gone` whether or not the request carries a "
        "bearer token, and `404 not_found` when it carries another user's; an unknown token is "
        "`404 not_found`",
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
    coordinator): the first return of a spent link is recorded, by its link id, once per link."""
    response = _operation("downloadBackup")["responses"]["410"]
    gone = text(response["description"])
    # R3-F2: the expiry and use causes lead the description, and `used` is its only example.
    assert gone.startswith("The link expired or was already used, or it ended with the events")
    assert "Every cause gets the same body, the `used` example; only the record's `reason`" in gone
    assert list(response["content"]["application/problem+json"]["examples"]) == ["used"]
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
