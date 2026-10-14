"""Signing failures carry no plaintext out of M2 (#2350 security review, C-2.7, C-12.2, C-12.6).

A failed MAC is raised as a typed `CredentialUnavailable("signing_failed")` with nothing chained,
after the failed call's frames are cleared: the stdlib `hmac` frames hold the secret and the
spliced key id. Mirrors `test_borrow_traceback_frame_locals_hold_no_plaintext` (in
`test_broker_safety.py`) for the only production decrypt path, `_sign`. Synthetic vectors only.
"""

from __future__ import annotations

import asyncio
import hmac
import sys
import traceback
from collections.abc import Iterator
from typing import NoReturn

import pytest

from candleviewer.secrets import KEY_ID_SLOT, CredentialUnavailable, Secret
from candleviewer.secrets import broker as broker_mod
from candleviewer.secrets import signing as signing_mod
from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.signing import mac_hex
from tests.unit.credentials_m2._helpers import _h, _store
from tests.unit.credentials_m2._vectors import API_KEY, API_SECRET

MSG = (b"1700000000000", KEY_ID_SLOT, b"5000", b"category=linear")


class _HmacFault:
    """Stands in for `signing.hmac`. It runs the real stdlib HMAC with a digest constructor that
    raises, so the failure happens inside the stdlib frames holding the secret (`key`) and the
    spliced key id (`msg`), as an allocation failure there would."""

    def __init__(self, fault: BaseException) -> None:
        self._fault = fault

    def new(self, key: bytes, msg: bytes, digestmod: object) -> hmac.HMAC:
        def failing_digest(*_: object) -> NoReturn:
            raise self._fault

        return hmac.new(key, msg, failing_digest)


def _rendered(exc: BaseException) -> str:
    """The traceback as a locals-capturing renderer sees it (structlog `dict_tracebacks`,
    `rich`, a crash reporter's local-variable capture)."""
    return "".join(traceback.TracebackException.from_exception(exc, capture_locals=True).format())


def _assert_no_plaintext(exc: BaseException) -> None:
    text = _rendered(exc)
    assert API_KEY not in text and API_SECRET not in text


@pytest.mark.parametrize("fault", [RuntimeError("boom"), MemoryError()], ids=repr)
async def test_sign_failure_is_typed_unchained_and_its_traceback_holds_no_plaintext(
    broker: CredentialBroker, monkeypatch: pytest.MonkeyPatch, fault: Exception
) -> None:
    meta = await _store(broker)
    monkeypatch.setattr(signing_mod, "hmac", _HmacFault(fault))
    with pytest.raises(CredentialUnavailable) as info:
        await _h(broker).sign(meta.key_id, MSG, purpose="sign_rest")
    assert str(info.value) == "signing_failed"
    assert info.value.__context__ is None and info.value.__cause__ is None
    _assert_no_plaintext(info.value)


@pytest.mark.parametrize("fault", [KeyboardInterrupt, asyncio.CancelledError])
async def test_sign_lets_base_exceptions_propagate_with_frames_cleared(
    broker: CredentialBroker, monkeypatch: pytest.MonkeyPatch, fault: type[BaseException]
) -> None:
    """Not caused by the MAC, so neither swallowed nor converted; still scrubbed on the way out."""
    meta = await _store(broker)
    monkeypatch.setattr(signing_mod, "hmac", _HmacFault(fault()))
    with pytest.raises(fault) as info:
        await _h(broker).sign(meta.key_id, MSG, purpose="sign_rest")
    _assert_no_plaintext(info.value)


def test_mac_hex_failure_is_typed_and_clears_the_stdlib_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(signing_mod, "hmac", _HmacFault(RuntimeError("boom")))
    with pytest.raises(CredentialUnavailable) as info:
        mac_hex(Secret(API_KEY), Secret(API_SECRET), MSG)
    assert str(info.value) == "signing_failed"
    assert info.value.__context__ is None and info.value.__cause__ is None
    _assert_no_plaintext(info.value)


def test_scrub_frames_clears_chained_tracebacks() -> None:
    def leaf(material: str) -> NoReturn:
        raise ValueError("inner")

    with pytest.raises(ValueError) as info:
        try:
            leaf(API_SECRET)
        except ValueError:
            leaf(API_KEY)
    assert info.value.__context__ is not None  # the chained exception's frames hold the secret
    signing_mod.scrub_frames(info.value)
    _assert_no_plaintext(info.value)


@pytest.fixture
def kept() -> Iterator[list[BaseException]]:
    """Every exception raised during the test, kept as a debugger or APM hook would keep it."""
    mon, tool = sys.monitoring, 4  # a free tool id (0 debugger, 1 coverage, 2 profiler)
    out: list[BaseException] = []

    def on_raise(code: object, offset: int, exc: BaseException) -> None:
        out.append(exc)

    mon.use_tool_id(tool, "cv-test-kept-exceptions")
    mon.register_callback(tool, mon.events.RAISE, on_raise)
    mon.set_events(tool, mon.events.RAISE)
    try:
        yield out
    finally:
        mon.set_events(tool, 0)
        mon.register_callback(tool, mon.events.RAISE, None)
        mon.free_tool_id(tool)


async def test_a_kept_reference_to_the_failed_mac_shows_no_plaintext(
    broker: CredentialBroker, monkeypatch: pytest.MonkeyPatch, kept: list[BaseException]
) -> None:
    meta = await _store(broker)
    fault = RuntimeError("boom")
    monkeypatch.setattr(signing_mod, "hmac", _HmacFault(fault))
    with pytest.raises(CredentialUnavailable):
        await _h(broker).sign(meta.key_id, MSG, purpose="sign_rest")
    assert fault in kept  # never chained, yet a hook still holds it: its frames are cleared
    _assert_no_plaintext(fault)


async def test_a_kept_reference_to_a_failure_below_mac_shows_no_plaintext(
    broker: CredentialBroker, monkeypatch: pytest.MonkeyPatch, kept: list[BaseException]
) -> None:
    """`mac` clears the frames below it too, whatever fails there (not only the stdlib HMAC)."""
    meta = await _store(broker)
    fault = MemoryError()

    def leak(plain: str) -> NoReturn:
        raise fault

    def failing_mac_hex(key_id: Secret[str], secret: Secret[str], message: object) -> str:
        leak(secret.reveal())  # a finished frame below `mac` that holds the secret

    monkeypatch.setattr(broker_mod, "mac_hex", failing_mac_hex)
    with pytest.raises(CredentialUnavailable) as info:
        await _h(broker).sign(meta.key_id, MSG, purpose="sign_rest")
    assert str(info.value) == "signing_failed" and info.value.__context__ is None
    assert fault in kept
    _assert_no_plaintext(fault)
