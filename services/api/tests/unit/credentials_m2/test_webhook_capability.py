"""The alert webhook's M2 capabilities (#1400 S3, ADR-0009 Amendment 9): the sealer, the URL opener
and the bounded signer, over fixed test KEKs and the synthetic vectors of
`packages/fixtures/webhook/hmac_v1_vectors.json` (BQ-12; never a key, C-2.7)."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.secrets import (
    WebhookCapabilityRefused,
    WebhookSealer,
    WebhookSigner,
    WebhookTargetOpener,
    webhook,
)
from candleviewer.secrets import _envelope as env
from candleviewer.secrets._kek import WEBHOOK_WRAP_LEN, LoadedKek
from candleviewer.secrets.errors import KekUnavailable
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2, kek

VECTORS: list[dict[str, Any]] = json.loads(
    (
        Path(__file__).resolve().parents[5] / "packages/fixtures/webhook/hmac_v1_vectors.json"
    ).read_text(encoding="utf-8")
)["vectors"]
ALERT = UUID("00000000-0000-4000-8000-00000000a1e7")
OTHER = UUID("00000000-0000-4000-8000-00000000b0b0")
URL = "https://hooks.example.test/alerts/receiver-path-token"
SECRET = b"synthetic webhook secret for tests, never a key."
DIGEST = hashlib.sha256(b'{"event":"alert.fired"}').digest()


def verify(secret: bytes, timestamp: int, delivery_id: int, body: bytes, signature: str) -> bool:
    """An independent receiver, written from the ADR text with the stdlib alone (BQ-03): hash the
    bytes received, rebuild the signed string, compare in constant time."""
    signed = f"cv.alert.webhook.v1:{timestamp}:{delivery_id}:{hashlib.sha256(body).hexdigest()}"
    mac = hmac.new(secret, signed.encode("ascii"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, signature)


class _Keks:
    """The KEKs held, the current first, counting each resolution; its `guard` stands in for the
    broker's `_guard`, held across the `with` body as `service._webhook_keks` holds it."""

    def __init__(self, *held: LoadedKek) -> None:
        self.held, self.calls, self.guard = held, 0, threading.Lock()

    @contextmanager
    def __call__(self) -> Iterator[tuple[LoadedKek, ...]]:
        self.calls += 1
        with self.guard:
            yield self.held


def _caps(keks: webhook.Keks) -> tuple[Any, Any, Any]:
    return webhook.sealer(keks), webhook.opener(keks), webhook.signer(keks)


async def _refused(call: Any) -> str:
    with pytest.raises(WebhookCapabilityRefused) as info:
        await call
    assert info.value.__cause__ is None and info.value.__context__ is None  # nothing chained
    return info.value.reason


# --- vectors and the independent verifier --------------------------------------------------


@pytest.mark.parametrize("vec", VECTORS, ids=[v["name"] for v in VECTORS])
def test_vector_verifies_with_the_independent_receiver(vec: dict[str, Any]) -> None:
    secret, body = vec["secret_utf8"].encode(), vec["body_utf8"].encode()
    assert len(secret) == vec["secret_len"] and 32 <= len(secret) <= 128
    assert hashlib.sha256(body).hexdigest() == vec["body_sha256_hex"]
    sig = vec["expected_hmac_hex"]
    assert verify(secret, vec["timestamp"], vec["delivery_id"], body, sig)
    flipped = ("0" if sig[0] != "0" else "1") + sig[1:]
    assert not verify(secret, vec["timestamp"], vec["delivery_id"], body, flipped)
    assert not verify(secret, vec["timestamp"] + 1, vec["delivery_id"], body, sig)


@pytest.mark.parametrize("vec", VECTORS, ids=[v["name"] for v in VECTORS])
async def test_signer_matches_each_vector(vec: dict[str, Any]) -> None:
    sealer, _, signer = _caps(_Keks(kek()))
    blob = await sealer.seal_secret(vec["secret_utf8"].encode(), ALERT)
    digest = bytes.fromhex(vec["body_sha256_hex"])
    sig = await signer.sign_delivery(blob, ALERT, vec["delivery_id"], vec["timestamp"], digest)
    assert sig == vec["expected_hmac_hex"]
    body = vec["body_utf8"].encode()
    assert verify(vec["secret_utf8"].encode(), vec["timestamp"], vec["delivery_id"], body, sig)
    signed = webhook.message(vec["timestamp"], vec["delivery_id"], digest)
    assert signed == vec["signed_string"].encode()


