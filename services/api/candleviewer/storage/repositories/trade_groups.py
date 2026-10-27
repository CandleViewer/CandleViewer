"""Driver-free port for trade groups and their legs (E28-T01 #905; 21-database-schema.md
Sec.3.3.2-3.3.3, M10).

Stdlib only, with the sibling ports `orders`, `accounts` and `exchange_payload`, none of which
imports a driver: M13 `accounts` maps these rows to the 24-internal-schemas.md Sec.9.1 models
(`candleviewer.accounts.trade_groups`), and M20 `journal` may read `LegSnapshotRow` as it stands.
`trade_groups_sqlalchemy.py` is the Postgres implementation. Values use the column vocabulary
(`'Buy'`, `'Market'`, `'LastPrice'`) and stored units: money is a `Decimal` its column holds
exactly (`orders.require_money`), a time an aware `datetime`, and a `jsonb` value a `JsonObject`
with no float (a `Decimal` travels as its string, as `model_dump(mode="json")` renders it).

Two columns are never read with a row: `client_body_sha256`, the replay anchor's request
fingerprint (G-6(b), SR-E29-07), which the store compares in SQL and never returns, and
`profile_snapshot` (SR-E28-07), which only `load_leg` returns. The anchor is read only with its
creator, `(created_by, client_group_ref)`, so another user's ref reads as missing.

`TradeGroupStore` is the system surface: it takes no principal and no route reaches it (an
architecture test pins its callers, C-12.4); the OMS, the lifecycle and the safety monitor call it
after admission. `create_group` writes a group with all its legs in one transaction, re-checks
under share locks that the definition, every leg account and every leg profile at its
`profile_version` are live (SR-E28-15), and awaits the caller's write-ahead record (C-2.9) before
the commit. No update reaches a write-once or create-only column (`WRITE_ONCE_GROUP_COLUMNS`,
`WRITE_ONCE_LEG_COLUMNS`, `CREATE_ONLY_GROUP_COLUMNS`): an update sets only the columns of its
patch (`GROUP_PATCH_COLUMNS`, `LEG_PATCH_COLUMNS`). `list_open_groups` and
`list_unprotected_legs` filter no soft delete, so the C-2.6 alarm sees every open leg.
`TradeGroupReads` is the principal-scoped read, SR-051 in SQL: an Owner sees every group, anyone
else a group that has a leg and whose every leg account is live and granted to them (SR-E28-21),
and every other group reads as missing.

A refusal is mapped by its constraint name, never by its message or DETAIL, which repeats the
failing row, and no error here carries a value. The store caps each statement as the order store
does, but not opening a connection or waiting for the pool, so a caller bounds each call with
`asyncio.timeout`; an exception from a write means it is not confirmed. `cv_app` holds no DELETE
on these tables: groups and legs are history.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, fields
from datetime import datetime
from decimal import Decimal
from typing import Final, Literal, NoReturn, Protocol
from uuid import UUID

from candleviewer.domain.text import UNSTORABLE_TEXT, refuse_unstorable_text
from candleviewer.storage.repositories.accounts import AccountScope
from candleviewer.storage.repositories.exchange_payload import (
    MAX_CODE_CHARS,
    MAX_DEPTH,
    MAX_PAYLOAD_CHARS,
)
from candleviewer.storage.repositories.orders import (
    OrderSide,
    TriggerBy,
    check_fields,
    typed_fields,
)

__all__ = [
    "ACCOUNT_NOT_LIVE", "CREATE_ONLY_GROUP_COLUMNS", "DEFINITION_NOT_LIVE", "GROUP_PATCH_COLUMNS",
    "LEG_PATCH_COLUMNS", "MAX_CODE_CHARS", "MAX_DEPTH", "MAX_PAYLOAD_CHARS",
    "NO_STOP_LEG_STATUSES", "OPEN_GROUP_STATUSES", "PROFILE_CHANGED", "TRADE_GROUP_CONFLICTS",
    "TRADE_GROUP_RULES", "UNPROTECTED_LEG_STATUSES", "WRITE_ONCE_GROUP_COLUMNS",
    "WRITE_ONCE_LEG_COLUMNS", "AccountScope", "AlgoKind", "EntryType", "ExchangeEnv",
    "GroupAnchor", "GroupCreated", "GroupExists", "GroupOrigin", "GroupPatch", "GroupWriteAhead",
    "JsonObject", "JsonValue", "LegFailurePolicy", "LegPatch", "LegSnapshotRow", "LegStatus",
    "NewTradeGroup", "NewTradeGroupLeg", "OrderSide", "RequestedQtyMode", "TradeGroupLegRow",
    "TradeGroupReads", "TradeGroupRecord", "TradeGroupRefusal", "TradeGroupRow",
    "TradeGroupStatus", "TradeGroupStore", "TradeGroupStoreConflictError", "TradeGroupStoreError",
    "TradeGroupStoreRefusedError", "TradeGroupStoreRuleError", "TradeGroupStoreScopeDeniedError",
    "TradeGroupStoreStaleError", "TriggerBy", "UnprotectedLegRow", "parse_json", "render_json",
]  # fmt: skip

#: A `jsonb` value as this store writes and reads it: no float anywhere (C2).
type JsonValue = bool | int | str | list[JsonValue] | dict[str, JsonValue] | None
type JsonObject = dict[str, JsonValue]

#: The `trade_group_status`, `leg_status`, `algo_kind`, `sizing_mode` and `exchange_env` types and
#: the `tg_origin`, `tg_policy` and `tg_entrytype` vocabularies (21 Sec.1.2, Sec.3.3.2-3.3.3); a
#: unit test pins each. `OrderSide` (`tg_side`) and `TriggerBy` (`tg_trigby`) are the order store's.
TradeGroupStatus = Literal[
    "draft", "submitting", "partially_open", "open", "closing", "closed", "failed", "cancelled",
]  # fmt: skip
LegStatus = Literal[
    "pending", "submitted", "rejected", "open", "partially_filled", "filled", "cancelled",
    "closed", "error",
]  # fmt: skip
AlgoKind = Literal["none", "oco", "iceberg", "twap", "chase", "scaled", "bracket"]
GroupOrigin = Literal[
    "manual", "hotkey", "dom_click", "chart_click", "rule", "alert", "replay_sim",
]  # fmt: skip
#: 24 Sec.9.5's policies in 24 Sec.9.1's order (`db.models.LEG_FAILURE_POLICIES`): write-once,
#: and named by every writer, since the column default is only Sec.9.5's manual-ticket default.
LegFailurePolicy = Literal["best_effort", "all_or_none", "abort_on_first"]
#: The column vocabulary; 24 Sec.9.1's `market`, `limit` and `conditional` are M13's.
EntryType = Literal["Market", "Limit", "Conditional"]
RequestedQtyMode = Literal["fixed_qty", "fixed_notional", "pct_equity", "risk_based"]
ExchangeEnv = Literal["live", "demo", "testnet"]
#: Why `create_group` wrote nothing although no constraint refused it
#: (`TradeGroupStoreRefusedError`).
TradeGroupRefusal = Literal["account_not_live", "definition_not_live", "profile_changed"]

#: The `ix_tg_open` predicate: the groups `list_open_groups` returns. Bind it, like the next one,
#: as literals in a fixed (sorted) order: a frozenset's order changes between runs.
OPEN_GROUP_STATUSES: Final[frozenset[TradeGroupStatus]] = frozenset(
    {"submitting", "partially_open", "open", "closing"}
)
#: The `ix_tgl_no_sl` predicate, with `native_sl_confirmed = false`: a leg in one of these whose
#: native stop is not confirmed is an open position without its stop (C-2.6).
UNPROTECTED_LEG_STATUSES: Final[frozenset[LegStatus]] = frozenset(
    {"open", "partially_filled", "filled"}
)
#: The statuses `tgl_sl_px` lets go without a stop (SR-E28-08): every other leg holds a
#: `resolved_sl_price` above zero.
NO_STOP_LEG_STATUSES: Final[frozenset[LegStatus]] = frozenset({"rejected", "cancelled", "error"})
#: Written when the group is created and never updated by this store (21 Sec.3.3.2).
CREATE_ONLY_GROUP_COLUMNS: Final = frozenset(
    {"symbol", "side", "entry_type", "origin", "origin_rule_id", "is_paper", "algo_params"}
)
#: The columns `trg_tg_write_once` freezes from the insert (21 Sec.3.3.2; more after `draft`, 0053).
WRITE_ONCE_GROUP_COLUMNS: Final = frozenset(
    {"id", "env", "created_by", "client_group_ref", "client_body_sha256", "definition_id",
     "leg_failure_policy"}
)  # fmt: skip
#: The columns `trg_tgl_write_once` freezes (21 Sec.3.3.3); `account_profile_id` may still become
#: NULL through its foreign key's `ON DELETE SET NULL`.
WRITE_ONCE_LEG_COLUMNS: Final = frozenset(
    {"id", "trade_group_id", "exchange_account_id", "profile_version", "profile_snapshot",
     "account_profile_id"}
)  # fmt: skip


# -- the JSON codec of `algo_params` and `profile_snapshot` ----------------------------------------


def render_json(value: JsonObject) -> str:
    """Compact JSON text of a `jsonb` object, bound as text and cast by the statement builders.

    Raises `TypeError` for a top level that is not an object, a float, a `Decimal`, a key that is
    not a `str` or anything else that is not JSON, and `ValueError` for text `jsonb` refuses
    (U+0000, an unpaired surrogate), nesting deeper than `MAX_DEPTH` containers or text longer
    than `MAX_PAYLOAD_CHARS`. No message names a value: they are P1 (21 Sec.12)."""
    if not isinstance(value, dict):
        raise TypeError("a stored JSON value must be an object")
    _check_json(value, 1)
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(text) > MAX_PAYLOAD_CHARS:
        raise ValueError(f"a stored JSON value is longer than {MAX_PAYLOAD_CHARS} characters")
    return text


def _check_json(value: object, depth: int) -> None:
    """`value` sits `depth` containers deep, the top-level object at 1."""
    if value is None or isinstance(value, bool | int):
        return
    if isinstance(value, str):
        _require_storable(value)
        return
    if isinstance(value, float):
        raise TypeError("a stored JSON number may not be a float (C2): a fraction is a string")
    if isinstance(value, Decimal):
        raise TypeError("a stored JSON number may not be a Decimal: it travels as its string")
    if not isinstance(value, dict | list):
        raise TypeError(f"a {type(value).__name__} is not a JSON value")
    if depth > MAX_DEPTH:
        raise ValueError(f"a stored JSON value nests deeper than {MAX_DEPTH} containers")
    if isinstance(value, list):
        for item in value:
            _check_json(item, depth + 1)
        return
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("a JSON object key must be a str")
        _require_storable(key)
        _check_json(item, depth + 1)


def _require_storable(text: str) -> None:
    try:
        refuse_unstorable_text(text)
    except ValueError:
        raise ValueError(f"a JSON string {UNSTORABLE_TEXT}") from None


def parse_json(text: str) -> JsonObject:
    """A stored `jsonb` object read as text (`CAST(... AS text)`), with `json.loads`.

    Refuses with `ValueError` a number with a fraction or an exponent (a float, C2), a non-finite
    constant and a top level that is not an object, naming no value. Integers stay exact. Nothing
    else is checked (`jsonb` re-spaces the text and may hold any depth), so every row this store
    wrote reads back."""
    value: object = json.loads(text, parse_float=_no_fraction, parse_constant=_no_constant)
    if not isinstance(value, dict):
        raise ValueError("a stored JSON value must be an object")
    return value


def _no_fraction(_: str) -> NoReturn:
    raise ValueError("a stored JSON number has a fraction or an exponent (C2)")


def _no_constant(_: str) -> NoReturn:
    raise ValueError("a stored JSON number is not finite")


def _json_text(value: JsonValue | None) -> str | None:
    """What Postgres `->>` reads for a scalar: a string as it is, `true` or `false`, an integer's
    digits; `None` for null, a missing key or a container."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | str):
        return str(value)
    return None


