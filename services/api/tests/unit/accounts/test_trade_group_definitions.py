"""The trade-group definition domain (E28-T05 #909, slice S1b): the model's bounds, the two guards,
the ETag, the store adapters and the refusal map. The store itself is pinned on Postgres by
`tests/integration/storage/test_trade_group_definitions_store_pg.py`.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import pytest
import structlog
from pydantic import ValidationError

from candleviewer.accounts.errors import (
    AccountConflictError,
    AccountNotFoundError,
    AccountRuleError,
    AccountScopeDeniedError,
    AccountsError,
    AccountVersionConflictError,
)
from candleviewer.accounts.profiles import SymbolEntries, SymbolScope, to_us
from candleviewer.accounts.trade_group_definitions import (
    MAX_MEMBERS,
    MAX_NAME_CHARS,
    MIXED_ENVIRONMENTS,
    NO_COMMON_SYMBOL,
    DefinitionInput,
    DefinitionMember,
    DuplicateMember,
    MemberAccount,
    StoredDefinition,
    common_symbols,
    definition_error,
    definition_etag,
    environment_mismatches,
    new_definition,
    stored_definition,
)
from candleviewer.api._generated.openapi_models import TradeGroupDefinitionInput
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.storage.repositories import trade_group_definitions as port
from candleviewer.storage.repositories.trade_groups import ACCOUNT_NOT_LIVE
from tests._corpus import rest

A, B, C, L = (AccountId(UUID(int=n)) for n in range(1, 5))
_ID: Final = UUID("0b5f6d0e-28a1-4c1e-9e01-0000000000d1")
_CREATED: Final = datetime(2026, 10, 27, 3, 0, tzinfo=UTC)
_UPDATED: Final = datetime(2026, 10, 27, 3, 5, 0, 123456, tzinfo=UTC)
_REPO: Final = Path(__file__).resolve().parents[5]
#: What a driver's text would carry, were it ever put on a store error.
_VALUE: Final = "Failing row contains (Core3, demo)"


def _listing() -> tuple[Instrument, ...]:
    """The recorded catalogue (C-13.5): BTC, ETH and SOL USDT trading, LUNAUSDT made closed, and
    BTCUSDT copied as BTCPERP, a trading USDC perpetual, as `test_profile_validator` patches it."""
    rows = rest("rest/instruments_before.json")["result"]["list"]
    listed = {i.symbol: i for i in parse_instruments(rows, fetched_at_us=0).instruments}
    listed["LUNAUSDT"] = listed["LUNAUSDT"].model_copy(update={"status": "closed"})
    perp = {"symbol": "BTCPERP", "quote_coin": "USDC", "settle_coin": "USDC"}
    return (*listed.values(), listed["BTCUSDT"].model_copy(update=perp))


LISTED: Final = _listing()


def _definition(
    *accounts: AccountId, off: frozenset[AccountId] = frozenset(), name: str = "Core3"
) -> DefinitionInput:
    members = tuple(DefinitionMember(account_id=a, enabled=a not in off) for a in accounts)
    return DefinitionInput(name=name, environment="demo", members=members)


def _scope(*allowed: str, every: bool = False, denied: tuple[str, ...] = ()) -> SymbolScope:
    return SymbolScope(every, SymbolEntries.of(allowed), SymbolEntries.of(denied))


def _record(*members: port.MemberRow, created_at: datetime = _CREATED) -> port.DefinitionRecord:
    owner = UUID(int=42)
    row = port.DefinitionRow(_ID, "Core3", "demo", owner, owner, created_at, _UPDATED)
    return port.DefinitionRecord(row, members)


def _shown(error: Exception) -> tuple[type[Exception], tuple[Any, ...], dict[str, Any]]:
    return type(error), error.args, vars(error)


def test_a_definition_holds_one_to_twenty_members() -> None:
    """SCR-062 (at least one) and SR-E28-17 (at most 20): the contract's bounds, as constants. A
    member is the contract's closed, frozen shape: a lax switch and an extra key are refused, and
    a field cannot be assigned."""
    bounds = TradeGroupDefinitionInput.model_json_schema()["properties"]["members"]
    assert (bounds["minItems"], bounds["maxItems"]) == (1, MAX_MEMBERS) == (1, 20)
    many = [AccountId(UUID(int=n)) for n in range(1, MAX_MEMBERS + 2)]
    assert len(_definition(*many[:MAX_MEMBERS]).members) == MAX_MEMBERS
    assert _definition(A).members == (DefinitionMember(account_id=A),)
    for accounts in ([], many):
        with pytest.raises(ValidationError):
            _definition(*accounts)
    for raw in ({"enabled": "yes"}, {"note": "x"}):  # `StrictBool`; `extra="forbid"`
        with pytest.raises(ValidationError):
            DefinitionMember.model_validate({"account_id": A} | raw)
    member = DefinitionMember(account_id=A)
    with pytest.raises(ValidationError):  # `frozen`
        member.enabled = False


def test_a_repeated_account_names_its_index() -> None:
    """SR-E28-17, PF-T17: one member per account, whatever its switch. The error names the
    repeat's place for 22's `members[i]` and no account."""
    for accounts, off, index in (([A, B, A], {A}, 2), ([C, C, B, B], set(), 1)):
        with pytest.raises(DuplicateMember) as repeated:
            _definition(*accounts, off=frozenset(off))
        assert isinstance(repeated.value, AccountRuleError)
        assert (repeated.value.index, repeated.value.args) == (index, ("duplicate_account",))
    enabled = DefinitionMember(account_id=A)
    disabled = DefinitionMember(account_id=A, enabled=False)
    for pair in ((enabled, disabled), (disabled, enabled)):  # a repeat with the other switch
        with pytest.raises(DuplicateMember) as switched:
            DefinitionInput(name="Core3", environment="demo", members=pair)
        assert switched.value.index == 1


def test_a_name_is_one_to_eighty_storable_characters() -> None:
    """`tgd_name` counts characters, as `len` does; U+0000 and a lone surrogate never reach it."""
    bounds = TradeGroupDefinitionInput.model_json_schema()["properties"]["name"]
    assert (bounds["minLength"], bounds["maxLength"]) == (1, MAX_NAME_CHARS) == (1, 80)
    for name in ("N", "x" * MAX_NAME_CHARS, "€" * MAX_NAME_CHARS):
        assert _definition(A, name=name).name == name
    for name in ("", "x" * (MAX_NAME_CHARS + 1), "a\x00b", "a\ud800b"):
        with pytest.raises(ValidationError):
            _definition(A, name=name)


def test_every_member_outside_the_environment_is_named_in_member_order() -> None:
    """AC 2, SR-E28-16: each member outside, in member order and the last one included; a member
    whose environment is unknown is outside too (fail closed)."""
    envs: dict[AccountId, Environment] = {A: "demo", B: "live", C: "demo", L: "testnet"}
    unknown = AccountId(UUID(int=99))
    assert environment_mismatches(_definition(B, A, unknown, C, L), envs) == (B, unknown, L)
    assert environment_mismatches(_definition(A, C), envs) == ()
    assert "cannot mix Demo and Live" in MIXED_ENVIRONMENTS


def test_disjoint_allow_lists_have_no_symbol_in_common() -> None:
    """AC 3: A allows only BTCUSDT and B only ETHUSDT. The refusal is SCR-062's sentence."""
    scopes = {A: _scope("BTCUSDT"), B: _scope("ETHUSDT")}
    assert common_symbols(_definition(A, B), scopes, LISTED) == frozenset()
    assert common_symbols(_definition(A), scopes, LISTED) == {"BTCUSDT"}
    catalogue = (_REPO / "docs/plan/14-screens-catalogue.md").read_text(encoding="utf-8")
    assert f'("{NO_COMMON_SYMBOL}")' in catalogue


