"""Trade groups and their legs (E28-T01 #905; 24-internal-schemas.md Sec.9.1, M13).

`TradeGroup` and `TradeGroupLeg` mirror one `trade_groups` and one `trade_group_legs` row
(21-database-schema.md Sec.3.3.2, Sec.3.3.3) as `AccountProfile` mirrors its table: every column
is a field except two. `client_body_sha256`, the replay anchor's request fingerprint (G-6(b)),
stays in the M10 store, which compares it in SQL and never returns it. `profile_snapshot` is read
on demand by `leg_profile_snapshot`, which validates it as the `AccountProfile` the leg was sized
from and checks that it names the leg's account, profile and version (`tgl_snapshot`, SR-E28-07).
A read model refuses what its table refuses (the `tg_*` and `tgl_*` CHECKs; SR-E28-08) and
nothing stricter, so a stored row stays readable, plus a `float` anywhere (C2) and a value its
column would round, so a valid group or leg round-trips with `Decimal` equality.

`group_from_row`, `leg_from_row`, `group_values` and `leg_values` are the one adapter between the
models and the rows of the M10 port (`candleviewer.storage.repositories.trade_groups`): they rename
the columns (`GROUP_FIELD_OF`, `LEG_FIELD_OF`), map the column labels (`Buy`, `Market`,
`LastPrice`) to 24 Sec.1.2's (`buy`, `market`, `last`) and `timestamptz` to `TsUs`. No column is a
percent, so nothing is scaled.

The write models add what the database cannot state. `TradeGroupDraft` names its
`leg_failure_policy` (the column default is only 24 Sec.9.5's manual-ticket default), keeps
`algo_params` absent when `algo` is `none`, a `replay_sim` group paper, the rule ids to a `rule`
origin and `note` to 280 storable characters. A `LegDraft` is built from the one `AccountProfile`
it was sized from, which gives the leg its account, `account_profile_id`, `profile_version` and
snapshot, so they cannot drift (`tgl_snapshot`, the `tgl_profile_revision` key). `LegUpdate` and
`GroupUpdate` carry absolute values and reach no write-once, create-only or sized column (amending
those is E34-S03's). `TakeProfitLeg` and `TradeGroupAggregate` are values that nothing stores.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from candleviewer.accounts.profiles import AccountProfile, SizingMode, exact_sum, to_us
from candleviewer.domain.primitives import (
    AccountId,
    Environment,
    GroupId,
    RuleId,
    Side,
    Symbol,
    TsUs,
    UserId,
)
from candleviewer.domain.text import refuse_unstorable_text
from candleviewer.storage.repositories.accounts import AccountScope, OwnerScope
from candleviewer.storage.repositories.orders import require_money
from candleviewer.storage.repositories.trade_groups import (
    MAX_CODE_CHARS,
    NO_STOP_LEG_STATUSES,
    UNPROTECTED_LEG_STATUSES,
    AlgoKind,
    GroupOrigin,
    GroupPatch,
    LegFailurePolicy,
    LegPatch,
    LegSnapshotRow,
    LegStatus,
    NewTradeGroup,
    NewTradeGroupLeg,
    OrderSide,
    TradeGroupLegRow,
    TradeGroupRecord,
    TradeGroupRow,
    TradeGroupStatus,
    UnprotectedLegRow,
)
from candleviewer.storage.repositories.trade_groups import EntryType as ColumnEntryType
from candleviewer.storage.repositories.trade_groups import TriggerBy as ColumnTriggerBy

_FROZEN = ConfigDict(frozen=True, extra="forbid")
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)

#: 24 Sec.1.2's labels for the columns' `Market`, `Limit` and `Conditional` (`tg_entrytype`).
EntryType = Literal["market", "limit", "conditional"]
#: 24 Sec.1.2's labels for the columns' `LastPrice`, `MarkPrice` and `IndexPrice` (`tg_trigby`).
TriggerBy = Literal["last", "mark", "index"]
#: A `jsonb` value as these models hold it. Strict, so a float, a `Decimal` or `2.0` is refused
#: and `True` stays a bool: a fraction travels as its string (C2), as `model_dump(mode="json")`
#: renders a `Decimal`.
type JsonValue = (
    StrictBool | StrictInt | StrictStr | list[JsonValue] | dict[StrictStr, JsonValue] | None
)
type JsonObject = dict[StrictStr, JsonValue]

#: The most characters a group's `note` may hold (22 `CreateTradeGroupRequest.note`).
MAX_NOTE_CHARS: Final = 280


def _refuse_float(value: object) -> object:
    """C2, as `risk.models` (24 Sec.8.11): a float has already rounded, so it is refused, never
    converted."""
    if isinstance(value, float):
        raise ValueError("money is a Decimal or a decimal string, never a float")
    return value


def _fit(precision: int, scale: int) -> Callable[[Decimal], Decimal]:
    """A validator keeping a value that numeric(precision, scale) holds exactly
    (`orders.require_money`: finite, nothing rounded); the column would round or refuse any
    other."""

    def check(value: Decimal) -> Decimal:
        require_money("value", value, precision, scale)
        return value

    return check


#: Money in a numeric(38,18) column (`OMS_MONEY_COMMENT`).
Money = Annotated[Decimal, BeforeValidator(_refuse_float), AfterValidator(_fit(38, 18))]
#: `resolved_leverage`: numeric(10,2), 1..100 (`tgl_lev`).
Leverage = Annotated[
    Decimal, BeforeValidator(_refuse_float), Field(ge=1, le=100), AfterValidator(_fit(10, 2))
]
#: A 24 Sec.8.6 taxonomy code as a writer sets it: 1..64 characters (the store redacts it too).
Code = Annotated[str, Field(min_length=1, max_length=MAX_CODE_CHARS)]
#: A value that is never stored, so bound to no column; it still refuses a float.
Figure = Annotated[Decimal, BeforeValidator(_refuse_float)]
#: A group's note: at most `MAX_NOTE_CHARS` characters `text` can store (no U+0000).
Note = Annotated[str, Field(max_length=MAX_NOTE_CHARS), AfterValidator(refuse_unstorable_text)]
#: The request fingerprint `sha256_hex` holds: 64 lower-case hex digits.
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

#: 24 Sec.1.2's labels to the columns' (`tg_side`, `tg_entrytype`, `tg_trigby`), each a bijection
#: with its inverse below (pinned by a unit test).
_SIDE: Final[Mapping[Side, OrderSide]] = {"buy": "Buy", "sell": "Sell"}
_ENTRY: Final[Mapping[EntryType, ColumnEntryType]] = {
    "market": "Market",
    "limit": "Limit",
    "conditional": "Conditional",
}
_TRIGGER: Final[Mapping[TriggerBy, ColumnTriggerBy]] = {
    "last": "LastPrice",
    "mark": "MarkPrice",
    "index": "IndexPrice",
}
_SIDE_OF: Final[Mapping[OrderSide, Side]] = {"Buy": "buy", "Sell": "sell"}
_ENTRY_OF: Final[Mapping[ColumnEntryType, EntryType]] = {
    "Market": "market",
    "Limit": "limit",
    "Conditional": "conditional",
}
_TRIGGER_OF: Final[Mapping[ColumnTriggerBy, TriggerBy]] = {
    "LastPrice": "last",
    "MarkPrice": "mark",
    "IndexPrice": "index",
}


def from_us(us: TsUs) -> datetime:
    """The UTC-aware datetime of epoch microseconds: the inverse of `profiles.to_us`, exactly
    (integer arithmetic, no float rounding)."""
    return _EPOCH + timedelta(microseconds=us)


def _check_entry(
    entry_type: EntryType,
    entry_price: Decimal | None,
    trigger_price: Decimal | None,
    trigger_by: TriggerBy | None,
) -> None:
    """`tg_limit_px` and `tg_cond_px`, NULL-safe as the CHECKs are."""
    if entry_type == "limit" and not (entry_price is not None and entry_price > 0):
        raise ValueError("a limit group needs an entry_price above zero (tg_limit_px)")
    if entry_type == "conditional" and not (
        trigger_price is not None and trigger_price > 0 and trigger_by is not None
    ):
        raise ValueError(
            "a conditional group needs a trigger_price above zero and a trigger_by (tg_cond_px)"
        )


def _check_stop(status: LegStatus, resolved_sl_price: Decimal | None) -> None:
    """`tgl_sl_px`: only a rejected, cancelled or failed leg may go without a native stop."""
    if status not in NO_STOP_LEG_STATUSES and not (
        resolved_sl_price is not None and resolved_sl_price > 0
    ):
        raise ValueError("a live leg needs a resolved_sl_price above zero (tgl_sl_px)")


def _check_snapshot(
    profile: AccountProfile, account_id: UUID, profile_id: UUID | None, version: int
) -> None:
    """`tgl_snapshot`: the snapshot names its leg's account and version, and its profile while
    the leg still references one."""
    if (
        profile.account_id != account_id
        or profile.version != version
        or (profile_id is not None and profile.profile_id != profile_id)
    ):
        raise ValueError(
            "the profile snapshot names another account, profile or version than its leg "
            "(tgl_snapshot)"
        )


# -- persisted read models -------------------------------------------------------------------


class TradeGroup(BaseModel):
    """24 Sec.9.1: one `trade_groups` row (21 Sec.3.3.2), every column but `client_body_sha256`.
    `client_group_ref`, `algo_params` and `note` are hidden from `repr` (P1 or the anchor).
    `leg_failure_policy` is write-once (`tg_policy`, `trg_tg_write_once`): B2, the unwind and a
    restart read it from here."""

    model_config = _FROZEN

    group_id: GroupId
    client_group_ref: UUID = Field(repr=False)
    definition_id: UUID | None
    environment: Environment
    symbol: Symbol
    side: Side
    status: TradeGroupStatus
    leg_failure_policy: LegFailurePolicy
    algo: AlgoKind
    algo_params: JsonObject | None = Field(repr=False)
    note: str | None = Field(repr=False)
    origin: GroupOrigin
    rule_id: RuleId | None
    rule_run_id: UUID | None
    requested_qty_mode: SizingMode
    requested_qty_value: Money | None
    entry_type: EntryType
    entry_price: Money | None
    trigger_price: Money | None
    trigger_by: TriggerBy | None
    sl_price_hint: Money | None
    tp_price_hint: Money | None
    is_paper: bool
    submitted_at: TsUs | None
    opened_at: TsUs | None
    closed_at: TsUs | None
    created_by: UserId
    created_at: TsUs
    updated_at: TsUs

    @model_validator(mode="after")
    def _rules(self) -> TradeGroup:
        _check_entry(self.entry_type, self.entry_price, self.trigger_price, self.trigger_by)
        if (
            self.closed_at is not None
            and self.opened_at is not None
            and self.closed_at < self.opened_at
        ):
            raise ValueError("closed_at is before opened_at (tg_times)")
        return self


class TradeGroupLeg(BaseModel):
    """24 Sec.9.1: one `trade_group_legs` row (21 Sec.3.3.3), every column but
    `profile_snapshot`. `account_profile_id` is `None` only once its profile row is gone (the key
    is `ON DELETE SET NULL`; the snapshot keeps the id). The rejection texts are as stored,
    redacted, and hidden from `repr`; no CHECK bounds them, so neither does this model (a code
    the model refused would fail the whole C-2.6 scan closed)."""

    model_config = _FROZEN

    leg_id: UUID
    group_id: GroupId
    account_id: AccountId
    account_profile_id: UUID | None
    profile_version: Annotated[int, Field(ge=1)]
    status: LegStatus
    sequence_no: Annotated[int, Field(ge=0, le=100)]
    target_qty: Annotated[Money, Field(gt=0)]
    filled_qty: Annotated[Money, Field(ge=0)]
    avg_entry_price: Money | None
    avg_exit_price: Money | None
    resolved_leverage: Leverage
    resolved_sl_price: Money | None
    resolved_tp_price: Money | None
    native_sl_confirmed: bool
    native_sl_confirmed_at: TsUs | None
    risk_usd: Money | None
    realised_pnl: Money
    fees_paid: Annotated[Money, Field(ge=0)]
    rejection_code: str | None = Field(repr=False)
    rejection_message: str | None = Field(repr=False)
    submitted_at: TsUs | None
    closed_at: TsUs | None
    created_at: TsUs
    updated_at: TsUs

    @model_validator(mode="after")
    def _rules(self) -> TradeGroupLeg:
        if self.filled_qty > self.target_qty:
            raise ValueError("filled_qty is above target_qty (tgl_filled_rng)")
        if self.native_sl_confirmed and self.native_sl_confirmed_at is None:
            raise ValueError("a confirmed native stop needs native_sl_confirmed_at (tgl_sl_conf)")
        _check_stop(self.status, self.resolved_sl_price)
        return self

    @property
    def unprotected(self) -> bool:
        """An open position whose native stop is not confirmed (C-2.6): the `ix_tgl_no_sl`
        predicate the safety monitor reads."""
        return self.status in UNPROTECTED_LEG_STATUSES and not self.native_sl_confirmed


# -- write models ------------------------------------------------------------------------------


class TradeGroupDraft(BaseModel):
    """A group to create, every writer-set column. `client_group_ref` is the route's
    `UUID(Idempotency-Key)`, `client_body_sha256` the request fingerprint (G-6(b)) and
    `created_by` the principal, or the rule owner (M15), never a client value. Stricter than the
    table: `algo_params` is absent when `algo` is `none`, a `replay_sim` group is paper, rule ids
    come with a `rule` origin only, and `note` holds at most `MAX_NOTE_CHARS` storable
    characters. Every value fits its column (`group_values` runs at validation).

    `leg_failure_policy` has no default: the column's (`best_effort`) is only 24 Sec.9.5's
    manual-ticket default, so a draft never takes it by omission. 24 Sec.9.5's default for each
    origin (`abort_on_first` for a rule-originated group) is the fan-out's to apply (E34-S02)."""

    model_config = _FROZEN

    group_id: GroupId
    client_group_ref: UUID = Field(repr=False)
    client_body_sha256: Sha256Hex = Field(repr=False)
    created_by: UserId
    environment: Environment
    symbol: Symbol
    side: Side
    status: TradeGroupStatus
    leg_failure_policy: LegFailurePolicy
    algo: AlgoKind
    algo_params: JsonObject | None = Field(repr=False)
    note: Note | None = Field(repr=False)
    origin: GroupOrigin
    rule_id: RuleId | None
    rule_run_id: UUID | None
    definition_id: UUID | None
    requested_qty_mode: SizingMode
    requested_qty_value: Money | None
    entry_type: EntryType
    entry_price: Money | None
    trigger_price: Money | None
    trigger_by: TriggerBy | None
    sl_price_hint: Money | None
    tp_price_hint: Money | None
    is_paper: bool

    @model_validator(mode="after")
    def _rules(self) -> TradeGroupDraft:
        _check_entry(self.entry_type, self.entry_price, self.trigger_price, self.trigger_by)
        if self.algo == "none" and self.algo_params is not None:
            raise ValueError("algo none takes no algo_params")
        if self.origin == "replay_sim" and not self.is_paper:
            raise ValueError("a replay_sim group is a paper group")
        if (self.origin == "rule") != (self.rule_id is not None):
            raise ValueError("rule_id is set exactly when the origin is rule")
        if self.rule_run_id is not None and self.origin != "rule":
            raise ValueError("rule_run_id is set only when the origin is rule")
        group_values(self)  # every value fits its column; algo_params renders (render_json)
        return self