async def test_signer_accepts_the_alert_id_as_text() -> None:
    sealer, _, signer = _caps(_Keks(kek()))
    blob = await sealer.seal_secret(SECRET, ALERT)
    by_text = await signer.sign_delivery(blob, str(ALERT), 5, 1_767_225_600, DIGEST)
    assert by_text == await signer.sign_delivery(blob, ALERT, 5, 1_767_225_600, DIGEST)


# --- seal and open, and what binds a blob -------------------------------------------------


async def test_target_round_trips_and_each_seal_is_fresh() -> None:
    sealer, opener, _ = _caps(_Keks(kek()))
    one, two = await sealer.seal_target(URL, ALERT), await sealer.seal_target(URL, ALERT)
    assert one != two and URL.encode() not in one
    assert await opener.open_target(one, ALERT) == await opener.open_target(two, ALERT) == URL
    assert one[:4] == webhook.MAGIC and int.from_bytes(one[4:8], "big") == 1


async def test_another_alerts_id_does_not_open_the_blob() -> None:
    sealer, opener, signer = _caps(_Keks(kek()))
    target, secret = await sealer.seal_target(URL, ALERT), await sealer.seal_secret(SECRET, ALERT)
    assert await _refused(opener.open_target(target, OTHER)) == "webhook_seal_invalid"
    signing = signer.sign_delivery(secret, OTHER, 1, 1, DIGEST)
    assert await _refused(signing) == "webhook_seal_invalid"


async def test_a_blob_does_not_open_as_the_other_column() -> None:
    sealer, opener, signer = _caps(_Keks(kek()))
    target, secret = await sealer.seal_target(URL, ALERT), await sealer.seal_secret(SECRET, ALERT)
    assert await _refused(opener.open_target(secret, ALERT)) == "webhook_seal_invalid"
    signing = signer.sign_delivery(target, ALERT, 1, 1, DIGEST)
    assert await _refused(signing) == "webhook_seal_invalid"


async def test_another_environments_kek_does_not_open_the_blob() -> None:
    blob = await webhook.sealer(_Keks(kek())).seal_target(URL, ALERT)
    other_env = webhook.opener(_Keks(kek(env="testnet")))
    assert await _refused(other_env.open_target(blob, ALERT)) == "webhook_seal_invalid"


@pytest.mark.parametrize(
    "damage",
    [
        lambda b: b[:-1] + bytes([b[-1] ^ 1]),  # the value's tag
        lambda b: b[:20] + bytes([b[20] ^ 1]) + b[21:],  # the DEK wrap
        lambda b: b"cvw0" + b[4:],  # another format
        lambda b: b[:4] + (0).to_bytes(4, "big") + b[8:],  # no KEK version
        lambda b: b[:-30],  # too short to hold a value
    ],
    ids=["tag", "wrap", "magic", "version0", "short"],
)
async def test_a_damaged_blob_is_refused(damage: Callable[[bytes], bytes]) -> None:
    sealer, opener, _ = _caps(_Keks(kek()))
    blob = damage(await sealer.seal_target(URL, ALERT))
    assert await _refused(opener.open_target(blob, ALERT)) == "webhook_seal_invalid"


async def test_a_bytearray_copy_of_a_blob_opens() -> None:
    sealer, opener, _ = _caps(_Keks(kek()))
    blob = bytearray(await sealer.seal_target(URL, ALERT))
    assert await opener.open_target(blob, ALERT) == URL


@pytest.mark.parametrize("blob", ["text", memoryview(b"x" * 200), None, 7], ids=repr)
async def test_a_blob_that_is_not_bytes_is_refused(blob: object) -> None:
    _, opener, _ = _caps(_Keks(kek()))
    assert await _refused(opener.open_target(blob, ALERT)) == "webhook_seal_invalid"


