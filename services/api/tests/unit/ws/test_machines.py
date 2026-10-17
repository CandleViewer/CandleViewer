"""E17-T08 `machines.{entity}.state` (`23-ws-protocol.md` §6.4): the entity grammar, the per-entity
refusal with no existence oracle, the bounded registry that answers `sub` and fans each publish
out, its metrics, entity-scoped matching and the §9.5 re-check on the stored scope. No network, no
clock reads, no sleeps."""

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
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.ws.machines import MachineEntity, MachineStateRegistry
from candleviewer.ws.permissions import (
    ConnectionRegistry,
    VersionedSnapshot,
    handle_ctl,
    handle_sub,
    handle_unsub,
)
from candleviewer.ws.sequencing import SequencingHub
from candleviewer.ws.topics import MACHINE_KINDS, EntityScope, TopicError, machine_refusal
from candleviewer.ws.topics import parse_topic as parse
from tests.unit.ws._seq_support import USER, Clock, Conn, Source, principal

A, B = uuid.UUID(int=0xA), uuid.UUID(int=0xB)
OID, OTHER = "0a000000-0000-4000-8000-000000000001", "0a000000-0000-4000-8000-000000000002"
ON_A, ON_B = EntityScope(accounts=frozenset({A})), EntityScope(accounts=frozenset({B}))
_SCOPE_MESSAGE = "None of the requested accounts are in scope."  # §6.2, whatever the cause
_FORBIDDEN = "Missing permission for this topic."  # whatever the cause
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
        (f"machines.order:{OID}.STATE", "invalid_topic_format"),  # the suffix is literal
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


_OTHERS = EntityScope(user=ACTORS[1].user_id)  # another user's alert, replay or session


@pytest.mark.parametrize("kind", ["alert", "replay", "session"])
@pytest.mark.parametrize(("scope", "why"), [(None, "unknown"), (_OTHERS, "foreign")])
def test_owner_is_refused_with_forbidden_on_a_user_kind(
    kind: str, scope: EntityScope | None, why: str
) -> None:
    assert machine_refusal(OWNER, kind, scope) == ("forbidden", why)  # D2: no Owner bypass


def test_owner_is_refused_another_users_session_like_an_unknown_one() -> None:
    conn, registry, _ = _world()
    conn.authz.principal = OWNER
    session = MachineEntity("session", OTHER, _OTHERS)
    registry.publish(session, _payload("session", "active"))
    foreign, _ = conn.authz.admit(session.ch)
    unknown, _ = conn.authz.admit(f"machines.session:{OID}.state")
    assert foreign["error"] == unknown["error"] == {"code": "forbidden", "message": _FORBIDDEN}


def test_unknown_and_foreign_entities_get_the_identical_sub_error() -> None:
    conn, registry, _ = _world()
    registry.publish(MachineEntity("order", OTHER, ON_B), _payload())
    unknown, _ = conn.authz.admit(f"machines.order:{OID}.state")
    foreign, _ = conn.authz.admit(f"machines.order:{OTHER}.state")
    expected = {"code": "account_scope_denied", "message": _SCOPE_MESSAGE}
    assert unknown["error"] == foreign["error"] == expected


# -- registry, matching and the sub flow -----------------------------------------------------------


def _world(**kw: Any) -> tuple[Conn, MachineStateRegistry, SequencingHub]:
    """A manager granted account A, whose `sub` is authorised and snapped from the registry; a
    registry publish fans out through the hub."""
    hub, conn = SequencingHub(), Conn(Source())
    registry = MachineStateRegistry(hub=hub, **kw)
    _attach(conn, registry, hub)
    return conn, registry, hub


def _attach(conn: Conn, registry: MachineStateRegistry, hub: SequencingHub) -> None:
    services = conn.authz.services
    services.machines = services.snapshots = conn.emitter.source = registry
    hub.register(conn.authz, conn.emitter)


def _count(metric: str, kind: str = "order") -> float:
    return REGISTRY.get_sample_value(metric, {"entity_kind": kind}) or 0.0


def _line(event: str, level: str) -> dict[str, str]:
    """A log line holds its event, level and `entity_kind` alone: no id, no payload (C-12.6)."""
    return {"event": event, "log_level": level, "entity_kind": "order"}


def test_sub_is_snapped_from_the_registry() -> None:
    conn, registry, _ = _world()
    order = MachineEntity("order", OID, ON_A)
    registry.publish(order, _payload())
    result, _ = conn.sub(order.ch)
    assert result["effective"] == {"throttle_ms": 100, "encoding": "structured", "coalesce": True}
    (snap,) = conn.take()  # validated against the envelope and §15.10
    assert (snap["s"], snap["meta"]["reason"], snap["p"]["state"]) == (1, "initial", "submitted")


