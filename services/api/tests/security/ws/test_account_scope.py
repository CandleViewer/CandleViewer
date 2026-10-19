"""E17-X02 AC-05, AC-06, AC-07 and AC-27 (#415, threat model `E17-ws-gateway.md` §7): what a
socket's principal may read is decided on the server, `sub` by `sub` and frame by frame. A Manager
(M1) granted account A only, raw-framing a `sub` for B, is refused `account_scope_denied` on every
account-scoped family, narrowed to A when it names both, and never sent a frame naming B once B's
data is published. A Viewer reads `orders` where it is granted and where it holds the
permission, as `23-ws-protocol.md` §6.3 builds it, and a frame type the gateway does not dispatch
(the eight it does are pinned) changes nothing. `replay_session_id` is refused on every private
family. A frozen grant is no access in any view of the scope. In process on the conformance
gateway (fake clock, no sleeps), under both subprotocols.
"""

from __future__ import annotations

import ast
import inspect
import uuid
from functools import partial
from typing import Any

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.ws import gateway
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from candleviewer.ws.topics import FAMILIES
from tests.contract.ws._harness import SCHEMAS
from tests.security.ws._raw import (
    SCOPED,
    Login,
    RawWorld,
    answers,
    authenticated,
    delta,
    drained,
    naming,
    publish,
    raw_connect,
    role_permissions,
    served,
    topic,
)
from tests.unit.ws._seq_support import ACC_A, ACC_B

_SCOPE = "None of the requested accounts are in scope."  # §6.2's one message, whatever the cause


def _socket(c: Any, auth_ok: dict[str, Any]) -> dict[str, Any]:
    """The socket a denial record names (#415, E17-R-16): its connection id and session."""
    (welcome,) = [f for f in c.seen if f["t"] == "welcome"]
    return {
        "connection_id": welcome["p"]["connection_id"],
        "session_id": auth_ok["p"]["session_id"],
    }


def _error(code: ErrorCode, message: str, **extra: str) -> dict[str, Any]:
    """The `error` of a refused `sub_ok` result, whole: the catalogue's retryable flag, no cause."""
    return {"code": code.value, "message": message, "retryable": ERROR_META[code].retryable} | extra


@pytest.mark.parametrize("family", SCOPED)
def test_x02_ac_05_a_sub_naming_another_account_is_denied_on_every_family(
    world: RawWorld, family: str
) -> None:
    m1 = world.login("m1", ACC_A)
    denied = delta("cv_ws_subscribe_total", topic=family, result="account_scope_denied")
    with raw_connect(world) as c:
        authenticated(c, m1)
        (r,) = answers(c, topic(family, ACC_B))
        assert r == {
            "ch": family,
            "ok": False,
            "error": _error(ErrorCode.ACCOUNT_SCOPE_DENIED, _SCOPE),
        }
        assert denied() == 1
        c.send({"t": "unsub", "id": "u", "p": {"topics": [family]}})
        assert c.next_of("unsub_ok")["p"]["results"] == [{"ch": family, "ok": True, "noop": True}]
    (row,) = world.audit.of("ws.subscribe.denied")  # one record for the frame, naming the family
    who = (row["object_id"], row["reason"], row["actor_user_id"], row["severity"], row["outcome"])
    assert who == (family, "account_scope_denied", m1.user_id, "warning", "denied")
    assert world.audit.of("ws.subscribe.granted") == []  # nothing was granted
    assert naming(c.seen, ACC_B) == []  # B is in none of its frames


def test_x02_ac_05_one_frame_naming_b_on_every_scoped_family_is_one_denial_record(
    world: RawWorld,
) -> None:
    """Each single-topic refusal asserts its `cv_ws_subscribe_total` count; this frame of six
    asserts their codes and its one record (SR-192)."""
    m1 = world.login("m1", ACC_A)
    with raw_connect(world) as c:
        socket = _socket(c, authenticated(c, m1))
        results = answers(c, *[topic(f, ACC_B) for f in SCOPED])
    assert [(r["ch"], r["error"]["code"]) for r in results] == [
        (f, "account_scope_denied") for f in SCOPED
    ]
    (row,) = world.audit.of("ws.subscribe.denied")  # never one record per entry (SR-192)
    assert (row["object_id"], row["reason"]) == (SCOPED[0], "account_scope_denied")
    assert row["after_state"] == {
        **socket,
        "count": len(SCOPED),
        "codes": ["account_scope_denied"],
        "refusals": [[f, "account_scope_denied"] for f in SCOPED],
    }


