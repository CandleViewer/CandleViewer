"""`createTradeGroupDefinition` (E28-T05 #909, slice S2c; 22; SR-E28-31), each check before the
next: no resolver 501, no session 401; `accounts:write`, the Owner's alone (403 audited
`rbac.denied`; unwritten, 503 as the profile writes); no store 503; `trading.trade_groups` off,
`403 trading_disabled` with no `reason` (21 Sec.10.7). `validated`: the shape (422, a repeat
`duplicate_account`); each member's account in the Owner's scope, a missing or deleted one `403
account_scope_denied` (SR-E29-13) before any environment is judged; the environments (400
`environment_mismatch`, the accounts named by label); a definition outside this process's
environment, whose listing alone judges (C-2.11), out of scope as the order path answers one; the
common symbols (400 `no_common_symbol`). Then the `risk_caps` step-up (SR-E28-02), naming the
environment and the member count, never the name; then the store, `trade_group_definition.created`
ahead of its commit (C-2.9; unwritten, 503 with nothing stored; `audit_definition_write` serves
every definition write), a live name in any letter case `409 conflict`. Logs carry no value.

`updateTradeGroupDefinition` and `deleteTradeGroupDefinition` (S2d) are admitted alike, meet the
flag alike, then read the definition as the Owner: missing, deleted or of another environment, one
404 (SEC-2-03, C-2.11). A replace's body is `validated` with another `environment` than the stored
one refused first (`400 write_once`); its `If-Match`, when sent, must be the `ETag` of the row read
(412), whose `updated_at` the store compares under its row lock (412), and without one the last
write wins. Their challenges name the definition by its id. On every write, after RBAC and before
the flag, which a replay never meets (21 Sec.10.7), this principal's kept `2xx` to the same request
(SR-E28-17) is answered behind the step-up; another request under its key is `409
idempotency_key_reuse`.
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Final, Protocol, cast

import structlog
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from candleviewer.accounts import errors
from candleviewer.accounts import profile_validator as validator
from candleviewer.accounts import trade_group_definitions as domain
from candleviewer.accounts.models import ExchangeAccount
from candleviewer.accounts.profile_cache import EffectiveProfiles
from candleviewer.accounts.profile_input import ProfileFieldError
from candleviewer.accounts.profiles import SymbolScope
from candleviewer.accounts.trade_group_readiness import ReadinessSource
from candleviewer.api import profile_body as edge
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.csrf import source_ip
from candleviewer.api.idempotency import (
    IdempotencyCache,
    IdempotencyKeyReuse,
    remember,
    replay,
    request_fingerprint,
)
from candleviewer.api.profile_audit import Emitter
from candleviewer.api.profiles import AccountReads, problem
from candleviewer.api.refusal_session import NamesSession, SessionsLike
from candleviewer.api.step_up import RequestElevation, demand_elevation
from candleviewer.api.step_up_challenge import ChallengeText, definition_write_text, quote_label
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.api.trade_group_definitions import definition_document, definition_readiness
from candleviewer.api.trade_groups_gate import TradeGroupsGate
from candleviewer.api.users import SnapshotResolver
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.metrics import count_authz_denial
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.observability.context import current_request_uuid
from candleviewer.storage.errors import StorageError, StorageQueryFailed, WriteAheadTimeout
from candleviewer.storage.repositories import trade_group_definitions as port
from candleviewer.storage.repositories.accounts import OwnerScope

#: 22 sets no cap: 20 members and an 80-character name take under 2 KiB.
MAX_DEFINITION_BODY_BYTES: Final = 16_384
_WRITE: Final = Permission.ACCOUNTS_WRITE
_NOT_OWNER: Final = f"not_owner:{_WRITE.value}:{Scope.GRANTED_ACCOUNTS.value}"  # as `enforce`
_STALE: Final = "If-Match does not name this definition's current version. Nothing was changed."
_WRITE_ONCE: Final = ProfileFieldError(
    "environment", "write_once", "A definition's environment cannot change."
)


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class DefinitionRows(port.DefinitionStore, port.DefinitionReads, Protocol):
    """The writes' store: its writes, and the read a replace and a delete answer 404 from."""