# -- what a writer sets ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class NewTradeGroup:
    """A `trade_groups` row to insert: every column a writer sets, in stored units, each one
    required, so no column takes its default by omission (`leg_failure_policy`'s is only 24
    Sec.9.5's manual-ticket default). The five times are the database's or an update's.

    `client_group_ref` is `str(UUID(key))`, the canonical lower-case form `tg_ref_fmt` requires,
    and `client_body_sha256` the request fingerprint (64 lower-case hex, `sha256_hex`), compared
    in SQL and never read back. Refuses, before any statement, a money value its numeric(38,18)
    column would not hold exactly and `algo_params` that `render_json` refuses."""

    id: UUID
    client_group_ref: str = field(repr=False)
    client_body_sha256: str = field(repr=False)
    created_by: UUID
    env: ExchangeEnv
    symbol: str
    side: OrderSide
    status: TradeGroupStatus
    leg_failure_policy: LegFailurePolicy
    algo: AlgoKind
    algo_params: JsonObject | None = field(repr=False)
    intent_note: str | None = field(repr=False)
    origin: GroupOrigin
    origin_rule_id: UUID | None
    origin_rule_run_id: UUID | None
    definition_id: UUID | None
    requested_qty_mode: RequestedQtyMode
    requested_qty_value: Decimal | None
    entry_type: EntryType
    entry_price: Decimal | None
    trigger_price: Decimal | None
    trigger_by: TriggerBy | None
    sl_price_hint: Decimal | None
    tp_price_hint: Decimal | None
    is_paper: bool

    def __post_init__(self) -> None:
        check_fields(self, _GROUP_MONEY, ())
        if self.algo_params is not None:
            render_json(self.algo_params)


