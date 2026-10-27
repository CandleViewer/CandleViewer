"""Trade-group definitions: the domain over the definition store (E28-T05 #909, slice S1b; 22
`TradeGroupDefinitionInput`; 21 Sec.3.3.3a; SCR-062).

`DefinitionInput` is the body as the domain takes it: a name of 1 to 80 characters that `text`
can store (`tgd_name`) and 1 to `MAX_MEMBERS` members, one per account (SR-E28-17). A repeat is
`DuplicateMember`, not a `ValidationError`, so the route can answer it at its index. The two
guards are pure and walk every member, enabled or not, failing closed: `environment_mismatches`
names each member outside the definition's environment (SR-E28-16, C-2.11; `trg_tgdm_env` checks
it again), and `common_symbols` intersects the members' bound profiles through the sizer's gate,
where a member with no bound profile allows nothing.

`stored_definition` and `new_definition` are the one adapter to the store's rows, and a stored row
the model refuses fails closed. `definition_error` maps a store error by its kind and name alone to
a fresh accounts error that holds no value (C-12.6). `definition_etag` is a weak tag of the id and
`updated_at`, which every write moves, so it versions the members; it leaves out readiness and
names no member.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated, Final, Self
from uuid import UUID

import structlog
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool, model_validator

from candleviewer.accounts.errors import (
    AccountConflictError,
    AccountNotFoundError,
    AccountRuleError,
    AccountScopeDeniedError,
    AccountsError,
    AccountVersionConflictError,
)
from candleviewer.accounts.profiles import SymbolScope, is_trading_usdt_perpetual, to_us
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId, Environment, Symbol, TsUs
from candleviewer.domain.text import refuse_unstorable_text
from candleviewer.storage.repositories import trade_group_definitions as port
from candleviewer.storage.repositories.trade_groups import ACCOUNT_NOT_LIVE

#: 22's `maxItems`. The ticket's `tradegroups.max_members` is this constant, never a setting.
MAX_MEMBERS: Final = 20
#: 22's `maxLength` and `tgd_name`'s bound.
MAX_NAME_CHARS: Final = 80
#: SCR-062's refusal, verbatim: 22's `no_common_symbol` detail.
NO_COMMON_SYMBOL: Final = (
    "These accounts have no symbol in common — the group can't trade anything."
)
#: The rule a mixed-environment refusal states (US-PROF-005, AC 2).
MIXED_ENVIRONMENTS: Final = "A trade group cannot mix Demo and Live accounts."
_FROZEN = ConfigDict(frozen=True, extra="forbid")


class DuplicateMember(AccountRuleError):
    """An account listed twice. `index` is the repeat's place: 22 answers `422 duplicate_account`
    on `members[index].exchange_account_id`. It names no account."""

    def __init__(self, index: int) -> None:
        super().__init__("duplicate_account")
        self.index = index


class DefinitionMember(BaseModel):
    """22's `TradeGroupDefinitionMember`: a disabled member stays, and a ticket skips it."""

    model_config = _FROZEN

    account_id: AccountId
    enabled: StrictBool = True


class DefinitionInput(BaseModel):
    """22's `TradeGroupDefinitionInput`: the writable columns, and nothing else."""

    model_config = _FROZEN

    name: Annotated[
        str, Field(min_length=1, max_length=MAX_NAME_CHARS), AfterValidator(refuse_unstorable_text)
    ]
    environment: Environment
    members: Annotated[tuple[DefinitionMember, ...], Field(min_length=1, max_length=MAX_MEMBERS)]

    @model_validator(mode="after")
    def _one_per_account(self) -> Self:
        seen: set[UUID] = set()
        for index, member in enumerate(self.members):
            if member.account_id in seen:
                raise DuplicateMember(index)
            seen.add(member.account_id)
        return self


@dataclass(frozen=True, slots=True)
class MemberAccount:
    """A member's account as read with the definition: its environment and its row's switch."""

    account_id: AccountId
    account_env: Environment
    account_enabled: bool


@dataclass(frozen=True, slots=True)
class StoredDefinition:
    """A live definition as read. `definition` is 22's `TradeGroupDefinition.definition`, times
    are `TsUs`, and no writer is kept: 22's model never carries one (SR-E28-21)."""

    definition_id: UUID
    definition: DefinitionInput
    created_at: TsUs
    updated_at: TsUs
    member_accounts: tuple[MemberAccount, ...]  # in `definition.members`' order


