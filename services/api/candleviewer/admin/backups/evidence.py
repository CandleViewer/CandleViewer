"""Run evidence from the append-only trail (E42-T05 #966 BK-9; Q7, SR-E42-05, the threat model's §6
step 3): what a backup's `backup.run` and `backup.verified` records say, never its mutable row.
`AuditRunEvidence` reads them through the audit query service's raw view, newest first by audit id,
`EVIDENCE_PAGE` at a time, without the read slot kept for the Owner (SR-017) and within the query's
own timeout; the caller bounds the whole wait. A page whose chain does not check out is no
evidence (logged): no bound record for a verification, no passed one for a restore."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol
from uuid import UUID

import structlog

from candleviewer.admin.backups.limits import EVIDENCE_BUDGET_S
from candleviewer.admin.backups.ports import CONCLUSIVE, RunRecord
from candleviewer.audit.models import AuditOutcome, AuditPage

#: A run writes two successful records; a restore's verification is the newest conclusive one,
#: behind the inconclusive attempts that followed it.
EVIDENCE_PAGE: Final = 16
Entries = list[tuple[int, AuditOutcome, dict[str, Any]]]  # (audit id, outcome, `after_state`)


@dataclass(frozen=True, slots=True)
class Verification:
    """A restore's record-sourced check (BK-14, the orchestrator's 10:12Z ruling): the newest
    conclusive `backup.verified` outcome. It proceeds on a pass only; none conclusive is refused,
    unknown is not good. Its own record names `record_id` and `inconclusive_after`."""

    passed: bool
    record_id: int | None  # the audit entry relied on; `None` when no record concludes
    inconclusive_after: bool  # an attempt after it (any attempt, with none) did not conclude


class RecordPages(Protocol):
    """The one read this makes of `AuditQueryService.query`."""

    async def query(
        self,
        *,
        restrict_to_actor: str | None,
        actions: list[str] | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
        outcome: str | None = None,
        limit: int = ...,
        timeout_ms: int | None = None,
        raw: bool = False,
    ) -> AuditPage: ...


def _aware(value: object) -> datetime | None:
    """An ISO 8601 time with its offset, else `None`."""
    try:
        at = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
    return at if at is not None and at.utcoffset() is not None else None


class AuditRunEvidence:
    """`ports.RunRecords` and `ports.RunEvidence`, and a restore's `verification` (BK-14)."""

    def __init__(self, pages: RecordPages) -> None:
        self._pages = pages

    async def run_record(self, backup_id: UUID) -> RunRecord | None:
        """The newest successful `backup.run` record at `stage: finished`: the digest it bound and
        its `covers_to` (none until the run's record binds one, #3319)."""
        for _, _, state in await self._entries("backup.run", backup_id, AuditOutcome.SUCCESS):
            if state.get("stage") == "finished":
                digest, covers_to = state.get("checksum_sha256"), state.get("covers_to")
                return RunRecord(digest if isinstance(digest, str) else None, _aware(covers_to))
        return None

    async def bound_digest(self, backup_id: UUID) -> str | None:
        record = await self.run_record(backup_id)
        return None if record is None else record.digest

    async def verification(self, backup_id: UUID) -> Verification:
        """The newest `finished` record that concludes, a pass or a failure coded in `CONCLUSIVE`;
        an inconclusive end neither refuses nor clears, so the one before it decides. A failure
        the check found (`check`, kept when its outcome could not be written) refuses too, and
        any record naming one is no pass (the coordinator's decision 6, fail-closed). So does a
        record whose `error` or `check` is not text: unknown, never a pass. A pass is a success
        with no `error` at all."""
        entries = await self._entries("backup.verified", backup_id, None)
        for index, (record_id, outcome, state) in enumerate(entries):
            codes = state.get("error"), state.get("check")
            unknown = any(code is not None and not isinstance(code, str) for code in codes)
            found = unknown or any(code in CONCLUSIVE for code in codes)
            passed = outcome is AuditOutcome.SUCCESS and not found and state.get("error") is None
            if state.get("stage") == "finished" and (passed or found):
                return Verification(passed, record_id, index > 0)
        return Verification(False, None, bool(entries))

    async def _entries(self, action: str, backup_id: UUID, outcome: AuditOutcome | None) -> Entries:
        page = await self._pages.query(
            restrict_to_actor=None, actions=[action], subject_type="backup",
            subject_id=str(backup_id), outcome=None if outcome is None else outcome.value,
            limit=EVIDENCE_PAGE, timeout_ms=int(EVIDENCE_BUDGET_S * 1000), raw=True,
        )  # fmt: skip
        if not page.chain_verified:  # a row or a link does not check out: nothing is trusted
            log = structlog.get_logger(__name__)  # per call, never module-level (#2008)
            log.warning("backups.evidence_unverified", action=action, backup_id=str(backup_id))
            return []
        entries = [
            (entry.id, entry.outcome, after)
            for entry in page.items  # an elided state is no evidence
            if isinstance(after := entry.detail.get("after"), dict)
        ]
        # The chain's order, the audit id: the page's event time can step back.
        return sorted(entries, key=lambda entry: entry[0], reverse=True)
