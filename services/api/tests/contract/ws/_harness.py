"""E17-Q01 conformance harness: the real `/ws` router driven only through a socket.

Reuses the E17-S01/S02/S03 fakes (`tests.unit.ws`) instead of inventing parallel ones: the fake
clock, the snapshot `Source`, the bounded `_recv`. The server side is wired exactly like
production (`make_ws_router` + `ConnectionRegistry` + `SequencingHub` + `SubscriptionServices`);
only time, the token verifier, the principal loader and the snapshot source are faked.

The client side is a protocol-level JSON client that does NOT use `apps/web`'s client, so an
app-client bug cannot mask a server bug. EVERY frame it receives is validated against the
`23-ws-protocol.md` §13-§15 schemas (`docs/plan/ws-schema.json`) before a test sees it; a frame
the schemas do not describe fails the test that received it (no allow-list).
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

import msgpack
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.ws.binary import BOOK_DELTA, Frame, decode, decode_b64
from candleviewer.ws.cvwb_vectors import structured, vector_frames
from candleviewer.ws.gateway import GatewayHub, make_ws_router
from candleviewer.ws.permissions import ConnectionRegistry, SubscriptionServices
from candleviewer.ws.revocation import RevocationHub
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody
from candleviewer.ws.upstream import UpstreamRefs
from tests.contract.ws._support import ORIGIN, SAMPLES, Clock, close_code, recv_json
from tests.unit.ws._seq_support import ACC_A, ACC_B, USER, Book, Source

REPO = Path(__file__).resolve().parents[5]
PROTOCOL_DOC = REPO / "docs" / "plan" / "23-ws-protocol.md"
_BUNDLE = REPO / "docs" / "plan" / "ws-schema.json"
SCHEMAS: dict[str, Any] = json.loads(_BUNDLE.read_text(encoding="utf-8"))["schemas"]
_REGISTRY: Registry[Any] = Registry().with_resources(
    (sid, Resource.from_contents(body)) for sid, body in SCHEMAS.items()
)
_BASE = "cv://ws/v1/"

#: §16.1 S5 causal order of private topics for one account event.
PRIVATE_ORDER = ["executions", "orders", "positions", "trade_groups"]
#: The private families that hold no accounts (F5, #2398, fixed by #2521): `alerts` (Scope.SELF) is
#: fanned out to its owner's connections, `recorder` (Scope.NONE) to every subscription. `system`
#: is also `private` but is never a Subscription: the gateway pushes it (`push_system`).
ACCOUNTLESS_PRIVATE = frozenset({"alerts", "recorder"})

SYM = "BTCUSDT"
ALL_PERMS = frozenset(
    {
        Permission.MARKETDATA_READ,
        Permission.ORDERS_READ,
        Permission.POSITIONS_READ,
        Permission.EXECUTIONS_READ,
        Permission.ACCOUNTS_READ,
        Permission.RULES_READ,
        Permission.ALERTS_READ,
        Permission.RECORDING_READ,
    }
)
#: §2.2: the subprotocol offers every test runs under. `cv.v1.msgpack` is served and preferred
#: (#2483), so the `msgpack-preferred` offer runs the test under MessagePack and `json` under JSON;
#: the client speaks whichever the server echoed.
OFFERS: dict[str, list[str]] = {
    "json": ["cv.v1.json"],
    "msgpack-preferred": ["cv.v1.msgpack", "cv.v1.json"],
}
JSON = OFFERS["json"]
#: Payload modes: structured JSON bodies, or CVWB binary carried as base64 in the JSON envelope.
MODES = ("structured", "binary")


# -- schema validation -------------------------------------------------------------------------


@cache
def _validator(schema_id: str) -> Draft202012Validator:
    schema = SCHEMAS.get(
        schema_id, {"$ref": schema_id}
    )  # `file#/$defs/x` refs resolve via registry
    return Draft202012Validator(schema, registry=_REGISTRY)


def check_schema(schema_id: str, doc: Any, what: str) -> None:
    errors = sorted(_validator(schema_id).iter_errors(doc), key=str)
    assert not errors, f"{what} violates {schema_id}: {[e.message for e in errors][:3]}"


#: Envelope `t` -> the §13 payload schema of its `p` (frames whose `p` is family-specific are
#: handled by `validate_frame`).
_CONTROL_SCHEMA = {
    "hello": "hello",
    "welcome": "welcome",
    "auth": "auth",
    "auth_ok": "auth_ok",
    "sub": "sub",
    "sub_ok": "sub_ok",
    "unsub": "unsub",
    "unsub_ok": "unsub_ok",
    "ctl": "ctl",
    "ctl_ok": "ctl_ok",
    "resync": "resync",
    "revoked": "revoked",
    "permission_change": "permission_change",
    "ping": "heartbeat",
    "pong": "heartbeat",
    "bye": "bye",
}


def topic_fields(ch: str) -> dict[str, Any]:
    """The topic-derived fields a binary body does not carry (§14: `symbol`, `bar_type`, ...)."""
    parts = ch.split(".")
    fam = parts[0]
    out: dict[str, Any] = {}
    if fam == "book":
        out = {"symbol": parts[1]}
    elif fam == "trades":
        out = {"symbol": parts[1]}
    elif fam == "heatmap":  # `time_bucket_ms` is the effective option (500 when absent, §6.1.1)
        out = {"symbol": parts[1], "time_bucket_ms": 500}
    elif fam in {"bars", "footprint"}:
        out = {"symbol": parts[1], "bar_type": parts[2], "param": parts[3]}
    return out


def structured_of(frame: dict[str, Any]) -> dict[str, Any]:
    """The §14 structured payload of a `snap`/`d`: the JSON body itself, or a CVWB body decoded
    and rendered in item form (binary/structured equivalence, §16.4)."""
    if frame["e"] == "j":
        body: dict[str, Any] = frame["p"]
        return body
    assert frame["e"] in {"b", "b64"}, frame["e"]  # raw on MessagePack, base64 on JSON (§3.2)
    part = decode(frame["p"]) if frame["e"] == "b" else decode_b64(frame["p"])
    return {**topic_fields(frame["ch"]), **structured(part)}


def validate_frame(frame: dict[str, Any]) -> None:
    """Envelope (§13.1) + the payload schema of whatever the frame carries."""
    what = f"{frame.get('t')} {frame.get('ch', '')}".strip()
    raw = frame.get("p")  # JSON Schema has no bytes: a `bin` is a `contentEncoding: binary` str
    envelope = {**frame, "p": raw.decode("latin-1")} if isinstance(raw, bytes) else frame
    check_schema(_BASE + "envelope.schema.json", envelope, what)
    t = frame["t"]
    if t == "err":
        check_schema(_BASE + "common.schema.json#/$defs/error", frame["p"], what)
    elif t in _CONTROL_SCHEMA:
        check_schema(_BASE + f"{_CONTROL_SCHEMA[t]}.schema.json", frame.get("p", {}), what)
    elif t in {"snap", "d"}:
        fam = frame["ch"].split(".", 1)[0]
        if frame["e"] in {"b", "b64"} and frame.get("s") is None and t == "snap":
            return  # a non-final snapshot chunk: each part is CVWB-validated by its decode
        check_schema(_BASE + f"{fam}.schema.json", structured_of(frame), what)


# -- the world ---------------------------------------------------------------------------------


def _bodies() -> dict[str, SnapshotBody]:
    """Per-family snapshot bodies. Structured twins come from the E17-S03 evidence table; the
    CVWB-carrying families (trades/bars/footprint/heatmap) also hold a binary part so the SAME
    state can be requested as `structured` or `binary` (the two encodings under test)."""
    out = {
        fam: SnapshotBody(snap, price_scale=1, qty_scale=3)
        for fam, (snap, _delta) in SAMPLES.items()
        if fam != "book"
    }
    frames = dict(vector_frames())
    series = {"symbol": SYM, "bar_type": "time", "param": "1"}
    extras: dict[str, tuple[str, dict[str, Any]]] = {
        "trades": ("trades", {"symbol": SYM}),
        "bars": ("bars_v2", series),
        "footprint": ("footprint", series),
        "heatmap": ("heatmap_column", {"symbol": SYM, "time_bucket_ms": 500}),
    }
    for fam, (name, extra) in extras.items():
        out[fam] = binary_body(frames[name], **extra)
    return out


#: The CVWB body a binary-mode delta carries, per family (kinds 2-6).
BIN_DELTA: dict[str, Frame] = {
    "book": Frame(BOOK_DELTA, ((0, 1000, 1500), (1, 1010, 0)), 0, 1, 3, 1_789_132_262_104),
    **{
        fam: dict(vector_frames())[name]
        for fam, name in (
            ("trades", "trades"),
            ("bars", "bars_v2"),
            ("footprint", "footprint"),
            ("heatmap", "heatmap_column"),
        )
    },
}


def delta_body(family: str) -> dict[str, Any]:
    """A schema-valid §14/§15 delta body for `family` (transport tests never judge content)."""
    return dict(SAMPLES[family][1])


def publish(
    world: World,
    family: str,
    ch: str,
    mode: str = "structured",
    *,
    account: uuid.UUID | None = None,
    user: uuid.UUID | None = None,
    replay: str | None = None,
    ts_ms: int | None = None,
    coalesced_count: int = 1,
) -> int:
    """One owning-module event for `ch` through the real `SequencingHub`, on the app loop. Like
    `account` for account-scoped families, `user` defaults to the world's user for SELF ones."""
    from candleviewer.auth.generated_permissions import Scope
    from candleviewer.ws.topics import FAMILIES

    part = BIN_DELTA.get(family) if mode == "binary" and FAMILIES[family].binary else None
    body = None if part is not None else delta_body(family)
    acc = account if FAMILIES[family].private else None
    if FAMILIES[family].account_scoped and acc is None:
        acc = ACC_A
    # By value: a test that reloads `generated_permissions` (test_rbac_generator) leaves two
    # `Scope` classes behind, so an identity check would depend on the test order.
    owner = user if user is not None or FAMILIES[family].scope != Scope.SELF else USER
    sent: int = world.call(
        lambda: world.hub.publish(
            ch,
            body,
            part=part,
            account=acc,
            user=owner,
            replay_session_id=replay,
            ts_ms=ts_ms,
            coalesced_count=coalesced_count,
        )
    )
    return sent


