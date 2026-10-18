"""E17-Q01 conformance harness: the real `/ws` router driven only through a socket.

Reuses the E17-S01/S02/S03 fakes (`tests.unit.ws`) instead of inventing parallel ones: the fake
clock, the snapshot `Source`, the bounded `_recv`. The server side is wired exactly like
production (`make_ws_router` + `ConnectionRegistry` + `SequencingHub` + `SubscriptionServices`);
only time, the token verifier, the principal loader and the snapshot source are faked.

The client side is a protocol-level client that does NOT use `apps/web`'s client, so an
app-client bug cannot mask a server bug. It speaks whichever subprotocol the server echoed, JSON
or MessagePack (§2.2), and `conftest.py` runs every socket-driven test under both. EVERY frame it
receives is validated against the `23-ws-protocol.md` §13-§15 schemas (`docs/plan/ws-schema.json`)
before a test sees it; a frame the schemas do not describe fails the test that received it (no
allow-list).
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
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
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.binary import BOOK_DELTA, Frame, decode, decode_b64, encode_b64
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
#: Payload modes: structured JSON bodies, or CVWB binary carried as base64 in the JSON envelope.
MODES = ("structured", "binary")
#: The wire (an `OFFERS` key) a `connect()` that names no offer speaks. The `wire` fixture
#: (conftest.py) sets it per test, so every socket-driven row runs under `cv.v1.json` AND
#: `cv.v1.msgpack` (AC6, §2.2). Each wire must negotiate its own subprotocol.
_WIRE: ContextVar[str | None] = ContextVar("cv_ws_wire", default=None)
WIRE_SUBPROTOCOL = {"json": "cv.v1.json", "msgpack-preferred": "cv.v1.msgpack"}
#: The attribute `json_only` sets. A plain function attribute, not a pytest marker: a marker would
#: need registering in pyproject.toml (`--strict-markers`).
JSON_ONLY_ATTR = "json_only"


def use_wire(name: str) -> Token[str | None]:
    return _WIRE.set(name)


def reset_wire(token: Token[str | None]) -> None:
    _WIRE.reset(token)


def current_wire() -> str:
    """The running test's wire. A socket-driven test that no `wire` was set for fails here,
    loudly, instead of silently running under JSON only."""
    name = _WIRE.get()
    if name is None:
        raise RuntimeError(
            "no wire set: a socket-driven test must mention `World` or `connect` (conftest.py "
            "parametrises it over both subprotocols) or take an explicit `offer` parameter"
        )
    return name


def current_offer() -> list[str]:
    """The subprotocol offer of the running test's wire."""
    return OFFERS[current_wire()]


def json_only[F: Callable[..., Any]](test: F) -> F:
    """Run this socket-driven test under `cv.v1.json` only: what it sends is inherently a JSON
    text frame (its size or shape has no MessagePack twin). Read by `pytest_generate_tests`."""
    setattr(test, JSON_ONLY_ATTR, True)
    return test


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


def raw_payload(frame: dict[str, Any]) -> bytes:
    """The CVWB bytes of a binary `snap`/`d`: raw on `cv.v1.msgpack` (`e: "b"`), base64 on JSON
    (`e: "b64"`), §3.2. Tests read the payload through this, never as one encoding."""
    assert frame["e"] in {"b", "b64"}, frame["e"]
    return bytes(frame["p"]) if frame["e"] == "b" else base64.b64decode(frame["p"], validate=True)


def wire_payload(e: str, raw: bytes) -> bytes | str:
    """The `p` a server frame with encoding `e` carries for the CVWB bytes `raw`: the inverse of
    `raw_payload`."""
    return raw if e == "b" else encode_b64(decode(raw))


def cvwb_part(frame: dict[str, Any]) -> Frame:
    """The decoded CVWB part of a binary `snap`/`d`, whichever encoding carried it."""
    assert frame["e"] in {"b", "b64"}, frame["e"]
    return decode(frame["p"]) if frame["e"] == "b" else decode_b64(frame["p"])


