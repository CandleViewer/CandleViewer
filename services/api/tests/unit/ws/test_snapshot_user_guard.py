"""#415 (E17-X02): a WS connection refuses a permission snapshot for another user
(`23-ws-protocol.md` §4.3, threat model WS-S04). `ConnectionAuthz.apply_snapshot` raises
`SnapshotUserMismatch` before it reads the version and changes nothing: the principal, the version,
the subscriptions and the registry's entry stay as they were. A snapshot of the connection's own
user applies as before.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.ws.permissions import (
    ConnectionAuthz,
    ConnectionRegistry,
    SnapshotUserMismatch,
    Subscription,
    SubscriptionServices,
    VersionedSnapshot,
    cv_ws_permission_snapshots_refused_total,
)
from tests.unit.ws._seq_support import ACC_A, ACC_B, principal

ALICE, BOB = uuid.UUID(int=0xA11CE), uuid.UUID(int=0xB0B)
_BOTH = {"exchange_account_ids": [str(ACC_A), str(ACC_B)]}


class _Socket:
    """The registry's view of one socket: the frames sent, the closes and the audit rows."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed = 0
        self.rows: list[str] = []

    async def send(self, frame: dict[str, Any]) -> None:
        self.sent.append(frame)

    async def close(self) -> None:
        self.closed += 1

    async def emit(self, action: str, **_row: Any) -> None:
        self.rows.append(action)


def _alice(version: int = 2) -> tuple[ConnectionRegistry, ConnectionAuthz, _Socket]:
    """Alice's registered connection at `version`, holding `positions` on accounts A and B. The
    principal store answers for Bob, whoever is asked."""

    async def store(_user: uuid.UUID) -> PrincipalSnapshot:
        return principal(ACC_B, user=BOB)

    sock = _Socket()
    reg = ConnectionRegistry(store, lambda: 42, SubscriptionServices(audit=sock))
    conn = ConnectionAuthz(principal(ACC_A, ACC_B, user=ALICE), reg.services, version=version)
    reg.register(conn, sock.send, sock.close)
    assert conn.admit({"ch": "positions", "opts": _BOTH})[1] is not None
    return reg, conn, sock


def _state(reg: ConnectionRegistry, conn: ConnectionAuthz) -> tuple[Any, ...]:
    entries = {user: [e[0] for e in held] for user, held in reg._conns.items()}
    subs = [(s.sub_id, s.accounts, dict(s.effective)) for s in conn.by_id.values()]
    return conn.principal, conn.version, subs, entries, list(conn.settling)


@pytest.mark.parametrize("version", [1, 2, 3], ids=["older", "same", "newer"])
def test_apply_snapshot_of_another_user_is_refused_and_changes_nothing(version: int) -> None:
    reg, conn, _ = _alice(version=2)
    dropped: list[list[Subscription]] = []
    conn.on_drop = dropped.append
    before = _state(reg, conn)
    with pytest.raises(SnapshotUserMismatch):
        conn.apply_snapshot(VersionedSnapshot(principal(ACC_B, user=BOB), version), 9)
    assert _state(reg, conn) == before
    assert before[3] == {ALICE: [conn]} and dropped == []  # still registered as Alice's only


async def test_registry_apply_passes_the_refusal_on_and_records_no_stale_refusal() -> None:
    reg, conn, sock = _alice()
    stale = cv_ws_permission_snapshots_refused_total.labels(event="reauth")
    counted = stale._value.get()
    with pytest.raises(SnapshotUserMismatch):
        await reg.apply(conn, VersionedSnapshot(principal(ACC_B, user=BOB), 3), 9, event="reauth")
    assert (sock.rows, sock.sent, stale._value.get()) == ([], [], counted)


def test_apply_snapshot_of_the_same_user_still_applies_by_version() -> None:
    _, conn, _ = _alice(version=2)
    newer = VersionedSnapshot(principal(ACC_A, user=uuid.UUID(str(ALICE))), 3)  # equal, not `is`
    frames = conn.apply_snapshot(newer, 9) or []
    assert [f["t"] for f in frames] == ["permission_change", "revoked"]
    assert frames[0]["p"]["user_id"] == str(ALICE)
    assert (conn.principal, conn.version, conn.subs) == (newer.principal, 3, {("positions", ACC_A)})
    older = VersionedSnapshot(principal(ACC_A, ACC_B, user=ALICE), 2)
    assert conn.apply_snapshot(older, 9) is None and conn.principal is newer.principal


async def test_grant_change_whose_snapshot_names_another_user_evicts_the_socket() -> None:
    """The registry's own fan-out: the store answers for Bob, so nothing is applied or sent and
    the socket is dropped and closed, as for any swap that raises (fail closed)."""
    reg, conn, sock = _alice()
    await reg.grants_changed(ALICE)
    assert (sock.sent, sock.closed, reg._conns, conn.principal.user_id) == ([], 1, {}, ALICE)
    assert conn.by_id == {} and sock.rows == []  # released, as an evicted socket is
