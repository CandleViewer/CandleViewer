"""`BybitSigner` (#2339, C-2.7): this module builds the string-to-sign; M2 computes the MAC.

Vectors are the Bybit v5 "Integration Guidance" worked examples recorded in
`docs/research/06-bybit-api.md` ("Confirmed worked example from the live docs"): the doc's
`XXXXXXXXXX` placeholder is the key id and, in the end-to-end case, also the synthetic secret.
The expected MACs are fixed values (HMAC-SHA256, lowercase hex). No real key is used anywhere.
"""

from __future__ import annotations

import dataclasses

import pytest

from candleviewer.exchange.bybit.signer import BybitSignature, BybitSigner
from candleviewer.secrets import Secret, mint_borrower
from candleviewer.secrets.store import InMemoryCredentialStore
from tests._signing import CREDENTIAL_ID, Call, fake_capability, stand_in_signature
from tests.unit.credentials_m2._service_fakes import _boot, _Src
from tests.unit.credentials_m2._vectors import ACCOUNT, KEK_V1, SNAPSHOT

DOC_KEY_ID = "XXXXXXXXXX"
DOC_GET = (1658384314791, "category=option&symbol=BTC-29JUL22-25000-C")
DOC_GET_STRING = b"1658384314791XXXXXXXXXX5000category=option&symbol=BTC-29JUL22-25000-C"
DOC_POST = (1658385579423, '{"category":"option"}')
DOC_POST_STRING = b'1658385579423XXXXXXXXXX5000{"category":"option"}'
#: HMAC-SHA256 of each string-to-sign with the doc placeholder as the (synthetic) secret.
DOC_GET_MAC = "c00720f96c5934ca7057ac28ae65b823f83b8b67a8fe784e7795ca0fa3c148ec"
DOC_POST_MAC = "ff137e622dc52629f41b52ea614eab59502e2b0663f153c528cb570379c469b7"
CASES = [(*DOC_GET, DOC_GET_MAC), (*DOC_POST, DOC_POST_MAC)]
#: A private-WS `auth` (24 §14.3 "Auth (WS)"): `expires` from the research doc's illustrative
#: op, and the MAC of `GET/realtime` + `expires` with the same synthetic secret.
WS_EXPIRES, WS_STRING = 1735500000000, b"GET/realtime1735500000000"
WS_MAC = "930517713cc9f5b0fcc3c2db56a9f291ecdd248eaac80c34bad925f729f4b36d"
STRINGS = [(*DOC_GET, DOC_GET_STRING), (*DOC_POST, DOC_POST_STRING)]


@pytest.mark.parametrize(("ts", "payload", "string_to_sign"), STRINGS, ids=["get", "post"])
async def test_string_to_sign_is_the_documented_example(
    ts: int, payload: str, string_to_sign: bytes
) -> None:
    calls: list[Call] = []
    signer = BybitSigner(fake_capability(DOC_KEY_ID, calls), CREDENTIAL_ID)
    out = await signer.sign(timestamp_ms=ts, recv_window_ms=5000, payload=payload)
    assert calls == [(CREDENTIAL_ID, string_to_sign, "sign_rest")]
    assert out == BybitSignature(DOC_KEY_ID, stand_in_signature(string_to_sign))


@pytest.mark.parametrize(("ts", "payload", "mac"), CASES, ids=["get", "post"])
async def test_m2_computes_the_documented_signature_end_to_end(
    ts: int, payload: str, mac: str
) -> None:
    """Real composition: started `SecretsService` -> minted capability -> `BybitSigner`."""
    svc = await _boot(InMemoryCredentialStore(), _Src(KEK_V1, 1))
    broker = svc._require()
    meta = await broker.store(
        "demo", ACCOUNT, "doc", Secret(DOC_KEY_ID), Secret(DOC_KEY_ID), SNAPSHOT
    )
    broker._store.activate(meta.key_id)  # type: ignore[attr-defined]  # in-memory fake helper
    signer = BybitSigner(mint_borrower(svc, "exchange_adapter"), meta.key_id)
    out = await signer.sign(timestamp_ms=ts, recv_window_ms=5000, payload=payload)
    assert out == BybitSignature(api_key=DOC_KEY_ID, signature=mac)


async def test_ws_auth_signs_get_realtime_and_expires_under_its_own_purpose() -> None:
    """No key-id slot; `sign_ws_auth` whatever the signer's REST purpose (#836 slice 2b5)."""
    calls: list[Call] = []
    signer = BybitSigner(fake_capability(DOC_KEY_ID, calls), CREDENTIAL_ID, purpose="key_verify")
    out = await signer.sign_ws_auth(expires_ms=WS_EXPIRES)
    assert calls == [(CREDENTIAL_ID, WS_STRING, "sign_ws_auth")]
    assert out == BybitSignature(DOC_KEY_ID, stand_in_signature(WS_STRING))


async def test_m2_computes_the_ws_auth_signature_end_to_end() -> None:
    store = InMemoryCredentialStore()
    svc = await _boot(store, _Src(KEK_V1, 1))
    meta = await svc._require().store(
        "demo", ACCOUNT, "doc", Secret(DOC_KEY_ID), Secret(DOC_KEY_ID), SNAPSHOT
    )
    store.activate(meta.key_id)  # `sign_ws_auth` signs active keys only
    signer = BybitSigner(mint_borrower(svc, "exchange_adapter"), meta.key_id)
    out = await signer.sign_ws_auth(expires_ms=WS_EXPIRES)
    assert out == BybitSignature(api_key=DOC_KEY_ID, signature=WS_MAC)


async def test_purpose_is_passed_to_m2() -> None:
    calls: list[Call] = []
    cap = fake_capability("k", calls)
    await BybitSigner(cap, CREDENTIAL_ID).sign(timestamp_ms=1, recv_window_ms=5000, payload="")
    await BybitSigner(cap, CREDENTIAL_ID, purpose="key_verify").sign(
        timestamp_ms=1, recv_window_ms=5000, payload=""
    )
    assert [c[2] for c in calls] == ["sign_rest", "key_verify"]


def test_signer_holds_no_credential_material() -> None:
    """C-2.7: the signer keeps a capability and a credential id, never a key or a secret."""
    signer = BybitSigner(fake_capability("visible-key"), CREDENTIAL_ID)
    assert set(BybitSigner.__slots__) == {"_credentials", "_credential_id", "_purpose"}
    assert "visible-key" not in repr(signer) and str(CREDENTIAL_ID) in repr(signer)


def test_signature_repr_hides_key_id_and_mac() -> None:
    """#1895: neither the key id nor the MAC is rendered by `repr`."""
    out = BybitSignature(api_key="visible-key", signature="ab" * 32)
    assert "visible-key" not in repr(out) and "ab" * 32 not in repr(out)
    assert [f.name for f in dataclasses.fields(out)] == ["api_key", "signature"]