def test_the_intersection_reads_the_sizers_gate() -> None:
    """A pattern matches a trading USDT perpetual, a block entry wins over the allow side, an
    empty allow-list allows nothing, and a symbol both allow that is not a trading USDT
    perpetual (BTCPERP, the closed LUNAUSDT) is never in common."""
    every = _scope(every=True)
    cases: list[tuple[dict[AccountId, SymbolScope], set[str]]] = [
        ({A: _scope("*USDT"), B: _scope("BTCUSDT", "ETHUSDT")}, {"BTCUSDT", "ETHUSDT"}),
        ({A: every, B: _scope("*USDT", denied=("ETHUSDT",))}, {"BTCUSDT", "SOLUSDT"}),
        ({A: every, B: _scope()}, set()),
        ({A: every, B: _scope("BTCPERP", "LUNAUSDT", "SOLUSDT")}, {"SOLUSDT"}),
    ]
    for scopes, common in cases:
        assert common_symbols(_definition(A, B), scopes, LISTED) == common


def test_a_member_without_a_bound_profile_admits_nothing() -> None:
    """Fail closed: a member that `scopes` lacks allows no symbol, so none is in common."""
    assert common_symbols(_definition(A, B), {A: _scope(every=True)}, LISTED) == frozenset()
    assert common_symbols(_definition(B), {}, LISTED) == frozenset()


def test_a_disabled_member_still_counts() -> None:
    """A member switched off stays in the definition: it narrows the intersection and must share
    the environment, so switching it on never changes what was saved."""
    definition = _definition(A, B, off=frozenset({B}))
    scopes = {A: _scope("BTCUSDT", "ETHUSDT"), B: _scope("ETHUSDT")}
    assert common_symbols(definition, scopes, LISTED) == {"ETHUSDT"}
    assert environment_mismatches(definition, {A: "demo", B: "live"}) == (B,)


