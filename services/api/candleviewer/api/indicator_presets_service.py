"""The indicator-presets service (E13-T03, #427): list, create, replace and soft delete for the
`/indicator-presets` routes, and the `WorkspaceBundle.indicator_presets` export and import
(no operation takes a bundle yet: E15-S07 adds the HTTP surface and calls these two).

A write runs in 22's order (`updateIndicatorPreset`): the body's validation (422, which reads
no stored preset); the store (503 when none is wired); for a replace or a delete, the target:
the caller's live preset, else a live built-in (403 rule `builtin_immutable`) or another user's
live preset (404), both audited `rbac.denied` and counted, or nothing (404: the foreign case is
identical on the wire, IR-01); the replace's `immutable_field`; the conflicts the store reports
before writing (409 `limit_reached`, `name_taken`); then the write-ahead audit record (C-2.9: a
refused audit write fails the request and nothing is stored) and the write. The store decides
the cap and `ux_ip_name` again, under its owner lock and the unique index, so a 409 after the
audit record is a race the pre-check lost.

Audit records name the preset (`object_kind` `indicator_preset`, `object_id` its id) and carry
`indicator_code` and `content_sha256`, the digest of the canonical preset, never its
parameters (IR-19). The digest is not called `*hash*`: the audit redaction drops such fields.
A denial is counted in `indicator_preset_denied_total{reason}` before its record is written, as
`enforce()` counts (SR-125), and logged with the actor, the target and the reason;
`indicator_presets_total{builtin}` is read again after each create, delete and import.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import UUID

import structlog
from pydantic import ValidationError

from candleviewer.api.drawings_models import format_errors
from candleviewer.api.indicator_presets_models import (
    PresetInput,
    PresetInvalidError,
    jsonb_text_bytes,
    preset_fields,
)
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.observability.metrics import BoundedMetric
from candleviewer.orderflow.indicators.catalogue import IndicatorCatalogue
from candleviewer.orderflow.indicators.limits import (
    BUNDLE_IMPORT_MAX_BYTES,
    BUNDLE_IMPORT_PRESETS_MAX,
    PRESETS_PER_USER_MAX,
)
from candleviewer.storage.repositories.indicator_presets import (
    IndicatorPresetRepository,
    PresetConflictError,
    PresetFields,
    PresetNotFoundError,
    PresetRow,
)

DenialReason = Literal["not_owner", "builtin_immutable"]
#: At most this many field errors in one 422 (the drawings and workspaces bound).
_MAX_ERRORS = 20


class PresetStoreUnavailableError(Exception):
    """No preset store is wired (the fake backend): 503 `store_unavailable`."""


class PresetBuiltinImmutableError(Exception):
    """The target is a built-in: 403 `forbidden`, rule `builtin_immutable`."""


class PresetBundleTooLargeError(Exception):
    """A bundle's `indicator_presets` past SR-E13-07's import limits; nothing was imported."""

    def __init__(self, rule: Literal["too_many_presets", "too_large"], message: str) -> None:
        super().__init__(message)
        self.rule = rule


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class IndicatorPresetMetricsLike(Protocol):
    """The two E13-T03 series (`app.state.indicator_presets_metrics`)."""

    @property
    def presets(self) -> BoundedMetric: ...  # indicator_presets_total{builtin} (gauge)

    @property
    def denied(self) -> BoundedMetric: ...  # indicator_preset_denied_total{reason} (counter)


@dataclass(frozen=True, slots=True)
class IndicatorPresetMetrics:
    presets: BoundedMetric
    denied: BoundedMetric


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger("candleviewer.api.indicator_presets")


def content_sha256(fields: PresetFields) -> str:
    """SHA-256 of the canonical preset (every writable field, keys sorted), for the audit."""
    canonical = json.dumps(
        dataclasses.asdict(fields), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _state(fields: PresetFields) -> dict[str, str]:
    return {"indicator_code": fields.indicator_code, "content_sha256": content_sha256(fields)}


def bundle_item(row: PresetRow) -> dict[str, Any]:
    """`row` as a closed `IndicatorPresetInput`: no id, owner, built-in flag or timestamp."""
    return {
        "name": row.name, "indicator_code": row.indicator_code, "params": row.params,
        "style": row.style, "pane_target": row.pane_target, "is_favourite": row.is_favourite,
    }  # fmt: skip


class IndicatorPresetService:
    """One per router; `repo_provider` is read on every call (the store may come and go)."""

    def __init__(
        self,
        repo_provider: Callable[[], IndicatorPresetRepository | None],
        catalogue: IndicatorCatalogue,
        audit: _Emitter,
        *,
        new_id: Callable[[], UUID],
        metrics: IndicatorPresetMetricsLike | None = None,
    ) -> None:
        self._repo_provider, self._catalogue, self._emitter = repo_provider, catalogue, audit
        self._new_id, self._metrics = new_id, metrics

    def _store(self) -> IndicatorPresetRepository:
        repo = self._repo_provider()
        if repo is None:
            raise PresetStoreUnavailableError
        return repo

    async def _audit(
        self, action: str, p: AuditPrincipal, preset_id: str | None, **kw: Any
    ) -> None:
        await self._emitter.emit(
            action, actor_label=str(p.user_id), actor_user_id=p.user_id, actor_ip=p.ip,
            session_id=p.session_id, request_id=p.request_id, object_kind="indicator_preset",
            object_id=preset_id, **kw,
        )  # fmt: skip

    async def _refuse_target(
        self, repo: IndicatorPresetRepository, p: AuditPrincipal, preset_id: str
    ) -> PresetBuiltinImmutableError | PresetNotFoundError:
        """The refusal for an id that is not the caller's live preset; a built-in or another
        user's preset is counted, logged and audited `rbac.denied` first (SR-062)."""
        other = await repo.other_class(str(p.user_id), preset_id)
        if other is None:
            return PresetNotFoundError(preset_id)
        reason: DenialReason = "builtin_immutable" if other == "builtin" else "not_owner"
        if self._metrics is not None:
            self._metrics.denied.labels(reason).inc()
        _log().warning(
            "indicator_preset_denied", user_id=str(p.user_id), preset_id=preset_id, reason=reason
        )
        await self._audit(
            "rbac.denied", p, preset_id, outcome=AuditOutcome.DENIED, severity=Severity.WARNING,
            reason=f"{reason}:workspaces:write:self",
        )  # fmt: skip
        if other == "builtin":
            return PresetBuiltinImmutableError(preset_id)
        return PresetNotFoundError(preset_id)

    async def _refresh_gauge(self, repo: IndicatorPresetRepository) -> None:
        """After a committed write: a store outage here leaves the gauge stale until the next
        write, never fails the request; anything else is a bug and propagates."""
        if self._metrics is None:
            return
        try:
            counts = await repo.count_live_by_builtin()
        except Exception as exc:  # re-raised below unless the store is unreachable
            if not is_storage_outage(exc):
                raise
            _log().warning("indicator_presets_gauge_stale", error=type(exc).__name__)
            return
        for builtin in (True, False):
            self._metrics.presets.labels(str(builtin).lower()).set(counts.get(builtin, 0))

    async def list_visible(self, owner: str) -> list[PresetRow]:
        """The built-ins and the caller's live presets (never another user's, SR-051)."""
        return await self._store().list_visible(owner)

    async def create(self, p: AuditPrincipal, body: PresetInput) -> PresetRow:
        fields = preset_fields(body, self._catalogue)
        repo, owner = self._store(), str(p.user_id)
        seen = await repo.occupancy(owner, (fields.indicator_code, fields.name))
        if seen.live_presets >= PRESETS_PER_USER_MAX:
            raise PresetConflictError("limit_reached")
        if seen.name_taken:
            raise PresetConflictError("name_taken")
        preset_id = str(self._new_id())
        await self._audit("indicator_preset.created", p, preset_id, after_state=_state(fields))
        row = await repo.create(owner, preset_id, fields)
        _log().info("indicator_preset_created", user_id=owner, preset_id=preset_id,
                    indicator_code=fields.indicator_code)  # fmt: skip
        await self._refresh_gauge(repo)
        return row

    async def replace(self, p: AuditPrincipal, preset_id: str, body: PresetInput) -> PresetRow:
        fields = preset_fields(body, self._catalogue)
        repo, owner = self._store(), str(p.user_id)
        current = await repo.get_own(owner, preset_id)
        if current is None:
            raise await self._refuse_target(repo, p, preset_id)
        if fields.indicator_code != current.indicator_code:
            message = "indicator_code cannot be changed; save a new preset instead."
            raise PresetInvalidError([{"field": "indicator_code", "rule": "immutable_field",
                                       "message": message}])  # fmt: skip
        seen = await repo.occupancy(
            owner, (fields.indicator_code, fields.name), exclude_id=preset_id
        )
        if seen.name_taken:
            raise PresetConflictError("name_taken")
        before, after = _state(current.fields()), _state(fields)
        await self._audit(
            "indicator_preset.updated", p, preset_id, before_state=before, after_state=after
        )
        row = await repo.update(owner, preset_id, fields)
        _log().info("indicator_preset_updated", user_id=owner, preset_id=preset_id,
                    indicator_code=fields.indicator_code)  # fmt: skip
        return row

    async def soft_delete(self, p: AuditPrincipal, preset_id: str) -> None:
        repo, owner = self._store(), str(p.user_id)
        current = await repo.get_own(owner, preset_id)
        if current is None:
            raise await self._refuse_target(repo, p, preset_id)
        before = _state(current.fields())
        await self._audit("indicator_preset.deleted", p, preset_id, before_state=before)
        if not await repo.soft_delete(owner, preset_id):
            raise PresetNotFoundError(preset_id)  # deleted by a concurrent request meanwhile
        _log().info("indicator_preset_deleted", user_id=owner, preset_id=preset_id,
                    indicator_code=current.indicator_code)  # fmt: skip
        await self._refresh_gauge(repo)

    async def export_for_bundle(self, owner: str) -> list[dict[str, Any]]:
        """The caller's live presets as closed `IndicatorPresetInput`s (IR-26): never a built-in
        or another user's preset, at most `PRESETS_PER_USER_MAX`, never cut to the import
        limits."""
        return [bundle_item(r) for r in await self._store().list_visible(owner) if not r.is_builtin]

    async def import_from_bundle(self, p: AuditPrincipal, items: object) -> list[PresetRow]:
        """`WorkspaceBundle.indicator_presets`, imported whole or not at all (SR-E13-07,
        IR-06, IR-35): each item is validated again exactly as a create (so `is_builtin` and
        `owner_user_id` are refused as unknown fields, and the caller owns what is imported);
        refused whole past `BUNDLE_IMPORT_PRESETS_MAX` items or `BUNDLE_IMPORT_MAX_BYTES` of
        preset JSON, on any invalid item, or past `PRESETS_PER_USER_MAX` live presets. A name
        the caller already holds for that indicator is renamed (` (2)`, ...), never overwritten.
        One `indicator_preset.imported` record is written ahead of the rows."""
        if not isinstance(items, list):
            message = "indicator_presets must be an array."
            raise PresetInvalidError([{"field": "indicator_presets", "rule": "list_type",
                                       "message": message}])  # fmt: skip
        if len(items) > BUNDLE_IMPORT_PRESETS_MAX:
            message = f"A bundle imports at most {BUNDLE_IMPORT_PRESETS_MAX} presets."
            raise PresetBundleTooLargeError("too_many_presets", message)
        if jsonb_text_bytes(items) > BUNDLE_IMPORT_MAX_BYTES:
            message = f"A bundle imports at most {BUNDLE_IMPORT_MAX_BYTES} bytes of presets."
            raise PresetBundleTooLargeError("too_large", message)
        validated = self._validate_items(items)
        repo, owner = self._store(), str(p.user_id)
        if (await repo.occupancy(owner)).live_presets + len(validated) > PRESETS_PER_USER_MAX:
            raise PresetConflictError("limit_reached")
        planned = [(str(self._new_id()), fields) for fields in validated]
        digest = hashlib.sha256(
            "".join(content_sha256(fields) for _, fields in planned).encode()
        ).hexdigest()
        after = {"count": len(planned), "content_sha256": digest,
                 "preset_ids": [preset_id for preset_id, _ in planned]}  # fmt: skip
        await self._audit("indicator_preset.imported", p, None, after_state=after)
        rows = await repo.import_many(owner, planned)
        _log().info("indicator_presets_imported", user_id=owner, count=len(rows))
        await self._refresh_gauge(repo)
        return rows

    def _validate_items(self, items: list[object]) -> list[PresetFields]:
        """Every item checked as a create checks its body; the first `_MAX_ERRORS` defects of
        the whole array are reported together, each rooted at `indicator_presets.<i>`."""
        errors: list[dict[str, str]] = []
        validated: list[PresetFields] = []
        for i, item in enumerate(items):
            prefix = f"indicator_presets.{i}"
            try:
                body = PresetInput.model_validate(item)
                validated.append(preset_fields(body, self._catalogue, prefix=prefix))
            except ValidationError as exc:
                errors += format_errors(exc, limit=_MAX_ERRORS, prefix=prefix)
            except PresetInvalidError as exc:
                errors += exc.errors
            if len(errors) >= _MAX_ERRORS:
                break
        if errors:
            raise PresetInvalidError(errors[:_MAX_ERRORS])
        return validated


__all__ = [
    "IndicatorPresetMetrics", "IndicatorPresetMetricsLike", "IndicatorPresetService",
    "PresetBuiltinImmutableError", "PresetBundleTooLargeError", "PresetStoreUnavailableError",
    "bundle_item", "content_sha256",
]  # fmt: skip