class World:
    """Production wiring of the gateway with fake time, identity and snapshot source."""

    def __init__(self, *, system_notices: Callable[[], list[dict[str, Any]]] | None = None) -> None:
        self.clock = Clock()
        self.source = Source()
        book = Book(SYM)
        book.apply(
            [[f"{100 - i}.0", "1.000"] for i in range(5)],
            [[f"{101 + i}.0", "2.000"] for i in range(5)],
        )
        self.source.books[SYM] = book
        self.source.bodies.update(_bodies())
        self.hub = SequencingHub()
        self.gateway = GatewayHub()
        self.revocation = RevocationHub()
        self.grants: tuple[AccountGrant, ...] = (
            AccountGrant(ACC_A, True, False, False),
            AccountGrant(ACC_B, True, False, False),
        )
        self.perms: frozenset[Permission] = ALL_PERMS
        self.tokens_seen: list[str] = []
        self.token_ttl_s = 600
        self.session = str(uuid.uuid4())
        services = SubscriptionServices(
            upstream=UpstreamRefs(), snapshots=self.source, sequencing=self.hub
        )
        self.registry = ConnectionRegistry(self._resolve, self.clock.wall_ms, services)
        app = FastAPI()
        app.include_router(
            make_ws_router(
                authenticate=self._authenticate,
                registry=self.registry,
                revocation_hub=self.revocation,
                allowed_origins=frozenset({ORIGIN}),
                hub=self.gateway,
                clock=self.clock,
                wall_ms=self.clock.wall_ms,
                tick_s=0.005,
                server_version="1.0.0",
                git_sha="conformance",
                system_notices=system_notices,
            )
        )
        self.app = app
        self.client = TestClient(app, headers={"origin": ORIGIN})

    async def _resolve(self, uid: uuid.UUID) -> PrincipalSnapshot:
        return PrincipalSnapshot(uid, frozenset({"manager"}), self.perms, self.grants)

    async def _authenticate(self, token: str) -> tuple[str, uuid.UUID, datetime]:
        self.tokens_seen.append(token)
        if not token.startswith("good"):
            raise PermissionError("bad token")
        exp = self.clock.wall_ms() + self.token_ttl_s * 1000
        return self.session, USER, datetime.fromtimestamp(exp / 1000, tz=UTC)

    def call(self, fn: Callable[..., Any], *args: Any) -> Any:
        """Run `fn` on the app's event loop (where production code publishes)."""
        assert self.client.portal is not None
        return self.client.portal.call(fn, *args)

    def advance(self, ws: Client, to: float) -> None:
        """Move the fake clock in 30 s steps, keeping the client alive with pings."""
        while self.clock.now < to:
            self.clock.now = min(to, self.clock.now + 30.0)
            ws.send({"t": "ping", "id": "keepalive"})
            ws.next_of("pong")


