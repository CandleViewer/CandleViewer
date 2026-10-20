"""Fixtures for cv-admin-no-secret-log in a file with PEP 695 generics, which Semgrep parses
another way (#3549, X03-F4): the rule must hold here too (D10)."""

import secrets

import structlog

from candleviewer.auth.models import MfaVerifyRequest


def _log() -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(__name__)


def first[T](items: list[T]) -> T:
    return items[0]


async def verify[T](body: MfaVerifyRequest, extra: T) -> T:
    _log().info("mfa verify", code=body.code)  # ruleid: cv-admin-no-secret-log
    return extra


class Links:
    def issue[T](self, item: T) -> T:
        token = secrets.token_urlsafe(32)
        _log().info("link issued", token=token)  # ruleid: cv-admin-no-secret-log
        _log().info("link issued", length=len(token))  # ok: cv-admin-no-secret-log
        return item

    def revoke[T](self, item: T, token: str, audit_log: object) -> T:
        audit_log.warning("link revoked %s", token[:6])  # ruleid: cv-admin-no-secret-log
        return item
