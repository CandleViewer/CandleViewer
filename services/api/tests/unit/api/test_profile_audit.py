"""The `profile.*` records of the profile writes (#906 D2-2; the D2 spec Sec.4 and Sec.6.1; 24
Sec.15.5), without a route: each hook is awaited as the profile store awaits it, through
`bounded_write_ahead` inside the write's unit of work and before its commit (the store's own tests
pin that order), and a recording writer stands in for the audit writer. That writer also checks
every state it is given as `AuditWriter.build` would redact it: no member meets a secret or PII
name of `audit.redact`.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from candleviewer.accounts.models import ExchangeEnv
from candleviewer.accounts.profile_caps import PROFILE_CAPS
from candleviewer.accounts.profile_input import ProfileFieldError
from candleviewer.accounts.profiles import AccountProfile, profile_values
from candleviewer.api import profile_audit as mod
from candleviewer.api.profile_audit import (
    ProfileActor,
    ProfileAudit,
    ProfileAuditRefused,
    UnknownSaveRefusedReason,
    profile_state,
)
from candleviewer.audit.redact import redact
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories.account_profiles import (
    AccountProfileRow,
    AccountProfileValues,
    RelaxedNotice,
)
from candleviewer.storage.repositories.user_roles_sqlalchemy import bounded_write_ahead

_USER, _ACCOUNT, _PROFILE = (UUID(int=n) for n in (1, 2, 3))
_REQUEST = UUID("6f1c2a3b-4d5e-4f60-8a7b-9c0d1e2f3a4b")
_ACTOR = ProfileActor(_USER, "100.64.0.7", _REQUEST, ExchangeEnv.DEMO)
_T = datetime(2026, 10, 24, 9, tzinfo=UTC)
_CAPS = tuple(cap.column for cap in PROFILE_CAPS)
_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "profiles" / "risk_based.json"
#: The `risk_based` fixture in stored units (its ladder's `pct` is `5E+1`): trading on, every cap
#: bounded; an alternate, with a cap as Postgres reads `numeric(38,18)` and a block entry.
_TRADES = dataclasses.replace(
    profile_values(AccountProfile.model_validate_json(_FIXTURE.read_text(encoding="utf-8"))),
    is_default=False, max_position_notional_usd=Decimal("50000.000000000000000000"),
    sl_atr_multiple=Decimal("2.2500"), blocked_symbols=("DOGEUSDT",),
)  # fmt: skip
_STATE = {
    "exchange_account_id": str(_ACCOUNT), "version": 3, "name": "Risk 1%", "is_default": False,
    "enabled": True, "trading_enabled": True, "leverage": "5", "margin_mode": "cross",
    "position_mode": "one_way", "sizing_mode": "risk_based", "size_fixed_qty": None,
    "size_fixed_notional_usd": None, "size_pct_equity": None, "risk_pct_equity": "1",
    "risk_fixed_amount_usd": None, "min_leg_notional_usd": "5", "sl_offset_value": "20",
    "sl_offset_unit": "ticks", "sl_atr_period": 14, "sl_atr_multiple": "2.25",
    "fallback_sl_offset_pct": "2", "tp_offset_value": None, "tp_offset_unit": None,
    "tp_ladder": [{"pct": "50", "r": "1"}, {"pct": "50", "r": "2"}], "require_native_sl": True,
    "max_position_notional_usd": "50000", "max_position_pct_equity": None,
    "max_daily_loss_usd": "1000", "max_daily_loss_pct": "3", "max_open_positions": 3,
    "max_concurrent_orders": 20, "max_leverage_cap": "10", "max_orders_per_minute": 30,
    "all_symbols": False, "allowed_symbols": ["BTCUSDT", "ETHUSDT"],
    "blocked_symbols": ["DOGEUSDT"], "reduce_only_default": False, "time_in_force_default": "GTC",
    "slippage_tolerance_bps": 10,
}  # fmt: skip
_INERT = dataclasses.replace(_TRADES, trading_enabled=False)  # every cap counts as zero (D11)
_RAISED = dataclasses.replace(_TRADES, max_leverage_cap=Decimal(20))
_LOWERED = dataclasses.replace(_TRADES, max_leverage_cap=Decimal(5))
_WIDENED = dataclasses.replace(_TRADES, allowed_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"))
_UNCAPPED: dict[str, Any] = dict.fromkeys(_CAPS[:-1])  # `max_orders_per_minute` is NOT NULL
_CLEARED = dataclasses.replace(_INERT, **_UNCAPPED)  # R1C-08: cleared on a profile that can't trade
_NATIVE = ProfileFieldError("require_native_stop", "native_stop_mandatory", "Cannot be off.")
_SHAPE = ProfileFieldError("stop_loss.unit", "stop_defines_r", "The stop defines R.")
_NOTIONAL = ProfileFieldError("risk_caps.max_position_notional_usd", "min_notional", "Too low.")
_UNBOUNDED = ProfileFieldError("risk_caps.max_daily_loss_usd", "cap_unbounded", "Bound it.")


def _lev(i: int) -> ProfileFieldError:
    """A second-pass entry, with its limit and symbol."""
    return ProfileFieldError(f"allowed_symbols[{i}]", "max_leverage", "High.", Decimal(25), "X")


def _row(values: AccountProfileValues = _TRADES, *, version: int = 3) -> AccountProfileRow:
    return AccountProfileRow(_PROFILE, _ACCOUNT, version, values, _USER, _USER, _T, _T, None)


def _on(object_id: UUID, kind: str = "account_profile") -> dict[str, Any]:
    """The fields every record carries: the actor, the request, the environment and the object."""
    return {
        "actor_label": str(_USER), "actor_user_id": _USER, "actor_ip": "100.64.0.7",
        "session_id": None, "request_id": _REQUEST, "env": "demo", "object_kind": kind,
        "object_id": str(object_id),
    }  # fmt: skip


class _Writer:
    """Records each `emit`; `fails` raises it, and `hangs` waits until a bound cancels it."""

    def __init__(self, fails: Exception | None = None, *, hangs: bool = False) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []
        self._fails, self._hangs = fails, hangs

    async def emit(self, action: str, **kwargs: Any) -> None:
        if self._hangs:
            await asyncio.Event().wait()
        if self._fails is not None:
            raise self._fails
        for state in (kwargs.get("before_state"), kwargs.get("after_state")):
            assert redact(state) == state  # as `AuditWriter.build` redacts it: nothing to redact
        self.records.append((action, kwargs))


async def _ahead(hook: Awaitable[RelaxedNotice | None]) -> RelaxedNotice | None:
    return await bounded_write_ahead(hook, 5.0)  # as the profile store awaits it


def test_a_records_profile_is_every_stored_column_with_its_version_and_account() -> None:
    """24 Sec.15.5: the account, the `version` and every column of 21 Sec.3.2.4 in stored units,
    each decimal by `plain` (no exponent, no trailing fractional zero), never a float."""
    state = profile_state(_row())
    assert state == _STATE
    columns = {f.name for f in dataclasses.fields(AccountProfileValues)}
    assert set(_STATE) - {"exchange_account_id", "version"} == columns
    assert json.loads(json.dumps(state)) == state


@pytest.mark.parametrize("env", list(ExchangeEnv))
async def test_a_create_is_one_profile_created_record_ahead_of_its_commit(env: ExchangeEnv) -> None:
    """Every record carries the account's environment, whichever it is (C-2.11)."""
    writer, created = _Writer(), _row(version=1)
    actor = dataclasses.replace(_ACTOR, env=env)
    hook = ProfileAudit(writer, actor, _ACCOUNT).audit_created()
    assert await _ahead(hook(None, created)) is None
    state = {"after_state": profile_state(created), "outcome": "success", "severity": "info"}
    assert writer.records == [("profile.created", _on(_PROFILE) | {"env": env} | state)]


