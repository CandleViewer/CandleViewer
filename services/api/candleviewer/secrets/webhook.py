"""The alert webhook's M2 capabilities (#1400 S3, ADR-0009 Amendment 9): a sealer, a target opener
and a bounded signer, each a closure minted once in `admin.wiring` (C-3.2). `alerts` reaches them
through its own ports and never imports this package.

A sealed column (`alerts.webhook_url_enc`, `alerts.webhook_secret_enc`, `21` §12) is one blob:
``b"cvw1" || kek_version (u32 BE) || DEK wrap (60) || nonce(12) || ciphertext || tag(16)``. A
fresh DEK per seal; the wrap binds the environment, the alert, the column and the KEK version
(`webhook_dek_aad`), the value the environment, the alert and the column (`webhook_aad`), so a
blob moved to another alert or column does not open.

The signer signs only ``cv.alert.webhook.v1:{timestamp}:{delivery_id}:{hex digest}``, built here
from a checked field set: no caller bytes reach the MAC but the 32 digest bytes, so it is no
general signing oracle. Each call checks its request before any decrypt; a seal wraps its DEK
under the current KEK, an open or a sign opens the DEK under the held KEK of the blob's version;
every wrap and unwrap runs under the broker's `_guard` (`Keks`), and the call zeroes the DEK and
any opened plaintext before it returns. A
refusal is a `WebhookCapabilityRefused` with a closed reason, raised after the handler (nothing
chained), and its log names the operation and the check, never a value (C-12.6). The secret is
write-only: no capability opens it outside the signer. SR-009's residual applies: `bytes` copies
that `hmac` and `AESGCM` take cannot be wiped, and the opened URL is a `str` the caller holds.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any, Final, NoReturn, final
from uuid import UUID

import structlog
from cryptography.exceptions import InvalidTag

from candleviewer.secrets import _envelope as env
from candleviewer.secrets._kek import WEBHOOK_WRAP_LEN, LoadedKek
from candleviewer.secrets.broker import _m2_only
from candleviewer.secrets.errors import KekUnavailable, WebhookCapabilityRefused, WebhookReason

#: The signed string's fixed prefix (BQ-03; the header and window rules are S1's `24` section).
PREFIX: Final = "cv.alert.webhook.v1"
MAGIC: Final = b"cvw1"
SECRET_MIN: Final = 32
SECRET_MAX: Final = 128
URL_MAX: Final = 2048
DIGEST_LEN: Final = 32
#: `alert_deliveries.id` is a `bigserial`.
DELIVERY_ID_MAX: Final = 2**63 - 1
#: Unix seconds; ten digits at most (before the year 2286).
TIMESTAMP_MAX: Final = 10**10 - 1
_WH_HEAD: Final = len(MAGIC) + 4
_WH_MIN_BLOB: Final = _WH_HEAD + WEBHOOK_WRAP_LEN + env.NONCE_LEN + env.TAG_LEN

#: The KEKs held, the current first, for the `with` body: the broker's `_guard` (a
#: `threading.Lock`) is held across it, so no `drop_kek` or rotation fence closes a KEK mid-wrap
#: (#913 L3b). The body is synchronous and never awaits. Raises `KekUnavailable` when none is held.
Keks = Callable[[], AbstractContextManager[tuple[LoadedKek, ...]]]


def _wh_log() -> Any:
    return structlog.get_logger(__name__)


class _WhRefused(Exception):
    """A refusal found inside a call: its reason and the check, never a value."""

    def __init__(self, reason: WebhookReason, check: str) -> None:
        super().__init__(reason)
        self.reason, self.check = reason, check


def _wh_invalid(check: str) -> NoReturn:
    raise _WhRefused("webhook_request_invalid", check)


def _wh_run[T](op: str, call: Callable[[], T]) -> T:
    """`call`, or a `WebhookCapabilityRefused` raised after the handler, so the exception that
    carried the frames with the KEK, the DEK or a plaintext is not chained to it."""
    reason: WebhookReason
    try:
        return call()
    except _WhRefused as exc:
        reason, check = exc.reason, exc.check
    except KekUnavailable:
        reason, check = "kek_unavailable", "kek"
    except (InvalidTag, ValueError):
        reason, check = "webhook_seal_invalid", "seal"
    except Exception as exc:  # a defect: its type is logged, never its text
        reason, check = "webhook_unavailable", type(exc).__name__
    _wh_log().warning("secrets.webhook_refused", op=op, reason=reason, check=check)
    raise WebhookCapabilityRefused(reason)


def _wh_alert_id(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if type(value) is str:
        try:
            return UUID(value)
        except ValueError:
            pass
    _wh_invalid("alert_id")


def _wh_bounded_int(value: object, high: int, check: str) -> int:
    if type(value) is not int or not 1 <= value <= high:  # `bool` is not an `int` here
        _wh_invalid(check)
    return value


def _wh_bytes(value: object) -> bytes | None:
    """A copy of exact `bytes` or `bytearray` (no subclass), else None."""
    if type(value) is bytes or type(value) is bytearray:
        return bytes(value)
    return None


def _wh_digest(value: object) -> bytes:
    digest = _wh_bytes(value)
    if digest is None or len(digest) != DIGEST_LEN:
        _wh_invalid("body_digest")
    return digest


def _wh_secret(value: object) -> bytes | bytearray:
    if type(value) is bytes or type(value) is bytearray:
        if SECRET_MIN <= len(value) <= SECRET_MAX:
            return value
    _wh_invalid("secret")


def _wh_url(value: object) -> bytes:
    if type(value) is not str or not value.isprintable() or " " in value:
        _wh_invalid("url")
    raw = value.encode("utf-8")
    if not 1 <= len(raw) <= URL_MAX:
        _wh_invalid("url")
    return raw


def _wh_blob(value: object) -> tuple[int, bytes, bytes]:
    """The KEK version, the DEK wrap and the sealed value of one column's blob."""
    blob = _wh_bytes(value)
    if blob is None or len(blob) < _WH_MIN_BLOB:
        raise _WhRefused("webhook_seal_invalid", "blob")
    version = int.from_bytes(blob[len(MAGIC) : _WH_HEAD], "big")
    if blob[: len(MAGIC)] != MAGIC or version < 1:
        raise _WhRefused("webhook_seal_invalid", "blob")
    return (
        version,
        blob[_WH_HEAD : _WH_HEAD + WEBHOOK_WRAP_LEN],
        blob[_WH_HEAD + WEBHOOK_WRAP_LEN :],
    )


