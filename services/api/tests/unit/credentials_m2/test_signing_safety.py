"""Signing failures and the signing audit trail (#2350 security review, C-2.7, C-2.9, C-12.6).

A failed MAC leaves M2 as a typed `signing_failed` with nothing chained, after the failed call's
frames (the stdlib `hmac` ones hold the secret and the spliced key id) are cleared. The write-ahead
`security.credential_borrowed` record carries `message_sha256` (the message before the key id is
spliced in); a failure after it appends `security.credential_sign_failed`. Synthetic vectors only.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import hmac
import sys
import traceback
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn

import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.redact import redact
from candleviewer.secrets import KEY_ID_SLOT, CredentialUnavailable
from candleviewer.secrets import broker as broker_mod
from candleviewer.secrets import signing as signing_mod
from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.signing import message_sha256, scrub_frames
from tests.unit.credentials_m2._helpers import _h, _Spy, _store
from tests.unit.credentials_m2._vectors import API_KEY, API_SECRET, AuditLog, kek

MSG = (b"1700000000000", KEY_ID_SLOT, b"5000", b"category=linear")
#: SHA-256 of MSG framed as 0x00 + 8-byte big-endian length + bytes per part, 0x01 per slot.
MSG_SHA256 = "ddbbbde75c987fc2b493300de90316732ad8e1d72d870be73b41b0f2d393cd2e"
OTHER_KEY = "testkey" + "1" * 13 + "QRST"  # a second synthetic, low-entropy key id
_BORROWED, _FAILED = "security.credential_borrowed", "security.credential_sign_failed"
Inject = Callable[[pytest.MonkeyPatch, BaseException], None]


def _throw(fault: BaseException, *held: object) -> NoReturn:
    raise fault  # this frame keeps `held` (plaintext, in the tests below)


def _fail_in_hmac(mp: pytest.MonkeyPatch, fault: BaseException) -> None:
    """The real stdlib HMAC fails inside its own frames, which hold the secret and the key id."""
    fake = SimpleNamespace(new=lambda k, m, _: hmac.new(k, m, lambda: _throw(fault)))
    mp.setattr(signing_mod, "hmac", fake)


def _fail_below_mac(mp: pytest.MonkeyPatch, fault: BaseException) -> None:
    """Any failure below `mac`, not only in the HMAC: a frame holding the revealed secret."""
    mp.setattr(broker_mod, "mac_hex", lambda k, s, m: _throw(fault, s.reveal()))


def _assert_no_plaintext(exc: BaseException) -> None:
    """As a locals-capturing renderer sees it (structlog `dict_tracebacks`, a crash reporter)."""
    text = "".join(traceback.TracebackException.from_exception(exc, capture_locals=True).format())
    assert API_KEY not in text and API_SECRET not in text


@pytest.fixture
def kept() -> Iterator[list[BaseException]]:
    """Every exception raised during the test, kept as a debugger or APM hook would keep it."""
    mon, tool, out = sys.monitoring, 4, []  # 4: a free tool id (0 debugger, 1 coverage, 2 profiler)
    mon.use_tool_id(tool, "cv-test-kept-exceptions")
    mon.register_callback(tool, mon.events.RAISE, lambda _c, _o, exc: out.append(exc))
    mon.set_events(tool, mon.events.RAISE)
    try:
        yield out
    finally:
        mon.set_events(tool, 0)
        mon.register_callback(tool, mon.events.RAISE, None)
        mon.free_tool_id(tool)


@pytest.mark.parametrize(
    "case",
    [
        (RuntimeError("boom"), CredentialUnavailable, "signing_failed"),
        (MemoryError(), CredentialUnavailable, "signing_failed"),
        (KeyboardInterrupt(), KeyboardInterrupt, "interrupted"),
        (asyncio.CancelledError(), asyncio.CancelledError, "cancelled"),
    ],
    ids=["error", "memory", "interrupt", "cancel"],
)
async def test_failed_mac_leaves_no_plaintext_and_closes_the_write_ahead_record(
    broker: CredentialBroker, audit: AuditLog, monkeypatch: pytest.MonkeyPatch, case: Any
) -> None:
    """An `Exception` becomes a typed, unchained `signing_failed`; a `BaseException` is not the
    MAC's doing and propagates unconverted. Neither traceback shows plaintext."""
    fault, raised, reason = case
    meta = await _store(broker)
    _fail_in_hmac(monkeypatch, fault)
    with pytest.raises(raised) as info:
        await _h(broker).sign(meta.key_id, MSG, purpose="sign_rest")
    if raised is CredentialUnavailable:
        assert str(info.value) == "signing_failed"
        assert info.value.__context__ is None and info.value.__cause__ is None
    _assert_no_plaintext(info.value)
    (borrowed_action, borrowed), (failed_action, failed) = audit.records[-2:]
    assert (borrowed_action, failed_action) == (_BORROWED, _FAILED)
    assert failed == {**borrowed, "reason": reason}


