"""Fixtures for cv-admin-no-secret-log: code outside services/api/candleviewer is out of its scope."""

import secrets

import structlog


def mint() -> None:
    token = secrets.token_urlsafe(32)
    structlog.get_logger(__name__).info("minted", token=token)  # ok: cv-admin-no-secret-log