def test_x02_ac_05_a_sub_naming_a_and_b_is_narrowed_to_a_and_b_data_never_reaches_m1(
    world: RawWorld,
) -> None:
    m1, n = world.login("m1", ACC_A), len(SCOPED)
    narrowed = delta("cv_ws_subscribe_narrowed_total")
    with raw_connect(world) as c:
        socket = _socket(c, authenticated(c, m1))
        results = answers(c, *[topic(f, ACC_B, ACC_A) for f in SCOPED])  # B named first
        assert [r["effective"]["exchange_account_ids"] for r in results] == [[str(ACC_A)]] * n
        assert [f["ch"] for f in sorted(drained(c), key=lambda f: f["ch"])] == list(SCOPED)
        assert [publish(world, f, ACC_B) for f in SCOPED] == [0] * n  # in nobody's scope
        assert [publish(world, f, ACC_A) for f in SCOPED] == [1] * n  # while A's reaches its one
        got = drained(c)
    assert sorted((f["t"], f["ch"], f["s"]) for f in got) == [("d", f, 2) for f in SCOPED]
    assert naming(c.seen, ACC_B) == []  # not one frame of the whole stream names B
    # §6.2: silent in the reply, not unrecorded (#415, E17-R-15): B counted once per entry, and
    # the frame's one denial record lists each narrowing, ...
    (row,) = world.audit.of("ws.subscribe.denied")
    assert (narrowed(), row["object_id"], row["reason"]) == (n, SCOPED[0], "narrowed")
    assert row["after_state"] == {
        **socket,
        "count": n,
        "codes": ["account_scope_denied"],
        "refusals": [[f, "narrowed"] for f in SCOPED],
    }
    (row,) = world.audit.of("ws.subscribe.granted")  # ... and the one grant record names A alone
    assert row["after_state"]["subscriptions"] == [[f, [str(ACC_A)]] for f in SCOPED]


@pytest.mark.parametrize("asks", ["own", "both"])
def test_x02_ac_27_two_users_on_one_symbol_never_see_each_others_account(
    world: RawWorld, asks: str
) -> None:
    alice, bob = world.login("alice", ACC_A), world.login("bob", ACC_B)
    with raw_connect(world) as ca, raw_connect(world) as cb:
        for c, login, own in ((ca, alice, ACC_A), (cb, bob, ACC_B)):
            authenticated(c, login)
            named = [own] if asks == "own" else [ACC_A, ACC_B]
            (r,) = answers(c, topic("positions", *named))
            assert r["effective"]["exchange_account_ids"] == [str(own)]
            assert [f["t"] for f in drained(c)] == ["snap"]
        assert [publish(world, "positions", a) for a in (ACC_A, ACC_B)] == [1, 1]  # BTCUSDT twice
        got = {"alice": drained(ca), "bob": drained(cb)}
    assert {name: len(frames) for name, frames in got.items()} == {"alice": 1, "bob": 1}
    assert naming(ca.seen, ACC_B) == [] and naming(cb.seen, ACC_A) == []  # nothing crossed
    assert (len(naming(got["alice"], ACC_A)), len(naming(got["bob"], ACC_B))) == (1, 1)


# -- a frozen grant is no access in every view of the scope (C-12.4, `auth.scopes.account_scope`) --


def _frozen(world: RawWorld) -> Login:
    return world.login("m1", ACC_A, ACC_B, frozen=(ACC_B,))  # A is live, B is frozen


def test_x02_auth_ok_lists_only_the_grants_that_currently_permit_access(world: RawWorld) -> None:
    with raw_connect(world) as c:
        auth_ok = authenticated(c, _frozen(world))
    assert auth_ok["p"]["account_scope"] == [str(ACC_A)]