@pytest.mark.parametrize("inject", [_fail_in_hmac, _fail_below_mac], ids=["hmac", "below-mac"])
async def test_a_hook_kept_mac_failure_shows_no_plaintext(
    broker: CredentialBroker, monkeypatch: pytest.MonkeyPatch, kept: list[Any], inject: Inject
) -> None:
    """Never chained, yet a hook still holds the original failure: `mac_hex` and `mac` each
    clear the frames below them."""
    meta = await _store(broker)
    fault = RuntimeError("boom")
    inject(monkeypatch, fault)
    with pytest.raises(CredentialUnavailable):
        await _h(broker).sign(meta.key_id, MSG, purpose="sign_rest")
    assert fault in kept
    _assert_no_plaintext(fault)


def test_scrub_frames_clears_the_chained_tracebacks() -> None:
    with pytest.raises(ValueError) as info:
        try:
            _throw(ValueError("first"), API_SECRET)
        except ValueError:
            _throw(ValueError("second"), API_KEY)
    scrub_frames(info.value)
    _assert_no_plaintext(info.value)


def test_scrub_frames_terminates_on_a_cyclic_chain() -> None:
    first, second = ValueError("first"), ValueError("second")
    first.__context__, second.__cause__ = second, first
    scrub_frames(first)  # visits each exception once


def test_message_digest_is_the_framed_sha256_of_the_unspliced_message() -> None:
    """Framed, so the same bytes split or slotted differently never share a digest."""
    framed = b"".join(
        b"\x00" + len(p).to_bytes(8, "big") + p if isinstance(p, bytes) else b"\x01" for p in MSG
    )
    assert message_sha256(MSG) == hashlib.sha256(framed).hexdigest() == MSG_SHA256
    assert message_sha256((b"ab",)) != message_sha256((b"a", b"b"))
    assert message_sha256((b"ab", KEY_ID_SLOT)) != message_sha256((b"a", KEY_ID_SLOT, b"b"))


async def test_borrowed_record_carries_the_digest_and_never_the_key_id(
    store: Any, audit: AuditLog
) -> None:
    b = CredentialBroker(store, audit, kek())
    metas = [await _store(b), await _store(b, key=OTHER_KEY)]
    sigs = {(await _h(b).sign(m.key_id, MSG, purpose="sign_rest")).signature for m in metas}
    borrowed = [f for a, f in audit.records if a == _BORROWED]
    assert [f["message_sha256"] for f in borrowed] == [MSG_SHA256] * 2 and len(sigs) == 2
    assert not any(k in v for k in (API_KEY, OTHER_KEY) for f in borrowed for v in f.values())
    assert redact(borrowed[0])["message_sha256"] == MSG_SHA256  # survives audit redaction


async def test_decrypt_failure_after_the_write_ahead_record_writes_the_outcome(
    broker: CredentialBroker, audit: AuditLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = await _store(broker)
    _Spy(monkeypatch, fail_on=2)  # the secret fails GCM authentication
    with pytest.raises(CredentialUnavailable):
        await _h(broker).sign(meta.key_id, MSG, purpose="sign_rest")
    assert audit.actions()[-2:] == [_BORROWED, _FAILED]
    assert audit.records[-1][1]["reason"] == "credential_unavailable"


async def test_refusal_before_the_write_ahead_record_writes_no_outcome(store: Any) -> None:
    attempted: list[str] = []
    refused: set[str] = set()

    async def sink(action: str, fields: dict[str, str]) -> None:
        attempted.append(action)
        if action in refused:
            raise RuntimeError("audit down")

    b = CredentialBroker(store, sink, kek())
    meta = await _store(b)
    store.activate(meta.key_id, "pending")  # refused at the status check, before any record
    with pytest.raises(CredentialUnavailable):
        await _h(b).sign(meta.key_id, MSG, purpose="sign_rest")
    store.activate(meta.key_id, "active")
    refused.add(_BORROWED)  # refused at the write-ahead record itself
    with pytest.raises(CredentialUnavailable):
        await _h(b).sign(meta.key_id, MSG, purpose="sign_rest")
    assert attempted == ["security.credential_stored", _BORROWED]


async def test_outcome_audit_failure_keeps_the_original_error(
    broker: CredentialBroker, audit: AuditLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = await _store(broker)

    def fail(*_: object) -> NoReturn:
        audit.fail = True  # the sink refuses the outcome record that follows
        raise RuntimeError("boom")

    monkeypatch.setattr(broker_mod, "mac_hex", fail)
    with pytest.raises(CredentialUnavailable, match=r"^signing_failed$"):
        await _h(broker).sign(meta.key_id, MSG, purpose="sign_rest")
    assert audit.actions()[-1] == _BORROWED


def test_every_m2_audit_action_is_registered() -> None:
    """`audit.emit` refuses an unregistered action, which would lose the record (C-2.9)."""
    used = {
        n.value
        for p in sorted(Path(signing_mod.__file__).parent.rglob("*.py"))
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        if n.value.startswith("security.") and " " not in n.value
    }
    assert _FAILED in used and used <= AUDIT_ACTIONS
