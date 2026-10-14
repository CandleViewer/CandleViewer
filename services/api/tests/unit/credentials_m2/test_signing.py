"""M2-side request signing (#2339, C-2.7): the API secret is used only inside `secrets/`.

The exchange adapter sends a message (byte segments plus `KEY_ID_SLOT`); M2 splices the key id in,
computes HMAC-SHA256 with the API secret and returns only the hex MAC and the key id. Fixed vectors
only: RFC 4231 test case 2 and known answers over the synthetic M2 vectors (never a real key).
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path
from typing import Any

import pytest

from candleviewer.secrets import KEY_ID_SLOT, CredentialUnavailable, RequestSignature, Secret
from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.service import mint_borrower
from candleviewer.secrets.signing import (
    MAX_KEY_ID_SLOTS,
    MAX_MESSAGE_BYTES,
    MAX_MESSAGE_PARTS,
    check_message,
    mac_hex,
)
from candleviewer.secrets.store import InMemoryCredentialStore
from tests.unit.credentials_m2._helpers import _h, _Spy, _store
from tests.unit.credentials_m2._service_fakes import _boot, _Src, _store_one
from tests.unit.credentials_m2._vectors import API_KEY, API_SECRET, KEK_V1, AuditLog, kek

MSG = (b"1700000000000", KEY_ID_SLOT, b"5000", b"category=linear")
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
    assert mac_hex(Secret("unused"), Secret(material), (data,)) == RFC4231_TC2_MAC


def test_key_id_is_spliced_at_every_slot() -> None:
    k1, k2, m = Secret("K1"), Secret("K2"), Secret("m")
    spliced = mac_hex(k1, m, (KEY_ID_SLOT, b"-", KEY_ID_SLOT, b"-"))
    assert spliced == mac_hex(Secret("unused"), m, (b"K1-K1-",))
    assert mac_hex(k1, m, (b"x",)) == mac_hex(k2, m, (b"x",))  # no slot: id unused


@pytest.mark.parametrize(
    "bad",
    [(), [b"x"], (b"x", "y"), (bytearray(b"x"),), ("key_id",), (b"x", None), b"x", None],
    ids=repr,
)
def test_check_message_refuses_malformed_messages(bad: Any) -> None:
    with pytest.raises(TypeError):
        check_message(bad)


def test_check_message_accepts_bytes_and_the_slot() -> None:
    assert check_message(MSG) is MSG


def test_message_bounds_fit_bybit_v5_with_room() -> None:
    """REST string-to-sign: four parts, one key-id slot; WS auth: no slot (#2350 review)."""
    assert (MAX_MESSAGE_BYTES, MAX_MESSAGE_PARTS, MAX_KEY_ID_SLOTS) == (65536, 16, 1)


@pytest.mark.parametrize(
    "ok",
    [(b"x" * 65536, KEY_ID_SLOT), (b"",) * 16, (b"GET/realtime", b"1700000005000")],
    ids=["64KiB-one-slot", "16-parts", "ws-auth-no-slot"],
)
def test_check_message_accepts_messages_at_the_bounds(ok: Any) -> None:
    assert check_message(ok) is ok


@pytest.mark.parametrize(
    "bad",
    [(b"x" * 65536, b"y"), (b"",) * 17, (KEY_ID_SLOT, b"-", KEY_ID_SLOT)],
    ids=["one-byte-over-64KiB", "17-parts", "two-slots"],
)
def test_check_message_refuses_messages_over_the_bounds(bad: Any) -> None:
    with pytest.raises(TypeError):
        check_message(bad)


async def test_message_over_the_bounds_is_refused_before_any_borrow(
    broker: CredentialBroker, audit: AuditLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = await _store(broker)
    spy = _Spy(monkeypatch)
    for bad in ((b"x" * 65537,), (KEY_ID_SLOT, KEY_ID_SLOT), (b"",) * 17):
        with pytest.raises(TypeError):
            await _h(broker).sign(meta.key_id, bad, purpose="sign_rest")
    assert audit.actions() == ["security.credential_stored"]  # nothing borrowed, nothing audited
    assert spy.bufs == []  # nothing decrypted


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


def _borrow_refs(source: str, filename: str) -> set[str]:
    """`file:function` for every reference to `_borrow` in `source`: any attribute or name
    `_borrow` (called, aliased, passed or stored) and any str constant with a dotted part
    `_borrow` (getattr, attrgetter, ...). Not flagged: the `def` itself and bare string
    statements (docstrings), which cannot reach anything."""
    found: set[str] = set()
    scope: list[str] = []

    def hit() -> None:
        found.add(f"{filename}:{scope[-1] if scope else '<module>'}")

    class Scan(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            scope.append(node.name)
            self.generic_visit(node)
            scope.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Expr(self, node: ast.Expr) -> None:
            if not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
                self.generic_visit(node)

        def visit_Attribute(self, node: ast.Attribute) -> None:
            if node.attr == "_borrow":
                hit()
            self.generic_visit(node)

        def visit_Name(self, node: ast.Name) -> None:
            if node.id == "_borrow":
                hit()

        def visit_Constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, str) and "_borrow" in node.value.split("."):
                hit()

    Scan().visit(ast.parse(source))
    return found


def test_decrypt_path_is_used_only_by_sign() -> None:
    """Structural (C-2.7): inside M2 the plaintext decrypt (`_borrow`) has one production
    caller, `_sign`, which uses the secret for the MAC and returns no plaintext secret. Every
    reference counts, not only a direct call, so an alias cannot add a second caller."""
    refs: set[str] = set()
    for path in sorted(_SECRETS_PKG.rglob("*.py")):
        refs |= _borrow_refs(path.read_text(encoding="utf-8"), path.name)
    assert refs == {"broker.py:_sign"}


@pytest.mark.parametrize(
    "probe",
    [
        "async def leak(self, k):\n    b = self._borrow\n    return await b(k)\n",
        "async def leak(self, k):\n    return await getattr(self, '_borrow')(k)\n",
        "import functools\nasync def leak(self, k):\n"
        "    return await functools.partial(self._borrow, k)()\n",
        "import operator\nasync def leak(self, k):\n"
        "    return await operator.attrgetter('broker._borrow')(self)(k)\n",
        "class B:\n    async def _borrow(self, k): ...\n    leak = _borrow\n",
    ],
    ids=["alias", "getattr", "partial", "attrgetter", "class-alias"],
)
def test_decrypt_path_scan_flags_every_reference_form(probe: str) -> None:
    assert _borrow_refs(probe, "probe.py")


def test_decrypt_path_scan_ignores_the_definition_and_docstrings() -> None:
    probe = 'class B:\n    async def _borrow(self, k):\n        """Not self._borrow."""\n'
    assert _borrow_refs(probe, "probe.py") == set()
