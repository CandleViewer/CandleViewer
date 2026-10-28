"""The scanner-presets service (E08-T09 PR 2a, #4708): list, create, replace and delete for the
`/scanner/presets*` routes.

A write runs in 22's order (`updateScannerPreset`): the body's validation (422, which reads no
stored preset); the store (503 when none is wired); for a replace or a delete, the target: the
caller's preset, else another user's (404, audited `rbac.denied`, 24 section 15.5) or nothing
(404: identical on the wire); the conflicts the store reports before writing (409
`limit_reached`, `name_taken`); then the write-ahead audit records (C-2.9: a refused record
fails the request and nothing is stored) and the write.

Records name the preset (`object_kind` `scanner_preset`, `object_id` its id) and carry `version`
and `content_sha256`, the digest of the canonical preset (`name`, `filter`, `sort`,
`is_default`), never the name or the filter. The digest is not called `*hash*`: the audit
redaction drops such fields. A write that sets the default and so clears the caller's previous
one also records that preset's `.updated`, its `version` raised, and tells the store which
default, at which `version`, it expects to clear, so the records and that row cannot disagree.
A write the store refuses after its records were written (409, a 404 or 422 it lost to a
concurrent request, or a constraint with no domain error, which stays a 500)
gets one record more per record, of the same action, with outcome `failure` and the same state,
so the chain shows the write did not land; a failure record that cannot be written is logged and
the refusal still answered.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import structlog

from candleviewer.api.scanner_presets_models import ScannerPresetInput, preset_fields
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.writer import AuditUnavailable, AuditWriterStopped
from candleviewer.storage.errors import StorageConstraintViolated
from candleviewer.storage.repositories.scanner_presets import (
    MAX_PRESETS,
    ExpectedDefault,
    ScannerPresetConflictError,
    ScannerPresetFields,
    ScannerPresetNotFoundError,
    ScannerPresetRepository,
    ScannerPresetRow,
    ScannerPresetShapeError,
)

_KIND = "scanner_preset"
#: The store's refusals that can follow the write-ahead records (each gets a failure record).
_REFUSED_AFTER_RECORD = (
    ScannerPresetConflictError, ScannerPresetNotFoundError, ScannerPresetShapeError,
    StorageConstraintViolated,
)  # fmt: skip


class ScannerPresetStoreUnavailableError(Exception):
    """No preset store is wired (the fake backend): 503 `store_unavailable`."""


class AuditEmitter(Protocol):
    """The audit writer as the router and the service use it (`_LazyAuditEmitter` in the app)."""

    async def emit(self, action: str, **kwargs: Any) -> None: ...


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger("candleviewer.api.scanner_presets")


def content_sha256(fields: ScannerPresetFields) -> str:
    """SHA-256 of the canonical preset (`name`, `filter`, `sort`, `is_default`, keys sorted)."""
    canonical = json.dumps(
        {"filter": fields.filter, "is_default": fields.is_default, "name": fields.name,
         "sort": fields.sort},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )  # fmt: skip
    return hashlib.sha256(canonical.encode()).hexdigest()


def _state(version: int, fields: ScannerPresetFields) -> dict[str, Any]:
    return {"version": version, "content_sha256": content_sha256(fields)}


@dataclass(frozen=True, slots=True)
class _Record:
    """One write-ahead record, kept so a refused write can be recorded `failure` alike."""

    action: str
    preset_id: str
    state: dict[str, Any]


class ScannerPresetService:
    """One per router; `repo_provider` is read on every call (the store may come and go)."""

    def __init__(
        self,
        repo_provider: Callable[[], ScannerPresetRepository | None],
        audit: AuditEmitter,
        *,
        new_id: Callable[[], UUID],
    ) -> None:
        self._repo_provider, self._emitter, self._new_id = repo_provider, audit, new_id

    def _store(self) -> ScannerPresetRepository:
        repo = self._repo_provider()
        if repo is None:
            raise ScannerPresetStoreUnavailableError
        return repo

    async def _audit(self, action: str, p: AuditPrincipal, preset_id: str, **kw: Any) -> None:
        await self._emitter.emit(
            action, actor_label=str(p.user_id), actor_user_id=p.user_id, actor_ip=p.ip,
            session_id=p.session_id, request_id=p.request_id, object_kind=_KIND,
            object_id=preset_id, **kw,
        )  # fmt: skip

    async def _ahead(self, p: AuditPrincipal, records: list[_Record]) -> None:
        for r in records:
            await self._audit(r.action, p, r.preset_id, **r.state)

    async def _failed(self, p: AuditPrincipal, records: list[_Record]) -> None:
        """The failure twin of each record written ahead of a write that did not land."""
        for r in records:
            try:
                await self._audit(r.action, p, r.preset_id, outcome=AuditOutcome.FAILURE,
                                  severity=Severity.WARNING, **r.state)  # fmt: skip
            except (AuditUnavailable, AuditWriterStopped) as exc:
                _log().error("scanner_preset_failure_unrecorded", action=r.action,
                             preset_id=r.preset_id, error=type(exc).__name__)  # fmt: skip

    async def _refuse_target(
        self, repo: ScannerPresetRepository, p: AuditPrincipal, preset_id: str
    ) -> ScannerPresetNotFoundError:
        """The refusal for an id that is not the caller's preset: another user's is logged and
        audited `rbac.denied` first; either way the answer is a missing preset's."""
        if await repo.is_foreign(str(p.user_id), preset_id):
            _log().warning("scanner_preset_denied", user_id=str(p.user_id), preset_id=preset_id,
                           reason="not_owner")  # fmt: skip
            await self._audit(
                "rbac.denied", p, preset_id, outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING, reason="not_owner:workspaces:write:self",
            )  # fmt: skip
        return ScannerPresetNotFoundError(preset_id)

    async def _cleared_record(
        self, repo: ScannerPresetRepository, owner: str, preset_id: str, fields: ScannerPresetFields
    ) -> tuple[ExpectedDefault | None, list[_Record]]:
        """The default this write clears (its id and version, for the store to expect) and its
        record."""
        if not fields.is_default:
            return None, []
        current = await repo.get_default(owner)
        if current is None or current.id == preset_id:
            return None, []
        before = current.fields()
        after = ScannerPresetFields(before.name, before.filter, before.sort, False)
        state = {"before_state": _state(current.version, before),
                 "after_state": _state(current.version + 1, after)}  # fmt: skip
        expected = ExpectedDefault(current.id, current.version)
        return expected, [_Record("scanner_preset.updated", current.id, state)]

    async def list_own(self, owner: str) -> list[ScannerPresetRow]:
        """The caller's presets only (never another user's, whatever the role)."""
        return await self._store().list_own(owner)

    async def create(self, p: AuditPrincipal, body: ScannerPresetInput) -> ScannerPresetRow:
        fields = preset_fields(body)
        repo, owner = self._store(), str(p.user_id)
        held, taken = await repo.occupancy(owner, fields.name)
        if held >= MAX_PRESETS:
            raise ScannerPresetConflictError("limit_reached")
        if taken:
            raise ScannerPresetConflictError("name_taken")
        preset_id = str(self._new_id())
        expected, cleared = await self._cleared_record(repo, owner, preset_id, fields)
        records = [_Record("scanner_preset.created", preset_id,
                           {"after_state": _state(1, fields)}), *cleared]  # fmt: skip
        await self._ahead(p, records)
        try:
            write = await repo.create(owner, preset_id, fields, expected_default=expected)
        except _REFUSED_AFTER_RECORD:
            await self._failed(p, records)
            raise
        _log().info("scanner_preset_created", user_id=owner, preset_id=preset_id)
        return write.row

    async def replace(
        self, p: AuditPrincipal, preset_id: str, body: ScannerPresetInput
    ) -> ScannerPresetRow:
        fields = preset_fields(body)
        repo, owner = self._store(), str(p.user_id)
        current = await repo.get_own(owner, preset_id)
        if current is None:
            raise await self._refuse_target(repo, p, preset_id)
        _, taken = await repo.occupancy(owner, fields.name, exclude_id=preset_id)
        if taken:
            raise ScannerPresetConflictError("name_taken")
        expected, cleared = await self._cleared_record(repo, owner, preset_id, fields)
        state = {"before_state": _state(current.version, current.fields()),
                 "after_state": _state(current.version + 1, fields)}  # fmt: skip
        records = [_Record("scanner_preset.updated", preset_id, state), *cleared]
        await self._ahead(p, records)
        try:
            write = await repo.update(owner, preset_id, fields, expected_default=expected)
        except _REFUSED_AFTER_RECORD:
            await self._failed(p, records)
            raise
        _log().info("scanner_preset_updated", user_id=owner, preset_id=preset_id)
        return write.row

    async def delete(self, p: AuditPrincipal, preset_id: str) -> None:
        repo, owner = self._store(), str(p.user_id)
        current = await repo.get_own(owner, preset_id)
        if current is None:
            raise await self._refuse_target(repo, p, preset_id)
        state = {"before_state": _state(current.version, current.fields())}
        records = [_Record("scanner_preset.deleted", preset_id, state)]
        await self._ahead(p, records)
        if not await repo.delete(owner, preset_id):  # deleted by a concurrent request meanwhile
            await self._failed(p, records)
            raise ScannerPresetNotFoundError(preset_id)
        _log().info("scanner_preset_deleted", user_id=owner, preset_id=preset_id)


__all__ = [
    "AuditEmitter", "ScannerPresetService", "ScannerPresetStoreUnavailableError",
    "content_sha256",
]  # fmt: skip
