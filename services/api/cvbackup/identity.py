"""The one module of the sidecar that may hold an age identity (ADR-0041 section 4; e42-admin.md
§6a AD-SC04, AD-SC06).

An identity reaches the sidecar only for a restore or a restore drill, through the Owner's
host-side intake (#3319 B2), for one named job. Here it is held in a mutable buffer bound to that
job and to the artefact digest the Owner confirmed, and overwritten when the job ends, fails, is
cancelled or passes its deadline (`IdentitySlots.held`, `expire`). It is never logged, printed,
put in an exception, `repr`'d, pickled, copied or serialised: `BoundIdentity` refuses each, and
its refusals are fixed text. A copy the runtime makes internally cannot be proven overwritten
(the stated residual of ADR-0041 section 4).

`IdentitySlots` refuses an identity for a job it is not waiting for, a second identity for a job,
one bound to another digest, and one that arrives after the job's deadline.
"""

from __future__ import annotations

import contextlib
import hmac
import time
from collections.abc import Callable, Iterator
from typing import Final, NoReturn

_REDACTED: Final = "<identity redacted>"


class IdentityRefused(Exception):
    """A refused delivery or use; `reason` is a fixed word, never material."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class BoundIdentity:
    """Identity material bound to one job and one digest, in a buffer only this object holds."""

    __slots__ = ("_buffer", "_clock", "_deadline", "_digest", "_job_id")

    def __init__(
        self, job_id: str, digest: str, material: bytearray, *, deadline: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:  # fmt: skip
        """Takes `material` over: its bytes are copied into this object's buffer and the
        caller's buffer is overwritten at once."""
        self._job_id, self._digest, self._deadline, self._clock = job_id, digest, deadline, clock
        self._buffer = bytearray(material)
        material[:] = bytes(len(material))

    @property
    def job_id(self) -> str:
        return self._job_id

    @property
    def deadline(self) -> float:
        return self._deadline

    @property
    def wiped(self) -> bool:
        return not any(self._buffer)

    def reveal(self, job_id: str, digest: str) -> memoryview:
        """A read-only view of the material, for the job and digest it is bound to only, before
        its deadline; else `IdentityRefused` (and wiped, past the deadline)."""
        if self.wiped:
            raise IdentityRefused("wiped")
        if self._clock() >= self._deadline:
            self.wipe()
            raise IdentityRefused("deadline")
        same_job = hmac.compare_digest(job_id, self._job_id)
        if not same_job & hmac.compare_digest(digest, self._digest):
            raise IdentityRefused("not_bound")
        return memoryview(self._buffer).toreadonly()

    def wipe(self) -> None:
        """Overwrite the buffer with zeros, in place; idempotent."""
        self._buffer[:] = bytes(len(self._buffer))

    def __repr__(self) -> str:
        return _REDACTED

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return _REDACTED

    def __bytes__(self) -> NoReturn:
        raise IdentityRefused("not_serialisable")

    def __reduce_ex__(self, protocol: object) -> NoReturn:
        raise IdentityRefused("not_serialisable")

    def __reduce__(self) -> NoReturn:
        raise IdentityRefused("not_serialisable")

    def __getstate__(self) -> NoReturn:
        raise IdentityRefused("not_serialisable")

    def __copy__(self) -> NoReturn:
        raise IdentityRefused("not_copyable")

    def __deepcopy__(self, memo: object) -> NoReturn:
        raise IdentityRefused("not_copyable")


class IdentitySlots:
    """The jobs waiting for an identity, and the identity each holds (at most one, ever)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._waiting: dict[str, tuple[str, float]] = {}  # job id: (digest, deadline)
        self._held: dict[str, BoundIdentity] = {}
        self._delivered: set[str] = set()

    def expect(self, job_id: str, digest: str, deadline: float) -> None:
        if job_id in self._waiting or job_id in self._delivered:
            raise IdentityRefused("job_known")
        self._waiting[job_id] = (digest, deadline)

    def deliver(self, job_id: str, digest: str, material: bytearray) -> None:
        """Bind `material` to `job_id`; the caller's buffer is overwritten whatever the answer."""
        try:
            if job_id in self._delivered:
                raise IdentityRefused("second_identity")
            if job_id not in self._waiting:
                raise IdentityRefused("not_waiting")
            expected, deadline = self._waiting[job_id]
            if self._clock() >= deadline:
                del self._waiting[job_id]
                raise IdentityRefused("deadline")
            if not hmac.compare_digest(digest, expected):
                raise IdentityRefused("not_bound")
            identity = BoundIdentity(job_id, digest, material, deadline=deadline, clock=self._clock)
        finally:
            material[:] = bytes(len(material))
        del self._waiting[job_id]
        self._delivered.add(job_id)
        self._held[job_id] = identity

    @contextlib.contextmanager
    def held(self, job_id: str) -> Iterator[BoundIdentity]:
        """The job's identity for the job's body; wiped and dropped however the body ends (done,
        failed or cancelled)."""
        identity = self._held.get(job_id)
        if identity is None:
            raise IdentityRefused("not_held")
        try:
            yield identity
        finally:
            self.end(job_id)

    def end(self, job_id: str) -> None:
        identity = self._held.pop(job_id, None)
        if identity is not None:
            identity.wipe()
        self._waiting.pop(job_id, None)

    def expire(self) -> int:
        """Wipe every identity, and drop every wait, past its deadline; how many it dropped."""
        now = self._clock()
        late = [j for j, i in self._held.items() if now >= i.deadline]
        late += [j for j, (_, deadline) in self._waiting.items() if now >= deadline]
        for job_id in late:
            self.end(job_id)
        return len(late)
