"""`TradeGroupRepository` and `TradeGroupReader` (E28-T01 #905): store rows to the 24 Sec.9.1
models, store errors to the accounts domain errors (`from None`), one not-found for every miss,
the replay anchor's answers, and a stored row the store cannot decode or the models refuse
failing closed with no value in the log. The store is a scripted fake of the M10 port; its SQL is
`tests/unit/storage/` and `tests/integration/storage/`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
import structlog

from candleviewer.accounts.errors import (
    AccountConflictError,
    AccountNotFoundError,
    AccountRuleError,
    AccountScopeDeniedError,
    AccountsError,
    ProfileChangedError,
    TradeGroupKeyReuseError,
    TradeGroupStaleError,
)
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.accounts.trade_group_repository import TradeGroupReader, TradeGroupRepository
from candleviewer.accounts.trade_groups import (
    GroupReplay,
    GroupUpdate,
    LegDraft,
    LegUpdate,
    TradeGroupDraft,
    group_patch,
    group_values,
    leg_patch,
    leg_values,
)
from candleviewer.domain.primitives import GroupId, UserId
from candleviewer.storage.errors import (
    StorageQueryFailed,
    StorageRecordInvalid,
    StorageTierUnavailable,
    WriteAheadTimeout,
)
from candleviewer.storage.repositories.accounts import AccountScope, GrantScope, OwnerScope
from candleviewer.storage.repositories.trade_groups import (
    GroupAnchor,
    GroupCreated,
    GroupExists,
    GroupPatch,
    GroupWriteAhead,
    LegPatch,
    LegSnapshotRow,
    LegStatus,
    NewTradeGroup,
    NewTradeGroupLeg,
    TradeGroupLegRow,
    TradeGroupRecord,
    TradeGroupRefusal,
    TradeGroupRow,
    TradeGroupStatus,
    TradeGroupStoreConflictError,
    TradeGroupStoreError,
    TradeGroupStoreRefusedError,
    TradeGroupStoreRuleError,
    TradeGroupStoreScopeDeniedError,
    TradeGroupStoreStaleError,
    UnprotectedLegRow,
    parse_json,
    render_json,
)

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "profiles"
_T = datetime(2026, 10, 20, 9, tzinfo=UTC)
_GROUP, _LEG, _USER, _OTHER = UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=9)
_REF = UUID("9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59")
_BODY = "ab" * 32  # synthetic 64-hex shape
#: A marker in every P1 value a test hands over: no log may repeat it.
_MARK = "q7z"
_P = AccountProfile.model_validate(
    json.loads((_FIXTURES / "risk_based.json").read_text(encoding="utf-8"))
)
_OWNER = OwnerScope(_OTHER)

_GROUP_ROW = TradeGroupRow(
    id=_GROUP, client_group_ref=str(_REF), definition_id=None, env="demo", symbol="BTCUSDT",
    side="Buy", status="submitting", leg_failure_policy="best_effort", algo="none",
    algo_params=None, intent_note=f"{_MARK} note", origin="manual", origin_rule_id=None,
    origin_rule_run_id=None, requested_qty_mode="risk_based", requested_qty_value=Decimal("1"),
    entry_type="Limit", entry_price=Decimal("63099.8"), trigger_price=None, trigger_by=None,
    sl_price_hint=Decimal("62000"), tp_price_hint=None, is_paper=False, submitted_at=None,
    opened_at=None, closed_at=None, created_by=_USER, created_at=_T, updated_at=_T,
)  # fmt: skip
_LEG_ROW = TradeGroupLegRow(
    id=_LEG, trade_group_id=_GROUP, exchange_account_id=_P.account_id,
    account_profile_id=_P.profile_id, profile_version=_P.version, status="filled",
    sequence_no=0, target_qty=Decimal("0.010"), filled_qty=Decimal("0.010"),
    avg_entry_price=Decimal("63000"), avg_exit_price=None, resolved_leverage=Decimal("5.00"),
    resolved_sl_price=Decimal("62000"), resolved_tp_price=None, native_sl_confirmed=False,
    native_sl_confirmed_at=None, risk_usd=Decimal("11.5"), realised_pnl=Decimal("0"),
    fees_paid=Decimal("0.02"), rejection_code=None, rejection_message=None, submitted_at=_T,
    closed_at=None, created_at=_T, updated_at=_T,
)  # fmt: skip
_RECORD = TradeGroupRecord(group=_GROUP_ROW, legs=(_LEG_ROW,))
_SNAPSHOT_ROW = LegSnapshotRow(
    leg=_LEG_ROW, profile_snapshot=parse_json(render_json(_P.model_dump(mode="json")))
)
_UNPROTECTED_ROW = UnprotectedLegRow(
    leg=_LEG_ROW, symbol="BTCUSDT", side="Buy", env="demo", is_paper=False
)


def _draft(**over: Any) -> TradeGroupDraft:
    base: dict[str, Any] = {
        "group_id": _GROUP, "client_group_ref": _REF, "client_body_sha256": _BODY,
        "created_by": _USER, "environment": "demo", "symbol": "BTCUSDT", "side": "buy",
        "status": "submitting", "leg_failure_policy": "best_effort", "algo": "none",
        "algo_params": None, "note": f"{_MARK} note", "origin": "manual", "rule_id": None,
        "rule_run_id": None, "definition_id": None, "requested_qty_mode": "risk_based",
        "requested_qty_value": Decimal("1"), "entry_type": "limit",
        "entry_price": Decimal("63099.8"), "trigger_price": None, "trigger_by": None,
        "sl_price_hint": Decimal("62000"), "tp_price_hint": None, "is_paper": False,
    }  # fmt: skip
    return TradeGroupDraft.model_validate(base | over)


def _leg_draft(**over: Any) -> LegDraft:
    base: dict[str, Any] = {
        "leg_id": _LEG, "profile": _P, "status": "pending", "sequence_no": 0,
        "target_qty": Decimal("0.010"), "resolved_leverage": Decimal("5"),
        "resolved_sl_price": Decimal("62000"), "resolved_tp_price": None,
        "risk_usd": Decimal("11.5"), "rejection_code": None, "rejection_message": None,
    }  # fmt: skip
    return LegDraft.model_validate(base | over)


class _Store:
    """A scripted `TradeGroupStore` and `TradeGroupReads`: every call is recorded and answered
    with `answer`, or raises it when it is an exception."""

    def __init__(self, answer: object = None) -> None:
        self.answer = answer
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def _answer(self, name: str, *args: object, **kwargs: object) -> object:
        self.calls.append((name, args, kwargs))
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer

    async def find_anchor(
        self, created_by: UUID, client_group_ref: str, client_body_sha256: str
    ) -> GroupAnchor | None:
        answer = self._answer("find_anchor", created_by, client_group_ref, client_body_sha256)
        return cast("GroupAnchor | None", answer)

    async def create_group(
        self,
        group: NewTradeGroup,
        legs: Sequence[NewTradeGroupLeg],
        *,
        write_ahead: GroupWriteAhead | None = None,
    ) -> GroupCreated | GroupExists:
        answer = self._answer("create_group", group, list(legs), write_ahead=write_ahead)
        return cast("GroupCreated | GroupExists", answer)

    async def update_leg(
        self,
        group_id: UUID,
        leg_id: UUID,
        patch: LegPatch,
        *,
        expected_status: LegStatus | None = None,
    ) -> TradeGroupLegRow | None:
        answer = self._answer(
            "update_leg", group_id, leg_id, patch, expected_status=expected_status
        )
        return cast("TradeGroupLegRow | None", answer)

    async def update_group(
        self,
        group_id: UUID,
        patch: GroupPatch,
        *,
        expected_status: TradeGroupStatus | None = None,
    ) -> TradeGroupRow | None:
        answer = self._answer("update_group", group_id, patch, expected_status=expected_status)
        return cast("TradeGroupRow | None", answer)

    async def load_group(self, group_id: UUID) -> TradeGroupRecord | None:
        return cast("TradeGroupRecord | None", self._answer("load_group", group_id))

    async def load_leg(self, leg_id: UUID) -> LegSnapshotRow | None:
        return cast("LegSnapshotRow | None", self._answer("load_leg", leg_id))

    async def list_open_groups(self) -> tuple[TradeGroupRecord, ...]:
        return cast("tuple[TradeGroupRecord, ...]", self._answer("list_open_groups"))

    async def list_unprotected_legs(self) -> tuple[UnprotectedLegRow, ...]:
        return cast("tuple[UnprotectedLegRow, ...]", self._answer("list_unprotected_legs"))

    async def get_group(self, scope: AccountScope, group_id: UUID) -> TradeGroupRecord | None:
        return cast("TradeGroupRecord | None", self._answer("get_group", scope, group_id))


async def _hook(record: TradeGroupRecord) -> None:  # the fake store never awaits it
    raise AssertionError("not awaited here")


class _HookingStore(_Store):
    """Awaits the write-ahead hook with `_RECORD` before it answers, as the adapter does once it
    has decoded the stored rows and before its commit."""

    async def create_group(
        self,
        group: NewTradeGroup,
        legs: Sequence[NewTradeGroupLeg],
        *,
        write_ahead: GroupWriteAhead | None = None,
    ) -> GroupCreated | GroupExists:
        assert write_ahead is not None
        await write_ahead(_RECORD)
        return await super().create_group(group, legs, write_ahead=write_ahead)


def _repo(answer: object = None) -> tuple[TradeGroupRepository, _Store]:
    store = _Store(answer)
    return TradeGroupRepository(store), store


#: Every facade call, as `(name, call)`; each reaches the store once.
_CALLS: dict[str, Any] = {
    "find_replay": lambda r: r.find_replay(UserId(_USER), _REF, _BODY),
    "create": lambda r: r.create(_draft(), [_leg_draft()], write_ahead=_hook),
    "update_leg": lambda r: r.update_leg(GroupId(_GROUP), _LEG, LegUpdate(status="open")),
    "update_group": lambda r: r.update_group(GroupId(_GROUP), GroupUpdate(status="open")),
    "get": lambda r: r.get(GroupId(_GROUP)),
    "leg_with_profile": lambda r: r.leg_with_profile(_LEG),
    "open_groups": lambda r: r.open_groups(),
    "unprotected_legs": lambda r: r.unprotected_legs(),
}


# -- the 24 Sec.9.1 mapping table ------------------------------------------------------------------

_MAPPED: list[tuple[str, TradeGroupStoreError, type[AccountsError], tuple[str, str] | None]] = [
    ("scope-denied", TradeGroupStoreScopeDeniedError(), AccountScopeDeniedError, None),
    (
        "conflict",
        TradeGroupStoreConflictError("ux_tgl_group_account"),
        AccountConflictError,
        ("constraint", "ux_tgl_group_account"),
    ),
    ("rule", TradeGroupStoreRuleError("trg_tgl_env"), AccountRuleError, ("rule", "trg_tgl_env")),
    (
        "account-not-live",
        TradeGroupStoreRefusedError("account_not_live"),
        AccountNotFoundError,
        ("entity", "account"),
    ),
    (
        "definition-not-live",
        TradeGroupStoreRefusedError("definition_not_live"),
        AccountNotFoundError,
        ("entity", "definition"),
    ),
    ("profile-changed", TradeGroupStoreRefusedError("profile_changed"), ProfileChangedError, None),
    ("stale", TradeGroupStoreStaleError(), TradeGroupStaleError, None),
    ("other", TradeGroupStoreError("x"), AccountsError, None),
    # a reason the port does not name never reads as one it does
    (
        "unknown-refusal",
        TradeGroupStoreRefusedError(cast(TradeGroupRefusal, "x")),
        AccountsError,
        None,
    ),
]


@pytest.mark.parametrize(
    ("raised", "mapped", "detail"),
    [case[1:] for case in _MAPPED],
    ids=[case[0] for case in _MAPPED],
)
async def test_store_errors_map_to_domain_errors_unchained(
    raised: TradeGroupStoreError, mapped: type[AccountsError], detail: tuple[str, str] | None
) -> None:
    repo, _ = _repo(raised)
    with pytest.raises(mapped) as exc:
        await repo.create(_draft(), [_leg_draft()], write_ahead=_hook)
    assert type(exc.value) is mapped and exc.value.__cause__ is None
    assert exc.value.__suppress_context__
    if detail is not None:
        assert getattr(exc.value, detail[0]) == detail[1]


@pytest.mark.parametrize("call", list(_CALLS))
async def test_every_call_maps_a_store_error_from_none(call: str) -> None:
    repo, store = _repo(TradeGroupStoreStaleError())
    with pytest.raises(TradeGroupStaleError) as exc:
        await _CALLS[call](repo)
    assert exc.value.__cause__ is None and exc.value.__suppress_context__
    assert len(store.calls) == 1


@pytest.mark.parametrize(
    ("raised", "constraint"),
    [
        (TradeGroupStoreConflictError("trade_groups_pkey"), "trade_groups_pkey"),
        (TradeGroupStoreRuleError("tgl_snapshot"), "tgl_snapshot"),
    ],
    ids=["conflict", "rule"],
)
async def test_a_refusal_is_logged_by_its_name_and_never_a_value(
    raised: TradeGroupStoreError, constraint: str
) -> None:
    repo, _ = _repo(raised)
    with structlog.testing.capture_logs() as logs, pytest.raises(AccountsError):
        await repo.create(_draft(), [_leg_draft()], write_ahead=_hook)
    assert logs == [
        {
            "event": "trade_group.constraint_violation",
            "constraint": constraint,
            "log_level": "warning",
        }
    ]


async def test_a_changed_profile_is_logged_at_info_with_ids_only() -> None:
    """SR-E28-15: the group and its leg accounts, never a version, a value or the ref."""
    repo, _ = _repo(TradeGroupStoreRefusedError("profile_changed"))
    with structlog.testing.capture_logs() as logs, pytest.raises(ProfileChangedError):
        await repo.create(_draft(), [_leg_draft()], write_ahead=_hook)
    assert logs == [
        {
            "event": "trade_group.profile_changed",
            "group_id": str(_GROUP),
            "account_ids": str(_P.account_id),
            "log_level": "info",
        }
    ]


@pytest.mark.parametrize(
    "raised",
    [
        StorageTierUnavailable(),
        StorageQueryFailed("57014"),
        WriteAheadTimeout(),
        TimeoutError(),
        StorageRecordInvalid("x"),
    ],
    ids=["tier-unavailable", "query-failed", "write-ahead-timeout", "timeout", "record-invalid"],
)
@pytest.mark.parametrize("call", list(_CALLS))
async def test_storage_errors_pass_unmapped(raised: Exception, call: str) -> None:
    """Whether a write committed is the caller's to reconcile: the facade never relabels it, not
    even a `StorageError` that is a `ValueError` too."""
    repo, _ = _repo(raised)
    with pytest.raises(type(raised)) as exc:
        await _CALLS[call](repo)
    assert exc.value is raised


# -- misses ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("call", "entity"),
    [
        ("update_leg", "leg"),
        ("update_group", "trade_group"),
        ("get", "trade_group"),
        ("leg_with_profile", "leg"),
    ],
)
async def test_every_miss_is_not_found(call: str, entity: str) -> None:
    repo, _ = _repo(None)
    with pytest.raises(AccountNotFoundError) as exc:
        await _CALLS[call](repo)
    assert exc.value.entity == entity and str(exc.value) == "not found"


async def test_a_missing_anchor_is_no_replay() -> None:
    repo, store = _repo(None)
    assert await repo.find_replay(UserId(_USER), _REF, _BODY) is None
    assert store.calls == [("find_anchor", (_USER, str(_REF), _BODY), {})]


# -- the replay anchor (G-6(b), SR-E29-07) -------------------------------------------------------


@pytest.mark.parametrize("via", ["find_replay", "create"])
async def test_create_answers_a_replay_or_raises_key_reuse_without_the_ref_in_the_log(
    via: str,
) -> None:
    same = GroupAnchor(group_id=_OTHER, body_matches=True)
    other = GroupAnchor(group_id=_OTHER, body_matches=False)
    wrap = (lambda anchor: anchor) if via == "find_replay" else GroupExists
    repo, _ = _repo(wrap(same))
    with structlog.testing.capture_logs() as quiet:
        assert await _CALLS[via](repo) == GroupReplay(GroupId(_OTHER))
    assert quiet == []
    repo, store = _repo(wrap(other))
    with structlog.testing.capture_logs() as logs, pytest.raises(TradeGroupKeyReuseError) as exc:
        await _CALLS[via](repo)
    assert logs == [
        {"event": "trade_group.key_reuse", "group_id": str(_OTHER), "log_level": "warning"}
    ]
    text = repr(logs) + str(exc.value) + repr(exc.value)
    assert str(_REF) not in text and _BODY not in text and _MARK not in text
    assert len(store.calls) == 1  # nothing else: no second write


async def test_find_replay_refuses_a_malformed_fingerprint_before_the_store() -> None:
    """A wrong fingerprint form would turn every replay into a key reuse (Q11)."""
    repo, store = _repo(GroupAnchor(group_id=_OTHER, body_matches=True))
    for malformed in ("AB" * 32, "ab" * 31, "zz" * 32, ""):
        with pytest.raises(ValueError, match="64 lower-case hex"):
            await repo.find_replay(UserId(_USER), _REF, malformed)
    assert store.calls == []


# -- create ----------------------------------------------------------------------------------------


async def test_create_sends_the_values_with_the_hook_and_returns_the_stored_group() -> None:
    draft, legs = _draft(), [_leg_draft()]
    store = _HookingStore(GroupCreated(record=_RECORD))
    seen: list[TradeGroupRecord] = []

    async def hook(record: TradeGroupRecord) -> None:
        seen.append(record)

    created = await TradeGroupRepository(store).create(draft, legs, write_ahead=hook)
    ((name, args, _),) = store.calls
    assert (name, args) == ("create_group", (group_values(draft), [leg_values(legs[0])]))
    assert seen == [_RECORD]  # the store's await reaches the caller's hook, once
    assert not isinstance(created, GroupReplay)
    assert created.group.group_id == _GROUP and created.account_ids == (_P.account_id,)
    assert created.legs[0].resolved_leverage == Decimal("5")


@pytest.mark.parametrize(
    "raised", [ValueError(f"{_MARK} audit"), KeyError(_MARK)], ids=["value", "key"]
)
async def test_an_error_the_hook_raises_passes_as_it_is(raised: Exception) -> None:
    """The store decodes the rows before it awaits the hook, so what the hook raises is its own
    refusal: never read as an unreadable row, nor logged as one."""
    store = _HookingStore(GroupCreated(record=_RECORD))

    async def refuses(record: TradeGroupRecord) -> None:
        raise raised

    with structlog.testing.capture_logs() as logs, pytest.raises(type(raised)) as exc:
        await TradeGroupRepository(store).create(_draft(), [_leg_draft()], write_ahead=refuses)
    assert exc.value is raised and logs == []


@pytest.mark.parametrize(
    "legs",
    [[], [_leg_draft(), _leg_draft(leg_id=_OTHER, sequence_no=0)]],
    ids=["no-leg", "repeated-sequence-no"],
)
async def test_create_refuses_empty_legs_and_repeated_sequence_numbers_before_the_store(
    legs: list[LegDraft],
) -> None:
    repo, store = _repo(GroupCreated(record=_RECORD))
    with pytest.raises(ValueError, match="leg"):
        await repo.create(_draft(), legs, write_ahead=_hook)
    assert store.calls == []


async def test_create_refuses_a_missing_write_ahead_hook() -> None:
    """C-2.9: the type requires the hook; a caller that bypasses the type is refused too."""
    repo, store = _repo(GroupCreated(record=_RECORD))
    hook = cast(GroupWriteAhead, None)
    with pytest.raises(TypeError, match=r"C-2\.9"):
        await repo.create(_draft(), [_leg_draft()], write_ahead=hook)
    assert store.calls == []


# -- updates and reads -----------------------------------------------------------------------------


async def test_update_leg_sends_the_patch_and_the_expected_status() -> None:
    update = LegUpdate(native_sl_confirmed=True, native_sl_confirmed_at=1_789_132_262_110_000)
    repo, store = _repo(_LEG_ROW)
    leg = await repo.update_leg(GroupId(_GROUP), _LEG, update, expected_status="filled")
    assert store.calls == [
        ("update_leg", (_GROUP, _LEG, leg_patch(update)), {"expected_status": "filled"})
    ]
    assert (leg.leg_id, leg.status) == (_LEG, "filled")  # the scripted row, as stored


async def test_update_group_sends_the_patch_and_the_expected_status() -> None:
    update = GroupUpdate(status="open", opened_at=1_789_132_262_110_000)
    repo, store = _repo(_GROUP_ROW)
    group = await repo.update_group(GroupId(_GROUP), update, expected_status="submitting")
    assert store.calls == [
        ("update_group", (_GROUP, group_patch(update)), {"expected_status": "submitting"})
    ]
    assert group.group_id == _GROUP and group.note == f"{_MARK} note"


async def test_reads_map_rows_to_the_models() -> None:
    repo, _ = _repo(_RECORD)
    assert (await repo.get(GroupId(_GROUP))).legs[0].leg_id == _LEG
    repo, _ = _repo(_SNAPSHOT_ROW)
    assert (await repo.leg_with_profile(_LEG)).profile == _P
    repo, _ = _repo((_RECORD, _RECORD))
    assert [r.group.group_id for r in await repo.open_groups()] == [_GROUP, _GROUP]
    repo, _ = _repo((_UNPROTECTED_ROW,))
    (unprotected,) = await repo.unprotected_legs()
    assert unprotected.leg.unprotected and unprotected.side == "buy"
    repo, _ = _repo(())
    assert await repo.open_groups() == () and await repo.unprotected_legs() == ()


# -- a stored row the models refuse fails closed ---------------------------------------------

_SNAPSHOT = _SNAPSHOT_ROW.profile_snapshot
#: A side label `tg_side` never stores: what a schema drift would read.
_LONG: dict[str, Any] = {"side": "Long"}
#: A policy `tg_policy` never stores (the value the 0039 Postgres suite has it refuse).
_COMPENSATE: dict[str, Any] = {"leg_failure_policy": "compensate"}
#: (stored answer, call, the ids logged, the error class logged); each carries a P1 marker.
_UNREADABLE: dict[str, tuple[object, str, dict[str, str], str]] = {
    "leg-without-stop": (
        replace(_LEG_ROW, resolved_sl_price=None, rejection_message=f"{_MARK} message"),
        "update_leg",
        {"group_id": str(_GROUP), "leg_id": str(_LEG)},
        "ValidationError",
    ),
    "unknown-label": (
        replace(_GROUP_ROW, **_LONG),
        "update_group",
        {"group_id": str(_GROUP)},
        "KeyError",
    ),
    "unknown-policy": (
        replace(_GROUP_ROW, **_COMPENSATE),
        "update_group",
        {"group_id": str(_GROUP)},
        "ValidationError",
    ),
    "naive-time": (
        TradeGroupRecord(group=replace(_GROUP_ROW, created_at=_T.replace(tzinfo=None)), legs=()),
        "get",
        {"group_id": str(_GROUP)},
        "TypeError",
    ),
    "foreign-snapshot": (
        LegSnapshotRow(leg=_LEG_ROW, profile_snapshot=_SNAPSHOT | {"account_id": str(_OTHER)}),
        "leg_with_profile",
        {"leg_id": str(_LEG)},
        "ValueError",
    ),
    "open-group-without-price": (
        (TradeGroupRecord(group=replace(_GROUP_ROW, entry_price=None), legs=()),),
        "open_groups",
        {"group_id": str(_GROUP)},
        "ValidationError",
    ),
    "unprotected-label": (
        (replace(_UNPROTECTED_ROW, **_LONG),),
        "unprotected_legs",
        {"leg_id": str(_LEG)},
        "KeyError",
    ),
    "created-unreadable": (
        GroupCreated(record=TradeGroupRecord(group=replace(_GROUP_ROW, **_LONG), legs=())),
        "create",
        {"group_id": str(_GROUP)},
        "KeyError",
    ),
}


@pytest.mark.parametrize(
    ("answer", "call", "ids", "error"), list(_UNREADABLE.values()), ids=list(_UNREADABLE)
)
async def test_an_unreadable_row_fails_closed_with_its_error_class_only(
    answer: object, call: str, ids: dict[str, str], error: str
) -> None:
    """A schema drift is never served half-read: the caller gets one `AccountsError`, unchained,
    and the log names the ids and the error class, never a value of the row."""
    repo, _ = _repo(answer)
    with structlog.testing.capture_logs() as logs, pytest.raises(AccountsError) as exc:
        await _CALLS[call](repo)
    assert type(exc.value) is AccountsError and str(exc.value) == "stored trade group unreadable"
    assert exc.value.__cause__ is None and exc.value.__suppress_context__
    assert logs == [
        {"event": "trade_group.read_failed_closed", "error": error, "log_level": "warning"} | ids
    ]
    assert _MARK not in repr(logs)


#: The ids each call logs when the store cannot decode a row it read (none for a list).
_CALL_IDS: dict[str, dict[str, str]] = {
    "find_replay": {},
    "create": {"group_id": str(_GROUP)},
    "update_leg": {"group_id": str(_GROUP), "leg_id": str(_LEG)},
    "update_group": {"group_id": str(_GROUP)},
    "get": {"group_id": str(_GROUP)},
    "leg_with_profile": {"leg_id": str(_LEG)},
    "open_groups": {},
    "unprotected_legs": {},
}


@pytest.mark.parametrize(
    "raised",
    [ValueError(f"{_MARK} fraction"), TypeError(_MARK), KeyError(_MARK), ArithmeticError(_MARK)],
    ids=["value", "type", "key", "arithmetic"],
)
@pytest.mark.parametrize("call", list(_CALLS))
async def test_a_row_the_store_cannot_decode_fails_closed_on_every_call(
    call: str, raised: Exception
) -> None:
    """`parse_json` refusing a stored `algo_params` or snapshot, or any other decode error the
    store raises, fails closed as a row a model refuses does: one `AccountsError`, unchained,
    and a log of the ids and the error class, never a value."""
    repo, store = _repo(raised)
    with structlog.testing.capture_logs() as logs, pytest.raises(AccountsError) as exc:
        await _CALLS[call](repo)
    assert type(exc.value) is AccountsError and str(exc.value) == "stored trade group unreadable"
    assert exc.value.__cause__ is None and exc.value.__suppress_context__
    error = type(raised).__name__
    assert logs == [
        {"event": "trade_group.read_failed_closed", "error": error, "log_level": "warning"}
        | _CALL_IDS[call]
    ]
    assert _MARK not in repr(logs) and len(store.calls) == 1


# -- the scoped read (SR-E28-21) -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scope", "shows"),
    [
        (OwnerScope(_OTHER), True),
        (GrantScope(_USER, frozenset({_P.account_id})), True),
        (GrantScope(_OTHER, frozenset({_P.account_id})), False),
    ],
    ids=["owner", "creator", "another-manager"],
)
async def test_scoped_get_sets_shows_private_fields(scope: AccountScope, shows: bool) -> None:
    store = _Store(_RECORD)
    scoped = await TradeGroupReader(store).get(scope, GroupId(_GROUP))
    assert scoped.shows_private_fields is shows and scoped.record.group.group_id == _GROUP
    assert store.calls == [("get_group", (scope, _GROUP), {})]


async def test_a_scoped_miss_is_not_found_and_a_false_owner_is_denied() -> None:
    """The store reads an ungranted, foreign or missing group alike (`None`): one not-found."""
    reader = TradeGroupReader(_Store(None))
    with pytest.raises(AccountNotFoundError) as missing:
        await reader.get(GrantScope(_USER, frozenset()), GroupId(_GROUP))
    assert missing.value.entity == "trade_group"
    reader = TradeGroupReader(_Store(TradeGroupStoreScopeDeniedError()))
    with pytest.raises(AccountScopeDeniedError) as denied:
        await reader.get(_OWNER, GroupId(_GROUP))
    assert denied.value.__cause__ is None and denied.value.__suppress_context__


async def test_a_scoped_read_passes_storage_errors_and_fails_closed_on_a_bad_row() -> None:
    raised = StorageTierUnavailable()
    with pytest.raises(StorageTierUnavailable) as exc:
        await TradeGroupReader(_Store(raised)).get(_OWNER, GroupId(_GROUP))
    assert exc.value is raised
    bad = TradeGroupRecord(group=replace(_GROUP_ROW, **_LONG), legs=())
    with pytest.raises(AccountsError, match="stored trade group unreadable"):
        await TradeGroupReader(_Store(bad)).get(_OWNER, GroupId(_GROUP))
    undecodable = TradeGroupReader(_Store(ValueError(f"{_MARK} fraction")))
    with structlog.testing.capture_logs() as logs, pytest.raises(AccountsError) as failed:
        await undecodable.get(_OWNER, GroupId(_GROUP))
    assert str(failed.value) == "stored trade group unreadable" and failed.value.__cause__ is None
    assert logs == [
        {
            "event": "trade_group.read_failed_closed",
            "error": "ValueError",
            "group_id": str(_GROUP),
            "log_level": "warning",
        }
    ]