class LegDraft(BaseModel):
    """A leg to create with its group, built from the one `AccountProfile` it was sized from: the
    profile gives the leg its account, `account_profile_id`, `profile_version` and snapshot
    (`leg_values`), so they cannot drift. A leg that is not rejected, cancelled or failed has a
    native stop above zero (`tgl_sl_px`). The rejection texts are redacted by the store before
    they are written."""

    model_config = _FROZEN

    leg_id: UUID
    profile: AccountProfile
    status: LegStatus
    sequence_no: Annotated[int, Field(ge=0, le=100)]
    target_qty: Annotated[Money, Field(gt=0)]
    resolved_leverage: Leverage
    resolved_sl_price: Money | None
    resolved_tp_price: Money | None
    risk_usd: Money | None
    rejection_code: Code | None = Field(repr=False)
    rejection_message: str | None = Field(repr=False)

    @model_validator(mode="after")
    def _rules(self) -> LegDraft:
        _check_stop(self.status, self.resolved_sl_price)
        leg_values(self)  # the snapshot renders (render_json) and names its leg (tgl_snapshot)
        return self


class LegUpdate(BaseModel):
    """What a leg update sets, as absolute values: `None` leaves a field as it is, and at least
    one field is set. `submitted_at` is set once (the store keeps a time already stored). A
    confirmed native stop needs its time (`tgl_sl_conf`). No write-once, create-only or sized
    column is here: amending `resolved_*`, `target_qty`, `risk_usd` or `sequence_no` is
    E34-S03's."""

    model_config = _FROZEN

    status: LegStatus | None = None
    filled_qty: Annotated[Money, Field(ge=0)] | None = None
    avg_entry_price: Money | None = None
    avg_exit_price: Money | None = None
    realised_pnl: Money | None = None
    fees_paid: Annotated[Money, Field(ge=0)] | None = None
    native_sl_confirmed: bool | None = None
    native_sl_confirmed_at: TsUs | None = None
    rejection_code: Code | None = Field(default=None, repr=False)
    rejection_message: str | None = Field(default=None, repr=False)
    submitted_at: TsUs | None = None
    closed_at: TsUs | None = None

    @model_validator(mode="after")
    def _rules(self) -> LegUpdate:
        if all(getattr(self, name) is None for name in type(self).model_fields):
            raise ValueError("a leg update sets at least one field")
        if self.native_sl_confirmed and self.native_sl_confirmed_at is None:
            raise ValueError("a confirmed native stop needs native_sl_confirmed_at (tgl_sl_conf)")
        return self