def structured_of(frame: dict[str, Any]) -> dict[str, Any]:
    """The §14 structured payload of a `snap`/`d`: the JSON body itself, or a CVWB body decoded
    and rendered in item form (binary/structured equivalence, §16.4)."""
    if frame["e"] == "j":
        body: dict[str, Any] = frame["p"]
        return body
    return {**topic_fields(frame["ch"]), **structured(cvwb_part(frame))}


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
    `account` for account-scoped families, `user` defaults to the world's user for SELF ones. In
    `binary` mode the CVWB part goes beside the structured body, as a producer sends it (#3268)."""
    from candleviewer.auth.generated_permissions import Scope
    from candleviewer.ws.topics import FAMILIES

    part = BIN_DELTA.get(family) if mode == "binary" and FAMILIES[family].binary else None
    body = delta_body(family)
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
    """Production wiring of the gateway with fake time, identity and snapshot source; with
    `backpressure`, the gateway runs with `CV_WS_BACKPRESSURE_ENABLED` on (§8.4)."""

    def __init__(
        self,
        *,
        system_notices: Callable[[], list[dict[str, Any]]] | None = None,
        backpressure: BackpressureConfig | None = None,
    ) -> None:
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
                backpressure=backpressure,
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

    @property
    def binary_e(self) -> str:
        """The `e` of a CVWB payload here: raw on MessagePack, base64 on JSON (§3.2)."""
        return "b" if self.msgpack else "b64"

    def send_raw(self, value: Any) -> None:
        """`value` as one unvalidated frame in the negotiated codec: what no conforming client
        sends (a non-object, a deep nest, an oversize body), as JSON text or as MessagePack."""
        if self.msgpack:
            self.ws.send_bytes(msgpack.packb(value))
        else:
            self.ws.send_text(json.dumps(value))

    def send_undecodable(self, text: str) -> None:
        """`text` as one frame in the negotiated KIND (§2.2: text on `cv.v1.json`, binary on
        `cv.v1.msgpack`), though no codec reads it as an envelope."""
        if self.msgpack:
            self.ws.send_bytes(text.encode())
        else:
            self.ws.send_text(text)

    def send_other_kind(self, text: str) -> None:
        """`text` as one frame of the kind the negotiated subprotocol does NOT take (§2.2): a binary
        frame on `cv.v1.json`, a text frame on `cv.v1.msgpack`."""
        if self.msgpack:
            self.ws.send_text(text)
        else:
            self.ws.send_bytes(text.encode())

    def recv(self, *, skip_ping: bool = True, validate: bool = True) -> dict[str, Any]:
        while True:
            frame: dict[str, Any] = recv_json(self.ws)
            assert frame.get("e") != ("b64" if self.msgpack else "b"), frame  # §3.2 per encoding
            # #3370: a top-level `err`'s `field` (a `sub_ok` result's: #3479). 64 is this harness's
            # bound, as the envelope `id`'s (§13.1); §13 sets none for `field` (#572).
            if frame["t"] == "err":
                assert len(frame["p"].get("field", "")) <= 64, frame
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
    offered = offer or current_offer()
    with world.client, world.client.websocket_connect("/ws", subprotocols=offered) as ws:
        # §2.2: the server picks by its own order, msgpack first. Without this check a server that
        # stopped preferring msgpack would run every `msgpack-preferred` row as JSON, unnoticed.
        expected = "cv.v1.msgpack" if "cv.v1.msgpack" in offered else "cv.v1.json"
        assert ws.accepted_subprotocol == expected, (ws.accepted_subprotocol, offered)
        if offer is None:  # the test's own wire: the socket must speak what the wire's name says
            assert ws.accepted_subprotocol == WIRE_SUBPROTOCOL[current_wire()], current_wire()
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


@dataclass(frozen=True)
class HeatmapRow:
    """One §6.1.1 reference-value row: the pane, its documented `ideal_ms` and the selected rung."""

    display: str
    css_px: int
    dpr: float
    device_px: int
    ideal_ms: int
    selected_ms: int
    rung_ms: int | None  # the rung before the clamp, where the row prints one (`**5000**† → …`)


@dataclass(frozen=True)
class HeatmapRef:
    """§6.1.1 as the document states it: the formula's constants, the ladder, the upward clamp, the
    server's fallback and the six reference rows."""

    window_s: int
    divisor: int
    ladder: tuple[int, ...]
    clamp_ms: int
    clamp_ideal_max_ms: int
    top_rung_above_ms: int
    fallback_ms: int
    rows: tuple[HeatmapRow, ...]


#: A reference-value row: pane CSS px, DPR, device px, `ideal_ms`, then the selected rung, where a
#: clamped row reads `**5000**† → clamped to **1000**` (the last bold number is the result).
_HEATMAP_ROW = re.compile(
    r"^\|\s*(?P<display>[^|]+?)\s*\|\s*(?P<css>\d+)\s*\|\s*(?P<dpr>\d+(?:\.\d+)?)\s*\|"
    r"\s*(?P<device>\d+)\s*\|\s*(?P<ideal>\d+)\s*\|\s*(?P<selected>[^|]*\*\*\d+\*\*[^|]*?)\s*\|\s*$",
    flags=re.M,
)


def _heatmap_row(m: re.Match[str]) -> HeatmapRow:
    bold = [int(n) for n in re.findall(r"\*\*(\d+)\*\*", m["selected"])]
    return HeatmapRow(
        " ".join(m["display"].split()),
        int(m["css"]),
        float(m["dpr"]),
        int(m["device"]),
        int(m["ideal"]),
        bold[-1],
        bold[0] if len(bold) > 1 else None,
    )


def heatmap_reference(text: str | None = None) -> HeatmapRef:
    """§6.1.1 parsed from the protocol document itself, as `wire_error_codes()` reads §10.2: an
    oracle independent of the server and of the reference algorithm. `text` is the document to read
    (default: the checked-in one), so a test can parse an edited copy. A statement the section no
    longer makes is an `AssertionError`, as is an edit that changes one."""
    doc = PROTOCOL_DOC.read_text(encoding="utf-8") if text is None else text
    start = doc.index("#### 6.1.1 ")
    section = doc[start : doc.index("\n### 6.2 ", start)]

    def stated(pattern: str) -> tuple[str, ...]:
        found = re.search(pattern, section)
        assert found, f"§6.1.1 does not state {pattern!r}"
        return found.groups()

    (ladder,) = stated(r"from \{([\d, ]+)\}")
    (divisor,) = stated(r"devicePixelRatio / (\d+)\)")
    (window,) = stated(r"shipped default `window_seconds: (\d+)`")
    (fallback,) = stated(r"server applies \*\*`(\d+)`\*\*")
    clamp, edge = stated(r"clamps upward selection at \*\*(\d+) ms\*\* whenever `ideal_ms ≤ (\d+)`")
    (above,) = stated(r"small pane \(`ideal_ms > (\d+)`\) takes the 5\s?000 ms rung")
    rows = tuple(_heatmap_row(m) for m in _HEATMAP_ROW.finditer(section))
    rungs = tuple(int(rung) for rung in ladder.split(","))
    return HeatmapRef(
        int(window), int(divisor), rungs, int(clamp), int(edge), int(above), int(fallback), rows
    )


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


def scenario_frames(wire: str, replay_session: str) -> list[dict[str, Any]]:
    """One fixed scenario on `wire`, for comparing the wires: snapshots and deltas of four families
    (one of them replayed), then a pong. The frames after the handshake, whose ids are random, with
    MessagePack's raw CVWB payloads written as the base64 JSON carries them."""
    token = use_wire(wire)
    try:
        w = World()
        with connect(w) as c:
            c.sub(
                entry("trades", ("symbol",), "binary"),
                entry("book", ("symbol", "depth"), "binary"),
                {"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}},
            )
            c.drain(3)
            c.send(
                {
                    "t": "sub",
                    "id": "r",
                    "p": {
                        "topics": [entry("ticker", ("symbol",))],
                        "replay_session_id": replay_session,
                    },
                }
            )
            c.drain(2)
            publish(w, "trades", "trades.BTCUSDT", "binary")
            publish(w, "book", "book.BTCUSDT.50", "binary")
            publish(w, "orders", "orders", account=ACC_A)
            publish(w, "ticker", "ticker.BTCUSDT", replay=replay_session, ts_ms=1_700_000_000_000)
            c.drain(4)
            c.send({"t": "ping", "id": "p"})
            c.next_of("pong")
    finally:
        reset_wire(token)
    return [
        {**f, "e": "b64", "p": base64.b64encode(f["p"]).decode()} if f.get("e") == "b" else f
        for f in c.seen[2:]
    ]


def all_private(c: Client, *fams: str) -> None:
    """Subscribe to private `fams` for account A and drain their snapshots."""
    res = c.sub(*[{"ch": f, "opts": {"exchange_account_ids": [str(ACC_A)]}} for f in fams])
    assert all(r["ok"] for r in res["p"]["results"]), res
    c.drain(len(fams))
