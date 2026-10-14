"""Redactor (property-based over the SECRET registry), action registry,
and server-side RBAC for the /admin/audit* operations."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.audit.access import (
    OWN_REDACTED_FIELDS,
    AuditAccessDenied,
    AuditPrincipal,
    AuditView,
    authorize,
    redact_entry_for_view,
)
from candleviewer.audit.actions import AUDIT_ACTIONS, UnknownAuditAction, validate_action
from candleviewer.audit.models import AuditEntry, AuditOutcome, Severity
from candleviewer.audit.redact import PII_HASH_PREFIX, REDACTION_MARKER, redact

_SECRET_KEYS = [
    "password_hash",
    "passwordHash",
    "totp_seed",
    "TOTP-SECRET",
    "recovery_codes",
    "refresh_token_hash",
    "invite_token",
    "api_key",
    "apiSecret",
    "signature",
]
_SENTINEL = "-".join(("sentinel", "value", "do-not-store"))


@given(
    key=st.sampled_from(_SECRET_KEYS),
    depth=st.integers(min_value=0, max_value=4),
    in_list=st.booleans(),
)
def test_redact_secret_never_survives_at_any_depth(key: str, depth: int, in_list: bool) -> None:
    node: Any = {key: _SENTINEL, "keep": 1}
    for _ in range(depth):
        node = {"nested": [node] if in_list else node}
    out = redact({"root": node})
    dumped = json.dumps(out)
    assert _SENTINEL not in dumped and REDACTION_MARKER in dumped


def test_redact_none_and_input_not_mutated() -> None:
    assert redact(None) is None
    plain = "p"
    src = {"password": plain, "list": [[{"x": 1}], 2]}
    out = redact(src)
    assert src["password"] is plain
    assert out == {"password": REDACTION_MARKER, "list": [[{"x": 1}], 2]}


def test_redact_pii_hashed_exact_names_only() -> None:
    out = redact({"email": "a@b.c", "ip": "1.2.3.4", "description": "d", "phone": None})
    assert out is not None
    assert out["email"].startswith(PII_HASH_PREFIX) and "a@b.c" not in out["email"]
    assert out["ip"].startswith(PII_HASH_PREFIX)
    assert out["description"] == "d" and out["phone"] is None


def test_actions_registry_accepts_known_rejects_unknown() -> None:
    assert validate_action("auth.login") == "auth.login"
    assert "admin.audit_denied" in AUDIT_ACTIONS
    with pytest.raises(UnknownAuditAction) as exc:
        validate_action("Auth.Login")
    assert exc.value.action == "Auth.Login"


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.calls.append((action, kw))


def _p(*perms: str) -> AuditPrincipal:
    return AuditPrincipal(
        user_id=uuid.uuid4(), username="u", permissions=frozenset(perms), ip="10.0.0.1"
    )


@pytest.mark.parametrize("op", ["query", "verify", "export"])
async def test_access_owner_allowed_everything(op: str) -> None:
    rec = _Recorder()
    await authorize(_p("*"), op, rec)
    assert rec.calls == []


MANAGER = (
    "orders:read",
    "orders:write",
    "accounts:read",
    "positions:read",
)


@pytest.mark.parametrize("op", ["query", "verify", "export"])
async def test_access_manager_denied_403_and_denial_audited(op: str) -> None:
    rec = _Recorder()
    principal = _p(*MANAGER)
    with pytest.raises(AuditAccessDenied):
        await authorize(principal, op, rec)
    [(action, kw)] = rec.calls
    assert action == "admin.audit_denied"
    assert kw["outcome"] is AuditOutcome.DENIED and kw["severity"] is Severity.WARNING
    assert kw["actor_user_id"] == principal.user_id


async def test_access_audit_read_holder_cannot_export() -> None:
    rec = _Recorder()
    with pytest.raises(AuditAccessDenied) as exc:
        await authorize(_p("audit:read"), "export", rec)
    assert exc.value.permission == "audit:export"


async def test_access_manager_with_account_scope_still_cannot_read_other_accounts() -> None:
    """IDOR: audit read is scope `none` — an account-scoped manager permission
    set never grants any slice of the log, including rows about accounts it
    is not assigned to."""
    rec = _Recorder()
    with pytest.raises(AuditAccessDenied):
        await authorize(_p(*MANAGER, "accounts:write"), "query", rec)


async def test_access_unknown_operation_fails_closed() -> None:
    rec = _Recorder()
    with pytest.raises(AuditAccessDenied) as exc:
        await authorize(_p("*"), "delete", rec)
    assert exc.value.permission == "<unknown-operation>" and len(rec.calls) == 1


# ---- #2083: audit:read grants per 04 §7.2.2 rows 49/49a and SR-067 ----------------


def _role(role: str, *perms: str) -> AuditPrincipal:
    return AuditPrincipal(
        user_id=uuid.uuid4(),
        username=role,
        permissions=frozenset(perms),
        is_owner=role == "owner",
    )


@pytest.mark.parametrize("op", ["query", "verify", "export"])
async def test_access_viewer_without_audit_read_denied_every_op(op: str) -> None:
    rec = _Recorder()
    with pytest.raises(AuditAccessDenied):
        await authorize(_role("viewer", "orders:read", "accounts:read"), op, rec)
    assert rec.calls[0][0] == "admin.audit_denied"


async def test_access_manager_with_audit_read_may_query_own_scope_only() -> None:
    rec = _Recorder()
    view = await authorize(_role("manager", "audit:read"), "query", rec)
    assert view is AuditView.OWN_REDACTED and rec.calls == []


async def test_access_manager_with_audit_read_denied_verify() -> None:
    rec = _Recorder()
    with pytest.raises(AuditAccessDenied):
        await authorize(_role("manager", "audit:read"), "verify", rec)
    assert len(rec.calls) == 1


async def test_access_owner_role_gets_raw_view() -> None:
    rec = _Recorder()
    assert await authorize(_role("owner", "audit:read"), "query", rec) is AuditView.RAW
    assert await authorize(_p("*"), "query", rec) is AuditView.RAW


def test_redact_entry_for_manager_strips_payload_and_pii() -> None:
    entry = AuditEntry(
        id=1,
        ts=datetime(2026, 10, 1, tzinfo=UTC),
        actor_user_id=uuid.uuid4(),
        actor_username="m",
        action="order.place",
        outcome=AuditOutcome.SUCCESS,
        severity=Severity.INFO,
        ip="100.84.12.9",
        user_agent="ua",
        request_id="r",
        detail={"symbol": "BTCUSDT"},
        entry_hash="h",
        prev_hash=None,
    )
    out = redact_entry_for_view(entry.model_copy(update={"prev_hash": "p"}), AuditView.OWN_REDACTED)
    assert out.detail == {} and out.ip is None and out.user_agent is None
    assert out.action == "order.place" and out.entry_hash is None and out.prev_hash is None
    assert redact_entry_for_view(entry, AuditView.RAW) == entry


def test_own_redacted_allow_list_is_pinned() -> None:
    """SR-067 and contract #2392: exactly these fields keep their values for a Manager;
    widening the list needs Security review."""
    assert OWN_REDACTED_FIELDS == {
        "id",
        "ts",
        "actor_user_id",
        "actor_username",
        "action",
        "subject_type",
        "subject_id",
        "outcome",
        "severity",
        "request_id",
    }


def test_redact_projection_is_an_allow_list_new_fields_hidden_by_default() -> None:
    class _FutureEntry(AuditEntry):
        geo_country: str | None = None

    entry = _FutureEntry(
        id=1,
        ts=datetime(2026, 10, 1, tzinfo=UTC),
        actor_user_id=uuid.uuid4(),
        action="order.place",
        outcome=AuditOutcome.SUCCESS,
        severity=Severity.INFO,
        ip="100.84.12.9",
        request_id="r",
        detail={"k": "v"},
        entry_hash="h",
        prev_hash=None,
        geo_country="NL",
    )
    out = redact_entry_for_view(entry, AuditView.OWN_REDACTED)
    assert isinstance(out, _FutureEntry)
    assert out.geo_country is None and out.detail == {} and out.ip is None
    assert out.action == "order.place"
    assert "geo_country" not in OWN_REDACTED_FIELDS
