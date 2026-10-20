"""Fixtures for cv-admin-no-secret-log (E42-X03, AC4; C-12.6, SR-122): no log call receives an
invite link, a backup download URL or token, an API secret or a TOTP code, or a value made from one."""

import hashlib
import hmac
import logging
import secrets

import structlog

from candleviewer.api._generated.openapi_models import FootprintBar
from candleviewer.auth.models import MfaVerifyRequest
from candleviewer.observability.redaction import redact_text
from candleviewer.observability.secret_type import Secret

log = structlog.get_logger(__name__)
logger = logging.getLogger(__name__)


def _log() -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(__name__)


def issue_link(backup_id: str) -> str:
    token = secrets.token_urlsafe(32)
    url = f"/admin/backups/{backup_id}/download/{token}"
    log.info("link issued", url=url)  # ruleid: cv-admin-no-secret-log
    logger.warning("link %s", token)  # ruleid: cv-admin-no-secret-log
    _log().debug("link issued", length=len(token))  # ok: cv-admin-no-secret-log
    digest = hashlib.sha256(token.encode()).hexdigest()
    _log().info("link issued", digest=digest)  # ok: cv-admin-no-secret-log
    return url


def invite_created(invite: object) -> None:
    link = invite.invite_url
    _log().info("invite created", link=link)  # ruleid: cv-admin-no-secret-log
    _log().bind(invite=invite.token).info("invite created")  # ruleid: cv-admin-no-secret-log
    _log().info("invite created", invite_id=invite.invite_id)  # ok: cv-admin-no-secret-log


def served(record: object) -> None:
    _log().error("download served", url=record.download_url)  # ruleid: cv-admin-no-secret-log
    _log().error("download served", link_id=record.link_id)  # ok: cv-admin-no-secret-log


def key_import(request: object) -> None:
    secret = request.api_secret.get_secret_value()
    _log().info("key import", secret=secret)  # ruleid: cv-admin-no-secret-log
    _log().info("key import", secret=Secret(secret))  # ok: cv-admin-no-secret-log
    _log().info("key import", key=redact_text(str(request.api_secret)))  # ok: cv-admin-no-secret-log


def verify(body: MfaVerifyRequest) -> None:
    _log().warning("mfa refused", code=body.code)  # ruleid: cv-admin-no-secret-log


def refused(error: object) -> None:
    _log().warning("refused", code=error.code)  # ok: cv-admin-no-secret-log


def fetch(backup_id: str, token: str) -> None:
    _log().info("fetch", path=f"/download/{token}")  # ruleid: cv-admin-no-secret-log
    structlog.contextvars.bind_contextvars(link=token)  # ruleid: cv-admin-no-secret-log
    _log().info("fetch", backup_id=backup_id)  # ok: cv-admin-no-secret-log


class OtpRequest:
    code: str


def otp_verify(body: OtpRequest) -> None:
    _log().warning("otp refused", code=body.code)  # ruleid: cv-admin-no-secret-log


def footprint(bar: FootprintBar) -> None:
    _log().info("bar built", code=bar.code)  # ok: cv-admin-no-secret-log


def from_store(store: object, sink: object) -> None:
    token = store.next_link()
    _log().info("link read", link=token)  # ruleid: cv-admin-no-secret-log
    raw_token = store.peek()
    sink.warning("link peeked %s", raw_token)  # ruleid: cv-admin-no-secret-log
    sink.bind(link=raw_token)  # ok: cv-admin-no-secret-log
    signature = hmac.new(b"fixture-key", raw_token.encode(), "sha256")  # ok: cv-admin-no-secret-log
    _log().bind(link=raw_token).info("link peeked")  # ruleid: cv-admin-no-secret-log


def prefix(token: str) -> None:
    _log().info("fetch", prefix=token[:4])  # ruleid: cv-admin-no-secret-log
    tail = token[-4:]
    _log().info("fetch", tail=tail)  # ruleid: cv-admin-no-secret-log
    _log().info("fetch", middle=token[2:6])  # ruleid: cv-admin-no-secret-log
    _log().info("fetch", whole=token[:])  # ruleid: cv-admin-no-secret-log
    _log().info("fetch", every_other=token[::2])  # ruleid: cv-admin-no-secret-log
    _log().info("fetch", reversed=token[::-1])  # ruleid: cv-admin-no-secret-log
    _log().info("fetch", odd=token[1::2])  # ruleid: cv-admin-no-secret-log
    _log().info("fetch", even_head=token[:8:2])  # ruleid: cv-admin-no-secret-log
    _log().info("fetch", stepped=token[1:9:2])  # ruleid: cv-admin-no-secret-log
    _log().info("fetch", length=len(token[:4]))  # ok: cv-admin-no-secret-log


class Notifier:
    def __init__(self, audit_log: object) -> None:
        self._audit_log = audit_log

    def sent(self, link_token: str) -> None:
        self._audit_log.error("link sent %s", link_token)  # ruleid: cv-admin-no-secret-log
        self._audit_log.critical("link sent", digest=hashlib.sha256(link_token.encode()).hexdigest())  # ok: cv-admin-no-secret-log


async def issue_download(issuer: object, backup_id: str) -> None:
    secret, link = await issuer.issue(backup_id)
    url = f"/api/v1/admin/backups/{backup_id}/download/{secret}"
    _log().info("download issued", url=url)  # ruleid: cv-admin-no-secret-log
    _log().info("download issued", link_id=link.link_id)  # ok: cv-admin-no-secret-log


def issue_again(links: object, backup_id: str) -> None:
    value, link = links.issue(backup_id=backup_id)
    logger.info("link %s", value)  # ruleid: cv-admin-no-secret-log
    logger.info("link %s", link.link_id)  # ok: cv-admin-no-secret-log
