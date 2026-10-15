"""Unit tests for MeshOnlyMiddleware (E09-T04).

Uses raw ASGI scope/receive/send fakes (no real sockets, no network) so the
"rejection happens before authentication" and "header cannot forge an
on-mesh source" scenarios can be asserted precisely.
"""

from __future__ import annotations

import pytest
from starlette.types import Receive, Scope, Send

from candleviewer.net.audit import InMemoryAuditSink
from candleviewer.net.cidr import CidrAllowList
from candleviewer.net.middleware import RESOLVED_SOURCE_KEY, MeshOnlyMiddleware

MESH_CIDR = "100.64.0.0/10"


async def _downstream_app(scope: dict, receive: object, send: object) -> None:
    """An app that would only be reached if auth/handling were allowed to run."""
    if scope["type"] == "websocket":
        await send({"type": "websocket.accept"})
        return
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def _http_scope(client_host: str, headers: list[tuple[bytes, bytes]] | None = None) -> dict:
    return {
        "type": "http",
        "path": "/v1/orders",
        "client": (client_host, 12345),
        "headers": headers or [],
    }


class _Sent:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def __call__(self, message: dict) -> None:
        self.messages.append(message)


async def _noop_receive() -> dict:
    return {"type": "http.request"}


@pytest.mark.asyncio
async def test_on_mesh_request_reaches_downstream_app() -> None:
    allow_list = CidrAllowList([MESH_CIDR])
    mw = MeshOnlyMiddleware(_downstream_app, allow_list=allow_list)
    sent = _Sent()

    await mw(_http_scope("100.70.1.2"), _noop_receive, sent)

    assert sent.messages[0]["status"] == 200


@pytest.mark.asyncio
async def test_off_mesh_request_is_rejected_with_generic_403() -> None:
    allow_list = CidrAllowList([MESH_CIDR])
    mw = MeshOnlyMiddleware(_downstream_app, allow_list=allow_list)
    sent = _Sent()

    await mw(_http_scope("8.8.8.8"), _noop_receive, sent)

    assert sent.messages[0]["status"] == 403
    assert b"Forbidden" in sent.messages[1]["body"]
    # Generic body: no hint about the allowed CIDR.
    assert MESH_CIDR.encode() not in sent.messages[1]["body"]


@pytest.mark.asyncio
async def test_off_mesh_request_never_reaches_downstream_app() -> None:
    calls: list[str] = []

    async def _tracking_app(scope: dict, receive: object, send: object) -> None:
        calls.append("reached")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    allow_list = CidrAllowList([MESH_CIDR])
    mw = MeshOnlyMiddleware(_tracking_app, allow_list=allow_list)
    sent = _Sent()

    await mw(_http_scope("8.8.8.8"), _noop_receive, sent)

    assert calls == []


@pytest.mark.asyncio
async def test_off_mesh_request_is_audited_with_source_address() -> None:
    allow_list = CidrAllowList([MESH_CIDR])
    audit = InMemoryAuditSink()
    mw = MeshOnlyMiddleware(_downstream_app, allow_list=allow_list, audit_sink=audit)
    sent = _Sent()

    await mw(_http_scope("8.8.8.8"), _noop_receive, sent)

    assert len(audit.events) == 1
    event = audit.events[0]
    assert event["event"] == "net.off_mesh_request"
    assert event["severity"] == "warning"
    assert event["source_address"] == "8.8.8.8"


@pytest.mark.asyncio
async def test_websocket_upgrade_from_off_mesh_is_closed() -> None:
    allow_list = CidrAllowList([MESH_CIDR])
    mw = MeshOnlyMiddleware(_downstream_app, allow_list=allow_list)
    sent = _Sent()
    scope = {"type": "websocket", "path": "/ws", "client": ("8.8.8.8", 1), "headers": []}

    await mw(scope, _noop_receive, sent)

    assert sent.messages[0] == {"type": "websocket.close", "code": 4403}


@pytest.mark.asyncio
async def test_header_cannot_forge_on_mesh_source_without_trusted_proxy() -> None:
    allow_list = CidrAllowList([MESH_CIDR])
    mw = MeshOnlyMiddleware(_downstream_app, allow_list=allow_list)
    sent = _Sent()
    scope = _http_scope("8.8.8.8", headers=[(b"x-forwarded-for", b"100.70.1.2")])

    await mw(scope, _noop_receive, sent)

    assert sent.messages[0]["status"] == 403


@pytest.mark.asyncio
async def test_header_is_honoured_only_from_the_configured_trusted_proxy() -> None:
    allow_list = CidrAllowList([MESH_CIDR])
    mw = MeshOnlyMiddleware(
        _downstream_app,
        allow_list=allow_list,
        trusted_proxy_header="x-forwarded-for",
        trusted_proxy_address="127.0.0.1",
    )
    sent = _Sent()
    scope = _http_scope("127.0.0.1", headers=[(b"x-forwarded-for", b"100.70.1.2")])

    await mw(scope, _noop_receive, sent)

    assert sent.messages[0]["status"] == 200