@dataclass(frozen=True, slots=True)
class DefinitionWrites:
    """The store, readiness for the answer, the members' accounts (in the Owner's scope), their
    bound profiles (`get_effective_profile`) and the listing of this environment (C-2.11)."""

    store: DefinitionRows
    readiness: ReadinessSource
    accounts: AccountReads
    profiles: EffectiveProfiles
    instruments: validator.InstrumentLimitsPort


@dataclass(frozen=True, slots=True)
class _Caller:
    """A write past admission; a refusal's record names the caller's session (#4174)."""

    principal: PrincipalSnapshot
    writes: DefinitionWrites
    named: NamesSession
    ip: str | None
    request_id: uuid.UUID | None


class _Rejected(edge.Refused):
    """A body the rules refuse: `400 validation_failed` (a shape refusal is 422)."""


class _Missing(Exception):
    """No live definition of this process's environment: missing, deleted or another's (404)."""


def _expected(request: Request, held: port.DefinitionRecord) -> datetime | None:
    """`If-Match` (22): absent, `None`, and the last write wins; else exactly the `ETag` of the row
    read, whose `updated_at` the store then compares under its row lock. Anything else (`*`, a
    list, two headers, another version) is `IfMatchRefused` (412)."""
    if not (sent := request.headers.getlist("if-match")):
        return None
    tag = domain.definition_etag(domain.stored_definition(held))  # the hash of the row read
    if len(sent) > 1 or sent[0].strip(" \t") != tag:  # RFC 9110's optional whitespace aside
        raise edge.IfMatchRefused
    return held.definition.updated_at


def _restated(verb: str, raw: bytes, of: uuid.UUID | None = None) -> ChallengeText:
    """A kept create's or replace's challenge, from its own body, which passed the model then."""
    sent = api.TradeGroupDefinitionInput.model_validate(edge.decode(raw))
    return definition_write_text(verb, sent.environment, len(sent.members), of)


def _forbidden() -> JSONResponse:
    return problem("forbidden", f"Requires {_WRITE.value}.", required_permissions=[_WRITE.value])


def _unaudited() -> JSONResponse:
    return problem("audit_unavailable", "The audit record could not be written; nothing was saved.")


def _mixed(
    definition: domain.DefinitionInput, accounts: Sequence[ExchangeAccount], outside: Sequence[Any]
) -> _Rejected:
    """An entry per member outside; `detail` the rule, then every member by label (AC 2)."""
    named = ", ".join(f"{quote_label(a.label)} ({a.env.value})" for a in accounts)
    message = "This account is not in the definition's environment."
    entries = [
        ProfileFieldError(f"members[{i}].exchange_account_id", "environment_mismatch", message)
        for i, account in enumerate(accounts) if account.id in outside
    ]  # fmt: skip
    return _Rejected(entries, f"{domain.MIXED_ENVIRONMENTS} {named}.")


class DefinitionAuditRefused(Exception):
    """A definition record could not be written; nothing changed (503 audit_unavailable)."""


def definition_state(found: port.DefinitionRecord) -> dict[str, object]:
    """The definition as a record holds it: its name, environment and members, by account id."""
    members = [{"exchange_account_id": str(m.exchange_account_id), "enabled": m.enabled}
               for m in found.members]  # fmt: skip
    return {"name": found.definition.name, "environment": found.definition.env, "members": members}


def membership_change(
    before: port.DefinitionRecord | None, after: port.DefinitionRecord | None
) -> dict[str, list[str]]:
    """The members added, removed and toggled (`enabled` flipped) by account id; `None` is no
    definition."""
    was = {} if before is None else {m.exchange_account_id: m.enabled for m in before.members}
    now = {} if after is None else {m.exchange_account_id: m.enabled for m in after.members}
    return {
        "added": [str(a) for a in now if a not in was],
        "removed": [str(a) for a in was if a not in now],
        "toggled": [str(a) for a in now if a in was and was[a] != now[a]],
    }