class GroupUpdate(BaseModel):
    """What a group update sets, as absolute values: `None` leaves a field as it is, and at least
    one field is set. `submitted_at` and `opened_at` are set once (the store keeps a time already
    stored), and `closed_at` is not before `opened_at` when both are given (`tg_times`)."""

    model_config = _FROZEN

    status: TradeGroupStatus | None = None
    submitted_at: TsUs | None = None
    opened_at: TsUs | None = None
    closed_at: TsUs | None = None

    @model_validator(mode="after")
    def _rules(self) -> GroupUpdate:
        if all(getattr(self, name) is None for name in type(self).model_fields):
            raise ValueError("a group update sets at least one field")
        if (
            self.closed_at is not None
            and self.opened_at is not None
            and self.closed_at < self.opened_at
        ):
            raise ValueError("closed_at is before opened_at (tg_times)")
        return self


# -- values: never stored --------------------------------------------------------------------


class TakeProfitLeg(BaseModel):
    """A resolved `TakeProfitRung` (24 Sec.9.2) on a leg: an absolute `price` and the fraction of
    the leg's filled size it takes. Always reduce-only: a take-profit that could add exposure is
    refused. Nothing stores it; `take_profit_ladder` checks a ladder's sum."""

    model_config = _FROZEN

    price: Annotated[Money, Field(gt=0)]
    qty_pct: Annotated[Decimal, BeforeValidator(_refuse_float), Field(gt=0, le=1)]
    reduce_only: Literal[True] = True


