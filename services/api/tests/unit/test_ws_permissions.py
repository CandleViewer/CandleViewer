"""WS auth_ok permissions, per-subscribe check, mid-connection downgrade (QA #1648 d1)."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, Allow, Deny, DenyReason, PrincipalSnapshot
from candleviewer.ws.permissions import (
    ConnectionAuthz,
    ConnectionRegistry,
    VersionedSnapshot,
    auth_ok_payload,
    check_subscribe,
    handle_sub,
)

ACC = uuid.uuid4()
ALL = frozenset(Permission)
MGR = frozenset({Permission.MARKETDATA_READ, Permission.ORDERS_READ, Permission.ORDERS_WRITE})
VIEWER = frozenset({Permission.MARKETDATA_READ, Permission.ORDERS_READ})


def _snap(role: str, perms: frozenset[Permission]) -> PrincipalSnapshot:
    return PrincipalSnapshot(
        uuid.UUID(int=1), frozenset({role}), perms, (AccountGrant(ACC, True, True, False),)
    )


def _apply(conn: ConnectionAuthz, new: PrincipalSnapshot, now_ms: int) -> list[dict[str, Any]]:
    frames = conn.apply_snapshot(VersionedSnapshot(new, conn.version + 1), now_ms)
    assert frames is not None  # a newer version is always applied (SR-189)
    return frames


def test_auth_ok_payload_carries_roles_permissions_and_scope() -> None:
    p = auth_ok_payload(_snap("manager", MGR))
    assert p["roles"] == ["manager"]
    assert "orders:write" in p["permissions"]
    assert p["account_scope"] == [str(ACC)]


def test_subscribe_checked_per_topic() -> None:
    s = _snap("viewer", frozenset({Permission.MARKETDATA_READ}))
    assert isinstance(check_subscribe(s, "book.BTCUSDT"), Allow)
    assert isinstance(check_subscribe(s, "orders"), Deny)
    assert isinstance(check_subscribe(s, "bogus.X"), Deny)
    assert check_subscribe(s, "system") is None


def _add(conn: ConnectionAuthz, ch: str, account: uuid.UUID | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"ch": ch}
    if account is not None:
        entry["opts"] = {"exchange_account_ids": [str(account)]}
    return conn.admit(entry)[0]


def test_downgrade_pushes_frame_revokes_and_refuses_orders() -> None:
    conn = ConnectionAuthz(_snap("manager", MGR))
    assert _add(conn, "book.BTCUSDT.50")["ok"]
    assert _add(conn, "orders", ACC)["ok"]
    assert conn.may_submit_order()
    frames = _apply(conn, _snap("viewer", frozenset({Permission.MARKETDATA_READ})), 1)
    assert frames[0]["t"] == "permission_change"
    assert frames[0]["p"]["roles"] == ["viewer"]
    assert [(f["t"], f["ch"]) for f in frames[1:]] == [("revoked", "orders")]
    assert frames[1]["p"]["reason"] == "permission_revoked"
    assert not conn.may_submit_order()
    assert conn.topics == {"book.BTCUSDT.50"}


OTHER = uuid.uuid4()


def _mgr(grants: tuple[AccountGrant, ...]) -> PrincipalSnapshot:
    return PrincipalSnapshot(uuid.UUID(int=2), frozenset({"manager"}), MGR, grants)


def test_manager_account_less_sub_on_account_scoped_topic_is_rejected() -> None:
    m = _mgr((AccountGrant(ACC, True, True, False),))
    for fam in ("orders", "positions", "executions", "wallet", "rules"):
        d = check_subscribe(
            m.__class__(m.user_id, m.roles, frozenset(Permission), m.account_grants), fam
        )
        assert isinstance(d, Deny) and d.reason is DenyReason.OBJECT_REQUIRED
    assert isinstance(check_subscribe(m, "orders", exchange_account_id=OTHER), Deny)
    assert isinstance(check_subscribe(m, "orders", exchange_account_id=ACC), Allow)


def test_owner_needs_an_account_id_but_any_account_is_allowed() -> None:
    o = PrincipalSnapshot(uuid.UUID(int=3), frozenset({"owner"}), ALL)
    assert isinstance(check_subscribe(o, "orders", exchange_account_id=OTHER), Allow)


def test_lost_account_grant_revokes_subscription_with_scope_reason() -> None:
    conn = ConnectionAuthz(_mgr((AccountGrant(ACC, True, True, False),)))
    assert _add(conn, "orders", ACC)["ok"]
    frames = _apply(conn, _mgr(()), 5)
    assert [(f["t"], f.get("ch")) for f in frames] == [
        ("permission_change", None),
        ("revoked", "orders"),
    ]
    assert frames[1]["p"]["reason"] == "account_scope_changed"
    assert conn.subs == set()


def test_owner_unaffected_by_grant_snapshot_refresh() -> None:
    o = PrincipalSnapshot(uuid.UUID(int=3), frozenset({"owner"}), ALL)
    conn = ConnectionAuthz(o)
    assert _add(conn, "orders", OTHER)["ok"]
    assert _apply(conn, o, 1)[1:] == []
    assert conn.topics == {"orders"}


def _run_sub(conn: ConnectionAuthz, entry: Any) -> dict[str, Any]:
    sent: list[dict[str, Any]] = []

    async def send(f: dict[str, Any]) -> None:
        sent.append(f)

    asyncio.run(handle_sub(conn, {"id": "x", "p": {"topics": [entry]}}, send))
    result: dict[str, Any] = sent[0]["p"]["results"][0]
    return result


def test_handle_sub_rejects_malformed_and_partial_account_lists() -> None:
    conn = ConnectionAuthz(_mgr((AccountGrant(ACC, True, True, False),)))
    bad = {"ch": "orders", "opts": {"exchange_account_ids": ["not-a-uuid"]}}
    assert _run_sub(conn, bad)["error"] == {
        "code": "invalid_options",
        "message": "Option 'exchange_account_ids' is out of range.",
        "field": "exchange_account_ids",
        "retryable": False,
    }
    assert _run_sub(conn, {"ch": "orders", "opts": {"exchange_account_ids": []}})["ok"] is False
    assert (
        _run_sub(conn, {"ch": "orders", "opts": {"exchange_account_ids": [str(OTHER)]}})["error"][
            "code"
        ]
        == "account_scope_denied"
    )
    assert conn.subs == set()
    # §6.2: a partially out-of-scope list is silently narrowed, never an error.
    mixed = {"ch": "orders", "opts": {"exchange_account_ids": [str(ACC), str(OTHER)]}}
    res = _run_sub(conn, mixed)
    assert res["ok"] and res["effective"]["exchange_account_ids"] == [str(ACC)]
    assert conn.subs == {("orders", ACC)}


def test_registry_without_connections_is_noop() -> None:
    async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
        raise AssertionError("must not resolve")

    asyncio.run(ConnectionRegistry(resolve, lambda: 0).roles_changed(uuid.uuid4()))


_REPO = Path(__file__).resolve().parents[4]
#: Both copies of the §13 schemas: the docs bundle the extractor writes and the packages/protocol
#: copy the TypeScript consumers read. They must accept and refuse exactly the same frames.
_BUNDLES = (
    pytest.param(_REPO / "docs" / "plan" / "ws-schema.json", id="docs-bundle"),
    pytest.param(_REPO / "packages" / "protocol" / "ws-schemas.json", id="protocol-bundle"),
)
_ENVELOPE = "cv://ws/v1/envelope.schema.json"
_PAYLOAD = "cv://ws/v1/permission_change.schema.json"
_REQUIRED_KEYS = ("user_id", "roles", "permissions", "account_scope")

_OWNER = PrincipalSnapshot(uuid.UUID(int=3), frozenset({"owner"}), ALL)
_VIEWER = PrincipalSnapshot(uuid.UUID(int=1), frozenset({"viewer"}), VIEWER, ())
_MANAGER = PrincipalSnapshot(
    uuid.UUID(int=2),
    frozenset({"manager"}),
    MGR,
    (AccountGrant(ACC, True, True, False), AccountGrant(OTHER, True, False, False)),
)


def _violations(bundle: Path, schema_id: str, doc: Any) -> list[tuple[str, str, str]]:
    """`(keyword, path, message)` for each way `doc` violates `schema_id` in `bundle`.

    Validated as the bundle declares (Draft 2020-12) with `format` ENFORCED: §13 only annotates
    `uuid` ids with `format`, so without a format checker `user_id: "bob"` would pass.
    """
    schemas: dict[str, Any] = json.loads(bundle.read_text(encoding="utf-8"))["schemas"]
    assert schemas[schema_id]["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    registry: Registry[Any] = Registry().with_resources(
        (sid, Resource.from_contents(body)) for sid, body in schemas.items()
    )
    validator = Draft202012Validator(
        schemas[schema_id], registry=registry, format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    return sorted(
        (str(e.validator), "/".join(str(part) for part in e.absolute_path), e.message)
        for e in validator.iter_errors(doc)
    )


def _emitted_permission_change(new: PrincipalSnapshot) -> dict[str, Any]:
    """The frame `ConnectionAuthz.apply_snapshot` really emits when `new` replaces a snapshot."""
    conn = ConnectionAuthz(_snap("viewer", VIEWER))
    frames = conn.apply_snapshot(VersionedSnapshot(new, conn.version + 1), 1)
    assert frames is not None
    frame = frames[0]
    assert frame["t"] == "permission_change", frame
    return frame


@pytest.mark.parametrize("bundle", _BUNDLES)
@pytest.mark.parametrize(
    ("principal", "roles", "account_scope"),
    [
        # An owner holds no grant rows: `account_scope == []` means ALL accounts (23 §9.5).
        pytest.param(_OWNER, ["owner"], [], id="owner"),
        pytest.param(_VIEWER, ["viewer"], [], id="viewer-without-grants"),
        pytest.param(_MANAGER, ["manager"], sorted([str(ACC), str(OTHER)]), id="manager-two"),
    ],
)
def test_permission_change_frame_validates_against_section_13_schema(
    bundle: Path, principal: PrincipalSnapshot, roles: list[str], account_scope: list[str]
) -> None:
    """#2297: the `apply_snapshot` frame is documented (23-ws-protocol §9.5/§13.4).

    Both the docs bundle and the packages/protocol bundle must accept the emitted frame, envelope
    and payload, for an owner (empty scope), a viewer (empty scope) and a manager (two accounts).
    """
    frame = _emitted_permission_change(principal)
    assert (frame["p"]["roles"], frame["p"]["account_scope"]) == (roles, account_scope)
    for schema_id, doc in ((_ENVELOPE, frame), (_PAYLOAD, frame["p"])):
        errors = _violations(bundle, schema_id, doc)
        assert errors == [], f"{bundle.name} rejects the emitted frame ({schema_id}): {errors}"


def _with(**changes: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    return lambda payload: {**payload, **changes}


def _without(key: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    return lambda payload: {k: v for k, v in payload.items() if k != key}


@pytest.mark.parametrize("bundle", _BUNDLES)
@pytest.mark.parametrize(
    ("break_payload", "expected"),
    [
        # `session_id` is an `auth_ok` field: this frame is the identity subset, never the session.
        pytest.param(
            _with(session_id=str(uuid.UUID(int=9))), ("additionalProperties", ""), id="extra-key"
        ),
        pytest.param(_with(roles=["admin"]), ("enum", "roles/0"), id="role-outside-closed-set"),
        pytest.param(_with(account_scope=None), ("type", "account_scope"), id="null-scope"),
        *(
            pytest.param(_without(key), ("required", ""), id=f"missing-{key}")
            for key in _REQUIRED_KEYS
        ),
        pytest.param(_with(user_id="bob"), ("format", "user_id"), id="user-id-not-a-uuid"),
    ],
)
def test_permission_change_payload_defect_is_rejected_by_section_13_schema(
    bundle: Path,
    break_payload: Callable[[dict[str, Any]], dict[str, Any]],
    expected: tuple[str, str],
) -> None:
    """Each defect is refused by BOTH bundles, for the intended reason and nothing else (#2297).

    Starts from a frame the emitter really produced and checks it is valid first, so the single
    change is what the schema rejects; `format` is enforced (see `_violations`).
    """
    payload = _emitted_permission_change(_MANAGER)["p"]
    assert _violations(bundle, _PAYLOAD, payload) == []
    violations = _violations(bundle, _PAYLOAD, break_payload(payload))
    assert [(keyword, path) for keyword, path, _ in violations] == [expected], violations
