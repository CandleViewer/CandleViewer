"""The sidecar's configuration (ADR-0041 section 1): `CVB_*` environment variables, read once at
start and refused whole on any fault, so it never serves half-configured. Only public values
live here: paths, the API's uid, the public recipient and its pinned fingerprint, and the floor's
figures (the run cap per window and the removal grace), which no request can change.

The database credentials, the age tool and the child processes come with the run path (#3319
B1c); the identity never reaches configuration (`identity.py`).
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from cvbackup import age_format

#: The floor's figures (24 §15.8 item 11, PROPOSED, B1 security review (ADR-0041)): six runs in a
#: rolling day, removals purged a week after their quarantine. None is configurable past its
#: floor: the cap may only be lowered, the window only lengthened, the grace never under an hour.
RUN_CAP: Final = 6
RUN_WINDOW_S: Final = 86400
REMOVE_GRACE_S: Final = 7 * 86400
MIN_GRACE_S: Final = 3600
MAX_RUN_WINDOW_S: Final = 31 * 86400
MAX_GRACE_S: Final = 90 * 86400


class ConfigError(Exception):
    """A refused configuration: the variable's name and the rule, never its value."""


@dataclass(frozen=True, slots=True)
class SidecarConfig:
    socket: str  # CVB_SOCKET: on the shared socket volume, never inside `root`
    root: str  # CVB_BACKUP_ROOT: the backup volume, mounted read-write here only
    api_uid: int  # CVB_API_UID: the only peer the socket answers
    recipient: str  # CVB_RECIPIENT: the public age recipient runs encrypt to (B1c)
    pin: str  # CVB_RECIPIENT_FINGERPRINT: `age-x25519-sha256:<hex>`
    run_cap: int = RUN_CAP  # CVB_RUN_CAP
    run_window: timedelta = timedelta(seconds=RUN_WINDOW_S)  # CVB_RUN_WINDOW_S
    grace: timedelta = timedelta(seconds=REMOVE_GRACE_S)  # CVB_REMOVE_GRACE_S


def _path(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "")
    parts = value.split("/")[1:]
    if not value.startswith("/") or not parts or any(p in ("", ".", "..") for p in parts):
        raise ConfigError(f"{name} must be an absolute path in canonical form, not /")
    if "\x00" in value or os.path.islink(value):
        raise ConfigError(f"{name} must not be a symlink")
    if os.path.realpath(value) != value:
        raise ConfigError(f"{name} must not lie under a symlinked directory")
    return value


def _int(env: Mapping[str, str], name: str, default: int | None, low: int, high: int) -> int:
    raw = env.get(name)
    if raw is None and default is not None:
        return default
    if raw is None or not raw.isascii() or not raw.isdigit() or len(raw) > 10:
        raise ConfigError(f"{name} must be a whole number")
    value = int(raw)
    if not low <= value <= high:
        raise ConfigError(f"{name} must be between {low} and {high}")
    return value


def backup_root(env: Mapping[str, str]) -> str:
    """`CVB_BACKUP_ROOT` alone, for `check-ledger`, which needs nothing else."""
    return _path(env, "CVB_BACKUP_ROOT")


def load(env: Mapping[str, str]) -> SidecarConfig:
    """The configuration `env` holds, or `ConfigError` for its first fault."""
    socket, root = _path(env, "CVB_SOCKET"), _path(env, "CVB_BACKUP_ROOT")
    if socket == root or socket.startswith(root + "/") or root.startswith(socket + "/"):
        raise ConfigError("CVB_SOCKET must not be, contain or lie inside CVB_BACKUP_ROOT")
    api_uid = _int(env, "CVB_API_UID", None, 1, 2**31 - 1)
    if api_uid == os.getuid():
        raise ConfigError("CVB_API_UID must not be the sidecar's own uid")
    recipient, pin = env.get("CVB_RECIPIENT", ""), env.get("CVB_RECIPIENT_FINGERPRINT", "")
    if not age_format.is_recipient(recipient):
        raise ConfigError("CVB_RECIPIENT must be an age X25519 recipient (age1...)")
    if not age_format.is_fingerprint(pin):
        raise ConfigError("CVB_RECIPIENT_FINGERPRINT must read age-x25519-sha256:<64 hex>")
    if not hmac.compare_digest(age_format.fingerprint(recipient), pin):
        raise ConfigError("CVB_RECIPIENT does not match CVB_RECIPIENT_FINGERPRINT")
    return SidecarConfig(
        socket, root, api_uid, recipient, pin,
        run_cap=_int(env, "CVB_RUN_CAP", RUN_CAP, 1, RUN_CAP),
        run_window=timedelta(seconds=_int(env, "CVB_RUN_WINDOW_S", RUN_WINDOW_S, RUN_WINDOW_S,
                                          MAX_RUN_WINDOW_S)),
        grace=timedelta(seconds=_int(env, "CVB_REMOVE_GRACE_S", REMOVE_GRACE_S, MIN_GRACE_S,
                                     MAX_GRACE_S)),
    )  # fmt: skip