def take_profit_ladder(legs: Iterable[TakeProfitLeg]) -> tuple[TakeProfitLeg, ...]:
    """The rungs as a tuple; `ValueError` when their `qty_pct` sum to more than the whole leg,
    summed exactly (`profiles.exact_sum`: a rounded sum could pass `<= 1` when the exact one does
    not)."""
    ladder = tuple(legs)
    if exact_sum(leg.qty_pct for leg in ladder) > 1:
        raise ValueError("the take-profit ladder takes more than the whole leg")
    return ladder


class TradeGroupAggregate(BaseModel):
    """24 Sec.9.1: a group's totals, E34-T01's output, recomputed on every execution or position
    event; nothing stores it. `target_qty` and `filled_qty` sum the legs';
    `unrealised_pnl` comes from positions, `total_funding` from funding executions and
    `legs_skipped` from the fan-out outcome (a skipped account has no leg row). Every number is a
    `Decimal` that refuses a float; NaN and the infinities are refused."""

    model_config = _FROZEN

    target_qty: Annotated[Figure, Field(ge=0)]
    filled_qty: Annotated[Figure, Field(ge=0)]
    weighted_avg_entry: Figure | None
    total_notional: Annotated[Figure, Field(ge=0)]
    unrealised_pnl: Figure
    realised_pnl: Figure
    total_fees: Annotated[Figure, Field(ge=0)]
    total_funding: Figure
    legs_ok: Annotated[int, Field(ge=0)]
    legs_failed: Annotated[int, Field(ge=0)]
    legs_skipped: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _rules(self) -> TradeGroupAggregate:
        if self.filled_qty > self.target_qty:
            raise ValueError("filled_qty is above target_qty")
        if (self.weighted_avg_entry is None) != (self.filled_qty == 0):
            raise ValueError("weighted_avg_entry is set exactly when something filled")
        if self.weighted_avg_entry is not None and self.weighted_avg_entry <= 0:
            raise ValueError("weighted_avg_entry is above zero")
        return self