def test_a_registry_publish_reaches_the_subscriber_of_its_entity() -> None:
    conn, registry, _ = _world()
    order = MachineEntity("order", OID, ON_A)
    registry.publish(order, _payload())
    conn.sub(order.ch)
    assert registry.publish(order, _payload(state="filled"))
    d = conn.take()[-1]
    assert (d["t"], d["s"], d["p"]["state"]) == ("d", 2, "filled")


def test_the_first_publish_wakes_a_pending_subscription() -> None:
    conn, registry, _ = _world()
    conn.sub("machines.kill_switch.state")
    registry.publish(MachineEntity("kill_switch"), _payload("kill_switch", "clear"))
    (snap,) = conn.take()
    assert (snap["t"], snap["s"], snap["meta"]["reason"]) == ("snap", 1, "initial")


def test_a_wake_leaves_a_backpressure_held_subscription_alone() -> None:
    conn, registry, _ = _world()
    _, sub = conn.sub("machines.kill_switch.state")  # pending: no entry yet
    sub.pending_reason = "backpressure"  # the ladder's hold: only its `drain` sends (#2831)
    registry.publish(MachineEntity("kill_switch"), _payload("kill_switch", "clear"))
    assert conn.take() == [] and sub.snapshot_pending


def test_a_published_payload_is_copied_whole() -> None:
    conn, registry, _ = _world()
    order, payload = MachineEntity("order", OID, ON_A), _payload()
    registry.publish(order, payload)
    payload["tags"].append("terminal")  # the producer reuses its dict
    conn.sub(order.ch)
    assert conn.take()[0]["p"] == _payload()
    registry.publish(order, payload)  # the `d` is queued, not yet written
    payload["tags"].append("again")  # so the hub must hold the stored copy, not the producer's dict
    assert conn.take()[0]["p"]["tags"] == ["terminal"]


def test_a_payload_that_cannot_be_copied_leaves_no_entry() -> None:
    registry, order = MachineStateRegistry(), MachineEntity("order", OID, ON_A)
    with pytest.raises(TypeError):  # a generator has no deep copy: a publisher bug
        registry.publish(order, {**_payload(), "feed": (n for n in ())})
    assert len(registry) == 0 and registry.scope(order.ch) is None


def test_a_publish_counts_once_however_many_subscribe() -> None:
    conn, registry, hub = _world()
    second = Conn(Source())
    _attach(second, registry, hub)
    switch = MachineEntity("kill_switch")  # not the `order` the helper defaults to
    registry.publish(switch, _payload("kill_switch"))
    conn.sub(switch.ch)
    second.sub(switch.ch)
    before = _count("cv_machine_ws_publish_total", "kill_switch")
    registry.publish(switch, _payload("kill_switch", "tripped"))
    assert _count("cv_machine_ws_publish_total", "kill_switch") - before == 1
    assert [f["t"] for f in conn.take() + second.take()] == ["snap", "d", "snap", "d"]


def test_a_scoped_entry_without_a_scope_is_counted_at_every_publish() -> None:
    registry = MachineStateRegistry()
    before = _count("cv_machine_ws_scope_missing_total")
    registry.publish(MachineEntity("order", OID), _payload())
    registry.publish(MachineEntity("order", OID, ON_A), _payload())  # the first scope stays
    registry.publish(MachineEntity("kill_switch"), _payload("kill_switch"))  # unscoped kind
    assert _count("cv_machine_ws_scope_missing_total") - before == 2
    alerts = _count("cv_machine_ws_scope_missing_total", "alert")  # a user kind needs its user
    registry.publish(MachineEntity("alert", OID, EntityScope(user=A)), _payload("alert"))
    registry.publish(MachineEntity("alert", OTHER), _payload("alert"))
    assert _count("cv_machine_ws_scope_missing_total", "alert") - alerts == 1


def test_a_scoped_entry_without_a_scope_logs_a_warning() -> None:
    with capture_logs() as logs:
        MachineStateRegistry().publish(MachineEntity("order", OID), _payload())
    assert logs == [_line("machine state without a scope: refused to every role", "warning")]


def test_the_metric_bound_is_the_closed_kind_set() -> None:
    specs = [s for s in CATALOGUE if s.name.startswith("cv_machine_ws_")]
    assert len(specs) == 3
    assert {(s.labels, s.max_series) for s in specs} == {(("entity_kind",), len(MACHINE_KINDS))}


def test_unscoped_kind_without_an_entry_stays_pending() -> None:
    conn, _, _ = _world()
    result, _ = conn.sub("machines.kill_switch.state")
    assert result["snapshot_pending"] is True and conn.take() == []