@dataclass(frozen=True, slots=True, kw_only=True)
class NewTradeGroupLeg:
    """A `trade_group_legs` row to insert with its group: every column a writer sets. The group id
    is `create_group`'s; the fill, P&L, fee, stop-confirmation and time columns start at the
    database's defaults.

    `account_profile_id` is required at insert (`trg_tgl_profile`), and `profile_snapshot` must
    name the leg's account, profile and version as `tgl_snapshot` reads them (`->>` text). Refuses,
    before any statement, a snapshot that does not, one `render_json` refuses, and a money value
    its column would not hold exactly (`resolved_leverage` is numeric(10,2)). The statement builder
    redacts `rejection_code` and `rejection_message` before they are bound."""

    id: UUID
    exchange_account_id: UUID
    account_profile_id: UUID
    profile_version: int
    profile_snapshot: JsonObject = field(repr=False)
    status: LegStatus
    sequence_no: int
    target_qty: Decimal
    resolved_leverage: Decimal
    resolved_sl_price: Decimal | None
    resolved_tp_price: Decimal | None
    risk_usd: Decimal | None
    rejection_code: str | None = field(repr=False)
    rejection_message: str | None = field(repr=False)

    def __post_init__(self) -> None:
        check_fields(self, _LEG_MONEY, ())
        snapshot = self.profile_snapshot
        render_json(snapshot)
        if (
            _json_text(snapshot.get("account_id")) != str(self.exchange_account_id)
            or _json_text(snapshot.get("profile_id")) != str(self.account_profile_id)
            or _json_text(snapshot.get("version")) != str(self.profile_version)
        ):
            raise ValueError(
                "profile_snapshot must name the leg's account, profile and version (tgl_snapshot)"
            )