# -- containers --------------------------------------------------------------------------------


class TradeGroupWithLegs(BaseModel):
    """A group with its legs, in fan-out order `(sequence_no, leg_id)`; every leg is the group's
    and listed once."""

    model_config = _FROZEN

    group: TradeGroup
    legs: tuple[TradeGroupLeg, ...]

    @field_validator("legs")
    @classmethod
    def _in_fan_out_order(cls, legs: tuple[TradeGroupLeg, ...]) -> tuple[TradeGroupLeg, ...]:
        return tuple(sorted(legs, key=lambda leg: (leg.sequence_no, leg.leg_id)))

    @model_validator(mode="after")
    def _rules(self) -> TradeGroupWithLegs:
        if any(leg.group_id != self.group.group_id for leg in self.legs):
            raise ValueError("a leg belongs to another group")
        if len({leg.leg_id for leg in self.legs}) != len(self.legs):
            raise ValueError("a leg is listed twice")
        return self

    @property
    def account_ids(self) -> tuple[AccountId, ...]:
        """24 Sec.9.1's `account_ids`: the legs' accounts in fan-out order."""
        return tuple(leg.account_id for leg in self.legs)


class ScopedTradeGroup(BaseModel):
    """A group as a principal-scoped read serves it. `shows_private_fields` is true for an Owner
    or the group's creator only; the projection (E28-T05) drops `created_by`, `note` and
    `client_group_ref` otherwise (SR-E28-21)."""

    model_config = _FROZEN

    record: TradeGroupWithLegs
    shows_private_fields: bool