async def test_a_blob_under_a_kek_not_held_is_refused() -> None:
    blob = await webhook.sealer(_Keks(kek(KEK_V2, 2))).seal_target(URL, ALERT)
    held_v1 = webhook.opener(_Keks(kek()))
    assert await _refused(held_v1.open_target(blob, ALERT)) == "webhook_kek_not_held"


async def test_a_blob_opens_under_the_previous_kek_while_held() -> None:
    blob = await webhook.sealer(_Keks(kek())).seal_target(URL, ALERT)
    opener = webhook.opener(_Keks(kek(KEK_V2, 2), kek()))
    assert await opener.open_target(blob, ALERT) == URL


async def test_a_blob_holding_a_secret_out_of_bounds_does_not_sign() -> None:
    held = kek()
    short = webhook._wh_seal((held,), ALERT, "secret", b"x" * 31)  # only M2 could write it
    signing = webhook.signer(_Keks(held)).sign_delivery(short, ALERT, 1, 1, DIGEST)
    assert await _refused(signing) == "webhook_seal_invalid"


# --- the signer's fixed field set -----------------------------------------------------------


class _Bytes(bytes):
    pass


#: Each bad member of a signing call, checked before any KEK is resolved or blob opened.
BAD_SIGN: dict[str, dict[str, object]] = {
    "digest_31": {"body_digest": DIGEST[:31]},
    "digest_33": {"body_digest": DIGEST + b"\x00"},
    "digest_hex_text": {"body_digest": DIGEST.hex()},
    "digest_subclass": {"body_digest": _Bytes(DIGEST)},
    "digest_view": {"body_digest": memoryview(DIGEST)},
    "delivery_0": {"delivery_id": 0},
    "delivery_negative": {"delivery_id": -1},
    "delivery_over_bigint": {"delivery_id": 2**63},
    "delivery_bool": {"delivery_id": True},
    "delivery_text": {"delivery_id": "1"},
    "delivery_float": {"delivery_id": 1.0},
    "timestamp_0": {"timestamp": 0},
    "timestamp_eleven_digits": {"timestamp": 10**10},
    "timestamp_bool": {"timestamp": True},
    "timestamp_float": {"timestamp": 1.5},
    "timestamp_with_colon": {"timestamp": "1:2"},
    "alert_not_uuid": {"alert_id": "not-a-uuid"},
    "alert_int": {"alert_id": 7},
}


@pytest.mark.parametrize("change", BAD_SIGN.values(), ids=list(BAD_SIGN))
async def test_signer_refuses_anything_outside_the_fixed_format(change: dict[str, object]) -> None:
    keks = _Keks(kek())
    blob = await webhook.sealer(keks).seal_secret(SECRET, ALERT)
    keks.calls = 0
    call: dict[str, Any] = {
        "sealed_secret": blob, "alert_id": ALERT, "delivery_id": 1, "timestamp": 1,
        "body_digest": DIGEST,
    } | change  # fmt: skip
    signer = webhook.signer(keks)
    assert await _refused(signer.sign_delivery(**call)) == "webhook_request_invalid"
    assert keks.calls == 0  # refused before any KEK is resolved or any blob opened


def test_the_signed_string_has_the_fixed_prefix_and_field_order() -> None:
    assert webhook.message(12, 34, b"\xab" * 32) == b"cv.alert.webhook.v1:12:34:" + b"ab" * 32


async def test_bounds_of_the_ids_and_timestamp_sign() -> None:
    sealer, _, signer = _caps(_Keks(kek()))
    blob = await sealer.seal_secret(SECRET, ALERT)
    top = await signer.sign_delivery(blob, ALERT, 2**63 - 1, 10**10 - 1, DIGEST)
    assert verify(SECRET, 10**10 - 1, 2**63 - 1, b'{"event":"alert.fired"}', top)


# --- the sealer's inputs --------------------------------------------------------------------

BAD_SEAL: dict[str, tuple[str, object]] = {
    "secret_31": ("secret", b"s" * 31),
    "secret_129": ("secret", b"s" * 129),
    "secret_text": ("secret", "s" * 40),
    "secret_subclass": ("secret", _Bytes(b"s" * 40)),
    "url_empty": ("url", ""),
    "url_space": ("url", "https://a.example.test/x y"),
    "url_newline": ("url", "https://a.example.test/\n"),
    "url_too_long": ("url", "https://a.example.test/" + "p" * 2048),
    "url_bytes": ("url", URL.encode()),
}


