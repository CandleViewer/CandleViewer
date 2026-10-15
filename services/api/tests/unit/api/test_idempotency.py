"""The shared Idempotency-Key helper (`api/idempotency.py`, E15-T01 ruling Q5), extracted from
/drawings unchanged: drawings re-exports it and keeps its body fingerprint, and a stored 2xx
replays as before. The LRU bounds stay pinned by `tests/drawings/test_drawings_idempotency.py`."""

from __future__ import annotations

import hashlib

import pytest
from fastapi.responses import JSONResponse

from candleviewer.api import drawings
from candleviewer.api.idempotency import (
    IdempotencyCache,
    IdempotencyKeyReuse,
    body_digest,
    remember,
    replay,
)


def test_a_stored_response_replays_its_body_and_etag_as_json() -> None:
    cache = IdempotencyCache()
    remember(cache, "u", "op:k", "d", JSONResponse({"a": 1}, 201, headers={"ETag": '"t"'}))
    hit = replay(cache, "u", "op:k", "d")
    assert hit is not None and (hit.status_code, hit.body) == (201, b'{"a":1}')
    assert hit.headers["etag"] == '"t"' and hit.headers["content-type"] == "application/json"
    assert hit.headers["idempotency-replayed"] == "true"
    with pytest.raises(IdempotencyKeyReuse):
        replay(cache, "u", "op:k", "another body")
    assert replay(cache, "u", None, "d") is None and replay(cache, "v", "op:k", "d") is None


def test_drawings_keeps_its_body_fingerprint_and_reexports_the_moved_names() -> None:
    assert body_digest(b"{}") == hashlib.sha256(b"{}").hexdigest()
    assert drawings.IdempotencyCache is IdempotencyCache
    assert (drawings.IDEMPOTENCY_MAX_ENTRIES, drawings.IDEMPOTENCY_TTL_S) == (4096, 86_400)