class LegWithProfile(BaseModel):
    """A leg with the `AccountProfile` it was sized from (its snapshot, SR-E28-07), which names
    the leg's account, profile and version (`tgl_snapshot`)."""

    model_config = _FROZEN

    leg: TradeGroupLeg
    profile: AccountProfile

    @model_validator(mode="after")
    def _rules(self) -> LegWithProfile:
        leg = self.leg
        _check_snapshot(self.profile, leg.account_id, leg.account_profile_id, leg.profile_version)
        return self


class UnprotectedLeg(BaseModel):
    """A leg whose position is open without a confirmed native stop (C-2.6), with what the alarm
    needs of its group."""

    model_config = _FROZEN

    leg: TradeGroupLeg
    symbol: Symbol
    side: Side
    environment: Environment
    is_paper: bool


@dataclass(frozen=True, slots=True)
class GroupReplay:
    """The caller's `Idempotency-Key` already anchors this group with the same request
    fingerprint: the route answers it from current state under current grants (SR-E29-07)."""

    group_id: GroupId


# -- the adapter -------------------------------------------------------------------------------

#: Column to field where they differ: the id fields keep 24 Sec.9.1's role names.
_GROUP_RENAMES: Final[Mapping[str, str]] = {
    "id": "group_id",
    "env": "environment",
    "intent_note": "note",
    "origin_rule_id": "rule_id",
    "origin_rule_run_id": "rule_run_id",
}
_LEG_RENAMES: Final[Mapping[str, str]] = {
    "id": "leg_id",
    "trade_group_id": "group_id",
    "exchange_account_id": "account_id",
}
#: `trade_groups` column to `TradeGroup` field: every column but `client_body_sha256`.
GROUP_FIELD_OF: Final[Mapping[str, str]] = {
    f.name: _GROUP_RENAMES.get(f.name, f.name) for f in fields(TradeGroupRow)
}
#: `trade_group_legs` column to `TradeGroupLeg` field: every column but `profile_snapshot`.
LEG_FIELD_OF: Final[Mapping[str, str]] = {
    f.name: _LEG_RENAMES.get(f.name, f.name) for f in fields(TradeGroupLegRow)
}