def test_x02_a_kill_switch_frame_names_no_frozen_account(world: RawWorld) -> None:
    state = {"engaged": True, "scope": "accounts", "exchange_account_ids": [str(ACC_A), str(ACC_B)]}
    with raw_connect(world) as c:
        authenticated(c, _frozen(world))
        world.call(world.gateway.broadcast_system, {"kind": "kill_switch", "kill_switch": state})
        (frame,) = [f for f in drained(c) if f["ch"] == "system"]
    assert frame["p"]["kill_switch"]["exchange_account_ids"] == [str(ACC_A)]
    assert naming(c.seen, ACC_B) == []


def test_x02_a_sub_naming_a_frozen_account_is_denied(world: RawWorld) -> None:
    m1 = _frozen(world)
    denied = delta("cv_ws_subscribe_total", topic="orders", result="account_scope_denied")
    with raw_connect(world) as c:
        authenticated(c, m1)
        (r,) = answers(c, topic("orders", ACC_B))
    error = _error(ErrorCode.ACCOUNT_SCOPE_DENIED, _SCOPE)
    assert r == {"ch": "orders", "ok": False, "error": error}
    assert denied() == 1
    (row,) = world.audit.of("ws.subscribe.denied")
    who = (row["object_id"], row["reason"], row["actor_user_id"])
    assert who == ("orders", "account_scope_denied", m1.user_id)


def test_x02_a_sub_naming_a_frozen_and_a_live_account_is_narrowed_to_the_live_one(
    world: RawWorld,
) -> None:
    with raw_connect(world) as c:
        authenticated(c, _frozen(world))
        (r,) = answers(c, topic("positions", ACC_B, ACC_A))
    assert r["effective"]["exchange_account_ids"] == [str(ACC_A)]
    (row,) = world.audit.of("ws.subscribe.denied")  # silent in the reply, recorded (E17-R-15)
    assert (row["object_id"], row["reason"]) == ("positions", "narrowed")


@pytest.mark.parametrize("how", ["drop", "freeze"])
def test_x02_a_grant_frozen_mid_session_is_revoked_and_narrowed_like_a_withdrawal(
    world: RawWorld, how: str
) -> None:
    m1 = world.login("m1", ACC_A, ACC_B)
    revoked = delta("cv_ws_revoked_total", reason="account_scope_changed")
    with raw_connect(world) as c:
        authenticated(c, m1)
        answers(c, topic("positions", ACC_A, ACC_B), topic("orders", ACC_B))
        drained(c)
        world.call(partial(world.amended, m1, **{how: (ACC_B,)}))
        frames = drained(c)
        assert publish(world, "orders", ACC_B) == 0  # the ended topic is routed to no one
        assert [publish(world, "positions", a) for a in (ACC_B, ACC_A)] == [0, 1]  # A stays served
        got = drained(c)
    change, *ends = frames
    assert (change["t"], change["p"]["account_scope"]) == ("permission_change", [str(ACC_A)])
    assert {f["ch"]: f["p"]["resubscribe_allowed"] for f in ends} == {
        "orders": False,
        "positions": True,
    }
    assert {(f["t"], f["p"]["reason"], *f["p"]["removed_accounts"]) for f in ends} == {
        ("revoked", "account_scope_changed", str(ACC_B))
    }
    assert revoked() == 2 and len(world.audit.of("ws.subscription.revoked")) == 2
    assert [(f["t"], f["ch"]) for f in got] == [("d", "positions")]  # A's row alone, none of B's
    assert naming(got, ACC_B) == []


def test_x02_ac_06_a_viewer_reads_orders_on_a_granted_account_and_holds_no_write_permission(
    world: RawWorld,
) -> None:
    viewer = world.login("viewer", ACC_A, role="viewer")
    with raw_connect(world) as c:
        auth_ok = authenticated(c, viewer)
        (r,) = answers(c, topic("orders", ACC_A))
        assert (r["ok"], r["effective"]["exchange_account_ids"]) == (True, [str(ACC_A)])
        assert [f["t"] for f in drained(c)] == ["snap"]  # §6.3: read-only, a snapshot and deltas
    held = auth_ok["p"]["permissions"]  # anything that acts comes over REST (`orders:write`)
    assert auth_ok["p"]["roles"] == ["viewer"] and "orders:read" in held
    assert not [p for p in held if p.endswith(":write")]
    assert world.audit.of("ws.subscribe.denied") == []


