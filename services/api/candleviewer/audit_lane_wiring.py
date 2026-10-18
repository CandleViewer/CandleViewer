"""Composition-root wiring (not a module) for the audit lane key (ADR-0037 decision 6, #3009).

`audit` neither imports `secrets` nor reads a secret file (C-3.2), so the composition root reads
the lane key, as it reads the CSRF key (`app.build_csrf_codec`), from the file that
`CV_AUDIT_LANE_KEY_FILE` names, and hands the bytes to `AuditService`. The file rules are
`24-internal-schemas.md` §15.6's; the refusals are ADR-0037's S2b row, except the two that need
the lane's own directory (an unanchored one, `lane.lock` held), which the code opening the lane
owns. Nothing calls `load_lane_keys` yet: the slice that wires the lane into `AuditService` runs
it at boot, so no boot changes here. The `kid` is safe to log; the key never is, so no message,
log line or `repr` here carries it.
"""

from __future__ import annotations

import errno
import hmac
import os
import re
import stat
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import structlog
from pydantic import SecretStr

from candleviewer.admin.wiring import audit_lane_key_id
from candleviewer.settings import Settings, key_file_path_refusal

KEY_FILE, PREVIOUS_KEY_FILE = "CV_AUDIT_LANE_KEY_FILE", "CV_AUDIT_LANE_PREVIOUS_KEY_FILE"
#: Decision 6: the keys have no environment form. Either name refuses boot, in any case and with
#: any value, an empty one too; only names are read, never a value.
ENVIRONMENT_FORMS = frozenset({"CV_AUDIT_LANE_KEY_HEX", "CV_AUDIT_LANE_PREVIOUS_KEY_HEX"})
_KEY_TEXT = re.compile(rb"[0-9a-fA-F]{64}\n?")
_READ_MAX = 66  # the longest valid file, and one byte more
#: A last-component symlink fails the open, and a FIFO or device node never blocks it.
_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class LaneKeyRefused(ValueError):
    """A boot refusal. The message names the setting and the rule, never a key."""

    def __init__(self, setting: str, rule: str) -> None:
        super().__init__(f"{setting} {rule}")
        self.setting = setting


@dataclass(frozen=True, slots=True, eq=False)
class LaneKeyMaterial:
    """The lane's keys, for `AuditService`; `repr` shows only their ids."""

    current: bytes = field(repr=False)
    previous: bytes | None = field(repr=False)
    kid: str
    previous_kid: str | None


def load_lane_keys(
    settings: Settings, environ: Mapping[str, str] = os.environ
) -> LaneKeyMaterial | None:
    """The lane's keys, read once, or None while no real audit backend is wired (the fake
    backend runs no lane). The environment form refuses on every backend. Each refusal raises
    `LaneKeyRefused` before any module starts."""
    refuse_environment_key(environ)
    if settings.storage_backend != "real":
        return None
    refuse_key_under_audit_dir(settings)
    current = read_key_file(KEY_FILE, settings.audit_lane_mac_file)
    path = settings.audit_lane_previous_mac_file
    previous = None if path is None else read_key_file(PREVIOUS_KEY_FILE, path)
    refuse_reused_key(settings, current, previous)
    material = LaneKeyMaterial(
        current,
        previous,
        audit_lane_key_id(current),
        None if previous is None else audit_lane_key_id(previous),
    )
    structlog.get_logger(__name__).info(
        "audit.lane.key_loaded", kid=material.kid, previous_kid=material.previous_kid
    )
    return material


def refuse_environment_key(environ: Mapping[str, str]) -> None:
    for name in environ:
        if name.upper() in ENVIRONMENT_FORMS:
            raise LaneKeyRefused(
                name.upper(),
                f"is refused: the audit lane keys are read from {KEY_FILE} and "
                f"{PREVIOUS_KEY_FILE} only, never from the environment",
            )


