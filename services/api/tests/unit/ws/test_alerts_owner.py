"""E40-T04 PR-B (#2521) at the WS layer: the owner a SELF-scoped subscription records at admit,
the fan-out reading it, and `cv_ws_alerts_subscriptions_in_use` staying exact across every way a
subscription ends."""

from __future__ import annotations

import uuid

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.ws.permissions import (
    ConnectionAuthz,
    SubscriptionServices,
    cv_ws_alerts_subscriptions_in_use,
)
from candleviewer.ws.sequencing import in_scope

USER = uuid.UUID("00000000-0000-4000-8000-00000000000a")
OTHER = uuid.UUID("00000000-0000-4000-8000-00000000000b")
ACC = uuid.UUID("a1000000-0000-4000-8000-000000000001")
PERMS = frozenset({Permission.ALERTS_READ, Permission.ACCOUNTS_READ, Permission.RULES_READ})


def _authz(user: uuid.UUID = USER) -> ConnectionAuthz:
    grants = (AccountGrant(ACC, True, False, False),)
    principal = PrincipalSnapshot(user, frozenset({"manager"}), PERMS, grants)
    return ConnectionAuthz(principal, SubscriptionServices())


def _gauge() -> float:
    return float(cv_ws_alerts_subscriptions_in_use._value.get())


def test_a_self_scoped_subscription_records_its_principal_as_owner() -> None:
    authz = _authz()
    _, sub = authz.admit({"ch": "alerts"})
    assert sub is not None and sub.owner == USER


@pytest.mark.parametrize(
    "entry",
    [
        {"ch": "wallet", "opts": {"exchange_account_ids": [str(ACC)]}},
        {"ch": "rules", "opts": {"exchange_account_ids": [str(ACC)]}},
    ],
)
def test_other_scopes_record_no_owner(entry: dict[str, object]) -> None:
    _, sub = _authz().admit(entry)
    assert sub is not None and sub.owner is None


def test_the_fan_out_reads_the_recorded_owner_not_the_event() -> None:
    authz = _authz()
    _, sub = authz.admit({"ch": "alerts"})
    assert sub is not None
    assert in_scope(authz, sub, None, USER) is True
    assert in_scope(authz, sub, None, OTHER) is False
    assert in_scope(authz, sub, None, None) is False  # an event naming nobody reaches nobody
    sub.owner = OTHER  # whatever the principal is, the recorded owner decides
    assert in_scope(authz, sub, None, USER) is False


def test_a_user_option_is_refused_not_honoured() -> None:
    result, sub = _authz().admit({"ch": "alerts", "opts": {"user_id": str(OTHER)}})
    assert sub is None and result["error"]["code"] == "invalid_options"


def test_the_gauge_follows_admits_and_every_way_a_subscription_ends() -> None:
    start = _gauge()
    a, b = _authz(), _authz(OTHER)
    _, sub_a = a.admit({"ch": "alerts"})
    b.admit({"ch": "alerts"})
    a.admit({"ch": "wallet", "opts": {"exchange_account_ids": [str(ACC)]}})  # not counted
    assert _gauge() == start + 2
    assert a.unsubscribe("alerts", None) is not None
    assert _gauge() == start + 1
    assert sub_a is not None
    a._drop(sub_a)  # dropped twice: counted once
    assert _gauge() == start + 1
    b.release_all()  # the connection closed
    assert _gauge() == start