def test_registry_bound_refuses_a_new_entity() -> None:
    conn, registry, _ = _world(max_entries=1)
    one, two = MachineEntity("order", OID, ON_A), MachineEntity("order", OTHER, ON_A)
    assert registry.publish(one, _payload()) and not registry.publish(two, _payload())
    assert conn.authz.admit(two.ch)[0]["error"]["code"] == "account_scope_denied"


def test_a_refusal_at_the_bound_is_counted_and_not_recorded() -> None:
    registry, kind = MachineStateRegistry(max_entries=0), "kill_switch"
    full, recorded = (
        _count(f"cv_machine_ws_{m}_total", kind) for m in ("registry_full", "publish")
    )
    registry.publish(MachineEntity(kind), _payload(kind))
    assert _count("cv_machine_ws_registry_full_total", kind) - full == 1
    assert _count("cv_machine_ws_publish_total", kind) == recorded


def test_a_refusal_at_the_bound_logs_at_most_once_a_minute() -> None:
    clock = Clock()
    registry = MachineStateRegistry(max_entries=0, clock=clock)
    with capture_logs() as logs:
        for at in (0.0, 59.9, 60.0):
            clock.now = at
            registry.publish(MachineEntity("order", OID, ON_A), _payload())
    assert logs == [_line("machine state refused: registry full", "error")] * 2


def test_each_event_of_a_kind_logs_once_a_minute() -> None:
    """The rate limit is per (event, kind): a scope change never hides a registry-full error."""
    registry = MachineStateRegistry(max_entries=1, clock=Clock())
    with capture_logs() as logs:
        for ident, scope in ((OID, ON_A), (OTHER, ON_A), (OID, ON_B)):  # new, full, scope change
            registry.publish(MachineEntity("order", ident, scope), _payload())
    assert logs == [
        _line("machine state refused: registry full", "error"),
        _line("machine scope change ignored", "warning"),
    ]


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


def test_a_scope_change_is_logged() -> None:
    registry = MachineStateRegistry()
    with capture_logs() as logs:
        registry.publish(MachineEntity("order", OID, ON_A), _payload())
        registry.publish(MachineEntity("order", OID, ON_B), _payload(state="filled"))
    assert logs == [_line("machine scope change ignored", "warning")]


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
    assert {f["p"]["resubscribe_allowed"] for f in frames[1:]} == {False}
    assert conn.authz.find(order.ch) is not None


@given(st.lists(st.booleans(), min_size=1, max_size=12))
def test_each_subscriber_gets_a_snap_then_contiguous_deltas_ending_on_the_latest(
    subs: list[bool],
) -> None:
    """Any interleaving of a new subscriber (True) and a publish (False) on one entity."""
    hub = SequencingHub()
    registry, entity, conns = MachineStateRegistry(hub=hub), MachineEntity("kill_switch"), []
    for i, new in enumerate(subs):
        if new:
            conns.append(conn := Conn(Source()))
            _attach(conn, registry, hub)
            conn.sub(entity.ch)
        else:
            registry.publish(entity, _payload("kill_switch", f"s{i}"))
    latest = [f"s{i}" for i, new in enumerate(subs) if not new][-1:]
    for conn in conns:
        frames = conn.take()
        assert [f["s"] for f in frames] == list(range(1, len(frames) + 1))
        assert [f["t"] for f in frames[:1]] == ["snap"] * len(latest)
        assert [f["p"]["state"] for f in frames[-1:]] == latest


def test_a_publish_before_sub_ok_leaves_the_snap_to_the_gateway_flush() -> None:
    """#2831 (F8): a wake never sends a `snap` ahead of `sub_ok`; the subscription stays pending,
    so the gateway's flush after `sub_ok` (this frame made it pending) sends it."""
    conn, registry, _ = _world()
    _, sub = conn.authz.admit("machines.kill_switch.state")  # unannounced: `sub_ok` not queued
    registry.publish(MachineEntity("kill_switch"), _payload("kill_switch", "clear"))
    assert sub is not None and sub.snapshot_pending and conn.take() == []
    sub.announced = True
    conn.emitter.flush_pending([sub])
    assert [f["t"] for f in conn.take()] == ["snap"]


def test_a_publish_wakes_no_principal_swapped_out_of_the_kind() -> None:
    conn, registry, _ = _world()
    conn.sub("machines.kill_switch.state")  # pending: no entry yet
    conn.authz.principal = BARE  # §9.5 swaps the principal in before it removes anything
    registry.publish(MachineEntity("kill_switch"), _payload("kill_switch", "clear"))
    assert conn.take() == []


def test_no_delta_reaches_a_principal_swapped_out_of_the_entity() -> None:
    conn, registry, hub = _world()
    order = MachineEntity("order", OID, ON_A)
    registry.publish(order, _payload())
    conn.sub(order.ch)
    conn.authz.principal = principal()  # §9.5 swaps the principal in before it removes anything
    assert hub.publish(order.ch, _payload(state="filled")) == 0