def read_key_file(variable: str, value: str) -> bytes:
    """§15.6: the path rules of `CV_TEST_CLOCK_FILE`, an `O_NOFOLLOW` open, a regular file of
    mode 0400 owned by the cv-api user (the KEK handle's rule, ADR-0009 Amendment 1), read once;
    its content exactly 64 hex digits, optionally followed by one line feed."""
    rule = key_file_path_refusal(value)
    if rule is not None:
        raise LaneKeyRefused(variable, rule)
    try:
        fd = os.open(value, _OPEN_FLAGS)
    except OSError as exc:
        raise LaneKeyRefused(variable, _open_rule(exc)) from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise LaneKeyRefused(variable, "must name a regular file")
        if stat.S_IMODE(st.st_mode) != 0o400 or st.st_uid != os.geteuid():
            raise LaneKeyRefused(variable, "must be mode 0400 and owned by the cv-api user")
        text = b""
        while len(text) < _READ_MAX and (chunk := os.read(fd, _READ_MAX - len(text))):
            text += chunk
    except OSError as exc:
        raise LaneKeyRefused(variable, _open_rule(exc)) from exc
    finally:
        os.close(fd)
    if _KEY_TEXT.fullmatch(text) is None:
        raise LaneKeyRefused(
            variable, "must hold exactly 64 hex digits, optionally followed by one line feed"
        )
    return bytes.fromhex(text[:64].decode("ascii"))


def _open_rule(exc: OSError) -> str:
    if exc.errno == errno.ENOENT:
        return "names no file"
    if exc.errno == errno.ELOOP:
        return "must not be a symlink"
    return f"cannot be read ({type(exc).__name__})"


def refuse_key_under_audit_dir(settings: Settings) -> None:
    """No key file, current or previous, lies under the directory of `CV_AUDIT_WAL_PATH`, so no
    key sits on the volume whose frames it authenticates. Both paths are resolved: a relative
    WAL path against the working directory, as cv-api opens it, and symlinks to their targets."""
    audit_dir = Path(os.path.realpath(Path(settings.audit_wal_path).parent))
    files = {KEY_FILE: settings.audit_lane_mac_file}
    if settings.audit_lane_previous_mac_file is not None:
        files[PREVIOUS_KEY_FILE] = settings.audit_lane_previous_mac_file
    for variable, value in files.items():
        if Path(os.path.realpath(value)).is_relative_to(audit_dir):
            raise LaneKeyRefused(
                variable,
                "must not lie under the directory of CV_AUDIT_WAL_PATH: no key sits on the "
                "volume whose frames it authenticates",
            )


def refuse_reused_key(settings: Settings, current: bytes, previous: bytes | None) -> None:
    """A lane key, current or previous, equal to the TOTP, recovery-code or CSRF key (either
    CSRF key) or the pepper refuses boot. Each secret is compared as configured and, when it is
    hex, decoded (`app._decode_key`'s reading), in constant time; the message names no secret."""
    secrets = (
        settings.auth_totp_key_hex,
        settings.auth_recovery_hmac_key_hex,
        settings.auth_csrf_key_hex,
        settings.auth_csrf_previous_key_hex,
        settings.auth_pepper,
    )
    others = [form for secret in secrets for form in _forms(secret)]
    for variable, key in ((KEY_FILE, current), (PREVIOUS_KEY_FILE, previous)):
        if key is not None and _equals_any(key, others):
            raise LaneKeyRefused(
                variable,
                "must hold a key of its own, not the TOTP, recovery-code or CSRF key or the pepper",
            )


def _forms(secret: SecretStr | None) -> tuple[bytes, ...]:
    if secret is None:
        return ()
    text = secret.get_secret_value()
    try:
        return text.encode(), bytes.fromhex(text)
    except ValueError:
        return (text.encode(),)


def _equals_any(key: bytes, others: Iterable[bytes]) -> bool:
    """Every comparison runs, in constant time, whichever one matches."""
    found = False
    for other in others:
        found |= hmac.compare_digest(key, other)
    return found
