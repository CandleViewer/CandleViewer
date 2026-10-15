"""Shared `Idempotency-Key` replay (convention C4), extracted unchanged from /drawings (E14-T01
decision 8) so /workspaces can use it too (E15-T01 D23, ruling Q5): a bounded LRU of 2xx
responses, keyed (user, "operationId:key") and checked against a request fingerprint. Losing an
entry only re-runs the request; correctness never depends on the cache. Routers keep their own
problem bodies: they map `ValueError` (malformed key, 422) and `IdempotencyKeyReuse` (409).
"""

import hashlib
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from fastapi import Request, Response

IDEMPOTENCY_MAX_ENTRIES: Final = 4096
IDEMPOTENCY_MAX_BYTES: Final = 32 * 1024 * 1024
IDEMPOTENCY_USER_MAX_ENTRIES: Final = 256
IDEMPOTENCY_USER_MAX_BYTES: Final = 4 * 1024 * 1024
IDEMPOTENCY_MAX_ENTRY_BYTES: Final = 256 * 1024
IDEMPOTENCY_TTL_S: Final = 86_400
#: Bytes charged per entry on top of len(body) + len(key): digest, ETag, entry tuple, LRU slots.
IDEMPOTENCY_ENTRY_OVERHEAD: Final = 512


@dataclass(frozen=True, slots=True)
class StoredResponse:
    digest: str  # sha256 of the raw request body
    status: int
    body: bytes
    etag: str | None


class IdempotencyCache:
    """Best-effort `Idempotency-Key` replay (#357 decision record 8: a bounded per-user LRU) of 2xx
    responses, keyed (user_id, "operationId:key"). Losing an entry only re-runs the request.

    Bounds (C-2.18): 4096 entries / 32 MiB in total and 256 entries / 4 MiB per user, an entry
    costing len(body) + len(key) + IDEMPOTENCY_ENTRY_OVERHEAD; a body over 256 KiB is never stored.
    A user over its caps loses its own oldest entry, so no user can evict another while the global
    caps hold; over the global caps the least recently used entry goes. Entries live
    IDEMPOTENCY_TTL_S on the injected monotonic clock; an expired hit is a miss and is dropped.
    Every operation is O(1) amortised (no scans).
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_entry_bytes: int = IDEMPOTENCY_MAX_ENTRY_BYTES,
    ) -> None:
        self._clock, self._max_entry = clock, max_entry_bytes
        self._lru: OrderedDict[tuple[str, str], tuple[StoredResponse, int, float]] = OrderedDict()
        self._users: dict[str, OrderedDict[str, None]] = {}  # per user, oldest first
        self._user_bytes: dict[str, int] = {}
        self.stored_bytes = 0

    def __len__(self) -> int:
        return len(self._lru)

    def get(self, user: str, key: str) -> StoredResponse | None:
        hit = self._lru.get((user, key))
        if hit is None:
            return None
        if self._clock() >= hit[2]:  # expired: a miss
            self._drop(user, key)
            return None
        self._lru.move_to_end((user, key))
        self._users[user].move_to_end(key)
        return hit[0]

    def put(self, user: str, key: str, value: StoredResponse) -> None:
        if len(value.body) > self._max_entry:
            return  # never stored: a retry simply runs again
        if (user, key) in self._lru:
            self._drop(user, key)
        size = len(value.body) + len(key) + IDEMPOTENCY_ENTRY_OVERHEAD
        self._lru[(user, key)] = (value, size, self._clock() + IDEMPOTENCY_TTL_S)
        self._users.setdefault(user, OrderedDict())[key] = None
        self._user_bytes[user] = self._user_bytes.get(user, 0) + size
        self.stored_bytes += size
        while user in self._users and (
            len(self._users[user]) > IDEMPOTENCY_USER_MAX_ENTRIES
            or self._user_bytes[user] > IDEMPOTENCY_USER_MAX_BYTES
        ):
            self._drop(user, next(iter(self._users[user])))
        while len(self._lru) > IDEMPOTENCY_MAX_ENTRIES or self.stored_bytes > IDEMPOTENCY_MAX_BYTES:
            self._drop(*next(iter(self._lru)))

    def _drop(self, user: str, key: str) -> None:
        size = self._lru.pop((user, key))[1]
        mine = self._users[user]
        del mine[key]
        self.stored_bytes -= size
        self._user_bytes[user] -= size
        if not mine:
            del self._users[user], self._user_bytes[user]


class IdempotencyKeyReuse(Exception):
    """The key was first used with another request fingerprint (409 `idempotency_key_reuse`)."""


def body_digest(raw: bytes) -> str:
    """/drawings' fingerprint: sha256 of the raw body (each of its keyed routes has one path)."""
    return hashlib.sha256(raw).hexdigest()


def idempotency_key(request: Request, operation: str) -> str | None:
    """`operationId:<uuid>` from the optional header; `ValueError` when it is not a UUID."""
    raw = request.headers.get("idempotency-key")
    return None if raw is None else f"{operation}:{UUID(raw)}"


def replay(cache: IdempotencyCache, owner: str, key: str | None, digest: str) -> Response | None:
    """The stored 2xx for this key and fingerprint, marked `Idempotency-Replayed: true`; the same
    key with another fingerprint raises `IdempotencyKeyReuse`."""
    hit = None if key is None else cache.get(owner, key)
    if hit is None:
        return None
    if hit.digest != digest:
        raise IdempotencyKeyReuse(key)
    headers = {"Idempotency-Replayed": "true"} | ({"ETag": hit.etag} if hit.etag else {})
    return Response(hit.body, hit.status, headers, media_type="application/json")


def remember(
    cache: IdempotencyCache, owner: str, key: str | None, digest: str, out: Response
) -> Response:
    """Keep `out` (a 2xx: callers pass successes only) for replay when a key was sent."""
    if key is not None:
        etag = out.headers.get("etag")
        cache.put(owner, key, StoredResponse(digest, out.status_code, bytes(out.body), etag))
    return out


__all__ = [
    "IDEMPOTENCY_ENTRY_OVERHEAD", "IDEMPOTENCY_MAX_BYTES", "IDEMPOTENCY_MAX_ENTRIES",
    "IDEMPOTENCY_MAX_ENTRY_BYTES", "IDEMPOTENCY_TTL_S", "IDEMPOTENCY_USER_MAX_BYTES",
    "IDEMPOTENCY_USER_MAX_ENTRIES", "IdempotencyCache", "IdempotencyKeyReuse", "StoredResponse",
    "body_digest", "idempotency_key", "remember", "replay",
]  # fmt: skip