class Client:
    """A validating protocol client over one starlette websocket session."""

    def __init__(self, ws: Any, *, conform: bool = True) -> None:
        self.ws = ws
        self.conform = conform  # default for `send`/`sub`; negative-path tests turn it off
        self.seen: list[dict[str, Any]] = []
        #: §2.2: every frame, both ways, is MessagePack on `cv.v1.msgpack`, else JSON text.
        self.msgpack = ws.accepted_subprotocol == "cv.v1.msgpack"

    # -- raw ---
    def send(self, frame: dict[str, Any], *, conform: bool | None = None) -> None:
        """Send a client frame. By default it is validated against §13 first, so a test cannot
        accidentally send a non-conformant frame; pass `conform=False` to send a deliberately
        invalid one (the negative tests do)."""
        if self.conform if conform is None else conform:
            validate_frame(frame)
        if self.msgpack:
            self.ws.send_bytes(msgpack.packb(frame))
        else:
            self.ws.send_json(frame)

    def send_text(self, text: str) -> None:
        self.ws.send_text(text)

    def recv(self, *, skip_ping: bool = True, validate: bool = True) -> dict[str, Any]:
        while True:
            frame: dict[str, Any] = recv_json(self.ws)
            assert frame.get("e") != ("b64" if self.msgpack else "b"), frame  # §3.2 per encoding
            if validate:
                validate_frame(frame)
            self.seen.append(frame)
            if frame["t"] != "ping" or not skip_ping:
                return frame

    def recv_err(self) -> dict[str, Any]:
        """Next `err` frame, fully validated: the §13 envelope and the `error` payload.

        Frames before it are skipped without validation, so a test does not depend on which other
        frames precede it. FINDING F1 (every `err` frame omitted `message`) was closed by #2520,
        so the whole frame is checked; `code` closure is still asserted by the caller.
        """
        frame = self.next_of_raw("err")
        validate_frame(frame)
        return frame

    def next_of_raw(self, t: str) -> dict[str, Any]:
        """Next frame of type `t`; frames before it are skipped WITHOUT schema validation."""
        for _ in range(2000):
            frame = self.recv(validate=False)
            if frame["t"] == t:
                return frame
        pytest.fail(f"no {t} frame")

    def next_validated(self, t: str) -> dict[str, Any]:
        """Next frame of type `t`, fully schema-validated; frames before it are skipped WITHOUT
        validation, so a test does not depend on which other frames precede it (a grant change
        pushes a `permission_change` ahead of its `revoked` frames, §9.5)."""
        frame = self.next_of_raw(t)
        validate_frame(frame)
        return frame

    def recv_permission_change(self) -> dict[str, Any]:
        """Next frame, which must be `permission_change`, validated like every other frame.

        `permission_change` is in the §13.1 envelope `t` enum and has its own §13.4 payload
        schema (#2297, closes FINDING F3 / #2397), so `recv` checks both the envelope and `p`.
        """
        frame = self.recv()
        assert frame["t"] == "permission_change", frame
        return frame

    def next_of(self, t: str) -> dict[str, Any]:
        for _ in range(2000):
            frame = self.recv()
            if frame["t"] == t:
                return frame
        pytest.fail(f"no {t} frame")

    def drain(self, n: int) -> list[dict[str, Any]]:
        return [self.recv() for _ in range(n)]

    def closed(self) -> int:
        return close_code(self.ws)

    def bye_then_close(self) -> tuple[dict[str, Any], int]:
        """S11: the next non-ping frame is `bye`, then the socket closes with its code."""
        bye = self.next_of_raw("bye")  # frames before the `bye` are skipped unvalidated
        check_schema(_BASE + "envelope.schema.json", bye, "bye")
        check_schema(_BASE + "bye.schema.json", bye["p"], "bye")
        code = self.closed()
        assert code == bye["p"]["code"], (code, bye)
        return bye, code

    # -- protocol helpers ---
    def open(
        self,
        *,
        auth: bool = True,
        token: str = "good-" + "x" * 20,
        **hello: Any,
    ) -> None:
        self.send(
            {
                "t": "hello",
                "id": "h",
                "p": {
                    "client": "conformance",
                    "client_version": "1.0.0",
                    "protocol": "cv.v1",
                    **hello,
                },
            }
        )
        assert self.recv()["t"] == "welcome"
        if auth:
            self.send({"t": "auth", "id": "a", "p": {"access_token": token}})
            assert self.recv()["t"] == "auth_ok"

    def sub(self, *topics: Any, conform: bool | None = None, **p: Any) -> dict[str, Any]:
        """`sub` with the §13.5 object form `{ch, opts}`; bare strings are normalised to it
        (the schema does not allow strings)."""
        entries = [{"ch": t} if isinstance(t, str) else t for t in topics]
        self.send({"t": "sub", "id": "s", "p": {"topics": entries, **p}}, conform=conform)
        return self.next_of("sub_ok")