@pytest.mark.parametrize(("field", "value"), BAD_SEAL.values(), ids=list(BAD_SEAL))
async def test_sealer_refuses_out_of_bounds_input(field: str, value: Any) -> None:
    keks = _Keks(kek())
    sealer = webhook.sealer(keks)
    call = (
        sealer.seal_secret(value, ALERT) if field == "secret" else sealer.seal_target(value, ALERT)
    )
    assert await _refused(call) == "webhook_request_invalid"
    assert keks.calls == 0


@pytest.mark.parametrize("size", [32, 128])
async def test_sealer_takes_a_secret_at_either_bound(size: int) -> None:
    sealer, _, signer = _caps(_Keks(kek()))
    secret = bytearray(b"t" * size)
    blob = await sealer.seal_secret(secret, ALERT)
    sig = await signer.sign_delivery(blob, ALERT, 3, 4, DIGEST)
    assert verify(bytes(secret), 4, 3, b'{"event":"alert.fired"}', sig)


async def test_sealer_takes_a_url_at_the_bound() -> None:
    sealer, opener, _ = _caps(_Keks(kek()))
    url = "https://a.example.test/" + "p" * (2048 - 23)
    assert await opener.open_target(await sealer.seal_target(url, ALERT), ALERT) == url


# --- no KEK, and a defect -------------------------------------------------------------------


@contextmanager
def _no_kek() -> Iterator[tuple[LoadedKek, ...]]:
    raise KekUnavailable("kek_unavailable")
    yield ()  # a generator: the refusal comes as the `with` is entered


async def test_every_capability_refuses_without_a_kek() -> None:
    blob = await webhook.sealer(_Keks(kek())).seal_secret(SECRET, ALERT)
    sealer, opener, signer = _caps(_no_kek)
    assert await _refused(sealer.seal_target(URL, ALERT)) == "kek_unavailable"
    assert await _refused(opener.open_target(blob, ALERT)) == "kek_unavailable"
    assert await _refused(signer.sign_delivery(blob, ALERT, 1, 1, DIGEST)) == "kek_unavailable"


async def test_a_closed_kek_refuses() -> None:
    held = kek()
    blob = await webhook.sealer(_Keks(held)).seal_secret(SECRET, ALERT)
    held.close()
    signing = webhook.signer(_Keks(held)).sign_delivery(blob, ALERT, 1, 1, DIGEST)
    assert await _refused(signing) == "kek_unavailable"


async def test_an_unexpected_failure_is_a_closed_reason_logged_by_type() -> None:
    @contextmanager
    def broken() -> Iterator[tuple[LoadedKek, ...]]:
        raise RuntimeError(f"leaky text {URL}")
        yield ()

    with capture_logs() as logs:
        reason = await _refused(webhook.sealer(broken).seal_target(URL, ALERT))
    assert reason == "webhook_unavailable"
    assert logs[-1]["check"] == "RuntimeError" and URL not in repr(logs)


# --- zeroing --------------------------------------------------------------------------------


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[bytearray]:
    """Every buffer M2 opens or draws (DEKs, plaintexts), kept to check they are zeroed."""
    seen: list[bytearray] = []
    real_open, real_new = env.open_, env.new_dek

    def open_(key: bytes | bytearray, blob: bytes, aad_: bytes) -> bytearray:
        seen.append(real_open(key, blob, aad_))
        return seen[-1]

    def new_dek() -> bytearray:
        seen.append(real_new())
        return seen[-1]

    monkeypatch.setattr(env, "open_", open_)
    monkeypatch.setattr(env, "new_dek", new_dek)
    return seen


async def test_seal_zeroes_its_dek(opened: list[bytearray]) -> None:
    await webhook.sealer(_Keks(kek())).seal_secret(SECRET, ALERT)
    assert len(opened) == 1 and opened[0] == bytearray(32)