_GROUP_MONEY: Final = dict.fromkeys(typed_fields(NewTradeGroup, Decimal), (38, 18))
_LEG_MONEY: Final = dict.fromkeys(typed_fields(NewTradeGroupLeg, Decimal), (38, 18)) | {
    "resolved_leverage": (10, 2)
}


@dataclass(frozen=True, slots=True, kw_only=True)
class LegPatch:
    """What `update_leg` sets, as absolute values; `None` leaves a column as it is, so a column is
    never set back to NULL. The fields are leg columns, in table order, and none is write-once,
    `resolved_*`, `target_qty`, `risk_usd` or `sequence_no` (amending those is E34-S03's).
    `submitted_at` is set once: the builder keeps a time already stored.

    Refuses, before any statement, a patch that sets nothing, a confirmed native stop without its
    time (`tgl_sl_conf`), a money value its numeric(38,18) column would not hold exactly and a
    naive time. The statement builder redacts the rejection texts before they are bound."""

    status: LegStatus | None = None
    filled_qty: Decimal | None = None
    avg_entry_price: Decimal | None = None
    avg_exit_price: Decimal | None = None
    native_sl_confirmed: bool | None = None
    native_sl_confirmed_at: datetime | None = None
    realised_pnl: Decimal | None = None
    fees_paid: Decimal | None = None
    rejection_code: str | None = field(default=None, repr=False)
    rejection_message: str | None = field(default=None, repr=False)
    submitted_at: datetime | None = None
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.changes():
            raise ValueError("a leg patch must set at least one column")
        if self.native_sl_confirmed and self.native_sl_confirmed_at is None:
            raise ValueError("a confirmed native stop needs native_sl_confirmed_at (tgl_sl_conf)")
        check_fields(self, _LEG_PATCH_MONEY, _LEG_PATCH_STAMPS)

    def changes(self) -> dict[str, object]:
        """The columns it sets, by name, in table order: every field that is not `None`. The
        rejection texts are as given; the statement builder redacts them."""
        values = ((f.name, getattr(self, f.name)) for f in fields(self))
        return {name: value for name, value in values if value is not None}


