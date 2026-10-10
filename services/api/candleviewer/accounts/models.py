"""Domain models for the accounts module (M13), E27-T01.

Frozen pydantic v2 types. Ciphertext columns (`secret_enc`, `key_id_enc`, `enc_nonce`,
`dek_ref`) are deliberately absent: no model here can carry them (C-5.9, ADR-0009); only the
credential broker's internal row type reads them. `key_id_last4` is the only key-derived value.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from candleviewer.accounts.errors import WithdrawPermissionError


def _require_utc(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("timestamp must be timezone-aware (UTC)")
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
OptUtcDatetime = Annotated[datetime | None, AfterValidator(_require_utc)]

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class AccountKind(StrEnum):
    MAIN = "main"
    SUB = "sub"


class KeyStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    ROTATING = "rotating"
    REVOKED = "revoked"
    EXPIRED = "expired"
    INVALID = "invalid"


class ExchangeEnv(StrEnum):
    LIVE = "live"
    DEMO = "demo"
    TESTNET = "testnet"


class ExchangeAccount(BaseModel):
    """One `exchange_accounts` row (21-database-schema.md §3.2.1)."""

    model_config = _FROZEN

    id: UUID
    env: ExchangeEnv
    kind: AccountKind
    exchange_uid: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")]
    parent_account_id: UUID | None = None
    label: Annotated[str, Field(min_length=1)]
    colour_token: str = "accent.neutral"  # noqa: S105 -- design token name, not a credential
    is_enabled: bool = True
    trading_enabled: bool = False
    position_mode: Literal["one_way", "hedge"] = "one_way"
    margin_mode: Literal["cross", "isolated", "portfolio"] = "cross"
    account_type: Literal["UNIFIED"] = "UNIFIED"
    quote_ccy: Literal["USDT"] = "USDT"
    equity_cached_usd: Decimal | None = None
    equity_cached_at: OptUtcDatetime = None
    max_sub_accounts_hint: int = 5
    last_reconciled_at: OptUtcDatetime = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    deleted_at: OptUtcDatetime = None

    @model_validator(mode="after")
    def _parent_shape(self) -> ExchangeAccount:
        if (self.kind is AccountKind.MAIN) != (self.parent_account_id is None):
            raise ValueError("parent_account_id must be NULL iff kind is 'main'")
        if self.parent_account_id == self.id:
            raise ValueError("an account cannot be its own parent")
        return self


class PermissionSet(BaseModel):
    """Exchange-reported `permissions` object; `Withdraw` must be empty (C-2.8)."""

    model_config = ConfigDict(frozen=True, extra="allow")

    ContractTrade: tuple[str, ...] = ()
    Spot: tuple[str, ...] = ()
    Wallet: tuple[str, ...] = ()
    Options: tuple[str, ...] = ()
    Derivatives: tuple[str, ...] = ()
    Exchange: tuple[str, ...] = ()
    NFT: tuple[str, ...] = ()
    Withdraw: tuple[str, ...] = ()


class PermissionSnapshot(BaseModel):
    """`api_keys.permission_snapshot` (21-database-schema.md §3.2.2)."""

    model_config = _FROZEN

    fetched_at: UtcDatetime
    uid: str
    note: str = ""
    readOnly: int = 0
    permissions: PermissionSet
    ips: tuple[str, ...] = ()
    type: int = 1
    expiredAt: str | None = None

    @model_validator(mode="after")
    def _no_withdraw(self) -> PermissionSnapshot:
        if self.permissions.Withdraw:
            raise WithdrawPermissionError("key_withdraw_permission")
        return self


class ApiKeyMetadata(BaseModel):
    """Safe-to-serialise view of `api_keys`: no ciphertext, nonce or DEK handle."""

    model_config = _FROZEN

    id: UUID
    exchange_account_id: UUID
    label: Annotated[str, Field(min_length=1)]
    key_id_last4: Annotated[str, Field(pattern=r"^[A-Za-z0-9]{4}$")]
    kek_version: Annotated[int, Field(ge=1)] = 1
    permission_snapshot: PermissionSnapshot
    permission_snapshot_at: UtcDatetime
    can_trade: bool = False
    can_withdraw: Literal[False] = False
    can_transfer: bool = False
    read_only: bool = False
    status: KeyStatus = KeyStatus.PENDING
    expires_at: OptUtcDatetime = None
    last_used_at: OptUtcDatetime = None
    rotation_due_at: OptUtcDatetime = None
    created_at: UtcDatetime
    revoked_at: OptUtcDatetime = None

    @property
    def key_id_masked(self) -> str:
        """Only the tail is persisted; the first four characters never are."""
        return f"...{self.key_id_last4}"

    @model_validator(mode="after")
    def _readonly_excl(self) -> ApiKeyMetadata:
        if self.read_only and self.can_trade:
            raise ValueError("read_only and can_trade are mutually exclusive")
        return self


class ApiKeyRotation(BaseModel):
    """One `api_key_rotations` row (§3.2.3)."""

    model_config = _FROZEN

    id: UUID
    old_api_key_id: UUID
    new_api_key_id: UUID
    started_at: UtcDatetime
    validated_at: OptUtcDatetime = None
    cutover_at: OptUtcDatetime = None
    completed_at: OptUtcDatetime = None
    failed_at: OptUtcDatetime = None
    failure_reason: str | None = None
    grace_seconds: Annotated[int, Field(ge=0, le=86400)] = 900

    @model_validator(mode="after")
    def _shape(self) -> ApiKeyRotation:
        if self.old_api_key_id == self.new_api_key_id:
            raise ValueError("old and new key must differ")
        if self.completed_at is not None and self.failed_at is not None:
            raise ValueError("a rotation cannot be both completed and failed")
        return self