@pytest.mark.parametrize(
    ("before", "after", "caps", "widened"),
    [
        (_TRADES, _LOWERED, (), False),
        (_TRADES, _RAISED, ("max_leverage_cap",), False),
        (_TRADES, _WIDENED, (), True),
        (_INERT, _CLEARED, (), False),
    ],
    ids=["narrowed", "cap-raised", "symbols-widened", "r1c08-caps-cleared"],
)
async def test_an_update_records_before_and_after_and_its_relaxing_labels(
    before: AccountProfileValues, after: AccountProfileValues, caps: tuple[str, ...], widened: bool
) -> None:
    """The 17:25Z ruling (1): a looser cap or widened symbols of a profile that can trade; R1C-08's
    cleared caps of one that cannot is no relaxing, and its record shows the caps before."""
    writer, stood, saved = _Writer(), _row(before), _row(after, version=4)
    notice = await _ahead(ProfileAudit(writer, _ACTOR, _ACCOUNT).audit_updated()(stood, saved))
    relaxing = bool(caps) or widened
    labels = {"relaxing": relaxing, "looser_caps": list(caps), "widened_symbols": widened}
    states = {"before_state": profile_state(stood), "after_state": profile_state(saved) | labels}
    severity = {"outcome": "success", "severity": "warning" if relaxing else "info"}
    assert writer.records == [("profile.updated", _on(_PROFILE) | states | severity)]
    assert notice == (RelaxedNotice(_PROFILE, None, caps, widened, _REQUEST) if relaxing else None)


