"""Domain models for the audit module (M19).

Pydantic v2 models for the WAL envelope (`AuditWalRecord`) and the query/verify
API surface (`AuditEntry`, `AuditPage`, `VerifyResult`, `ExportResult`),
matching `docs/plan/22-api-openapi.yaml` `AuditEntry`/`AuditOutcome`/`Severity`
schemas and `services/api/candleviewer/db/models.py`'s `audit_log` columns.
"""

from __future__ import annotations

import ipaddress
import math
import re
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"


class Severity(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ExchangeEnv(StrEnum):
    LIVE = "live"
    DEMO = "demo"
    TESTNET = "testnet"


#: What U+0000 becomes in an audit record.
_NUL_REPLACEMENT = "\N{REPLACEMENT CHARACTER}"


def _unstorable(text: str) -> bool:
    """True if `text` holds U+0000 or a lone surrogate, which Postgres `text`/`jsonb` refuse."""
    if "\x00" in text:
        return True
    if text.isascii():
        return False
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return False


def _needs_scrub(value: object) -> bool:
    if isinstance(value, str):
        return _unstorable(value)
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        for key, item in value.items():
            if (isinstance(key, str) and _unstorable(key)) or _needs_scrub(item):
                return True
    elif isinstance(value, list | tuple):
        for item in value:
            if _needs_scrub(item):
                return True
    return False


def _scrub(value: object) -> Any:
    """A copy of `value` with U+0000 replaced by U+FFFD and each lone surrogate by `?`
    in every string, dict keys included, at any depth, and each non-finite float (NaN or an
    infinity, which `jsonb` refuses) by `None`. A key that is not a `str` is kept as it is.
    Two keys that differ only in a replaced character collide and the last one wins, as a
    duplicate key does in `jsonb`."""
    if isinstance(value, str):
        if not _unstorable(value):
            return value
        text = value.replace("\x00", _NUL_REPLACEMENT)
        return text.encode("utf-8", "replace").decode("utf-8")
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {
            (_scrub(key) if isinstance(key, str) else key): _scrub(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_scrub(item) for item in value]
    return value


def storable(record: dict[str, Any]) -> dict[str, Any]:
    """`record` with every string and non-finite float made storable (`_scrub`), or `record`
    itself, uncopied, when nothing needs replacing. Applied by `AuditEmission` and again by the
    WAL flusher."""
    if not _needs_scrub(record):
        return record
    scrubbed: dict[str, Any] = _scrub(record)
    return scrubbed


class AuditEmission(BaseModel):
    """The fully-validated, not-yet-persisted shape `audit.emit()` builds
    before it ever reaches the WAL or a connection. `before_state`/
    `after_state` here are already redacted (`candleviewer.audit.redact`) —
    the WAL never holds an unredacted secret."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: uuid.UUID
    action: str
    actor_user_id: uuid.UUID | None = None
    actor_label: str
    actor_ip: str | None = None
    session_id: uuid.UUID | None = None
    object_kind: str | None = None
    object_id: str | None = None
    object_label: str | None = None
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    severity: Severity = Severity.INFO
    reason: str | None = None
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    request_id: uuid.UUID | None = None
    env: ExchangeEnv | None = None
    event_ts: datetime

    @model_validator(mode="before")
    @classmethod
    def _storable_text(cls, data: Any) -> Any:
        """Before validation, replace what Postgres cannot store in any string or float
        (`storable`). `emit()`, `ingest()` and the break-glass journal all build this model, so
        the record is always written. Input with nothing to replace is passed through
        uncopied."""
        return storable(data) if isinstance(data, dict) else data


class AuditEntry(BaseModel):
    """Mirrors `docs/plan/22-api-openapi.yaml` `#/components/schemas/AuditEntry`."""

    model_config = ConfigDict(frozen=True)

    id: int
    ts: datetime
    actor_user_id: uuid.UUID | None
    actor_username: str | None = None
    action: str
    subject_type: str | None = None
    subject_id: str | None = None
    outcome: AuditOutcome
    severity: Severity
    ip: str | None
    user_agent: str | None = None
    request_id: str | None
    detail: dict[str, Any] = Field(default_factory=dict)
    entry_hash: str
    prev_hash: str | None


#: Upper bound on one `GET /admin/audit` page (PR #1561 finding 5).
AUDIT_QUERY_MAX_LIMIT = 500

#: Default page size (contract #2392: 1..500, default 100).
AUDIT_QUERY_DEFAULT_LIMIT = 100

#: Contract #2392 parameter rules for `GET /admin/audit` (matched in full, not searched).
AUDIT_QUERY_MAX_ACTIONS = 50
_UUID_TEXT = re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_SUBJECT_TYPE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_ACTION_CODE = re.compile(r"[a-z0-9_]+([.][a-z0-9_]+){1,3}")


class AuditQueryRequest(BaseModel):
    """Validated filter set for `AuditQueryService.query` — `limit` bounded
    to 1..`AUDIT_QUERY_MAX_LIMIT`, unknown keys rejected. `from_ts`/`to_ts`
    must be tz-aware UTC and `from_ts <= to_ts` (PR #1608 review finding 3:
    previously a naive datetime or `from_ts > to_ts` was accepted silently).
    The other filters follow the contract's parameter rules and are kept in
    canonical form, so only canonical values are queried or recorded."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_user_id: str | None = None
    actions: list[str] | None = None
    subject_type: str | None = None
    ip: str | None = None
    severity: Severity | None = None
    outcome: AuditOutcome | None = None
    from_ts: datetime | None = None
    to_ts: datetime | None = None
    cursor: int | None = Field(default=None, ge=1)
    limit: int = Field(default=AUDIT_QUERY_DEFAULT_LIMIT, ge=1, le=AUDIT_QUERY_MAX_LIMIT)

    @field_validator("ip")
    @classmethod
    def _single_ip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if "%" in value:  # a scope id (fe80::1%eth0) is not a single plain address
            raise ValueError("ip must not carry a scope id")
        return str(ipaddress.ip_address(value))  # one address only; CIDR raises ValueError

    @field_validator("actor_user_id")
    @classmethod
    def _canonical_uuid(cls, value: str | None) -> str | None:
        """`format: uuid`, compared in canonical (lower-case) form, so another casing of
        the caller's own id is still the caller."""
        if value is not None and not _UUID_TEXT.fullmatch(value):
            raise ValueError("actor_user_id must be a UUID")
        return None if value is None else str(uuid.UUID(value))

    @field_validator("subject_type")
    @classmethod
    def _subject_type(cls, value: str | None) -> str | None:
        if value is not None and not _SUBJECT_TYPE.fullmatch(value):
            raise ValueError("subject_type is not a recorded subject kind")
        return value

    @field_validator("actions")
    @classmethod
    def _action_codes(cls, value: list[str] | None) -> list[str] | None:
        """At most 50 codes of at most 64 characters each; kept sorted and unique, which
        is the same filter (any of) in canonical form."""
        if value is None:
            return None
        if len(value) > AUDIT_QUERY_MAX_ACTIONS:
            raise ValueError(f"at most {AUDIT_QUERY_MAX_ACTIONS} action codes")
        if any(len(a) > 64 or not _ACTION_CODE.fullmatch(a) for a in value):
            raise ValueError("action is not an action code")
        return sorted(set(value))

    @field_validator("from_ts", "to_ts")
    @classmethod
    def _tz_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("must be a tz-aware (UTC) timestamp")
        return value

    @model_validator(mode="after")
    def _range_ordered(self) -> Self:
        if self.from_ts is not None and self.to_ts is not None and self.from_ts > self.to_ts:
            raise ValueError("from_ts must be <= to_ts")
        return self


class AuditPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[AuditEntry]
    chain_verified: bool
    next_cursor: str | None = None
    has_more: bool = False
    count: int = 0


class VerifyResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    verified: bool
    entries_checked: int
    first_bad_id: int | None
    checked_at: datetime


class ExportResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: uuid.UUID
    download_url: str | None = None


class AuditVerifyRequest(BaseModel):
    """Validated body for `POST /admin/audit/verify` (PR #1608 review
    finding 3): unknown keys rejected, `from_id`/`to_id` type-checked as
    positive ids rather than accepted as arbitrary `Any`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    from_id: int | None = Field(default=None, ge=1)
    to_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _range_ordered(self) -> Self:
        if self.from_id is not None and self.to_id is not None and self.from_id > self.to_id:
            raise ValueError("from_id must be <= to_id")
        return self


class AuditExportRequest(BaseModel):
    """Validated body for `POST /admin/audit/export` (PR #1608 review
    finding 3): `from`/`to` must be tz-aware UTC timestamps with
    `from_ts <= to_ts`, and a malformed value is rejected by pydantic (422)
    rather than reaching `_parse_ts` and raising an unhandled `ValueError`
    (500)."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    from_ts: datetime = Field(alias="from")
    to_ts: datetime = Field(alias="to")

    @field_validator("from_ts", "to_ts")
    @classmethod
    def _tz_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("must be a tz-aware (UTC) timestamp")
        return value

    @model_validator(mode="after")
    def _range_ordered(self) -> Self:
        if self.from_ts > self.to_ts:
            raise ValueError("`from` must be <= `to`")
        return self