async def test_sign_zeroes_the_dek_and_the_secret(opened: list[bytearray]) -> None:
    sealer, _, signer = _caps(_Keks(kek()))
    blob = await sealer.seal_secret(SECRET, ALERT)
    opened.clear()
    await signer.sign_delivery(blob, ALERT, 1, 1, DIGEST)
    assert [len(b) for b in opened] == [32, len(SECRET)]  # the DEK, then the secret
    assert all(b == bytearray(len(b)) for b in opened)


async def test_open_target_zeroes_the_dek_and_the_url_bytes(opened: list[bytearray]) -> None:
    sealer, opener, _ = _caps(_Keks(kek()))
    blob = await sealer.seal_target(URL, ALERT)
    opened.clear()
    assert await opener.open_target(blob, ALERT) == URL
    assert [len(b) for b in opened] == [32, len(URL)]
    assert all(b == bytearray(len(b)) for b in opened)


async def test_a_refused_open_still_zeroes_the_dek(opened: list[bytearray]) -> None:
    sealer, opener, _ = _caps(_Keks(kek()))
    blob = await sealer.seal_target(URL, ALERT)
    opened.clear()
    damaged = blob[:-1] + bytes([blob[-1] ^ 1])
    assert await _refused(opener.open_target(damaged, ALERT)) == "webhook_seal_invalid"
    assert len(opened) == 1 and opened[0] == bytearray(32)  # the DEK opened, then zeroed


# --- redaction ------------------------------------------------------------------------------


async def test_no_value_reaches_a_log_or_an_exception() -> None:
    """C-12.6: refusals name the operation, the reason and the check, never the URL, the secret,
    a digest or an id."""
    sealer, opener, signer = _caps(_Keks(kek()))
    target, secret = await sealer.seal_target(URL, ALERT), await sealer.seal_secret(SECRET, ALERT)
    texts: list[str] = []
    with capture_logs() as logs:
        for call in (
            opener.open_target(target, OTHER),
            signer.sign_delivery(secret, OTHER, 77, 1_767_225_600, DIGEST),
            signer.sign_delivery(secret, ALERT, 77, 1_767_225_600, DIGEST[:31]),
            sealer.seal_secret(SECRET + b"x" * 100, ALERT),
            sealer.seal_target(URL + " ", ALERT),
        ):
            with pytest.raises(WebhookCapabilityRefused) as info:
                await call
            texts += [str(info.value), repr(info.value), repr(info.value.args)]
    assert {log["event"] for log in logs} == {"secrets.webhook_refused"}
    assert all(set(log) == {"event", "log_level", "op", "reason", "check"} for log in logs)
    haystack = " ".join(texts) + repr(logs)
    for value in (URL, "receiver-path-token", SECRET.decode(), DIGEST.hex(), str(ALERT),
                  str(OTHER), "1767225600", "77"):  # fmt: skip
        assert value not in haystack


def test_capabilities_hold_a_closure_only_and_stay_sealed() -> None:
    sealer, opener, signer = _caps(_Keks(kek()))
    for cap, public in (
        (sealer, {"seal_target", "seal_secret"}),
        (opener, {"open_target"}),
        (signer, {"sign_delivery"}),
    ):
        assert {n for n in dir(cap) if not n.startswith("_")} == public
        assert not hasattr(cap, "__dict__")
    for cls in (WebhookSealer, WebhookTargetOpener, WebhookSigner):
        with pytest.raises(TypeError, match="may not be subclassed"):
            type("Sub", (cls,), {"__module__": "candleviewer.alerts.x"})
        inside = type("Sub", (cls,), {"__module__": "candleviewer.secrets.x"})  # M2's own: allowed
        assert issubclass(inside, cls)


# --- KEK rotation ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["url", "secret"])
async def test_rewrap_moves_the_dek_to_the_current_kek(field: str) -> None:
    old, new = kek(KEK_V1, 1), kek(KEK_V2, 2)
    sealer = webhook.sealer(_Keks(old))
    blob = await (
        sealer.seal_target(URL, ALERT) if field == "url" else sealer.seal_secret(SECRET, ALERT)
    )
    moved = webhook.rewrap(_Keks(new, old), blob, ALERT, field)
    assert int.from_bytes(moved[4:8], "big") == 2 and moved[68:] == blob[68:]  # value unchanged
    only_new = _Keks(new)
    if field == "url":
        assert await webhook.opener(only_new).open_target(moved, ALERT) == URL
    else:
        sig = await webhook.signer(only_new).sign_delivery(moved, ALERT, 1, 2, DIGEST)
        assert verify(SECRET, 2, 1, b'{"event":"alert.fired"}', sig)
    assert webhook.rewrap(_Keks(new, old), moved, ALERT, field) == moved  # already current


