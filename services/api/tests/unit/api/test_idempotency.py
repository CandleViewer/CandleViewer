"""The shared Idempotency-Key helper (`api/idempotency.py`, E15-T01 ruling Q5), extracted from
/drawings unchanged: drawings re-exports it and keeps its body fingerprint, and a stored 2xx
replays as before. For /workspaces (D23) the fingerprint covers method, path and body and only
2xx outcomes are kept. The LRU bounds stay pinned by `tests/drawings/test_drawings_idempotency.py`.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi import Response
from fastapi.responses import JSONResponse

from candleviewer.api import drawings
from candleviewer.api.idempotency import (
    IdempotencyCache,
    IdempotencyKeyReuse,
    body_digest,
    remember,
    replay,
    request_fingerprint,
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


def test_the_workspaces_fingerprint_covers_method_path_and_body() -> None:
    base = request_fingerprint("DELETE", "/workspaces/a", b"")
    assert base == hashlib.sha256(b"DELETE\n/workspaces/a\n").hexdigest()
    variants = {request_fingerprint("DELETE", "/workspaces/b", b""),
                request_fingerprint("POST", "/workspaces/a", b""),
                request_fingerprint("DELETE", "/workspaces/a", b"{}")}  # fmt: skip
    assert base not in variants and len(variants) == 3


def test_only_successes_are_kept_and_a_stored_204_replays_without_a_body() -> None:
    cache = IdempotencyCache()
    for status in (409, 412, 422, 503):
        remember(cache, "u", "op:k", "d", JSONResponse({"code": "x"}, status))
    assert len(cache) == 0 and replay(cache, "u", "op:k", "d") is None
    remember(cache, "u", "op:k", "d", Response(status_code=204))
    hit = replay(cache, "u", "op:k", "d")
    assert hit is not None and (hit.status_code, hit.body) == (204, b"")
    assert hit.headers["idempotency-replayed"] == "true" and "content-type" not in hit.headers
