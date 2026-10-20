"""Unit (E42-T05 #966 BK-9): run evidence read from the append-only trail, never the row (Q7,
SR-E42-05, the threat model's §6 step 3), through the audit query service's raw view."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.backups import ports
from candleviewer.admin.backups.evidence import AuditRunEvidence, RecordPages, Verification
from candleviewer.audit.actions import validate_action
from candleviewer.audit.models import AuditEntry, AuditPage, AuditPageMeta, Severity
from candleviewer.audit.query import AuditQueryService

BACKUP = UUID(int=1)
SUM, AT = "ab" * 32, datetime(2026, 10, 18, 6, 0, tzinfo=UTC)


def entry(stage: str, outcome: str = "success", **after: Any) -> AuditEntry:
    detail = {"after": {"stage": stage, **after}}
    return AuditEntry.model_validate(
        {"id": 1, "ts": AT, "actor_user_id": None, "action": "backup.run", "outcome": outcome,
         "severity": Severity.INFO, "ip": None, "request_id": None, "entry_hash": "e" * 64,
         "prev_hash": "p" * 64, "detail": detail}
    )  # fmt: skip


class Pages:
    """`AuditQueryService.query` answering one page; it keeps every call."""

    def __init__(self, *items: AuditEntry, chain: bool = True, more: bool = False) -> None:
        ids = [e.model_copy(update={"id": 100 - n}) for n, e in enumerate(items)]  # newest first
        meta = AuditPageMeta(has_more=more, count=len(items))
        self.page = AuditPage(items=ids, chain_verified=chain, meta=meta)
        self.calls: list[dict[str, Any]] = []

    async def query(self, **call: Any) -> AuditPage:
        self.calls.append(call)
        return self.page


async def test_the_newest_finished_success_binds_the_digest_and_covers_to() -> None:
    pages = Pages(
        entry("finished", checksum_sha256=SUM, covers_to=AT.isoformat(), error=None),
        entry("finished", checksum_sha256="0" * 64),  # an older run's record: never the newest
        entry("requested", kind="pg_dump"),
    )
    evidence: ports.RunRecords = AuditRunEvidence(pages)
    assert await evidence.run_record(BACKUP) == ports.RunRecord(SUM, AT)
    assert await AuditRunEvidence(pages).bound_digest(BACKUP) == SUM  # `ports.RunEvidence`
    assert pages.calls[0] == {
        "restrict_to_actor": None, "actions": ["backup.run"], "subject_type": "backup",
        "subject_id": str(BACKUP), "outcome": "success", "limit": 16, "timeout_ms": 2000,
        "raw": True,
    }  # fmt: skip


@pytest.mark.parametrize("digest", [None, 123])
async def test_a_directory_or_repository_run_binds_no_digest(digest: object) -> None:
    pages = Pages(entry("finished", checksum_sha256=digest))
    record = await AuditRunEvidence(pages).run_record(BACKUP)
    assert record == ports.RunRecord(None, None)  # a record, binding none (Q8): not unbound


@pytest.mark.parametrize("covers_to", [None, "2026-10-18T06:00:00", "yesterday", 1760767200])
async def test_covers_to_is_only_an_aware_time(covers_to: object) -> None:
    pages = Pages(entry("finished", checksum_sha256=SUM, covers_to=covers_to))
    assert await AuditRunEvidence(pages).run_record(BACKUP) == ports.RunRecord(SUM, None)


@pytest.mark.parametrize(
    "pages",
    [
        Pages(),
        Pages(entry("requested")),
        Pages(entry("finished", checksum_sha256=SUM), chain=False),
        Pages(AuditEntry.model_validate(entry("finished").model_dump() | {"detail": {"after": None,
              "elided": ["after"]}})),
        Pages(*[entry("requested")] * 16, more=True),
    ],
    ids=["none", "no-finished", "chain-broken", "state-withheld", "page-full"],
)  # fmt: skip
async def test_no_trustworthy_record_is_no_evidence(pages: Pages) -> None:
    evidence = AuditRunEvidence(pages)
    assert (await evidence.run_record(BACKUP), await evidence.bound_digest(BACKUP)) == (None, None)


_PASS = entry("finished", verify_method="restore_smoke")
_FAIL = entry("finished", "failure", error="checksum_mismatch")
_UNREAD = entry("finished", "failure", error="store_unavailable")
_KEPT = entry("finished", "failure", error="store_unavailable", check="checksum_mismatch")
_KEPT_PASS = entry("finished", "failure", error="store_unavailable", check=None)  # never a pass
_KEPT_UNREAD = entry("finished", "failure", error="store_unavailable", check="store_unavailable")
_LOST = entry("requested")  # an attempt a restart cut short
_FOUND = ["checksum_mismatch", "checksum_unbound", "artefact_missing", "verify_failed"]


@pytest.mark.parametrize(
    ("items", "chain", "verdict"),
    [
        ([_UNREAD, _FAIL, _PASS], True, (False, 99, True)),
        ([_UNREAD, _LOST, _PASS], True, (True, 98, True)),
        ([_PASS, _FAIL], True, (True, 100, False)),
        ([_UNREAD, _KEPT_PASS, _KEPT_UNREAD, _LOST], True, (False, None, True)),
        ([_UNREAD, _KEPT, _PASS], True, (False, 99, True)),
        ([], True, (False, None, False)),
        ([_PASS], False, (False, None, False)),
    ],
    ids=["newest-conclusive-failed", "passed-then-inconclusive", "failed-then-passed",
         "only-inconclusive", "kept-check-refuses", "none", "chain-broken"],
)  # fmt: skip
async def test_a_restore_relies_on_the_newest_conclusive_verification(
    items: list[AuditEntry], chain: bool, verdict: tuple[bool, int | None, bool]
) -> None:
    """The orchestrator's 10:12Z ruling: an inconclusive end neither refuses nor clears; none
    conclusive refuses; the record relied on and a later inconclusive attempt are named."""
    pages = Pages(*items, chain=chain)
    with capture_logs() as logs:
        found = await AuditRunEvidence(pages).verification(BACKUP)
    assert found == Verification(*verdict)
    assert (pages.calls[0]["actions"], pages.calls[0]["outcome"]) == (["backup.verified"], None)
    unverified = {"event": "backups.evidence_unverified", "action": "backup.verified"}
    unverified |= {"backup_id": str(BACKUP), "log_level": "warning"}
    assert logs == ([] if chain else [unverified])


@pytest.mark.parametrize("error", ["store_unavailable", "audit_unavailable", "internal_error"])
@pytest.mark.parametrize("check", _FOUND)
async def test_a_failure_the_check_found_refuses_though_its_end_went_unrecorded(
    error: str, check: str
) -> None:
    """The coordinator's decision 6, fail-closed: the check's own conclusive result, kept on an
    end the row could not record, refuses a restore; the pass before it never clears it."""
    pages = Pages(entry("finished", "failure", error=error, check=check), _PASS)
    assert await AuditRunEvidence(pages).verification(BACKUP) == Verification(False, 100, False)


async def test_a_pass_that_names_a_conclusive_check_refuses() -> None:
    """Fail-closed: a record naming a failure the check found is never a pass."""
    pages = Pages(entry("finished", verify_method="restore_smoke", check="checksum_mismatch"))
    assert await AuditRunEvidence(pages).verification(BACKUP) == Verification(False, 100, False)


async def test_the_chains_order_decides_never_the_pages() -> None:
    """A clock stepped back puts an older pass (id 100) ahead of a newer failure (101)."""
    pages = Pages()
    items = [_PASS.model_copy(update={"id": 100}), _FAIL.model_copy(update={"id": 101})]
    pages.page = pages.page.model_copy(update={"items": items})
    assert await AuditRunEvidence(pages).verification(BACKUP) == Verification(False, 101, False)


@pytest.mark.parametrize("field", ["error", "check"])
@pytest.mark.parametrize(
    "junk", [["checksum_mismatch"], {"code": "verify_failed"}, 5, True, 1.5], ids=str
)
async def test_a_record_whose_code_is_not_text_is_never_a_pass(field: str, junk: Any) -> None:
    """Unknown, hashable or not: never a `TypeError`, never a pass; no older pass clears it."""
    pages = Pages(entry("finished", verify_method="restore_smoke", **{field: junk}), _PASS)
    assert await AuditRunEvidence(pages).verification(BACKUP) == Verification(False, 100, False)


@pytest.mark.parametrize("error", ["store_unavailable", "no_such_code"])
async def test_a_success_record_naming_an_error_is_never_a_pass(error: str) -> None:
    """A pass is `outcome: success` with no `error`: a success that names one is no pass."""
    pages = Pages(entry("finished", verify_method="restore_smoke", error=error))
    assert await AuditRunEvidence(pages).verification(BACKUP) == Verification(False, None, True)


def _pages(service: AuditQueryService) -> RecordPages:
    return service  # mypy: the evidence reads the audit query service itself


def test_the_conclusive_failures_are_the_contracts_four() -> None:
    assert ports.CONCLUSIVE == {"checksum_mismatch", "checksum_unbound", "artefact_missing",
                                "verify_failed"}  # fmt: skip


def test_backup_verified_is_a_registered_action() -> None:
    assert validate_action("backup.verified") == "backup.verified"  # SR-E42-11, read above
