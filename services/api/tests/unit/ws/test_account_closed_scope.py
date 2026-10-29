"""#898 B3b2 (E27-S04; 23 §9.5, the B3b1 security lens's F-01): after an account's disable, a new
`sub` naming it is refused for it with `account_scope_denied` (one naming others too is narrowed
to them), until the account is re-enabled. The scope decision reads `KeyStandings.closed`, bound
on `SubscriptionServices.account_closed`, synchronously; the refusal holds after a restart, since
the tracking read lists the account disabled again. Pure bookkeeping over the real standing and
`ConnectionAuthz`: no socket, no I/O."""

from __future__ import annotations

from typing import Any

from candleviewer.accounts.key_standing import KeyStandings
from candleviewer.accounts.order_gate import DisabledReason
from candleviewer.ws.permissions import ConnectionAuthz, SubscriptionServices
from tests.unit.accounts._fakes import FakeClock, key_row
from tests.unit.ws.test_account_revoked import READ, A, B, _on
from tests.unit.ws.test_revocation_fanout import USER, _principal


def _standings(*rows: Any) -> KeyStandings:
    standings = KeyStandings(None, interval_s=3600.0, stale_after_s=60.0, clock=FakeClock())
    standings.observe(rows or (key_row(A), key_row(B)))
    return standings


def _socket(standings: KeyStandings | None) -> ConnectionAuthz:
    services = SubscriptionServices(account_closed=None if standings is None else standings.closed)
    return ConnectionAuthz(_principal(USER, READ, A, B), services)


def test_a_sub_naming_a_disabled_account_alone_is_refused_and_accepted_after_re_enable() -> None:
    standings = _standings()
    standings.hold(B, "account_disabled")
    refused, sub = _socket(standings).admit(_on("orders", B))
    assert sub is None and refused["error"]["code"] == "account_scope_denied"
    standings.release(B)
    accepted, sub = _socket(standings).admit(_on("orders", B))
    assert sub is not None and accepted["effective"]["exchange_account_ids"] == [str(B)]


def test_a_sub_naming_a_disabled_account_beside_another_is_narrowed_to_the_other() -> None:
    standings = _standings()
    standings.hold(B, "account_disabled")
    result, sub = _socket(standings).admit(_on("positions", A, B))
    assert sub is not None and sub.accounts == frozenset({A})
    assert result["effective"]["exchange_account_ids"] == [str(A)]


def test_the_refusal_outlives_a_restart_through_the_tracking_read() -> None:
    """hpe-worker-2 item 2: a fresh standing (the restart: no hold) rebuilt from the tracking read
    alone closes the account the read lists `is_enabled=false`, from the same snapshot the order
    gate's `standing` reads, and a re-enable's `release` opens it before the next read."""
    standings = _standings(key_row(A), key_row(B, enabled=False))
    assert standings._state.holds == {} and standings.closed(B) is True
    assert standings.closed(A) is False
    held = standings.standing(B)
    assert held is not None and held.disabled_reason is DisabledReason.ACCOUNT_DISABLED
    refused, sub = _socket(standings).admit(_on("wallet", B))
    assert sub is None and refused["error"]["code"] == "account_scope_denied"
    standings.release(B)
    _, sub = _socket(standings).admit(_on("wallet", B))
    assert sub is not None


def test_with_no_standing_bound_the_grant_alone_decides() -> None:
    _, sub = _socket(None).admit(_on("orders", B))
    assert sub is not None