# -- §6.4 audit detail: the full `ch`, and the internal reason in `reason` only -------------------


class _Audit:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.rows.append({"action": action, **kw})


async def _drop(frame: dict[str, Any]) -> None:
    """A socket that discards what it is sent."""


#: The fields a Manager can read about their own rows (SR-067): the same for every reason.
_DENIED = {"action": "ws.subscribe.denied", "actor_label": "ws", "object_kind": "ws_topic",
           "outcome": AuditOutcome.DENIED, "severity": Severity.WARNING}  # fmt: skip


@pytest.mark.parametrize(
    ("who", "scope", "why"),
    [
        (BARE, ON_A, "role"),
        (None, None, "unknown"),
        (None, ON_B, "foreign"),
        (None, EntityScope(), "unscoped"),
    ],
)
def test_a_refusal_audits_the_full_ch_and_its_internal_reason(
    who: PrincipalSnapshot | None, scope: EntityScope | None, why: str
) -> None:
    conn, registry, _ = _world()
    conn.authz.services.audit = audit = _Audit()
    conn.authz.principal = who or conn.authz.principal
    order = MachineEntity("order", OID, scope or EntityScope())
    if scope is not None:
        registry.publish(order, _payload())
    asyncio.run(handle_sub(conn.authz, {"t": "sub", "p": {"topics": [order.ch]}}, _drop))
    user = conn.authz.principal.user_id
    assert audit.rows == [{**_DENIED, "actor_user_id": user, "object_id": order.ch, "reason": why}]


def test_a_refusal_that_is_not_an_authorisation_one_audits_its_error_code() -> None:
    conn, _, _ = _world()
    conn.authz.services.audit = audit = _Audit()
    ch = "machines.bogus.state"  # an unknown kind: invalid_topic_format, no §6.4 reason
    asyncio.run(handle_sub(conn.authz, {"t": "sub", "p": {"topics": [ch]}}, _drop))
    assert [(r["object_id"], r["reason"]) for r in audit.rows] == [(ch, "invalid_topic_format")]


@pytest.mark.parametrize(
    ("who", "why"),
    [
        (PrincipalSnapshot(USER, frozenset({"manager"}), frozenset()), "role"),
        (principal(), "foreign"),  # account A withdrawn
    ],
)
def test_a_revocation_audits_the_full_ch_and_its_internal_reason(
    who: PrincipalSnapshot, why: str
) -> None:
    conn, registry, _ = _world()
    conn.authz.services.audit = audit = _Audit()
    order = MachineEntity("order", OID, ON_A)
    registry.publish(order, _payload())
    conn.sub(order.ch)

    async def resolve(_user: uuid.UUID) -> PrincipalSnapshot:
        return who

    connections = ConnectionRegistry(resolve, lambda: 7, conn.authz.services)
    connections.register(conn.authz, _drop)
    asyncio.run(connections.roles_changed(USER))
    assert [(r["action"], r["object_id"], r["reason"]) for r in audit.rows] == [
        ("ws.subscription.revoked", order.ch, why)
    ]


# -- `ctl`, `unsub` and `resync` on a uuid entity (its `:` and `-` pass the topic-name gate) -------


def _subscribed() -> tuple[Conn, MachineEntity]:
    conn, registry, _ = _world()
    order = MachineEntity("order", OID, ON_A)
    registry.publish(order, _payload())
    conn.sub(order.ch)
    conn.take()
    return conn, order


def test_ctl_retunes_a_machines_subscription() -> None:
    conn, order = _subscribed()
    conn.push(handle_ctl(conn.authz, {"t": "ctl", "ch": order.ch, "p": {"throttle_ms": 250}}, 1))
    (ok,) = conn.take()
    assert (ok["t"], ok["ch"], ok["p"]) == ("ctl_ok", order.ch, {"effective": {"throttle_ms": 250}})


def test_unsub_drops_a_machines_subscription() -> None:
    conn, order = _subscribed()
    reply = handle_unsub(conn.authz, {"t": "unsub", "p": {"topics": [order.ch]}}, 1)
    assert reply["p"]["results"] == [{"ch": order.ch, "ok": True}]
    assert conn.authz.find(order.ch) is None


def test_resync_snaps_a_machines_subscription_from_the_registry() -> None:
    conn, order = _subscribed()
    frame = {"t": "resync", "ch": order.ch, "p": {"reason": "sequence_gap", "last_seq": 1}}
    conn.emitter.client_resync(conn.authz, frame)
    (snap,) = conn.take()
    assert (snap["s"], snap["meta"]["reason"], snap["p"]["state"]) == (
        2,
        "client_resync",
        "submitted",
    )