@contextmanager
def connect(
    world: World,
    offer: list[str] | None = None,
    *,
    authed: bool = True,
    handshake: bool = True,
    conform: bool = True,
    **hello: Any,
) -> Iterator[Client]:
    offered = offer or JSON
    with world.client, world.client.websocket_connect("/ws", subprotocols=offered) as ws:
        # §2.2: the server picks by its own order, msgpack first. Without this check a server that
        # stopped preferring msgpack would run every `msgpack-preferred` row as JSON, unnoticed.
        expected = "cv.v1.msgpack" if "cv.v1.msgpack" in offered else "cv.v1.json"
        assert ws.accepted_subprotocol == expected, (ws.accepted_subprotocol, offered)
        c = Client(ws, conform=conform)
        if handshake:
            c.open(auth=authed, **hello)
        yield c


# -- catalogue helpers -------------------------------------------------------------------------

_SEG = {"symbol": SYM, "depth": "50", "bar_type": "time", "param": "1", "profile_kind": "volume",
        "entity": "kill_switch", "state": "state"}  # fmt: skip


def entry(
    family: str, shape: tuple[str, ...], mode: str = "structured", **opts: Any
) -> dict[str, Any]:
    """A `sub` topic entry for one registry row (accounts attached for scoped families)."""
    from candleviewer.ws.topics import FAMILIES

    fam = FAMILIES[family]
    ch = ".".join((family, *(_SEG[s] for s in shape)))
    o: dict[str, Any] = dict(opts)
    if fam.account_scoped:
        o.setdefault("exchange_account_ids", [str(ACC_A)])
    if fam.binary:
        o.setdefault("encoding", "binary" if mode == "binary" else "structured")
    elif mode == "binary":
        o.setdefault("encoding", "structured")
    return {"ch": ch, "opts": o}