async def test_rewrap_refuses_a_bad_field_another_alert_or_a_kek_not_held() -> None:
    old, new = kek(KEK_V1, 1), kek(KEK_V2, 2)
    blob = await webhook.sealer(_Keks(old)).seal_target(URL, ALERT)
    cases = (
        ((_Keks(new, old), blob, ALERT, "token"), "webhook_request_invalid"),
        ((_Keks(new, old), blob, OTHER, "url"), "webhook_seal_invalid"),
        ((_Keks(new, old), blob, ALERT, "secret"), "webhook_seal_invalid"),
        ((_Keks(new), blob, ALERT, "url"), "webhook_kek_not_held"),
    )
    for args, reason in cases:
        with pytest.raises(WebhookCapabilityRefused) as info:
            webhook.rewrap(*args)
        assert info.value.reason == reason


async def test_rewrap_refuses_a_wrap_that_does_not_verify(
    monkeypatch: pytest.MonkeyPatch, opened: list[bytearray]
) -> None:
    old, new = kek(KEK_V1, 1), kek(KEK_V2, 2)
    blob = await webhook.sealer(_Keks(old)).seal_target(URL, ALERT)
    real = LoadedKek.unwrap_webhook_dek
    calls: list[int] = []

    def unwrap(self: LoadedKek, wrapped: bytes, *, alert_id: UUID, field: str) -> bytearray:
        calls.append(self.version)
        out = real(self, wrapped, alert_id=alert_id, field=field)
        if self.version == 2:
            out[0] ^= 1  # the new wrap's check reads back another DEK
        return out

    monkeypatch.setattr(LoadedKek, "unwrap_webhook_dek", unwrap)
    opened.clear()
    with pytest.raises(WebhookCapabilityRefused) as info:
        webhook.rewrap(_Keks(new, old), blob, ALERT, "url")
    assert info.value.reason == "webhook_seal_invalid" and calls == [1, 2]
    assert [len(b) for b in opened] == [32, len(URL), 32]  # the DEK, the value, the check
    assert all(b == bytearray(len(b)) for b in opened)  # a refused verify zeroes them all


async def test_rewrap_refuses_a_row_whose_value_does_not_open(opened: list[bytearray]) -> None:
    """A corrupt row fails closed: the DEK opens, the value under it does not, nothing re-wraps."""
    old, new = kek(KEK_V1, 1), kek(KEK_V2, 2)
    blob = await webhook.sealer(_Keks(old)).seal_target(URL, ALERT)
    corrupt = blob[:-1] + bytes([blob[-1] ^ 1])  # the DEK wrap intact, the value's tag damaged
    opened.clear()
    with pytest.raises(WebhookCapabilityRefused) as info:
        webhook.rewrap(_Keks(new, old), corrupt, ALERT, "url")
    assert info.value.reason == "webhook_seal_invalid"
    assert len(opened) == 1 and opened[0] == bytearray(32)  # the DEK opened, then zeroed


async def test_rewrap_zeroes_the_dek_the_value_and_the_check(opened: list[bytearray]) -> None:
    old, new = kek(KEK_V1, 1), kek(KEK_V2, 2)
    blob = await webhook.sealer(_Keks(old)).seal_secret(SECRET, ALERT)
    opened.clear()
    webhook.rewrap(_Keks(new, old), blob, ALERT, "secret")
    assert [len(b) for b in opened] == [32, len(SECRET), 32]
    assert all(b == bytearray(len(b)) for b in opened)


