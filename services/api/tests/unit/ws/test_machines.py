"""E17-T08 `machines.{entity}.state` (`23-ws-protocol.md` §6.4): the entity grammar, the per-entity
refusal with no existence oracle, the bounded registry that answers `sub`, entity-scoped matching
and the §9.5 re-check on the stored scope. No network, no clock reads, no sleeps."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.ws.machines import MachineEntity, MachineStateRegistry
from candleviewer.ws.permissions import VersionedSnapshot
from candleviewer.ws.sequencing import SequencingHub
from candleviewer.ws.topics import MACHINE_KINDS, EntityScope, TopicError, machine_refusal
from candleviewer.ws.topics import parse_topic as parse
from tests.unit.ws._seq_support import Conn, Source, principal

A, B = uuid.UUID(int=0xA), uuid.UUID(int=0xB)
OID, OTHER = "0a000000-0000-4000-8000-000000000001", "0a000000-0000-4000-8000-000000000002"
ON_A, ON_B = EntityScope(accounts=frozenset({A})), EntityScope(accounts=frozenset({B}))
_SEED = Path(__file__).resolve().parents[3] / "candleviewer" / "auth" / "rbac_seed.json"
_ROLES: dict[str, list[str]] = json.loads(_SEED.read_text(encoding="utf-8"))["role_permissions"]


def _who(role: str, uid: int, *grants: uuid.UUID) -> PrincipalSnapshot:
    perms = frozenset(p for p in Permission if {"*", p.value} & set(_ROLES[role]))
    held = tuple(AccountGrant(a, True, False, False) for a in grants)
    return PrincipalSnapshot(uuid.UUID(int=uid), frozenset({role}), perms, held)


OWNER = _who("owner", 1)
#: The RBAC matrix actors in column order: owner, manager with and without the grant on A, viewer.
ACTORS = (OWNER, _who("manager", 2, A), _who("manager", 3), _who("viewer", 4))
BARE = PrincipalSnapshot(uuid.UUID(int=5), frozenset({"viewer"}), frozenset())  # no permission


def _payload(kind: str = "order", state: str = "submitted") -> dict[str, Any]:
    return {"machine_kind": kind, "state": state, "tags": [], "degraded": False,
            "machine_hash": "0" * 64, "environment": "demo", "updated_at_ms": 1}  # fmt: skip


# -- grammar -------------------------------------------------------------------------------------

_HEX = "[0-9a-f]"
_ID = {
    "uuid": f":{_HEX}{{8}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{12}}",
    "symbol": ":[A-Z0-9]{2,20}USDT",
    "singleton": "",
}
#: The §6.4 grammar as an oracle, written independently of the parser's code path.
_REFERENCE = re.compile("|".join(re.escape(k) + _ID[m.id_format] for k, m in MACHINE_KINDS.items()))


@given(
    st.sampled_from(sorted(MACHINE_KINDS)),
    st.uuids(),
    st.from_regex("[A-Z0-9]{2,20}USDT", fullmatch=True),
)
def test_parse_every_kind_with_a_valid_id_round_trips(kind: str, oid: uuid.UUID, sym: str) -> None:
    fmt = MACHINE_KINDS[kind].id_format
    ident = {"uuid": str(oid), "symbol": sym, "singleton": None}[fmt]
    topic = parse(MachineEntity(kind, ident).ch)
    assert (topic.entity_kind, topic.symbol) == (kind, ident if fmt == "symbol" else None)
    assert len(topic.ch) <= 66 and topic.family.family == "machines"


_VALID = st.from_regex(_REFERENCE, fullmatch=True)
_NOISE = st.text(alphabet="abcdeghiklnoprstuvwyBCDSTU0145:-_", max_size=48)


@given(st.one_of(_VALID, _VALID.map(lambda e: e[:-1]), _VALID.map(str.upper), _NOISE))
def test_parse_accepts_exactly_the_entities_of_the_6_4_grammar(entity: str) -> None:
    try:
        accepted = parse(f"machines.{entity}.state").entity_kind is not None
    except TopicError as exc:
        accepted = False
        assert exc.code == "invalid_topic_format", entity
    assert accepted is (_REFERENCE.fullmatch(entity) is not None), entity


@pytest.mark.parametrize(
    ("ch", "code"),
    [
        (f"machines.order:{OID.upper()}.state", "invalid_topic_format"),  # one spelling only
        (f"machines.kill_switch:{OID}.state", "invalid_topic_format"),  # a singleton has no id
        ("machines.order.state", "invalid_topic_format"),
        (f"machines.position_protection:{OID}.state", "invalid_topic_format"),  # W9
        ("machines.book:BTCUSDT:50.state", "invalid_topic_format"),  # the tier is internal
        ("machines.recording:btcusdt.state", "invalid_topic_format"),
        (f"machines.order:{OID}.status", "invalid_topic_format"),
        (f"machines.order:{OID}\n.state", "invalid_topic_format"),
        ("machines.book:ZZZUSDT.state", "unsupported_symbol"),
        ("book.BTC-USDT.50", "invalid_topic_format"),  # `-` stays illegal elsewhere
    ],
)
def test_parse_refuses(ch: str, code: str) -> None:
    with pytest.raises(TopicError) as exc:
        parse(ch, instrument_known=lambda s: s == "BTCUSDT")
    assert exc.value.code == code


def test_machine_entity_refuses_an_id_outside_the_grammar() -> None:
    with pytest.raises(ValueError, match="machine entity"):  # a publisher bug, not a wire refusal
        MachineEntity("order", OID.upper())


# -- the no-oracle rule (the 13 x 5 cells run end to end in tests/contract/rbac) ------------------


def _code(who: PrincipalSnapshot, kind: str, scope: EntityScope | None) -> str | None:
    refusal = machine_refusal(who, kind, scope)
    return None if refusal is None else refusal[0]


@pytest.mark.parametrize("kind", sorted(k for k, m in MACHINE_KINDS.items() if m.scope != "none"))
def test_unknown_unscoped_and_foreign_entities_get_one_refusal(kind: str) -> None:
    foreign = EntityScope(accounts=frozenset({B}), user=uuid.UUID(int=9))
    for who in (*ACTORS, BARE):
        sees_b = who.is_owner and MACHINE_KINDS[kind].scope == "granted_accounts"
        scopes = (None, EntityScope(), *(() if sees_b else (foreign,)))
        codes = {_code(who, kind, s) for s in scopes}
        assert len(codes) == 1 and None not in codes, (kind, who.roles, codes)


@pytest.mark.parametrize(
    ("who", "scope", "expected"),
    [
        (BARE, ON_A, ("forbidden", "role")),  # the permission step comes first
        (ACTORS[1], None, ("account_scope_denied", "unknown")),
        (ACTORS[1], EntityScope(), ("account_scope_denied", "unscoped")),
        (ACTORS[1], ON_B, ("account_scope_denied", "foreign")),
        (ACTORS[1], EntityScope(accounts=frozenset({A, B})), ("account_scope_denied", "foreign")),
    ],
)
def test_refusal_and_its_internal_reason(
    who: PrincipalSnapshot, scope: EntityScope | None, expected: tuple[str, str]
) -> None:
    assert machine_refusal(who, "order", scope) == expected  # every account must be granted


def test_unknown_and_foreign_entities_get_the_identical_sub_error() -> None:
    conn, registry, _ = _world()
    registry.publish(MachineEntity("order", OTHER, ON_B), _payload())
    unknown, _ = conn.authz.admit(f"machines.order:{OID}.state")
    foreign, _ = conn.authz.admit(f"machines.order:{OTHER}.state")
    expected = {"code": "account_scope_denied", "message": _SCOPE_MESSAGE}
    assert unknown["error"] == foreign["error"] == expected


_SCOPE_MESSAGE = "None of the requested accounts are in scope."  # §6.2, whatever the cause


# -- registry, matching and the sub flow -----------------------------------------------------------


def _world(**kw: Any) -> tuple[Conn, MachineStateRegistry, SequencingHub]:
    """A manager granted account A, whose `sub` is authorised and snapped from the registry."""
    registry, hub, conn = MachineStateRegistry(**kw), SequencingHub(), Conn(Source())
    services = conn.authz.services
    services.machines = services.snapshots = conn.emitter.source = registry
    hub.register(conn.authz, conn.emitter)
    return conn, registry, hub


def test_sub_is_snapped_from_the_registry() -> None:
    conn, registry, _ = _world()
    order = MachineEntity("order", OID, ON_A)
    registry.publish(order, _payload())
    result, _ = conn.sub(order.ch)
    assert result["effective"] == {"throttle_ms": 100, "encoding": "structured", "coalesce": True}
    (snap,) = conn.take()  # validated against the envelope and §15.10
    assert (snap["s"], snap["meta"]["reason"], snap["p"]["state"]) == (1, "initial", "submitted")


def test_a_delta_reaches_the_subscriber_of_its_entity() -> None:
    conn, registry, hub = _world()
    order = MachineEntity("order", OID, ON_A)
    registry.publish(order, _payload())
    conn.sub(order.ch)
    assert hub.publish(order.ch, _payload(state="filled")) == 1
    d = conn.take()[-1]
    assert (d["t"], d["s"], d["p"]["state"]) == ("d", 2, "filled")


def test_unscoped_kind_without_an_entry_stays_pending() -> None:
    conn, _, _ = _world()
    result, _ = conn.sub("machines.kill_switch.state")
    assert result["snapshot_pending"] is True and conn.take() == []


def test_registry_bound_refuses_a_new_entity() -> None:
    conn, registry, _ = _world(max_entries=1)
    one, two = MachineEntity("order", OID, ON_A), MachineEntity("order", OTHER, ON_A)
    with capture_logs() as logs:
        assert registry.publish(one, _payload()) and not registry.publish(two, _payload())
    assert [(e["event"], e["entity_kind"]) for e in logs] == [
        ("machine state refused: registry full", "order")
    ]
    assert conn.authz.admit(two.ch)[0]["error"]["code"] == "account_scope_denied"


def test_registry_bound_keeps_updating_the_others() -> None:
    _, registry, _ = _world(max_entries=1)
    one, two = MachineEntity("order", OID, ON_A), MachineEntity("order", OTHER, ON_A)
    registry.publish(one, _payload())
    registry.publish(two, _payload())
    assert registry.publish(one, _payload(state="filled")) and len(registry) == 1


def test_terminal_payload_is_the_entitys_last() -> None:
    conn, registry, _ = _world()
    order = MachineEntity("order", OID, ON_A)
    assert registry.terminal(order, _payload(state="filled"))
    assert not registry.publish(order, _payload()) and not registry.terminal(order, _payload())
    conn.sub(order.ch)
    assert conn.take()[0]["p"]["state"] == "filled"


def test_scope_is_bound_by_the_first_payload() -> None:
    registry = MachineStateRegistry()
    registry.publish(MachineEntity("order", OID, ON_A), _payload())
    registry.publish(MachineEntity("order", OID, ON_B), _payload(state="filled"))
    assert registry.scope(f"machines.order:{OID}.state") == ON_A


def test_sub_refuses_exchange_account_ids() -> None:
    entry = {"ch": "machines.kill_switch.state", "opts": {"exchange_account_ids": [str(A)]}}
    result, sub = _world()[0].authz.admit(entry)
    assert sub is None and result["error"]["code"] == "invalid_options"


def test_snapshot_false_is_always_forced() -> None:
    conn, registry, _ = _world()
    registry.publish(MachineEntity("kill_switch"), _payload("kill_switch", "clear"))
    entry = {"ch": "machines.kill_switch.state", "opts": {"from_seq": 1, "from_ts_ms": 1}}
    result, _ = conn.sub(entry, snapshot=False)
    assert result["snapshot_forced"] is True and conn.take()[0]["t"] == "snap"


def test_book_entities_count_toward_the_symbol_cap_and_take_no_lease() -> None:
    conn, _, _ = _world()
    conn.sub({"ch": "ticker", "opts": {"symbols": [f"S{i:02d}USDT" for i in range(40)]}})
    over, _ = conn.authz.admit("machines.book:BTCUSDT.state")
    _, sub = conn.authz.admit("machines.book:S01USDT.state")
    assert over["error"]["code"] == "subscription_limit" and sub is not None
    assert asyncio.run(conn.authz.subscribe_upstream(sub)) is None
    assert conn.authz.services.upstream.active() == set()


# -- §9.5 re-check on the stored scope -------------------------------------------------------------


def test_recheck_reads_the_scope_stored_at_sub_and_revokes_a_lost_account() -> None:
    conn, registry, _ = _world()
    order = MachineEntity("order", OID, ON_A)
    registry.publish(order, _payload())
    conn.sub(order.ch)
    conn.authz.services.machines = MachineStateRegistry()  # the entry is gone: no lookup happens
    kept = conn.authz.apply_snapshot(VersionedSnapshot(principal(A), 1), 7) or []
    assert [f["t"] for f in kept] == ["permission_change"]
    lost = conn.authz.apply_snapshot(VersionedSnapshot(principal(), 2), 8) or []
    assert lost[1]["p"] == {
        "reason": "account_scope_changed",
        "message": "Access to one or more accounts was withdrawn.",
        "removed_accounts": [str(A)],
        "resubscribe_allowed": False,
    }
    assert conn.authz.find(order.ch) is None


def test_demoted_owner_loses_the_pending_decision_kinds_with_permission_revoked() -> None:
    conn, registry, _ = _world()
    conn.authz.principal = OWNER
    pending = [MachineEntity("trade_group", OID, ON_A), MachineEntity("live_gate")]
    pending.append(MachineEntity("reconciliation", str(A), ON_A))
    order = MachineEntity("order", OID, ON_A)
    for entity in (*pending, order):
        registry.publish(entity, _payload(entity.kind))
        conn.sub(entity.ch)
    frames = conn.authz.apply_snapshot(VersionedSnapshot(_who("manager", 1, A), 1), 7) or []
    assert {(f["ch"], f["p"]["reason"]) for f in frames[1:]} == {
        (e.ch, "permission_revoked") for e in pending
    }
    assert conn.authz.find(order.ch) is not None


def test_no_delta_reaches_a_principal_swapped_out_of_the_entity() -> None:
    conn, registry, hub = _world()
    order = MachineEntity("order", OID, ON_A)
    registry.publish(order, _payload())
    conn.sub(order.ch)
    conn.authz.principal = principal()  # §9.5 swaps the principal in before it removes anything
    assert hub.publish(order.ch, _payload(state="filled")) == 0