@dataclass(frozen=True, slots=True, kw_only=True)
class GroupPatch:
    """What `update_group` sets, as absolute values; `None` leaves a column as it is. The fields
    are the only group columns an update reaches. `submitted_at` and `opened_at` are set once: the
    builder keeps a time already stored. Refuses a patch that sets nothing and a naive time;
    `closed_at` before `opened_at` is `tg_times`'s refusal."""

    status: TradeGroupStatus | None = None
    submitted_at: datetime | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.changes():
            raise ValueError("a group patch must set at least one column")
        check_fields(self, {}, _GROUP_PATCH_STAMPS)

    def changes(self) -> dict[str, object]:
        """The columns it sets, by name, in table order: every field that is not `None`."""
        values = ((f.name, getattr(self, f.name)) for f in fields(self))
        return {name: value for name, value in values if value is not None}


_LEG_PATCH_MONEY: Final = dict.fromkeys(typed_fields(LegPatch, Decimal), (38, 18))
_LEG_PATCH_STAMPS: Final = typed_fields(LegPatch, datetime)
_GROUP_PATCH_STAMPS: Final = typed_fields(GroupPatch, datetime)
#: The only columns an update sets (`updated_at` aside, which the touch trigger writes).
LEG_PATCH_COLUMNS: Final = tuple(f.name for f in fields(LegPatch))
GROUP_PATCH_COLUMNS: Final = tuple(f.name for f in fields(GroupPatch))