_BARE = role_permissions("viewer") - {Permission.ORDERS_READ}  # a Viewer without the permission
_VIEWER_REFUSALS = {
    "ungranted-account": (None, ACC_B, ErrorCode.ACCOUNT_SCOPE_DENIED, _SCOPE),
    "no-permission": (_BARE, ACC_A, ErrorCode.FORBIDDEN, "Missing permission for this topic."),
}


@pytest.mark.parametrize(
    ("perms", "asked", "code", "message"), _VIEWER_REFUSALS.values(), ids=_VIEWER_REFUSALS
)
def test_x02_ac_06_a_viewer_is_refused_orders_on_an_ungranted_account_or_without_the_permission(
    world: RawWorld,
    perms: frozenset[Permission] | None,
    asked: uuid.UUID,
    code: ErrorCode,
    message: str,
) -> None:
    viewer = world.login("viewer", ACC_A, role="viewer", perms=perms)
    refused = delta("cv_ws_subscribe_total", topic="orders", result=code.value)
    with raw_connect(world) as c:
        authenticated(c, viewer)
        (r,) = answers(c, topic("orders", asked))
        assert r == {"ch": "orders", "ok": False, "error": _error(code, message)}
        assert refused() == 1
    (row,) = world.audit.of("ws.subscribe.denied")
    assert (row["reason"], row["actor_user_id"]) == (code.value, viewer.user_id)


_ENVELOPE = SCHEMAS["cv://ws/v1/envelope.schema.json"]["properties"]["t"]["enum"]
#: The frame types the gateway handles (§13.1 minus what only the server sends): no action frame.
_DISPATCHED = {"hello", "auth", "ping", "pong", "sub", "unsub", "ctl", "resync"}
_ACTIONS = ["order", "place_order", "cancel_order", "amend_order", "close_position", "kill_switch"]
_REFUSED = [*sorted(set(_ENVELOPE) - _DISPATCHED), *_ACTIONS, "set_leverage", "withdraw"]


def _kind_uses(fn: ast.AsyncFunctionDef) -> tuple[set[str], list[str]]:
    """Every load of `kind`, the name `dispatch` binds a frame's type to: the strings it is
    compared with, and the uses that are neither that nor `isinstance(kind, str)`."""
    parent = {child: node for node in ast.walk(fn) for child in ast.iter_child_nodes(node)}
    compared: set[str] = set()
    other: list[str] = []
    for load in ast.walk(fn):
        if not (
            isinstance(load, ast.Name) and load.id == "kind" and isinstance(load.ctx, ast.Load)
        ):
            continue
        use = parent[load]
        if (
            isinstance(use, ast.Compare)
            and use.left is load
            and len(use.ops) == 1
            and isinstance(use.ops[0], ast.Eq | ast.NotEq)
            and isinstance(use.comparators[0], ast.Constant)
            and isinstance(use.comparators[0].value, str)
        ):
            compared.add(use.comparators[0].value)
        elif ast.unparse(use) != "isinstance(kind, str)":
            other.append(ast.unparse(use))
    return compared, other


def test_x02_the_gateway_dispatches_these_frame_types_and_no_action_frame() -> None:
    """A pin on `dispatch`'s own source: a new branch on the frame's type is a new surface, for a
    security review (§6.3: a viewer's `orders` is read-only, and anything that acts comes over
    REST). It fails closed: no `match`, each use of `kind` is a `==`/`!=` against a string or
    `isinstance(kind, str)` (so a table, an `in` or a call on it fails the pin too), and the key
    `"t"` is read once, where `kind` is bound (so a second read of the type fails it as well). The
    test below covers each type of the envelope."""
    (fn,) = [
        n
        for n in ast.walk(ast.parse(inspect.getsource(gateway)))
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "dispatch"
    ]
    compared, other = _kind_uses(fn)
    assert not [n for n in ast.walk(fn) if isinstance(n, ast.Match)]
    assert other == []
    # The key "t" is read once, to bind `kind`; a branch on `frame.get("t")` would read it again.
    assert sum(isinstance(n, ast.Constant) and n.value == "t" for n in ast.walk(fn)) == 1
    assert compared == _DISPATCHED and _DISPATCHED <= set(_ENVELOPE)