async def test_a_delete_records_the_profile_as_it_stood() -> None:
    writer, stood = _Writer(), _row()
    gone = dataclasses.replace(stood, version=4, deleted_at=_T)
    assert await _ahead(ProfileAudit(writer, _ACTOR, _ACCOUNT).audit_deleted()(stood, gone)) is None
    state = {"before_state": profile_state(stood), "outcome": "success", "severity": "info"}
    assert writer.records == [("profile.deleted", _on(_PROFILE) | state)]


@pytest.mark.parametrize("hook", ["audit_updated", "audit_deleted"])
async def test_a_record_with_no_profile_before_it_is_refused_unwritten(hook: str) -> None:
    """Rather than a wrong record: the store reads `before` for both writes, so none is a defect."""
    writer = _Writer()
    with pytest.raises(ProfileAuditRefused):
        await getattr(ProfileAudit(writer, _ACTOR, _ACCOUNT), hook)()(None, _row())
    assert writer.records == []


@pytest.mark.parametrize(
    ("errors", "profile_id", "records"),
    [
        ([_SHAPE, _NATIVE], _PROFILE, [("native_stop_mandatory", [_NATIVE])]),
        (
            [_NOTIONAL, _lev(0), _lev(1), _lev(2)],  # first named, last by name: the order kept
            _PROFILE,
            [("min_notional", [_NOTIONAL]), ("max_leverage", [_lev(0), _lev(1), _lev(2)])],
        ),
        ([_SHAPE, _SHAPE], _PROFILE, []),
        ([_NATIVE, _SHAPE], None, [("native_stop_mandatory", [_NATIVE])]),
        ([_UNBOUNDED] * 25, _PROFILE, [("cap_unbounded", [_UNBOUNDED] * 25)]),
    ],
    ids=[
        "native-stop-and-shape",
        "two-rules",
        "shape-only",
        "create-names-the-account",
        "first-20",
    ],
)
async def test_a_refused_save_is_one_record_per_audited_rule_and_none_for_shape(
    errors: list[ProfileFieldError],
    profile_id: UUID | None,
    records: list[tuple[str, list[ProfileFieldError]]],
) -> None:
    writer = _Writer()
    await ProfileAudit(writer, _ACTOR, _ACCOUNT).audit_refused(errors, profile_id=profile_id)
    named = _on(_ACCOUNT, "exchange_account") if profile_id is None else _on(profile_id)
    expected = [
        named | {"outcome": "denied", "severity": "warning", "reason": rule, "after_state": {
            "exchange_account_id": str(_ACCOUNT), "count": len(entries),
            "errors": [entry.to_dict() for entry in entries[:20]],
        }}
        for rule, entries in records
    ]  # fmt: skip
    assert writer.records == [("profile.save_refused", record) for record in expected]


