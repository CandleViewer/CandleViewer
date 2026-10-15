"""Argon2id password hashing (E09-S01 "Technical notes").

Constant-time verification, a per-user pepper mixed in before hashing (KEK
handling — see the module docstring below for the boundary this ticket
draws), and a fixed dummy hash so `LoginService` performs the *identical*
Argon2id verification call whether the user exists or not (enumeration
resistance: same timing profile, same code path).

Pepper: `04-security-program.md` places the KEK/pepper material behind
`candleviewer.secrets`, which M18 (`auth`) is *not* on the allow-list to
import (CONSTITUTION.md C-3.2: M2 is importable only by M4 and M21). This
module therefore accepts the already-resolved pepper as a plain string
argument (`Hasher(pepper=...)`) — the composition root is responsible for
fetching it from wherever `secrets`/KEK wiring lands and passing it in,
mirroring how `AuditWriter` is handed a repository rather than importing
`storage` itself. Until that wiring exists, callers pass `pepper=""`
(no-op) rather than reading a fake secret out of this module.
"""

from __future__ import annotations

import asyncio
import hmac
import time
from collections.abc import Callable
from contextvars import ContextVar

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

#: Default parameters (ticket: "m=65536,t=3,p=4 default"), matching
#: `users.password_algo_params`'s column default in
#: `0001_identity_rbac_sessions_mfa.py`.
DEFAULT_ARGON2_PARAMS: dict[str, int] = {"m": 65536, "t": 3, "p": 4}

#: #2097: wall time in ms of the latest `Hasher.verify` awaited in this context, timed in the
#: worker thread around the Argon2id call alone. A ContextVar, so each request (task) sees only
#: its own value; the perf-only login `Server-Timing` header reads it via `last_verify_ms()`.
_LAST_VERIFY_MS: ContextVar[float | None] = ContextVar("cv_argon2_last_verify_ms", default=None)

#: A fixed, valid Argon2id hash of an arbitrary constant string. Used only
#: as the verification target for an unknown identifier so the CPU work
#: (and therefore the wall-clock time) is the same as a real user's
#: verification, never so a "correct" password could ever match it.
_DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$SBCH3a1MjHOuiTouZgR4bA$umiYIItBsPSAhOO1pYFi6IVfawadHXCivexpiinH8OU"  # noqa: E501 -- a real Argon2id encoded hash cannot be wrapped without changing its bytes


def _params_to_hasher(params: dict[str, int]) -> PasswordHasher:
    return PasswordHasher(
        time_cost=params.get("t", DEFAULT_ARGON2_PARAMS["t"]),
        memory_cost=params.get("m", DEFAULT_ARGON2_PARAMS["m"]),
        parallelism=params.get("p", DEFAULT_ARGON2_PARAMS["p"]),
    )


class Hasher:
    """Argon2id verify/hash with a mixed-in pepper.

    The pepper is appended to the password before hashing/verification
    (never stored, never logged) so a stolen `password_hash` column alone
    is insufficient to crack offline (ticket "Security notes": "offline
    cracking if the database leaks ... Argon2id with tuned parameters plus
    pepper outside the database").
    """

    def __init__(
        self, pepper: str = "", *, perf_counter: Callable[[], float] = time.perf_counter
    ) -> None:
        self._pepper = pepper
        self._default_hasher = _params_to_hasher(DEFAULT_ARGON2_PARAMS)
        self._perf_counter = perf_counter

    def _peppered(self, password: str) -> str:
        return password + self._pepper

    async def hash(self, password: str, params: dict[str, int] | None = None) -> str:
        """Hash `password` (plus pepper) with `params` (or the default).

        Argon2id hashing is deliberately CPU/memory heavy (tuned cost
        parameters), so it must never run inline on the asyncio event loop
        (C-2.18) — the actual work happens in a worker thread via
        `asyncio.to_thread`."""
        hasher = _params_to_hasher(params) if params is not None else self._default_hasher
        peppered = self._peppered(password)
        return await asyncio.to_thread(hasher.hash, peppered)

    async def verify(self, password_hash: str, password: str) -> bool:
        """Constant-time-equivalent verify (argon2-cffi's C extension does
        the actual comparison; this wrapper just turns the library's
        exception-based API into a bool without ever branching on *why* it
        failed, keeping the code path identical to the dummy-hash path).

        Runs off the event loop (`asyncio.to_thread`) — same C-2.18 rationale
        as `hash()`: Argon2id verification is deliberately slow and must
        never block the loop, or a caller could stall the whole backend by
        hammering `/auth/login` (see this module's PR review history).

        #2097: the worker thread times the Argon2id call alone (no thread-pool
        queueing) and the result is kept for this context (`last_verify_ms`).
        Every path, the dummy hash included, runs the same timed call."""
        peppered = self._peppered(password)
        ok, elapsed_ms = await asyncio.to_thread(self._timed_verify_sync, password_hash, peppered)
        _LAST_VERIFY_MS.set(elapsed_ms)
        return ok

    def _timed_verify_sync(self, password_hash: str, peppered_password: str) -> tuple[bool, float]:
        started = self._perf_counter()
        ok = self._verify_sync(password_hash, peppered_password)
        return ok, (self._perf_counter() - started) * 1000.0

    def _verify_sync(self, password_hash: str, peppered_password: str) -> bool:
        try:
            self._default_hasher.verify(password_hash, peppered_password)
        except VerifyMismatchError:
            return False
        except Exception:
            return False
        return True

    async def verify_dummy(self, password: str) -> bool:
        """Run the same Argon2id verification work against `_DUMMY_HASH` so
        an unknown-identifier login takes the same CPU time as a real one.
        Always returns `False` (the dummy hash matches no real password)."""
        return await self.verify(_DUMMY_HASH, password)

    def needs_rehash(self, password_hash: str, params: dict[str, int]) -> bool:
        """True when `password_hash`'s embedded parameters differ from
        `params` (ticket "transparent rehash-on-login when parameters
        change")."""
        hasher = _params_to_hasher(params)
        return bool(hasher.check_needs_rehash(password_hash))


def constant_time_eq(a: str, b: str) -> bool:
    """`hmac.compare_digest` wrapper — used for opaque-token comparisons
    elsewhere in this module (never for the Argon2id hash itself, which
    `argon2-cffi` already compares safely)."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def last_verify_ms() -> float | None:
    """#2097: wall time in ms of the latest Argon2id verification awaited in this context, or
    None when none ran. Read only by the perf-only login `Server-Timing` header."""
    return _LAST_VERIFY_MS.get()