@pytest.mark.parametrize("kind", _REFUSED)
def test_x02_ac_06_a_frame_type_the_gateway_does_not_dispatch_is_refused_and_changes_nothing(
    world: RawWorld, kind: str
) -> None:
    viewer = world.login("viewer", ACC_A, role="viewer")
    refused = delta("cv_ws_errors_total", code="frame_malformed")
    meta = ERROR_META[ErrorCode.FRAME_MALFORMED]
    with raw_connect(world) as c:
        authenticated(c, viewer)
        answers(c, topic("orders", ACC_A))
        assert [f["t"] for f in drained(c)] == ["snap"]
        rows = list(world.audit.records)
        c.send({"t": kind, "id": "x", "p": {"symbol": "BTCUSDT", "side": "buy", "qty": "1"}})
        err = c.recv_err()
        assert err["id"] == "x"
        assert err["p"] == {
            "code": "frame_malformed",
            "message": meta.title,
            "retryable": meta.retryable,
            "close": False,
        }
        assert drained(c) == [] and world.audit.records == rows and refused() == 1
        c.send({"t": "unsub", "id": "u", "p": {"topics": ["orders"]}})  # still the same one held
        ended = [{"ch": "orders", "ok": True, "ended": [{"sub_id": "s_01"}]}]
        assert c.next_of("unsub_ok")["p"]["results"] == ended


_RS = "bb000000-0000-4000-8000-000000000001"
_PRIVATE = [
    "machines.kill_switch.state" if name == "machines" else name
    for name, fam in FAMILIES.items()
    if fam.private and name != "system"  # `system` is implicit: nothing is subscribed to
]


@pytest.mark.parametrize("ch", _PRIVATE)
def test_x02_ac_07_a_replay_session_on_a_private_topic_is_invalid_options(
    world: RawWorld, ch: str
) -> None:
    m1, family = world.login("m1", ACC_A), ch.split(".")[0]
    scoped = FAMILIES[family].account_scoped  # so that the id is all that is wrong
    entry = {"ch": ch, "opts": {"exchange_account_ids": [str(ACC_A)]} if scoped else {}}
    refused = delta("cv_ws_subscribe_total", topic=family, result="invalid_options")
    with raw_connect(world) as c:
        authenticated(c, m1)
        c.send({"t": "sub", "id": "s", "p": {"topics": [entry], "replay_session_id": _RS}})
        (r,) = c.next_of("sub_ok")["p"]["results"]
        message = "Private topics cannot be replayed."
        error = _error(ErrorCode.INVALID_OPTIONS, message, field="ch")
        assert r == {"ch": ch, "ok": False, "rs": _RS, "error": error}
        assert refused() == 1
        assert drained(c) == []  # no snapshot: nothing was attached
        c.send({"t": "unsub", "id": "u", "p": {"topics": [ch]}})
        assert c.next_of("unsub_ok")["p"]["results"] == [{"ch": ch, "ok": True, "noop": True}]
    (row,) = world.audit.of("ws.subscribe.denied")  # as built (§5.2): a private refusal is kept
    assert (row["object_id"], row["reason"]) == (ch, "invalid_options")  # a machine's names its ch
    assert world.audit.of("ws.subscribe.granted") == []


def test_x02_the_rigs_own_asserts_report_their_values(world: RawWorld) -> None:
    """`_raw` is assert-rewritten like a test (C-13.7): a red pin names what it compared."""
    bob = world.login("bob", ACC_B)  # `served` expects alice's, which holds A
    with raw_connect(world) as c:
        authenticated(c, bob)
        with pytest.raises(AssertionError, match=r"== \(True, None\)"):
            served(c)