# -- what a reader gets --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TradeGroupRow:
    """One `trade_groups` row, every column but `client_body_sha256`, in table order (pinned to
    the table by a unit test). `algo_params` is decoded with `parse_json`; times are aware."""

    id: UUID
    client_group_ref: str = field(repr=False)
    definition_id: UUID | None
    env: ExchangeEnv
    symbol: str
    side: OrderSide
    status: TradeGroupStatus
    leg_failure_policy: LegFailurePolicy
    algo: AlgoKind
    algo_params: JsonObject | None = field(repr=False)
    intent_note: str | None = field(repr=False)
    origin: GroupOrigin
    origin_rule_id: UUID | None
    origin_rule_run_id: UUID | None
    requested_qty_mode: RequestedQtyMode
    requested_qty_value: Decimal | None
    entry_type: EntryType
    entry_price: Decimal | None
    trigger_price: Decimal | None
    trigger_by: TriggerBy | None
    sl_price_hint: Decimal | None
    tp_price_hint: Decimal | None
    is_paper: bool
    submitted_at: datetime | None
    opened_at: datetime | None
    closed_at: datetime | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TradeGroupLegRow:
    """One `trade_group_legs` row, every column but `profile_snapshot`, in table order (pinned to
    the table by a unit test). `rejection_code` and `rejection_message` are what was stored: the
    redacted values. `account_profile_id` is `None` only once its profile row is gone."""

    id: UUID
    trade_group_id: UUID
    exchange_account_id: UUID
    account_profile_id: UUID | None
    profile_version: int
    status: LegStatus
    sequence_no: int
    target_qty: Decimal
    filled_qty: Decimal
    avg_entry_price: Decimal | None
    avg_exit_price: Decimal | None
    resolved_leverage: Decimal
    resolved_sl_price: Decimal | None
    resolved_tp_price: Decimal | None
    native_sl_confirmed: bool
    native_sl_confirmed_at: datetime | None
    risk_usd: Decimal | None
    realised_pnl: Decimal
    fees_paid: Decimal
    rejection_code: str | None = field(repr=False)
    rejection_message: str | None = field(repr=False)
    submitted_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TradeGroupRecord:
    """A group with its legs, in `(sequence_no, id)` order."""

    group: TradeGroupRow
    legs: tuple[TradeGroupLegRow, ...]


@dataclass(frozen=True, slots=True)
class LegSnapshotRow:
    """A leg with its `profile_snapshot`, decoded with `parse_json`: the `AccountProfile` it was
    sized from as `model_dump(mode="json")` wrote it (SR-E28-07). Only `load_leg` returns one."""

    leg: TradeGroupLegRow
    profile_snapshot: JsonObject = field(repr=False)


@dataclass(frozen=True, slots=True)
class UnprotectedLegRow:
    """A leg `list_unprotected_legs` returns, with what the C-2.6 alarm needs of its group."""

    leg: TradeGroupLegRow
    symbol: str
    side: OrderSide
    env: ExchangeEnv
    is_paper: bool


@dataclass(frozen=True, slots=True)
class GroupAnchor:
    """The group a creator's `client_group_ref` anchors, and whether the request fingerprint given
    equals the stored one (G-6(b)); the fingerprint itself is never returned."""

    group_id: UUID
    body_matches: bool


@dataclass(frozen=True, slots=True)
class GroupCreated:
    """`create_group` stored the group with its legs, as `record` reads them."""

    record: TradeGroupRecord


@dataclass(frozen=True, slots=True)
class GroupExists:
    """`create_group` met an existing anchor of the same creator and ref, and wrote nothing."""

    anchor: GroupAnchor


#: Awaited once in `create_group`'s transaction, after the legs insert and before the commit, with
#: the rows as stored (stored units). Never for `GroupExists` or a refusal. A hook that raises, or
#: outlasts the store's audit timeout (`WriteAheadTimeout`), leaves nothing written (C-2.9
#: write-ahead; E29-T04 and E34-S02 wire `trade_group.submit` and one record per leg). A hook
#: raises its own typed refusal: a raw `OSError` or driver error from it is mapped as the
#: database's own, `StorageTierUnavailable` or `StorageQueryFailed`.
GroupWriteAhead = Callable[[TradeGroupRecord], Awaitable[None]]


# -- refusals ------------------------------------------------------------------------------------