def _domain(value: object) -> object:
    """A stored value in domain units: a time is `TsUs`; anything else is unchanged."""
    return to_us(value) if isinstance(value, datetime) else value


def _stored(us: TsUs | None) -> datetime | None:
    return None if us is None else from_us(us)


def group_from_row(row: TradeGroupRow) -> TradeGroup:
    """The domain model of a stored group. A row the model refuses raises `ValueError`
    (`pydantic.ValidationError`) and an unknown label `KeyError`; either is a schema drift."""
    values = {GROUP_FIELD_OF[f.name]: _domain(getattr(row, f.name)) for f in fields(row)}
    values["side"] = _SIDE_OF[row.side]
    values["entry_type"] = _ENTRY_OF[row.entry_type]
    values["trigger_by"] = None if row.trigger_by is None else _TRIGGER_OF[row.trigger_by]
    return TradeGroup.model_validate(values)


def leg_from_row(row: TradeGroupLegRow) -> TradeGroupLeg:
    """The domain model of a stored leg; a row the model refuses raises `ValueError`."""
    return TradeGroupLeg.model_validate(
        {LEG_FIELD_OF[f.name]: _domain(getattr(row, f.name)) for f in fields(row)}
    )


def record_from_rows(record: TradeGroupRecord) -> TradeGroupWithLegs:
    """A stored group with its legs."""
    return TradeGroupWithLegs(
        group=group_from_row(record.group), legs=tuple(leg_from_row(leg) for leg in record.legs)
    )


def unprotected_leg_from_row(row: UnprotectedLegRow) -> UnprotectedLeg:
    """A leg the C-2.6 alarm lists, with its group's symbol, side, environment and mode."""
    return UnprotectedLeg(
        leg=leg_from_row(row.leg),
        symbol=row.symbol,
        side=_SIDE_OF[row.side],
        environment=row.env,
        is_paper=row.is_paper,
    )