def audit_definition_write(
    audit: Emitter, user_id: uuid.UUID, ip: str | None, request_id: uuid.UUID | None
) -> port.DefinitionWriteAhead:
    """One request's hook (module docstring), naming the Owner `user_id` its actor."""

    async def ahead(
        before: port.DefinitionRecord | None, after: port.DefinitionRecord | None
    ) -> None:
        held = cast(port.DefinitionRecord, after or before)  # the store passes one at least
        action = "created" if before is None else "deleted" if after is None else "updated"
        state = {} if after is None else definition_state(after)
        try:
            await audit.emit(
                f"trade_group_definition.{action}", actor_label=str(user_id),
                actor_user_id=user_id, actor_ip=ip, session_id=None, env=held.definition.env,
                object_kind="trade_group_definition", object_id=str(held.definition.id),
                request_id=request_id, outcome="success", severity="info",
                before_state=None if before is None else definition_state(before),
                after_state=state | {"membership_change": membership_change(before, after)},
            )  # fmt: skip
        except (AuditError, RuntimeError, TimeoutError) as exc:
            raise DefinitionAuditRefused("a definition record could not be written") from exc

    return ahead


def make_trade_group_definition_writes_router(
    writes: DefinitionWrites | None, gate: TradeGroupsGate, audit: Emitter,
    resolver: SnapshotResolver | None, *, auth: SessionsLike | None = None,
    elevation: RequestElevation | None = None, new_id: Callable[[], uuid.UUID] = uuid.uuid4,
    replays: IdempotencyCache | None = None,
) -> APIRouter:  # fmt: skip
    """The writes over `writes` (`None`: 503); `resolver=None`: 501; `elevation` demands the
    `risk_caps` step-up (`None`: 503, nothing stored); `replays` keeps their `2xx` answers."""
    router = APIRouter(tags=["trading"])
    cache = IdempotencyCache() if replays is None else replays

    async def admit(request: Request) -> _Caller | Response:
        if resolver is None:
            return problem("not_implemented", "No principal resolver is wired.")
        got = resolver.resolve(request)
        if (principal := await got if inspect.isawaitable(got) else got) is None:
            return problem("unauthenticated", "No verified session for this request.")
        named, ip = NamesSession(audit, auth, request), source_ip(request.scope)
        request_id = current_request_uuid()
        try:  # the permission alone: the stores' live-owner gate holds the Owner (SR-051)
            await enforce(principal, _WRITE, emitter=named, actor_ip=ip, request_id=request_id)
        except ForbiddenError:
            return _forbidden()
        except (AuditError, RuntimeError):  # RuntimeError: the audit writer is not started
            return _unaudited()
        if writes is None:
            return problem("store_unavailable", "Trade-group definitions are not available here.")
        return _Caller(principal, writes, named, ip, request_id)

    async def bound(got: _Caller, account_id: AccountId) -> SymbolScope | None:
        """The symbols its bound profile allows; none without one (it allows nothing)."""
        try:
            return SymbolScope.of(await got.writes.profiles.get_effective_profile(account_id))
        except errors.AccountNotFoundError:
            return None

    def kept(
        got: _Caller, request: Request, operation: str, raw: bytes
    ) -> tuple[str | None, str, Response | None]:
        """The key, the request's fingerprint, and this principal's kept answer to both."""
        key = edge.idempotency(request, operation)
        digest = request_fingerprint(request.method, request.url.path, raw)
        return key, digest, replay(cache, str(got.principal.user_id), key, digest)

    async def replayed(request: Request, hit: Response, text: ChallengeText) -> Response:
        """A kept answer, behind the step-up its write took; never the flag (21 Sec.10.7)."""
        return await demand_elevation(elevation, request, text) or hit

    async def current(got: _Caller, definition_id: uuid.UUID) -> port.DefinitionRecord:
        """The live definition as the Owner reads it; one of another environment is answered as a
        missing or deleted one (C-2.11, SEC-2-03), as the profile writes answer an account."""
        found = await got.writes.store.get(OwnerScope(got.principal.user_id), definition_id)
        if found is None or found.definition.env != got.writes.instruments.environment:
            raise _Missing
        return found

    async def validated(
        got: _Caller, body: object, stored: port.DefinitionRecord | None = None
    ) -> domain.DefinitionInput:
        """`body` as the domain takes it, judged in the module docstring's order; a replace's
        `environment` must be the `stored` one's, judged before its members."""
        try:
            sent = api.TradeGroupDefinitionInput.model_validate(body)
            member = domain.DefinitionMember
            members = tuple(
                member(account_id=AccountId(m.exchange_account_id), enabled=m.enabled)
                for m in sent.members
            )
            definition = domain.DefinitionInput(
                name=sent.name, environment=sent.environment, members=members
            )
        except ValidationError as exc:
            raise edge.refused(edge.model_errors(exc)) from None
        except domain.DuplicateMember as exc:
            field = f"members[{exc.index}].exchange_account_id"
            repeated = ProfileFieldError(field, "duplicate_account", "This account is a member.")
            raise edge.refused([repeated]) from None
        if stored is not None and definition.environment != stored.definition.env:
            raise _Rejected([_WRITE_ONCE], "A definition's environment is write-once.")
        held, scope = got.writes, OwnerScope(got.principal.user_id)
        accounts = [await held.accounts.get_account(scope, m.account_id) for m in members]
        envs = cast(Mapping[AccountId, Environment], {a.id: a.env.value for a in accounts})
        if outside := domain.environment_mismatches(definition, envs):
            raise _mixed(definition, accounts, outside)
        if held.instruments.environment != definition.environment:  # another process's (C-2.11)
            raise errors.AccountNotFoundError("account")
        listed = await held.instruments.listed(
            max_age_s=validator.INSTRUMENT_MAX_AGE_S, deadline_s=validator.INSTRUMENT_DEADLINE_S
        )
        scopes = {m.account_id: await bound(got, m.account_id) for m in members}
        allowed = {account: scope for account, scope in scopes.items() if scope is not None}
        if not domain.common_symbols(definition, allowed, listed.values()):
            none = ProfileFieldError("members", "no_common_symbol", domain.NO_COMMON_SYMBOL)
            raise _Rejected([none], domain.NO_COMMON_SYMBOL)
        return definition

    async def answer(exc: Exception, got: _Caller) -> Response:
        """A write that stored nothing, answered as 22 says; a defect is raised."""
        if isinstance(exc, port.DefinitionStoreError):
            exc = domain.definition_error(exc)  # a fresh error holding a name alone (C-12.6)
        if isinstance(exc, _Missing):
            return problem("not_found", "No such trade-group definition.")
        if isinstance(exc, IdempotencyKeyReuse):
            return problem("idempotency_key_reuse", "The key was used for another request.")
        if isinstance(exc, edge.IfMatchRefused | errors.AccountVersionConflictError):
            return problem("version_conflict", _STALE)
        if isinstance(exc, edge.Refused):
            status = 400 if isinstance(exc, _Rejected) else 422
            entries = [entry.to_dict() for entry in exc.errors]
            return problem("validation_failed", exc.detail, status=status, errors=entries)
        if isinstance(exc, edge.BodyTooLarge):
            too_large = ProfileFieldError("body", "body_too_large", str(exc)).to_dict()
            return problem("validation_failed", str(exc), errors=[too_large])
        if isinstance(exc, DefinitionAuditRefused | WriteAheadTimeout):
            return _unaudited()
        if isinstance(exc, validator.InstrumentLimitsUnavailable):
            detail = "The exchange's listing could not be refreshed in time; nothing was saved."
            return problem("instrument_cache_unavailable", detail, retry_s=2)
        if isinstance(exc, errors.AccountNotFoundError) and exc.entity == "account":  # not 404
            detail = "A member's exchange account is not in your scope."
            return problem("account_scope_denied", detail, status=403)
        if isinstance(exc, errors.AccountConflictError) and exc.constraint == "ux_tgd_name":
            return problem("conflict", "A live definition has that name, in any letter case.")
        if isinstance(exc, errors.AccountRuleError):  # the store's own rule the checks missed
            _log().error("trade_group_definition_refused_by_constraint", rule=exc.rule)
            return problem("validation_failed", "The definition breaks a stored rule.", status=400)
        if isinstance(exc, errors.AccountScopeDeniedError):  # the stores' live-owner gate (SR-051)
            count_authz_denial(_WRITE, got.principal.roles)
            actor = got.principal.user_id
            try:
                await got.named.emit(
                    "rbac.denied", actor_label=str(actor), actor_user_id=actor, actor_ip=got.ip,
                    outcome="denied", severity="warning", request_id=got.request_id,
                    reason=_NOT_OWNER,
                )  # fmt: skip
            except (AuditError, RuntimeError):
                return _unaudited()
            return _forbidden()
        if not isinstance(exc, errors.AccountsError | StorageError) and not is_storage_outage(exc):
            raise exc
        facts = exc if isinstance(exc, StorageQueryFailed) else getattr(exc, "orig", None)
        state, name = getattr(facts, "sqlstate", None), type(exc).__name__
        _log().warning("trade_group_definition_write_unavailable", error=name, sqlstate=state)
        return problem("store_unavailable", "The trade-group definition store is unavailable.")

    @router.post("/trade-group-definitions", status_code=201)
    async def create_trade_group_definition(request: Request) -> Response:
        if isinstance(got := await admit(request), Response):
            return got
        owner = got.principal.user_id
        try:
            raw = await edge.read_capped(request, MAX_DEFINITION_BODY_BYTES)
            key, digest, hit = kept(got, request, "createTradeGroupDefinition", raw)
            if hit is not None:
                return await replayed(request, hit, _restated("create", raw))
            if (off := gate.refusal()) is not None:
                return off
            definition = await validated(got, edge.decode(raw))
            text = definition_write_text("create", definition.environment, len(definition.members))
            if (challenge := await demand_elevation(elevation, request, text)) is not None:
                return challenge
            ahead = audit_definition_write(audit, owner, got.ip, got.request_id)
            new = domain.new_definition(new_id(), definition)
            made = await got.writes.store.create(OwnerScope(owner), new, write_ahead=ahead)
            stored = domain.stored_definition(made)
        except Exception as exc:  # mapped, or raised as a defect
            return await answer(exc, got)
        doc = definition_document(stored, definition_readiness(stored, got.writes.readiness))
        out = JSONResponse(doc, 201, {"ETag": domain.definition_etag(stored)})
        return remember(cache, str(owner), key, digest, out)

    @router.put("/trade-group-definitions/{definitionId}")
    async def update_trade_group_definition(
        request: Request, definition_id: Annotated[uuid.UUID, Path(alias="definitionId")]
    ) -> Response:
        if isinstance(got := await admit(request), Response):
            return got
        owner = got.principal.user_id
        try:
            raw = await edge.read_capped(request, MAX_DEFINITION_BODY_BYTES)
            key, digest, hit = kept(got, request, "updateTradeGroupDefinition", raw)
            if hit is not None:
                return await replayed(request, hit, _restated("replace", raw, definition_id))
            if (off := gate.refusal()) is not None:
                return off
            held = await current(got, definition_id)
            definition = await validated(got, edge.decode(raw), held)
            expected, size = _expected(request, held), len(definition.members)
            text = definition_write_text("replace", definition.environment, size, definition_id)
            if (challenge := await demand_elevation(elevation, request, text)) is not None:
                return challenge
            ahead = audit_definition_write(audit, owner, got.ip, got.request_id)
            new = domain.new_definition(definition_id, definition)
            made = await got.writes.store.replace(
                OwnerScope(owner), definition_id, new, expected_updated_at=expected,
                write_ahead=ahead,
            )  # fmt: skip
            if made is None:  # deleted since the read: it takes no member (SEC-2-03)
                raise _Missing
            stored = domain.stored_definition(made)
        except Exception as exc:  # mapped, or raised as a defect
            return await answer(exc, got)
        doc = definition_document(stored, definition_readiness(stored, got.writes.readiness))
        out = JSONResponse(doc, 200, {"ETag": domain.definition_etag(stored)})
        return remember(cache, str(owner), key, digest, out)

    @router.delete("/trade-group-definitions/{definitionId}", status_code=204)
    async def delete_trade_group_definition(
        request: Request, definition_id: Annotated[uuid.UUID, Path(alias="definitionId")]
    ) -> Response:
        if isinstance(got := await admit(request), Response):
            return got
        owner, scope = got.principal.user_id, OwnerScope(got.principal.user_id)
        text = definition_write_text("delete", got.writes.instruments.environment, 0, definition_id)
        try:
            key, digest, hit = kept(got, request, "deleteTradeGroupDefinition", b"")  # no body
            if hit is not None:
                return await replayed(request, hit, text)
            if (off := gate.refusal()) is not None:
                return off
            await current(got, definition_id)
            if (challenge := await demand_elevation(elevation, request, text)) is not None:
                return challenge
            ahead = audit_definition_write(audit, owner, got.ip, got.request_id)
            if await got.writes.store.soft_delete(scope, definition_id, write_ahead=ahead) is None:
                raise _Missing  # deleted since the read
        except Exception as exc:  # mapped, or raised as a defect
            return await answer(exc, got)
        return remember(cache, str(owner), key, digest, Response(status_code=204))

    return router