async def test_two_seals_draw_fresh_wrap_and_value_nonces() -> None:
    """The DEK wrap's nonce and the value's are fresh per seal, read at the offsets the blob
    layout gives (`b"cvw1" || version(4) || wrap(nonce 12 ...) || nonce 12 ...`)."""
    sealer = webhook.sealer(_Keks(kek()))
    one, two = await sealer.seal_secret(SECRET, ALERT), await sealer.seal_secret(SECRET, ALERT)
    wrap_nonce = slice(webhook._WH_HEAD, webhook._WH_HEAD + env.NONCE_LEN)
    at = webhook._WH_HEAD + WEBHOOK_WRAP_LEN
    value_nonce = slice(at, at + env.NONCE_LEN)
    assert (wrap_nonce.start, wrap_nonce.stop, value_nonce.start) == (8, 20, 68)
    assert one[wrap_nonce] != two[wrap_nonce]
    assert one[value_nonce] != two[value_nonce]


# --- the broker's guard (Amendment 9, C-2.7) ------------------------------------------------


async def test_every_wrap_and_unwrap_runs_under_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    old, new = kek(KEK_V1, 1), kek(KEK_V2, 2)
    stale = await webhook.sealer(_Keks(old)).seal_target(URL, ALERT)
    keks = _Keks(new, old)
    seen: list[tuple[str, bool]] = []
    real_wrap, real_unwrap = LoadedKek.wrap_webhook_dek, LoadedKek.unwrap_webhook_dek

    def wrap(self: LoadedKek, dek: bytearray, *, alert_id: UUID, field: str) -> bytes:
        seen.append(("wrap", keks.guard.locked()))
        return real_wrap(self, dek, alert_id=alert_id, field=field)

    def unwrap(self: LoadedKek, wrapped: bytes, *, alert_id: UUID, field: str) -> bytearray:
        seen.append(("unwrap", keks.guard.locked()))
        return real_unwrap(self, wrapped, alert_id=alert_id, field=field)

    monkeypatch.setattr(LoadedKek, "wrap_webhook_dek", wrap)
    monkeypatch.setattr(LoadedKek, "unwrap_webhook_dek", unwrap)
    sealer, opener, signer = _caps(keks)
    target, secret = await sealer.seal_target(URL, ALERT), await sealer.seal_secret(SECRET, ALERT)
    await opener.open_target(target, ALERT)
    await signer.sign_delivery(secret, ALERT, 1, 1, DIGEST)
    webhook.rewrap(keks, stale, ALERT, "url")
    ops = ["wrap", "wrap", "unwrap", "unwrap", "unwrap", "wrap", "unwrap"]
    assert seen == [(op, True) for op in ops]
    assert await _refused(opener.open_target(target, OTHER)) == "webhook_seal_invalid"
    assert not keks.guard.locked()  # released after each call, a refused one too


def test_kek_wrap_refuses_a_dek_of_the_wrong_shape() -> None:
    held = kek()
    with pytest.raises(ValueError, match="32-byte"):
        held.wrap_webhook_dek(bytearray(31), alert_id=ALERT, field="url")
    with pytest.raises(ValueError, match="32-byte"):
        immutable: Any = bytes(32)  # a DEK that could not be zeroed
        held.wrap_webhook_dek(immutable, alert_id=ALERT, field="url")
    with pytest.raises(ValueError, match="length"):
        held.unwrap_webhook_dek(bytes(59), alert_id=ALERT, field="url")


@pytest.mark.parametrize(
    "call",
    [
        lambda: env.webhook_dek_aad("prod", ALERT, "url", 1),
        lambda: env.webhook_dek_aad("demo", ALERT, "token", 1),
        lambda: env.webhook_dek_aad("demo", ALERT, "url", 0),
        lambda: env.webhook_dek_aad("demo", ALERT, "url", True),
        lambda: env.webhook_aad("prod", ALERT, "url"),
        lambda: env.webhook_aad("demo", ALERT, "token"),
    ],
)
def test_webhook_aads_refuse_unknown_parts(call: Callable[[], bytes]) -> None:
    with pytest.raises(ValueError):
        call()


def test_webhook_aads_bind_label_environment_alert_and_field() -> None:
    assert env.webhook_aad("demo", ALERT, "url") == env.aad(
        b"cv.alert.webhook.url.v1", b"demo", ALERT.bytes
    )
    assert env.webhook_dek_aad("live", ALERT, "secret", 3) == env.aad(
        b"cv-webhook-dek-v1", b"live", ALERT.bytes, b"secret", b"3"
    )