#: The rules a write can break, by the name the database gives the refusal
#: (`.diag.constraint_name`): the CHECKs of both tables, the integrity triggers (which name
#: themselves as the constraint, `USING CONSTRAINT`), the two domains' CHECKs and the foreign keys
#: (23503). Pinned to `db.models` and the 0039 revision by a unit test.
TRADE_GROUP_RULES: Final[frozenset[str]] = frozenset(
    {
        # trade_groups CHECKs
        "tg_side", "tg_origin", "tg_policy", "tg_entrytype", "tg_limit_px", "tg_cond_px",
        "tg_trigby", "tg_times", "tg_ref_fmt", "tg_finite",
        # trade_group_legs CHECKs
        "tgl_qty_pos", "tgl_filled_rng", "tgl_seq", "tgl_lev", "tgl_sl_conf", "tgl_fees_nonneg",
        "tgl_profile_version", "tgl_snapshot", "tgl_sl_px", "tgl_finite",
        # triggers (USING CONSTRAINT)
        "trg_tg_env", "trg_tg_write_once", "trg_tgl_env", "trg_tgl_profile", "trg_tgl_write_once",
        # domain CHECKs
        "sha256_hex_check", "symbol_code_check",
        # foreign keys (23503)
        "tgl_profile_revision", "trade_groups_created_by_fkey", "trade_groups_definition_id_fkey",
        "trade_groups_origin_rule_id_fkey", "trade_groups_origin_rule_run_id_fkey",
        "trade_group_legs_trade_group_id_fkey", "trade_group_legs_exchange_account_id_fkey",
        "trade_group_legs_account_profile_id_fkey",
    }
)  # fmt: skip
#: Unique refusals: the anchor, one leg per account and group, and the primary keys.
TRADE_GROUP_CONFLICTS: Final[frozenset[str]] = frozenset(
    {"ux_tg_creator_ref", "ux_tgl_group_account", "trade_groups_pkey", "trade_group_legs_pkey"}
)
#: `TradeGroupStoreRefusedError.reason`: a leg account is missing or soft-deleted.
ACCOUNT_NOT_LIVE: Final = "account_not_live"
#: The definition the group names is missing or soft-deleted (21 Sec.3.3.3a).
DEFINITION_NOT_LIVE: Final = "definition_not_live"
#: A leg's profile is missing, soft-deleted or no longer at the leg's `profile_version`
#: (SR-E28-15).
PROFILE_CHANGED: Final = "profile_changed"


class TradeGroupStoreError(Exception):
    """Base for trade-group store errors; none carries a value, only a rule, constraint or reason
    name."""


class TradeGroupStoreScopeDeniedError(TradeGroupStoreError):
    """An `OwnerScope` held by someone who is not a live owner (uniform 403; depends only on the
    caller)."""


class TradeGroupStoreConflictError(TradeGroupStoreError):
    """A name in `TRADE_GROUP_CONFLICTS` (problem code `conflict`)."""

    def __init__(self, constraint: str) -> None:
        super().__init__(constraint)
        self.constraint = constraint


class TradeGroupStoreRuleError(TradeGroupStoreError):
    """A name in `TRADE_GROUP_RULES` (problem code `validation_failed`)."""

    def __init__(self, rule: str) -> None:
        super().__init__(rule)
        self.rule = rule


class TradeGroupStoreRefusedError(TradeGroupStoreError):
    """`create_group` found, under its share locks, the definition, a leg account or a leg's
    profile at its version not live, and wrote nothing: `ACCOUNT_NOT_LIVE`,
    `DEFINITION_NOT_LIVE` or `PROFILE_CHANGED`."""

    def __init__(self, reason: TradeGroupRefusal) -> None:
        super().__init__(reason)
        self.reason: TradeGroupRefusal = reason


class TradeGroupStoreStaleError(TradeGroupStoreError):
    """The status compare-and-set missed: the row no longer holds `expected_status`, and nothing
    was written."""