def _wh_held(keks: tuple[LoadedKek, ...], version: int) -> LoadedKek:
    for kek in keks:
        if kek.version == version:
            return kek
    raise _WhRefused("webhook_kek_not_held", "kek_version")


def message(timestamp: int, delivery_id: int, digest: bytes) -> bytes:
    """The one string the signer signs, from fields its caller checked."""
    return f"{PREFIX}:{timestamp}:{delivery_id}:{digest.hex()}".encode("ascii")


def _wh_seal(
    keks: tuple[LoadedKek, ...], alert: UUID, field: str, value: bytes | bytearray
) -> bytes:
    kek, dek = keks[0], env.new_dek()
    try:
        wrapped = kek.wrap_webhook_dek(dek, alert_id=alert, field=field)
        sealed = env.seal(dek, value, env.webhook_aad(kek.env_name, alert, field))
    finally:
        env.zero(dek)
    return MAGIC + kek.version.to_bytes(4, "big") + wrapped + sealed


def _wh_open(keks: tuple[LoadedKek, ...], alert: UUID, field: str, value: object) -> bytearray:
    version, wrapped, sealed = _wh_blob(value)
    kek = _wh_held(keks, version)
    dek = kek.unwrap_webhook_dek(wrapped, alert_id=alert, field=field)
    try:
        return env.open_(dek, sealed, env.webhook_aad(kek.env_name, alert, field))
    finally:
        env.zero(dek)


def _wh_sign(keks: Keks, call: tuple[object, ...]) -> str:
    blob, alert_id, delivery_id, timestamp, body_digest = call
    alert = _wh_alert_id(alert_id)
    signed = message(
        _wh_bounded_int(timestamp, TIMESTAMP_MAX, "timestamp"),
        _wh_bounded_int(delivery_id, DELIVERY_ID_MAX, "delivery_id"),
        _wh_digest(body_digest),
    )
    with keks() as held:
        secret = _wh_open(held, alert, "secret", blob)
    try:
        if not SECRET_MIN <= len(secret) <= SECRET_MAX:
            raise _WhRefused("webhook_seal_invalid", "secret_length")
        return hmac.new(bytes(secret), signed, hashlib.sha256).hexdigest()
    finally:
        env.zero(secret)


def _wh_open_target(keks: Keks, blob: object, alert_id: object) -> str:
    alert = _wh_alert_id(alert_id)
    with keks() as held:
        raw = _wh_open(held, alert, "url", blob)
    try:
        return raw.decode("utf-8")
    finally:
        env.zero(raw)