def group_values(draft: TradeGroupDraft) -> NewTradeGroup:
    """The columns a writer sets for `draft`, in stored units (the inverse of `group_from_row`).
    `client_group_ref` is `str(UUID)`, the canonical form `tg_ref_fmt` requires."""
    return NewTradeGroup(
        id=draft.group_id,
        client_group_ref=str(draft.client_group_ref),
        client_body_sha256=draft.client_body_sha256,
        created_by=draft.created_by,
        env=draft.environment,
        symbol=draft.symbol,
        side=_SIDE[draft.side],
        status=draft.status,
        leg_failure_policy=draft.leg_failure_policy,
        algo=draft.algo,
        algo_params=draft.algo_params,
        intent_note=draft.note,
        origin=draft.origin,
        origin_rule_id=draft.rule_id,
        origin_rule_run_id=draft.rule_run_id,
        definition_id=draft.definition_id,
        requested_qty_mode=draft.requested_qty_mode,
        requested_qty_value=draft.requested_qty_value,
        entry_type=_ENTRY[draft.entry_type],
        entry_price=draft.entry_price,
        trigger_price=draft.trigger_price,
        trigger_by=None if draft.trigger_by is None else _TRIGGER[draft.trigger_by],
        sl_price_hint=draft.sl_price_hint,
        tp_price_hint=draft.tp_price_hint,
        is_paper=draft.is_paper,
    )


def leg_values(draft: LegDraft) -> NewTradeGroupLeg:
    """The columns a writer sets for `draft`. The account, `account_profile_id`,
    `profile_version` and snapshot all come from `draft.profile`; the snapshot is its
    `model_dump(mode="json")` (decimals and ids as strings, never a float)."""
    profile = draft.profile
    return NewTradeGroupLeg(
        id=draft.leg_id,
        exchange_account_id=profile.account_id,
        account_profile_id=profile.profile_id,
        profile_version=profile.version,
        profile_snapshot=profile.model_dump(mode="json"),
        status=draft.status,
        sequence_no=draft.sequence_no,
        target_qty=draft.target_qty,
        resolved_leverage=draft.resolved_leverage,
        resolved_sl_price=draft.resolved_sl_price,
        resolved_tp_price=draft.resolved_tp_price,
        risk_usd=draft.risk_usd,
        rejection_code=draft.rejection_code,
        rejection_message=draft.rejection_message,
    )


def leg_patch(update: LegUpdate) -> LegPatch:
    """The columns a leg update sets, in stored units."""
    return LegPatch(
        status=update.status,
        filled_qty=update.filled_qty,
        avg_entry_price=update.avg_entry_price,
        avg_exit_price=update.avg_exit_price,
        native_sl_confirmed=update.native_sl_confirmed,
        native_sl_confirmed_at=_stored(update.native_sl_confirmed_at),
        realised_pnl=update.realised_pnl,
        fees_paid=update.fees_paid,
        rejection_code=update.rejection_code,
        rejection_message=update.rejection_message,
        submitted_at=_stored(update.submitted_at),
        closed_at=_stored(update.closed_at),
    )


def group_patch(update: GroupUpdate) -> GroupPatch:
    """The columns a group update sets, in stored units."""
    return GroupPatch(
        status=update.status,
        submitted_at=_stored(update.submitted_at),
        opened_at=_stored(update.opened_at),
        closed_at=_stored(update.closed_at),
    )


def leg_profile_snapshot(row: LegSnapshotRow) -> AccountProfile:
    """The `AccountProfile` a leg was sized from, validated from its stored snapshot (about
    0.15 ms, so only on demand). `ValueError` when the snapshot is not a valid profile or names
    another account, profile or version than its leg (`tgl_snapshot`)."""
    profile = AccountProfile.model_validate(row.profile_snapshot)
    leg = row.leg
    _check_snapshot(profile, leg.exchange_account_id, leg.account_profile_id, leg.profile_version)
    return profile


def shows_private_fields(scope: AccountScope, group: TradeGroup) -> bool:
    """SR-E28-21: an Owner, or the group's creator, sees its `created_by`, `note` and
    `client_group_ref`; nobody else does."""
    return isinstance(scope, OwnerScope) or scope.user_id == group.created_by