async def test_a_refused_saves_record_holds_its_own_rules_entries_alone() -> None:
    """D2-2's R1S-01: even called directly, the record holds `reason`'s entries only, so no shape
    entry, with its client-chosen `field`, reaches it."""
    writer = _Writer()
    await ProfileAudit(writer, _ACTOR, _ACCOUNT).save_refused(
        "native_stop_mandatory", [_SHAPE, _NATIVE, _lev(0)], profile_id=_PROFILE
    )
    [(_, record)] = writer.records
    assert record["after_state"] == {
        "exchange_account_id": str(_ACCOUNT), "count": 1, "errors": [_NATIVE.to_dict()],
    }  # fmt: skip


@pytest.mark.parametrize("reason", ["step_up", "stop_defines_r", "max_leverage "])
async def test_save_refused_takes_only_a_closed_reason(reason: str) -> None:
    """R1S-03 (#4087): refused before anything is written, and the refusal echoes no reason."""
    writer = _Writer()
    with pytest.raises(UnknownSaveRefusedReason) as refused:
        await ProfileAudit(writer, _ACTOR, _ACCOUNT).save_refused(
            reason, [_lev(0)], profile_id=None
        )
    assert writer.records == [] and reason.strip() not in str(refused.value)
    assert isinstance(refused.value, ValueError)


def _writes(audit: ProfileAudit) -> list[Callable[[], Awaitable[object]]]:
    """Every record `audit` writes: the three hooks, then a refused save."""
    return [
        lambda: audit.audit_created()(None, _row()),
        lambda: audit.audit_updated()(_row(), _row()),
        lambda: audit.audit_deleted()(_row(), _row()),
        lambda: audit.audit_refused([_NATIVE], profile_id=_PROFILE),
    ]


@pytest.mark.parametrize(
    "failure",
    [AuditUnavailable("the WAL is full"), RuntimeError("not started"), TimeoutError()],
    ids=["audit-unavailable", "writer-not-started", "timeout-error"],
)
async def test_a_record_that_cannot_be_written_is_a_typed_refusal(failure: Exception) -> None:
    """Never swallowed, and never an `OSError`, which the store would map as its own failure."""
    for write in _writes(ProfileAudit(_Writer(failure), _ACTOR, _ACCOUNT)):
        with pytest.raises(ProfileAuditRefused) as refused:
            await write()
        assert refused.value.__cause__ is failure and not isinstance(refused.value, OSError)


async def test_a_record_past_its_bound_is_refused_and_a_hook_past_the_stores_is_its_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No sleep: a writer that never answers, and a bound of 0. A refusal's record has its own
    bound (`AUDIT_TIMEOUT_S`); a hook has the store's, whose overrun is `WriteAheadTimeout`."""
    audit = ProfileAudit(_Writer(hangs=True), _ACTOR, _ACCOUNT)
    monkeypatch.setattr(mod, "AUDIT_TIMEOUT_S", 0)
    with pytest.raises(ProfileAuditRefused) as refused:
        async with asyncio.timeout(2):  # without its bound the record would hang: fail instead
            await audit.save_refused("native_stop_mandatory", [_NATIVE], profile_id=_PROFILE)
    assert isinstance(refused.value.__cause__, TimeoutError)
    for write in _writes(audit)[:-1]:
        with pytest.raises(WriteAheadTimeout):
            await bounded_write_ahead(write(), 0)