def wire_error_codes() -> frozenset[str]:
    """The §10.2 `code` column, parsed from the protocol document itself (an oracle independent of
    the generated registry the server uses)."""
    text = PROTOCOL_DOC.read_text(encoding="utf-8")
    start = text.index("### 10.2 Catalogue")
    end = text.index("### 10.3", start)
    return frozenset(re.findall(r"^\| `([a-z_]+)`\s+\|", text[start:end], flags=re.M))


def binary_body(frame: Frame, **extra: Any) -> SnapshotBody:
    """A snapshot body whose CVWB part and structured twin come from the same `Frame`."""
    return SnapshotBody(
        {**extra, **structured(frame)},
        (frame,),
        price_scale=frame.price_scale,
        qty_scale=frame.qty_scale,
        estimated=bool(frame.flags & 1),
    )


def assert_contiguous(frames: list[dict[str, Any]]) -> None:
    """S3 oracle: per (topic, replay session) the sequence numbers of delivered frames are exactly
    1, 2, 3, ... (a chunked snapshot's non-final parts carry `s: null` and consume none)."""
    last: dict[tuple[str, str | None], int] = {}
    for f in frames:
        if f["t"] not in {"snap", "d"} or f.get("s") is None:
            continue
        key = (f["ch"], f.get("rs"))
        expected = last.get(key, 0) + 1
        assert f["s"] == expected, f"{key}: got s={f['s']}, expected {expected} (skipped or reused)"
        last[key] = f["s"]


def all_private(c: Client, *fams: str) -> None:
    """Subscribe to private `fams` for account A and drain their snapshots."""
    res = c.sub(*[{"ch": f, "opts": {"exchange_account_ids": [str(ACC_A)]}} for f in fams])
    assert all(r["ok"] for r in res["p"]["results"]), res
    c.drain(len(fams))