def definition_etag(stored: StoredDefinition) -> str:
    """Weak, over the id and `updated_at`. The store moves `updated_at` on every write, so the tag
    versions the members too; readiness is outside it, and it names no member."""
    version = f"{stored.definition_id}|{stored.updated_at}".encode()
    return f'W/"{hashlib.sha256(version).hexdigest()[:16]}"'


def environment_mismatches(
    definition: DefinitionInput, envs: Mapping[AccountId, Environment]
) -> tuple[AccountId, ...]:
    """Each member whose account is outside the definition's environment, enabled or not, in
    member order. A member whose environment `envs` lacks is outside too."""
    return tuple(
        m.account_id for m in definition.members if envs.get(m.account_id) != definition.environment
    )


def common_symbols(
    definition: DefinitionInput,
    scopes: Mapping[AccountId, SymbolScope],
    instruments: Iterable[Instrument],
) -> frozenset[Symbol]:
    """The listed, trading USDT perpetuals that every member's bound profile allows, through the
    sizer's gate (`SymbolScope.allows`: the allow side, where an empty list allows nothing, then
    the block list). Every member counts, enabled or not, so switching one on never empties a
    saved group's intersection. A member with no bound profile in `scopes` allows nothing."""
    bound = [scopes.get(m.account_id) for m in definition.members]
    return frozenset(
        i.symbol
        for i in instruments
        if is_trading_usdt_perpetual(i) and all(s is not None and s.allows(i) for s in bound)
    )


def stored_definition(record: port.DefinitionRecord) -> StoredDefinition:
    """A stored definition in the domain's terms. A row the model refuses (no member, more than
    `MAX_MEMBERS`, an account twice) is a schema drift: it fails closed as `AccountsError`, logged
    by id and error class alone, as the fired-group facade does."""
    row = record.definition
    try:
        members = tuple(
            DefinitionMember(account_id=AccountId(m.exchange_account_id), enabled=m.enabled)
            for m in record.members
        )
        definition = DefinitionInput(name=row.name, environment=row.env, members=members)
        created_at, updated_at = to_us(row.created_at), to_us(row.updated_at)
    except (ValueError, TypeError, DuplicateMember) as exc:
        structlog.get_logger(__name__).warning(
            "trade_group_definition.read_failed_closed",
            definition_id=str(row.id),
            error=type(exc).__name__,
        )
        raise AccountsError("stored trade group definition unreadable") from None
    accounts = tuple(
        MemberAccount(AccountId(m.exchange_account_id), m.account_env, m.account_enabled)
        for m in record.members
    )
    return StoredDefinition(row.id, definition, created_at, updated_at, accounts)


def new_definition(definition_id: UUID, definition: DefinitionInput) -> port.NewDefinition:
    """What the store inserts or sets. It takes no writer: the store stores its Owner scope's."""
    members = tuple(port.NewMember(m.account_id, m.enabled) for m in definition.members)
    return port.NewDefinition(
        id=definition_id, name=definition.name, env=definition.environment, members=members
    )


#: Each name the store refuses with, as 22 answers it: the error and the one name it holds.
_REFUSALS: Final[Mapping[str, tuple[type[AccountsError], str]]] = {
    "ux_tgd_name": (AccountConflictError, "ux_tgd_name"),
    "trade_group_definitions_pkey": (AccountConflictError, "trade_group_definitions_pkey"),
    "tgd_name": (AccountRuleError, "tgd_name"),
    "trg_tgdm_env": (AccountRuleError, "environment_mismatch"),
    "trg_tgd_write_once": (AccountRuleError, "write_once"),
    "trade_group_definition_members_exchange_account_id_fkey": (AccountNotFoundError, "account"),
    ACCOUNT_NOT_LIVE: (AccountNotFoundError, "account"),
}


def definition_error(exc: port.DefinitionStoreError) -> AccountsError:
    """The accounts error a store error answers as, chosen by its kind and name alone: a fresh one
    that holds a name and nothing of `exc` (C-12.6). A name the store never uses fails closed."""
    match exc:
        case port.DefinitionScopeDeniedError():
            return AccountScopeDeniedError()
        case port.DefinitionStaleError():
            return AccountVersionConflictError()
        case port.DefinitionConflictError(constraint=name) | port.DefinitionRuleError(rule=name):
            if name in _REFUSALS:
                kind, held = _REFUSALS[name]
                return kind(held)
    return AccountsError("store error")
