"""Domain models for the risk module (M17), E39-T02.

Frozen pydantic v2 types for the state E39 persists (`docs/plan/21-database-schema.md` §3.11)
and the evaluator's verdict, documented in `docs/plan/24-internal-schemas.md` §8.11. Each
validator mirrors a CHECK of the table it reads, so a model refuses what the database refuses.
Money and measured values are `Decimal`, never `float`; every timestamp is timezone-aware UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def _require_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware (UTC)")
    return value.astimezone(UTC)


def _require_text(value: str) -> str:
    if len(value.strip()) < 3:
        raise ValueError("a reason needs at least 3 non-blank characters (rl_text, kss_reason)")
    return value


def _refuse_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("money and measured values are Decimal or a decimal string, never float")
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
OptUtcDatetime = Annotated[datetime | None, AfterValidator(_require_utc)]
#: The bounds of `rl_text` and `kss_reason`, and of the contract's `reason` (3..280).
Reason = Annotated[str, Field(min_length=3, max_length=280), AfterValidator(_require_text)]
#: `numeric(38,18)`: at most 20 whole digits and 18 places, so a value the column would refuse never
#: reaches it. `Field` precedes the validator: after a `BeforeValidator` pydantic checks digits and
#: places apart, and 21 whole digits pass. A writer quantizes a computed figure to 18 places first,
#: where the column would round.
Amount = Annotated[Decimal, Field(max_digits=38, decimal_places=18), BeforeValidator(_refuse_float)]
#: A verdict's figure: any finite `Decimal` (NaN and the infinities are refused). It is never
#: persisted, so it is not bounded to a column.
Figure = Annotated[Decimal, BeforeValidator(_refuse_float)]

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class LockoutReason(StrEnum):
    """`risk_lockouts.reason`, the contract's `RiskSummary.accounts[].lockout.reason`."""

    DAILY_LOSS = "daily_loss"
    CONSECUTIVE_LOSSES = "consecutive_losses"
    MAX_POSITIONS = "max_positions"
    MANUAL = "manual"


class RiskRefusal(StrEnum):
    """Why the gate refused an order (`RiskDecision.code`, E39-T01)."""

    RISK_LIMIT_BREACHED = "risk_limit_breached"
    ACCOUNT_LOCKED = "account_locked"
    TRADING_DISABLED = "trading_disabled"
    RISK_STATE_UNAVAILABLE = "risk_state_unavailable"
    SYMBOL_NOT_ALLOWED = "symbol_not_allowed"


class KillSwitchScope(StrEnum):
    """`kill_switch_state.scope`, the contract's `KillSwitch.scope`."""

    GLOBAL = "global"
    ACCOUNTS = "accounts"


class LockoutActions(BaseModel):
    """`risk_lockouts.actions_taken`: what the lockout did when it opened."""

    model_config = _FROZEN

    orders_cancelled: int = Field(default=0, ge=0)
    positions_flattened: int = Field(default=0, ge=0)


class LockoutState(BaseModel):
    """One `risk_lockouts` row: a lockout, active until `released_at` is set."""

    model_config = _FROZEN

    id: UUID
    exchange_account_id: UUID
    user_id: UUID | None = None  # None: the whole account; set: one manager
    reason: LockoutReason
    threshold: Amount | None = None
    actual_value: Amount | None = None
    since: UtcDatetime
    until: OptUtcDatetime = None  # absolute end (B20); None: never released by a clock
    released_at: OptUtcDatetime = None
    released_by: UUID | None = None  # with release_reason: a person's release
    release_reason: Reason | None = None
    actions_taken: LockoutActions = LockoutActions()

    @model_validator(mode="after")
    def _times_and_release_agree(self) -> Self:
        if self.reason is LockoutReason.MANUAL and self.until is not None:
            raise ValueError("a manual lockout is never released by a clock (rl_manual)")
        if self.until is not None and self.until <= self.since:
            raise ValueError("until must be after since (rl_until)")
        attributed = self.released_by is not None and self.release_reason is not None
        unattributed = self.released_by is None and self.release_reason is None
        if self.released_at is None:
            if not unattributed:
                raise ValueError("a releaser or reason needs a release time (rl_release)")
        elif self.released_at < self.since:
            raise ValueError("released_at must not precede since (rl_released)")
        elif not attributed and not (
            unattributed and self.until is not None and self.released_at >= self.until
        ):
            raise ValueError(
                "a release is a person's (releaser and reason) or the clock's at a stored end "
                "(rl_release)"
            )
        return self

    @property
    def is_active(self) -> bool:
        return self.released_at is None


class KillSwitchOptions(BaseModel):
    """`kill_switch_state.options`: the contract's `SetKillSwitchRequest` options, its defaults."""

    model_config = _FROZEN

    cancel_open_orders: bool = True
    flatten_positions: bool = False
    disarm_rules: bool = True


class KillSwitchState(BaseModel):
    """One `kill_switch_state` row: the `global` target or one account."""

    model_config = _FROZEN

    id: UUID
    scope: KillSwitchScope
    exchange_account_id: UUID | None = None
    engaged: bool
    engaged_at: OptUtcDatetime = None
    engaged_by: UUID | None = None  # None on an engaged row: an automatic engagement
    reason: Reason | None = None
    options: KillSwitchOptions = KillSwitchOptions()
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def _target_and_engagement_agree(self) -> Self:
        if (self.scope is KillSwitchScope.GLOBAL) != (self.exchange_account_id is None):
            raise ValueError(
                "the global row names no account; an account row names one (kss_target)"
            )
        if self.engaged and (self.engaged_at is None or self.reason is None):
            raise ValueError("an engaged row carries its time and reason (kss_engaged)")
        return self


class RiskDecision(BaseModel):
    """The gate's verdict on one order: allowed, or refused with one `RiskRefusal`.

    `message` names only the caller's own figures; `cap`, `limit` and `actual` say which limit
    refused and by how much (E39-T01).
    """

    model_config = _FROZEN

    allowed: bool
    code: RiskRefusal | None = None
    message: str = ""
    cap: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")
    limit: Figure | None = None
    actual: Figure | None = None
    evaluated_at: UtcDatetime

    @model_validator(mode="after")
    def _verdict_is_one_of_two_shapes(self) -> Self:
        if self.allowed != (self.code is None):
            raise ValueError("an allowed decision has no code; a refusal has exactly one")
        if self.allowed and (
            self.cap is not None or self.limit is not None or self.actual is not None
        ):
            raise ValueError("an allowed decision names no cap")
        return self
