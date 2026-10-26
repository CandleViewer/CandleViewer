"""The `profile.*` audit records of the profile writes (E28-T02, #906 D2-2; 24 Sec.15.5).

A write's handler builds a `ProfileAudit` per request and hands its `audit_*` hook, through
`ProfilesRepository`, to the profile store, which awaits it in the write's unit of work before the
commit, bounded by `bounded_write_ahead` (C-2.9). The hook writes its record and answers a
`RelaxedNotice` for a relaxing write (SR-E28-01; the 2026-10-22 17:25Z ruling (1)), which the store
adds in the same transaction. A move's hook runs twice (D2-6): for the default it demotes
(`.unbound`), then for the new one (`.bound`, judged on the caps alone against the demoted
default's values). A record not written (`AuditError`; `RuntimeError`, a writer not
started; `TimeoutError`) is `ProfileAuditRefused`, no `OSError`, which the store rolls back on and
never maps as its own; a hook past the store's bound is its `WriteAheadTimeout`. A refused save
writes one `profile.save_refused` per audited rule it names, none for shape alone, its reason
checked first (#4087 R1S-03) and its record bounded by `AUDIT_TIMEOUT_S`, as no transaction bounds
it (the 17:25Z ruling (3)). The edge answers either refusal `503 audit_unavailable`. A state's names
meet no secret or PII name of `audit.redact`, and nothing here logs (C-12.6). The writer's `redact`
(`audit/redact.py`) re-serialises, and redacts, a `name` that is a JSON object or array, so
`[1, 2]` is recorded as `[1,2]`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass, fields
from decimal import Decimal
from typing import Any, Final, Protocol
from uuid import UUID

from candleviewer.accounts.models import ExchangeEnv
from candleviewer.accounts.profile_input import ProfileFieldError
from candleviewer.accounts.profile_relaxing import looser_caps, widens_symbols
from candleviewer.api.profile_projection import plain
from candleviewer.audit.actions import PROFILE_SAVE_REFUSED_REASONS
from candleviewer.audit.errors import AuditError
from candleviewer.storage.repositories.account_profiles import (
    AccountProfileRow,
    AccountProfileValues,
    LadderRung,
    ProfileWriteAhead,
    RelaxedNotice,
)

AUDIT_TIMEOUT_S: Final = 5.0  # a refusal's record, outside any transaction
SAVE_REFUSED_SHOWN: Final = 20
#: A record not written: the writer refused it, has not started (`RuntimeError`), or timed out.
_UNWRITTEN: Final = (AuditError, RuntimeError, TimeoutError)


class Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class ProfileAuditRefused(Exception):
    """A profile record could not be written; nothing changed (503 audit_unavailable)."""


class UnknownSaveRefusedReason(ValueError):
    """R1S-03 (#4087): a `profile.save_refused` reason outside `PROFILE_SAVE_REFUSED_REASONS`."""


@dataclass(frozen=True, slots=True)
class ProfileActor:
    """The Owner who writes, as every record names them. The handler builds it per request, with
    `request_id` from `current_request_uuid()` (#3990) and `env` the account's environment."""

    user_id: UUID
    ip: str | None
    request_id: UUID | None
    env: ExchangeEnv


def _stored(value: object) -> object:
    if isinstance(value, Decimal):
        return plain(value)
    if isinstance(value, LadderRung):
        return {"pct": plain(value.pct), "r": plain(value.r)}
    if isinstance(value, tuple):
        return [_stored(item) for item in value]
    return value


def profile_state(row: AccountProfileRow) -> dict[str, object]:
    """The profile as a record holds it: its account, its `version` and every column a write sets
    (21 Sec.3.2.4) in stored units, each decimal by `plain`, a tuple as a list and a ladder rung as
    `{"pct", "r"}`; never a float."""
    state: dict[str, object] = {
        "exchange_account_id": str(row.exchange_account_id),
        "version": row.version,
    }
    for column in fields(AccountProfileValues):
        state[column.name] = _stored(getattr(row.values, column.name))
    return state


async def _written(record: Awaitable[None], bound: float | None = None) -> None:
    """Await one record, within `bound` when one is given; a record not written is refused."""
    try:
        async with asyncio.timeout(bound):
            await record
    except _UNWRITTEN as exc:
        raise ProfileAuditRefused("a profile record could not be written") from exc


def _binding(profile_id: UUID | None, version: int) -> dict[str, object]:
    """The default binding, before a move or after it."""
    default = None if profile_id is None else str(profile_id)
    return {"default_profile_id": default, "binding_version": version}


class ProfileAudit:
    """The `profile.*` records of one request's write on one account (the module docstring)."""

    def __init__(self, audit: Emitter, actor: ProfileActor, account_id: UUID) -> None:
        self._audit, self._actor, self._account = audit, actor, account_id

    def _on(self, object_id: UUID, kind: str = "account_profile") -> dict[str, Any]:
        """Every record's actor, environment and object; each call passes its `request_id`."""
        actor = self._actor
        return {
            "actor_label": str(actor.user_id), "actor_user_id": actor.user_id,
            "actor_ip": actor.ip, "session_id": None, "env": actor.env, "object_kind": kind,
            "object_id": str(object_id),
        }  # fmt: skip

    async def audit_refused(
        self, errors: Sequence[ProfileFieldError], *, profile_id: UUID | None
    ) -> None:
        """One `profile.save_refused` per audited rule `errors` name, in the order first named;
        none for a refusal of shape alone."""
        for rule in dict.fromkeys(e.rule for e in errors if e.rule in PROFILE_SAVE_REFUSED_REASONS):
            entries = [e for e in errors if e.rule == rule]
            await self.save_refused(rule, entries, profile_id=profile_id)

    async def save_refused(
        self, reason: str, entries: Sequence[ProfileFieldError], *, profile_id: UUID | None
    ) -> None:
        """A refused save's record of one rule: its `after` the account, the rule's entry count and
        its first `SAVE_REFUSED_SHOWN` entries, of `reason` alone whatever else `entries` holds. A
        create, with no profile yet, names the account."""
        if reason not in PROFILE_SAVE_REFUSED_REASONS:  # before anything is written
            raise UnknownSaveRefusedReason("not a profile.save_refused reason")
        if profile_id is None:  # a create: no profile yet
            on = self._on(self._account, "exchange_account")
        else:
            on = self._on(profile_id)
        entries = [entry for entry in entries if entry.rule == reason]  # never a shape entry
        shown = [entry.to_dict() for entry in entries[:SAVE_REFUSED_SHOWN]]
        after = {"exchange_account_id": str(self._account), "count": len(entries), "errors": shown}
        await _written(
            self._audit.emit(
                "profile.save_refused", **on, request_id=self._actor.request_id,
                outcome="denied", severity="warning", reason=reason, after_state=after,
            ),
            AUDIT_TIMEOUT_S,
        )  # fmt: skip

    def audit_created(self) -> ProfileWriteAhead:
        """The create's hook: `profile.created`, the profile as stored."""

        async def created(_: AccountProfileRow | None, after: AccountProfileRow) -> None:
            await _written(
                self._audit.emit(
                    "profile.created", **self._on(after.id), request_id=self._actor.request_id,
                    outcome="success", severity="info", after_state=profile_state(after),
                )
            )  # fmt: skip

        return created

    def audit_updated(self) -> ProfileWriteAhead:
        """The replace's hook: `profile.updated`, the profile before and after, labelled relaxing
        and answered with the Owner's notice when it loosens a cap or widens the symbols. Without
        the profile before it, the record would be wrong, so it is refused."""

        async def updated(
            before: AccountProfileRow | None, after: AccountProfileRow
        ) -> RelaxedNotice | None:
            if before is None:
                raise ProfileAuditRefused("a replace's record needs the profile before it")
            caps = looser_caps(before.values, after.values)
            widened = widens_symbols(before.values, after.values)
            relaxing = bool(caps) or widened
            labels = {"relaxing": relaxing, "looser_caps": list(caps), "widened_symbols": widened}
            await _written(
                self._audit.emit(
                    "profile.updated", **self._on(after.id), request_id=self._actor.request_id,
                    outcome="success", severity="warning" if relaxing else "info",
                    before_state=profile_state(before), after_state=profile_state(after) | labels,
                )
            )  # fmt: skip
            if not relaxing:
                return None
            return RelaxedNotice(after.id, None, caps, widened, self._actor.request_id)

        return updated

    def audit_deleted(self) -> ProfileWriteAhead:
        """The delete's hook: `profile.deleted`, the profile as it stood (refused without it)."""

        async def deleted(before: AccountProfileRow | None, after: AccountProfileRow) -> None:
            if before is None:
                raise ProfileAuditRefused("a delete's record needs the profile as it stood")
            await _written(
                self._audit.emit(
                    "profile.deleted", **self._on(after.id), request_id=self._actor.request_id,
                    outcome="success", severity="info", before_state=profile_state(before),
                )
            )  # fmt: skip

        return deleted

    def audit_moved(self, profile_id: UUID, binding_version: int) -> ProfileWriteAhead:
        """The move's hook, given the new default and the binding's version (the `If-Match` the
        store compared): for the demoted default, `.unbound`, keeping its values; then for the new
        default, `.bound`, judged on the caps alone against them, or against none when the account
        had no default. Both carry the binding before the move and after it, one version on."""
        demoted: AccountProfileRow | None = None

        async def moved(
            _: AccountProfileRow | None, after: AccountProfileRow
        ) -> RelaxedNotice | None:
            nonlocal demoted
            moved_to = _binding(profile_id, binding_version + 1)
            if not after.values.is_default:
                demoted = after
                await _written(
                    self._audit.emit(
                        "profile.unbound", **self._on(after.id), request_id=self._actor.request_id,
                        outcome="success", severity="info",
                        before_state=_binding(after.id, binding_version), after_state=moved_to,
                    )
                )  # fmt: skip
                return None
            previous = None if demoted is None else demoted.id
            caps = looser_caps(None if demoted is None else demoted.values, after.values)
            labels = {"relaxing": bool(caps), "looser_caps": list(caps)}
            await _written(
                self._audit.emit(
                    "profile.bound", **self._on(after.id), request_id=self._actor.request_id,
                    outcome="success", severity="warning" if caps else "info",
                    before_state=_binding(previous, binding_version), after_state=moved_to | labels,
                )
            )  # fmt: skip
            if not caps:
                return None
            return RelaxedNotice(after.id, previous, caps, False, self._actor.request_id)

        return moved