def test_the_etag_moves_with_updated_at_and_names_no_member() -> None:
    """Weak, over the id and `updated_at`, which every write moves; never the members' accounts,
    which readiness reads, and never an id in the clear."""
    stored = stored_definition(_record(port.MemberRow(A, True, "demo", True)))
    tag = definition_etag(stored)
    assert re.fullmatch(r'W/"[0-9a-f]{16}"', tag)
    moved = replace(stored, updated_at=stored.updated_at + 1)
    other = replace(stored, definition_id=UUID(int=7))
    assert len({tag, definition_etag(moved), definition_etag(other)}) == 3
    unready = replace(stored, member_accounts=(MemberAccount(A, "demo", False),))
    assert definition_etag(unready) == tag


def test_each_store_refusal_maps_by_name_and_carries_no_value() -> None:
    """Every name the store refuses with, and its scope and stale errors, maps to a fresh accounts
    error that holds one name and nothing of the store error's (C-12.6); any other fails closed,
    and so does a name under the other kind of store error."""
    by_name: dict[str, Exception] = {
        "ux_tgd_name": AccountConflictError("ux_tgd_name"),
        "trade_group_definitions_pkey": AccountConflictError("trade_group_definitions_pkey"),
        "tgd_name": AccountRuleError("tgd_name"),
        "trg_tgdm_env": AccountRuleError("environment_mismatch"),
        "trg_tgd_write_once": AccountRuleError("write_once"),
        "trade_group_definition_members_exchange_account_id_fkey": AccountNotFoundError("account"),
        ACCOUNT_NOT_LIVE: AccountNotFoundError("account"),
    }
    assert set(by_name) == port.DEFINITION_RULES | port.DEFINITION_CONFLICTS | {ACCOUNT_NOT_LIVE}
    conflict, rule = port.DefinitionConflictError, port.DefinitionRuleError
    cases: list[tuple[port.DefinitionStoreError, Exception]] = [
        (conflict(n) if n in port.DEFINITION_CONFLICTS else rule(n), e) for n, e in by_name.items()
    ]
    cases += [
        (port.DefinitionScopeDeniedError(), AccountScopeDeniedError()),
        (port.DefinitionStaleError(), AccountVersionConflictError()),
        (rule("tgd_unknown"), AccountsError("store error")),
        (port.DefinitionStoreError(), AccountsError("store error")),
        (conflict("trg_tgdm_env"), AccountsError("store error")),  # a rule's name as a conflict
        (rule("ux_tgd_name"), AccountsError("store error")),  # a conflict's name as a rule
    ]
    for refusal, expected in cases:
        refusal.args = (*refusal.args, _VALUE)
        refusal.add_note(_VALUE)
        mapped = definition_error(refusal)
        assert _shown(mapped) == _shown(expected), refusal
        assert mapped.__cause__ is None and _VALUE not in repr(mapped)


def test_a_stored_definition_reads_back_as_written() -> None:
    """`new_definition` is what the store writes, with no writer (the store takes its Owner's);
    the record it reads back maps to the same input, its times in `TsUs`."""
    definition = _definition(A, B, off=frozenset({B}))
    members = (port.NewMember(A, True), port.NewMember(B, False))
    expected = port.NewDefinition(id=_ID, name="Core3", env="demo", members=members)
    assert new_definition(_ID, definition) == expected
    stored = stored_definition(
        _record(port.MemberRow(A, True, "demo", True), port.MemberRow(B, False, "demo", False))
    )
    accounts = (MemberAccount(A, "demo", True), MemberAccount(B, "demo", False))
    assert stored == StoredDefinition(_ID, definition, to_us(_CREATED), to_us(_UPDATED), accounts)


@pytest.mark.parametrize(
    ("members", "created_at", "error"),
    [
        ((), _CREATED, "ValidationError"),
        ((A, A), _CREATED, "DuplicateMember"),
        ((A,), _CREATED.replace(tzinfo=None), "TypeError"),
    ],
    ids=["no_member", "an_account_twice", "a_naive_timestamp"],
)
def test_an_unreadable_stored_row_fails_closed(
    members: tuple[UUID, ...], created_at: datetime, error: str
) -> None:
    """A row the model refuses (or a time `to_us` refuses) is a schema drift: `AccountsError`,
    logged by id and error class alone, as the fired-group facade does."""
    rows = tuple(port.MemberRow(m, True, "demo", True) for m in members)
    with structlog.testing.capture_logs() as logs, pytest.raises(AccountsError) as failed:
        stored_definition(_record(*rows, created_at=created_at))
    assert _shown(failed.value) == _shown(AccountsError("stored trade group definition unreadable"))
    assert failed.value.__cause__ is None and failed.value.__suppress_context__
    event = "trade_group_definition.read_failed_closed"
    assert logs == [
        {"event": event, "definition_id": str(_ID), "error": error, "log_level": "warning"}
    ]
