"""The signing audit trail (#2350 security review, C-2.9).

The write-ahead `security.credential_borrowed` record carries `message_sha256`: a digest of the
message as the caller sent it, before the key id is spliced in, so the key id is never hashed. A
signing failure after that record is closed by `security.credential_sign_failed`; a refusal
before it writes neither. Synthetic vectors only (never a real key).
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
from pathlib import Path
from typing import Any, NoReturn

import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.redact import redact
from candleviewer.secrets import KEY_ID_SLOT, CredentialUnavailable
from candleviewer.secrets import broker as broker_mod
from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.signing import SigningMessage, message_sha256
from tests.unit.credentials_m2._helpers import _h, _Spy, _store
from tests.unit.credentials_m2._vectors import API_KEY, AuditLog, kek

MSG = (b"1700000000000", KEY_ID_SLOT, b"5000", b"category=linear")
#: `message_sha256(MSG)`: SHA-256 over each bytes part framed as 0x00, its 8-byte big-endian
#: length and the bytes, and each `KEY_ID_SLOT` as 0x01. Computed independently.
MSG_SHA256 = "ddbbbde75c987fc2b493300de90316732ad8e1d72d870be73b41b0f2d393cd2e"
#: A second synthetic, low-entropy key id (same shape as `_vectors.API_KEY`).
OTHER_KEY = "testkey" + "1" * 13 + "QRST"
_SECRETS_PKG = Path(__file__).resolve().parents[3] / "candleviewer" / "secrets"
_BORROWED, _FAILED = "security.credential_borrowed", "security.credential_sign_failed"


def _mac_fails_with(monkeypatch: pytest.MonkeyPatch, fault: BaseException) -> None:
    def failing_mac_hex(*_: object) -> NoReturn:
        raise fault

    monkeypatch.setattr(broker_mod, "mac_hex", failing_mac_hex)


def test_message_digest_is_a_framed_sha256_of_the_unspliced_message() -> None:
    framed = b"".join(
        b"\x00" + len(p).to_bytes(8, "big") + p if isinstance(p, bytes) else b"\x01" for p in MSG
    )
    assert hashlib.sha256(framed).hexdigest() == MSG_SHA256  # the pinned framing
    assert message_sha256(MSG) == MSG_SHA256


@pytest.mark.parametrize(
    ("one", "other"),
    [((b"ab",), (b"a", b"b")), ((b"ab", KEY_ID_SLOT), (b"a", KEY_ID_SLOT, b"b"))],
    ids=["split", "slot-position"],
)
def test_message_digest_tells_apart_messages_with_the_same_bytes(
    one: SigningMessage, other: SigningMessage
) -> None:
    assert message_sha256(one) != message_sha256(other)


def test_message_digest_survives_audit_redaction() -> None:
    fields = {"message_sha256": MSG_SHA256}
    assert redact(fields) == fields


async def test_borrowed_record_carries_the_digest_and_never_the_key_id(
    store: Any, audit: AuditLog
) -> None:
    b = CredentialBroker(store, audit, kek())
    metas = [await _store(b), await _store(b, key=OTHER_KEY)]
    sigs = {(await _h(b).sign(m.key_id, MSG, purpose="sign_rest")).signature for m in metas}
    borrowed = [f for a, f in audit.records if a == _BORROWED]
    assert [f["message_sha256"] for f in borrowed] == [MSG_SHA256] * 2  # same for both key ids
    assert len(sigs) == 2  # while the two credentials do sign differently
    assert not any(k in v for k in (API_KEY, OTHER_KEY) for f in borrowed for v in f.values())


async def test_sign_failure_after_the_write_ahead_record_writes_the_outcome(
    broker: CredentialBroker, audit: AuditLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = await _store(broker)
    _mac_fails_with(monkeypatch, RuntimeError("boom"))
    with pytest.raises(CredentialUnavailable):
        await _h(broker).sign(meta.key_id, MSG, purpose="sign_rest")
    assert audit.actions() == ["security.credential_stored", _BORROWED, _FAILED]
    borrowed, failed = audit.records[1][1], audit.records[2][1]
    assert failed == {**borrowed, "reason": "signing_failed"}


async def test_decrypt_failure_after_the_write_ahead_record_writes_the_outcome(
    broker: CredentialBroker, audit: AuditLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = await _store(broker)
    _Spy(monkeypatch, fail_on=2)  # the secret fails GCM authentication
    with pytest.raises(CredentialUnavailable):
        await _h(broker).sign(meta.key_id, MSG, purpose="sign_rest")
    assert audit.actions()[-2:] == [_BORROWED, _FAILED]
    assert audit.records[-1][1]["reason"] == "credential_unavailable"


async def test_interrupted_sign_writes_the_outcome_and_propagates(
    broker: CredentialBroker, audit: AuditLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = await _store(broker)
    _mac_fails_with(monkeypatch, KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        await _h(broker).sign(meta.key_id, MSG, purpose="sign_rest")
    assert audit.actions()[-2:] == [_BORROWED, _FAILED]
    assert audit.records[-1][1]["reason"] == "interrupted"


async def test_sign_cancelled_after_the_write_ahead_record_writes_the_outcome(store: Any) -> None:
    started, audit = asyncio.Event(), AuditLog()
    b = CredentialBroker(store, audit, kek())
    meta = await _store(b)

    async def hang(key_id: Any) -> None:
        started.set()
        await asyncio.Event().wait()

    store.touch_last_used = hang
    task = asyncio.create_task(_h(b).sign(meta.key_id, MSG, purpose="sign_rest"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert audit.actions()[-2:] == [_BORROWED, _FAILED]
    assert audit.records[-1][1]["reason"] == "cancelled"


async def test_refusal_before_the_write_ahead_record_writes_no_outcome(store: Any) -> None:
    attempted: list[str] = []
    refuse_borrowed = False

    async def sink(action: str, fields: dict[str, str]) -> None:
        attempted.append(action)
        if refuse_borrowed and action == _BORROWED:
            raise RuntimeError("audit down")

    b = CredentialBroker(store, sink, kek())
    meta = await _store(b)
    store.activate(meta.key_id, "pending")  # refused at the status check, before any record
    with pytest.raises(CredentialUnavailable):
        await _h(b).sign(meta.key_id, MSG, purpose="sign_rest")
    store.activate(meta.key_id, "active")
    refuse_borrowed = True  # refused at the write-ahead record itself
    with pytest.raises(CredentialUnavailable):
        await _h(b).sign(meta.key_id, MSG, purpose="sign_rest")
    assert attempted == ["security.credential_stored", _BORROWED]


async def test_outcome_audit_failure_keeps_the_original_error(
    broker: CredentialBroker, audit: AuditLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = await _store(broker)

    def failing_mac_hex(*_: object) -> NoReturn:
        audit.fail = True  # the sink refuses the outcome record that follows
        raise RuntimeError("boom")

    monkeypatch.setattr(broker_mod, "mac_hex", failing_mac_hex)
    with pytest.raises(CredentialUnavailable) as info:
        await _h(broker).sign(meta.key_id, MSG, purpose="sign_rest")
    assert str(info.value) == "signing_failed"
    assert audit.actions()[-1] == _BORROWED


def test_every_m2_audit_action_is_registered() -> None:
    """`audit.emit` refuses an unregistered action, which would lose the record (C-2.9)."""
    used = {
        n.value
        for path in sorted(_SECRETS_PKG.rglob("*.py"))
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        if n.value.startswith("security.") and " " not in n.value
    }
    assert _FAILED in used
    assert used <= AUDIT_ACTIONS