def rewrap(keks: Keks, blob: object, alert_id: object, field: str) -> bytes:
    """KEK rotation (Amendment 9): the blob with its DEK wrapped by the current KEK, verified before
    it is returned; the sealed value is unchanged. The value must open under the DEK first, so a
    corrupt row is refused (fail closed), never carried to the new KEK. A blob already current is
    returned as is. S4's store runs it on the alert rows at the rotation boot."""

    def run() -> bytes:
        if field not in env.WEBHOOK_FIELDS:
            _wh_invalid("field")
        alert = _wh_alert_id(alert_id)
        with keks() as held:
            version, wrapped, sealed = _wh_blob(blob)
            current = held[0]
            if version == current.version:
                return MAGIC + version.to_bytes(4, "big") + wrapped + sealed
            old = _wh_held(held, version)
            dek = old.unwrap_webhook_dek(wrapped, alert_id=alert, field=field)
            check: bytearray | None = None
            try:
                env.zero(env.open_(dek, sealed, env.webhook_aad(old.env_name, alert, field)))
                again = current.wrap_webhook_dek(dek, alert_id=alert, field=field)
                check = current.unwrap_webhook_dek(again, alert_id=alert, field=field)
                if not hmac.compare_digest(check, dek):
                    raise _WhRefused("webhook_seal_invalid", "rewrap_verify")
            finally:
                if check is not None:
                    env.zero(check)
                env.zero(dek)
        return MAGIC + current.version.to_bytes(4, "big") + again + sealed

    return _wh_run("rewrap", run)


@final
class WebhookSealer:
    """Seals a webhook's URL or secret for one alert (`alerts`' `WebhookSealerPort`). Minted once
    by `mint_webhook_sealer` in `admin.wiring`; it holds a closure only (C-3.2)."""

    def __init_subclass__(cls, **kw: Any) -> None:
        _m2_only(cls)
        super().__init_subclass__(**kw)

    __slots__ = ("__seal",)

    def __init__(self, seal: Callable[[str, object, object], bytes]) -> None:
        self.__seal = seal

    async def seal_target(self, url: str, alert_id: UUID | str) -> bytes:
        """The `webhook_url_enc` blob: a printable URL of 1 to 2,048 UTF-8 bytes, no space."""
        return self.__seal("url", url, alert_id)

    async def seal_secret(self, secret: bytes | bytearray, alert_id: UUID | str) -> bytes:
        """The `webhook_secret_enc` blob: 32 to 128 secret bytes, never read back. The caller
        passes a `bytearray` it owns and zeroes it once this returns or raises; M2 cannot wipe
        the caller's buffer (SR-009)."""
        return self.__seal("secret", secret, alert_id)


@final
class WebhookTargetOpener:
    """Opens a webhook's URL blob for the egress client (`WebhookTargetOpenerPort`), never the
    secret's. Minted once by `mint_webhook_opener`; it holds a closure only."""

    def __init_subclass__(cls, **kw: Any) -> None:
        _m2_only(cls)
        super().__init_subclass__(**kw)

    __slots__ = ("__open",)

    def __init__(self, open_target: Callable[[object, object], str]) -> None:
        self.__open = open_target

    async def open_target(self, sealed: bytes, alert_id: UUID | str) -> str:
        return self.__open(sealed, alert_id)


@final
class WebhookSigner:
    """Signs one delivery attempt (`WebhookSignerPort`): the hex HMAC-SHA256, under the alert's
    sealed secret, of `message(timestamp, delivery_id, body_digest)`, and nothing else. Minted once
    by `mint_webhook_signer`; it holds a closure only."""

    def __init_subclass__(cls, **kw: Any) -> None:
        _m2_only(cls)
        super().__init_subclass__(**kw)

    __slots__ = ("__sign",)

    def __init__(self, sign: Callable[[tuple[object, ...]], str]) -> None:
        self.__sign = sign

    async def sign_delivery(
        self,
        sealed_secret: bytes,
        alert_id: UUID | str,
        delivery_id: int,
        timestamp: int,
        body_digest: bytes,
    ) -> str:
        return self.__sign((sealed_secret, alert_id, delivery_id, timestamp, body_digest))


def sealer(keks: Keks) -> WebhookSealer:
    def seal(field: str, value: object, alert_id: object) -> bytes:
        def run() -> bytes:
            alert = _wh_alert_id(alert_id)
            plain = _wh_url(value) if field == "url" else _wh_secret(value)
            with keks() as held:
                return _wh_seal(held, alert, field, plain)

        return _wh_run(f"seal_{field}", run)

    return WebhookSealer(seal)


def opener(keks: Keks) -> WebhookTargetOpener:
    def open_target(blob: object, alert_id: object) -> str:
        return _wh_run("open_target", lambda: _wh_open_target(keks, blob, alert_id))

    return WebhookTargetOpener(open_target)


def signer(keks: Keks) -> WebhookSigner:
    def sign(call: tuple[object, ...]) -> str:
        return _wh_run("sign", lambda: _wh_sign(keks, call))

    return WebhookSigner(sign)