# -- the store -------------------------------------------------------------------------------------


class TradeGroupStore(Protocol):
    """The system surface: no principal. Never reached from a route (architecture-pinned)."""

    async def find_anchor(
        self, created_by: UUID, client_group_ref: str, client_body_sha256: str
    ) -> GroupAnchor | None:
        """The group this creator's ref anchors, and whether its stored fingerprint equals
        `client_body_sha256`; `None` when this creator has no such ref (another user's ref reads
        as missing). `created_by` is the authenticated principal's id, or the rule owner's (M15),
        never a client value."""
        ...

    async def create_group(
        self,
        group: NewTradeGroup,
        legs: Sequence[NewTradeGroupLeg],
        *,
        write_ahead: GroupWriteAhead | None = None,
    ) -> GroupCreated | GroupExists:
        """Insert `group` with every leg in one transaction, or answer `GroupExists` when the
        creator's ref already anchors a group, with nothing written and the hook not called.
        Under share locks, in order (the definition, the leg accounts by id, their profiles by
        id), `TradeGroupStoreRefusedError` when the definition or a leg account is not live, or a
        leg's profile is missing, soft-deleted or past the leg's `profile_version`. `write_ahead`
        is awaited after the legs insert and before the commit. Any refusal writes nothing."""
        ...

    async def update_leg(
        self,
        group_id: UUID,
        leg_id: UUID,
        patch: LegPatch,
        *,
        expected_status: LegStatus | None = None,
    ) -> TradeGroupLegRow | None:
        """Set the patch's columns on this group's leg under a row lock (`FOR NO KEY UPDATE`) and
        return the leg as stored; `None` when the group has no such leg.
        `TradeGroupStoreStaleError`, with nothing written, when `expected_status` is given and
        the leg holds another."""
        ...

    async def update_group(
        self,
        group_id: UUID,
        patch: GroupPatch,
        *,
        expected_status: TradeGroupStatus | None = None,
    ) -> TradeGroupRow | None:
        """Set the patch's columns on the group under a row lock (`FOR NO KEY UPDATE`) and return
        it as stored; `None` when there is no such group. `TradeGroupStoreStaleError`, with
        nothing written, when `expected_status` is given and the group holds another."""
        ...

    async def load_group(self, group_id: UUID) -> TradeGroupRecord | None:
        """The group with its legs; `None` when there is no such group."""
        ...

    async def load_leg(self, leg_id: UUID) -> LegSnapshotRow | None:
        """The leg with its `profile_snapshot`; `None` when there is no such leg."""
        ...

    async def list_open_groups(self) -> tuple[TradeGroupRecord, ...]:
        """Every group in `OPEN_GROUP_STATUSES` with its legs, oldest first (`ix_tg_open`). No
        soft-delete filter."""
        ...

    async def list_unprotected_legs(self) -> tuple[UnprotectedLegRow, ...]:
        """Every leg in `UNPROTECTED_LEG_STATUSES` whose native stop is not confirmed, by group
        and `sequence_no` (`ix_tgl_no_sl`). No soft-delete filter: the C-2.6 alarm sees a leg of
        a soft-deleted account too."""
        ...


class TradeGroupReads(Protocol):
    """The principal-scoped read; the scope is applied in SQL (SR-051, SR-E28-21)."""

    async def get_group(self, scope: AccountScope, group_id: UUID) -> TradeGroupRecord | None:
        """The group with its legs when the scope sees it, else `None`. An `OwnerScope` call first
        checks the live owner role (`TradeGroupStoreScopeDeniedError` for anyone else) and sees
        every group; a `GrantScope` sees a group that has a leg and whose every leg account is
        live, in the scope and under a live `can_view` grant that is not frozen. A `GrantScope`
        read never yields a record without legs: the legs read is all or none (SR-E28-21), so a
        scope that changes between the group and its legs reads as `None`. An empty `GrantScope`
        runs no SQL."""
        ...
