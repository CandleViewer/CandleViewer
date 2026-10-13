"""M2-side request signing (#2339, C-2.7): the API secret is used only inside `secrets/`.

The exchange adapter sends a message (byte segments plus `API_KEY_ID`); M2 splices the key id in,
computes HMAC-SHA256 with the API secret and returns only the hex MAC and the key id. Fixed vectors
only: RFC 4231 test case 2 and known answers over the synthetic M2 vectors (never a real key).
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path
from typing import Any

import pytest

from candleviewer.secrets import API_KEY_ID, CredentialUnavailable, RequestSignature
from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.service import mint_borrower
from candleviewer.secrets.signing import check_message, mac_hex
from candleviewer.secrets.store import InMemoryCredentialStore
from tests.unit.credentials_m2._helpers import _h, _Spy, _store
from tests.unit.credentials_m2._service_fakes import _boot, _Src, _store_one
from tests.unit.credentials_m2._vectors import API_KEY, API_SECRET, KEK_V1, AuditLog, kek

MSG = (b"1700000000000", API_KEY_ID, b"5000", b"category=linear")
#: HMAC-SHA256 of MSG with the `_vectors` key id spliced in, keyed with the `_vectors` secret.
STORED_MAC = "81c6a542a4b8fd34eb4b302bba6ff87d48a986d190365f9eebcb17b55fec2a5f"
#: The same message for the `_service_fakes` credential (key id "ABCD1234", secret "s").
SERVICE_MAC = "1a64e943d14e0332b0cb874842b901a056faae11b4a12158cabf785d8dcd7c3a"
#: RFC 4231 HMAC-SHA256 test case 2.
RFC4231_TC2 = ("Jefe", b"what do ya want for nothing?")
RFC4231_TC2_MAC = "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"
_SECRETS_PKG = Path(__file__).resolve().parents[3] / "candleviewer" / "secrets"


def test_mac_matches_rfc4231_test_case_2() -> None:
    material, data = RFC4231_TC2
    assert mac_hex("unused", material, (data,)) == RFC4231_TC2_MAC


def test_key_id_is_spliced_at_every_slot() -> None:
    spliced = mac_hex("K1", "m", (API_KEY_ID, b"-", API_KEY_ID, b"-"))
    assert spliced == mac_hex("unused", "m", (b"K1-K1-",))
    assert mac_hex("K1", "m", (b"x",)) == mac_hex("K2", "m", (b"x",))  # no slot: id unused


@pytest.mark.parametrize(
    "bad",
    [(), [b"x"], (b"x", "y"), (bytearray(b"x"),), ("api_key_id",), (b"x", None), b"x", None],
    ids=repr,
)
def test_check_message_refuses_malformed_messages(bad: Any) -> None:
    with pytest.raises(TypeError):
        check_message(bad)


def test_check_message_accepts_bytes_and_the_slot() -> None:
    assert check_message(MSG) is MSG


async def test_sign_returns_only_the_mac_and_the_key_id(
    broker: CredentialBroker, audit: AuditLog
) -> None:
    meta = await _store(broker)
    out = await _h(broker).sign(meta.key_id, MSG, purpose="sign_rest")
    assert isinstance(out, RequestSignature)
    assert [f.name for f in dataclasses.fields(out)] == ["api_key", "signature"]
    assert out.api_key.reveal() == API_KEY and out.signature == STORED_MAC
    assert API_SECRET not in repr(out) and STORED_MAC not in repr(out)
    assert audit.actions() == ["security.credential_stored", "security.credential_borrowed"]
    borrowed = audit.records[1][1]
    assert borrowed["caller_module"] == "exchange_adapter" and borrowed["purpose"] == "sign_rest"


async def test_malformed_message_is_refused_before_any_borrow(
    broker: CredentialBroker, audit: AuditLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = await _store(broker)
    spy = _Spy(monkeypatch)
    with pytest.raises(TypeError):
        await _h(broker).sign(meta.key_id, [b"x"], purpose="sign_rest")  # type: ignore[arg-type]
    assert audit.actions() == ["security.credential_stored"]  # nothing borrowed, nothing audited
    assert spy.bufs == []  # nothing decrypted


async def test_sign_zeroes_every_decrypted_buffer(monkeypatch: pytest.MonkeyPatch) -> None:
    b = CredentialBroker(InMemoryCredentialStore(), AuditLog(), kek(), dek_cache_ttl_s=0)
    meta = await _store(b)
    spy = _Spy(monkeypatch)
    assert (await _h(b).sign(meta.key_id, MSG, purpose="sign_rest")).signature == STORED_MAC
    assert spy.all_zero()  # DEK, key id and secret buffers


async def test_sign_refuses_unknown_caller_and_purpose(broker: CredentialBroker) -> None:
    meta = await _store(broker)
    for caller, purpose in (("admin", "sign_rest"), ("exchange_adapter", "anything")):
        with pytest.raises(CredentialUnavailable):
            await broker._sign(meta.key_id, MSG, caller, purpose)


def test_borrow_handle_exposes_only_sign(broker: CredentialBroker) -> None:
    assert {n for n in dir(_h(broker)) if not n.startswith("_")} == {"sign"}


async def test_minted_capability_signs_and_exposes_only_sign() -> None:
    svc = await _boot(InMemoryCredentialStore(), _Src(KEK_V1, 1))
    meta = await _store_one(svc)
    cap = mint_borrower(svc, "exchange_adapter")
    assert {n for n in dir(cap) if not n.startswith("_")} == {"sign"}
    out = await cap.sign(meta.key_id, MSG, purpose="sign_rest")
    assert out.api_key.reveal() == "ABCD1234" and out.signature == SERVICE_MAC


def test_decrypt_path_is_used_only_by_sign() -> None:
    """Structural (C-2.7): inside M2 the plaintext decrypt (`_borrow`) has one production
    caller, `_sign`, which uses the secret for the MAC and returns no plaintext secret."""
    callers: set[str] = set()
    for path in sorted(_SECRETS_PKG.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                for n in ast.walk(fn):
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                        if n.func.attr == "_borrow":
                            callers.add(f"{path.name}:{fn.name}")
    assert callers == {"broker.py:_sign"}