@pytest.mark.asyncio
async def test_only_the_right_most_forwarded_hop_is_trusted() -> None:
    # A client cannot pre-seed an on-mesh address as the left-most hop to
    # get through: only the right-most hop (appended by our own proxy) is
    # trusted.
    allow_list = CidrAllowList([MESH_CIDR])
    mw = MeshOnlyMiddleware(
        _downstream_app,
        allow_list=allow_list,
        trusted_proxy_header="x-forwarded-for",
        trusted_proxy_address="127.0.0.1",
    )
    sent = _Sent()
    scope = _http_scope(
        "127.0.0.1",
        headers=[(b"x-forwarded-for", b"100.70.1.2, 8.8.8.8")],
    )

    await mw(scope, _noop_receive, sent)

    assert sent.messages[0]["status"] == 403


class _Admitted:
    """Downstream app recording the source address MeshOnly admitted."""

    def __init__(self) -> None:
        self.sources: list[object] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.sources.append(scope["state"][RESOLVED_SOURCE_KEY])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


@pytest.mark.asyncio
async def test_a_repeated_forwarded_header_from_the_trusted_proxy_is_refused() -> None:
    # #2275: a proxy that appends to the first line but passes a client's second line through
    # would let the client choose the last line's hop (joining the lines picks the same hop).
    # Which line the proxy wrote cannot be told, so no source is trusted and MeshOnly refuses.
    audit, admitted = InMemoryAuditSink(), _Admitted()
    mw = MeshOnlyMiddleware(
        admitted,
        allow_list=CidrAllowList([MESH_CIDR]),
        audit_sink=audit,
        trusted_proxy_header="x-forwarded-for",
        trusted_proxy_address="127.0.0.1",
    )
    sent = _Sent()
    lines = [(b"x-forwarded-for", b"203.0.113.9, 8.8.8.8"), (b"x-forwarded-for", b"100.70.1.2")]

    await mw(_http_scope("127.0.0.1", headers=lines), _noop_receive, sent)

    assert sent.messages[0]["status"] == 403
    assert admitted.sources == []
    assert audit.events[0]["source_address"] is None


@pytest.mark.parametrize(
    ("configured", "peer"),
    [
        ("127.0.0.1", "::ffff:127.0.0.1"),  # a dual-stack listener reports the mapped form
        ("::ffff:127.0.0.1", "127.0.0.1"),
        ("0:0:0:0:0:0:0:1", "::1"),  # not the canonical spelling of the peer
    ],
)
@pytest.mark.asyncio
async def test_the_trusted_proxy_is_matched_as_an_address_not_a_string(
    configured: str, peer: str
) -> None:
    admitted = _Admitted()
    mw = MeshOnlyMiddleware(
        admitted,
        allow_list=CidrAllowList([MESH_CIDR]),
        trusted_proxy_header="X-Forwarded-For",
        trusted_proxy_address=configured,
    )
    scope = _http_scope(peer, headers=[(b"x-forwarded-for", b"100.70.1.2")])

    await mw(scope, _noop_receive, _Sent())

    assert admitted.sources == ["100.70.1.2"]


@pytest.mark.parametrize("address", ["localhost", "127.0.0.1:8080", "127.0.0.0/8", "[::1]"])
def test_a_trusted_proxy_address_that_is_not_an_ip_fails_construction(address: str) -> None:
    # #2275: it would never equal the peer, so the header would silently never be read.
    with pytest.raises(ValueError, match="does not appear to be an IPv4 or IPv6 address"):
        MeshOnlyMiddleware(
            _Admitted(),
            allow_list=CidrAllowList([MESH_CIDR]),
            trusted_proxy_header="x-forwarded-for",
            trusted_proxy_address=address,
        )


@pytest.mark.parametrize(
    ("client", "lines", "status", "admitted"),
    [
        (("127.0.0.1", 1), [], 200, ["127.0.0.1"]),  # the proxy's own request: its address
        (("127.0.0.1", 1), [(b"x-forwarded-for", b" , ")], 200, ["127.0.0.1"]),  # no hop in it
        (("testclient", 1), [(b"x-forwarded-for", b"100.70.1.2")], 403, []),  # peer not an IP
        (None, [(b"x-forwarded-for", b"100.70.1.2")], 403, []),  # no peer at all
    ],
)
@pytest.mark.asyncio
async def test_without_a_usable_hop_from_the_trusted_proxy_the_peer_is_judged(
    client: tuple[str, int] | None,
    lines: list[tuple[bytes, bytes]],
    status: int,
    admitted: list[object],
) -> None:
    recorder = _Admitted()
    mw = MeshOnlyMiddleware(
        recorder,
        allow_list=CidrAllowList([MESH_CIDR]),
        trusted_proxy_header="x-forwarded-for",
        trusted_proxy_address="127.0.0.1",
    )
    sent = _Sent()

    await mw({"type": "http", "path": "/", "client": client, "headers": lines}, _noop_receive, sent)

    assert (sent.messages[0]["status"], recorder.sources) == (status, admitted)
