"""Shared fakes for the E17-S03 sequencing tests: a snapshot source, a book model driven by the
recorded exchange corpus, and the §13-§15 schema validator."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.ws.binary import BOOK_SNAPSHOT, Frame
from candleviewer.ws.permissions import ConnectionAuthz, Subscription, SubscriptionServices
from candleviewer.ws.sequencing import SnapshotBody, SnapshotCache, TopicEmitter
from candleviewer.ws.upstream import UpstreamRefs

_BUNDLE = Path(__file__).resolve().parents[5] / "docs" / "plan" / "ws-schema.json"
_SCHEMAS: dict[str, Any] = json.loads(_BUNDLE.read_text(encoding="utf-8"))["schemas"]
_REGISTRY: Registry[Any] = Registry().with_resources(
    (sid, Resource.from_contents(body)) for sid, body in _SCHEMAS.items()
)
_CONTROL = {"revoked": "revoked", "resync": "resync", "sub_ok": "sub_ok", "ctl_ok": "ctl_ok"}

ACC_A = uuid.UUID(int=0xA)
ACC_B = uuid.UUID(int=0xB)
USER = uuid.UUID(int=0x100)
PERMS = frozenset(
    {
        Permission.MARKETDATA_READ,
        Permission.ORDERS_READ,
        Permission.POSITIONS_READ,
        Permission.EXECUTIONS_READ,
    }
)


def validate(frame: dict[str, Any]) -> None:
    """Envelope (§13.1) plus the payload schema of control frames and structured data frames."""

    def check(schema_id: str, doc: Any) -> None:
        v = Draft202012Validator(_SCHEMAS[schema_id], registry=_REGISTRY)
        errors = sorted(v.iter_errors(doc), key=str)
        assert not errors, f"{frame.get('t')} {frame.get('ch')}: {[e.message for e in errors]}"

    check("cv://ws/v1/envelope.schema.json", frame)
    t = frame["t"]
    if t in _CONTROL:
        check(f"cv://ws/v1/{_CONTROL[t]}.schema.json", frame.get("p", {}))
    elif t in {"snap", "d"} and frame.get("e") == "j":
        check(f"cv://ws/v1/{frame['ch'].split('.', 1)[0]}.schema.json", frame["p"])


def principal(*accounts: uuid.UUID) -> PrincipalSnapshot:
    grants = tuple(AccountGrant(a, True, False, False) for a in accounts)
    return PrincipalSnapshot(USER, frozenset({"manager"}), PERMS, grants)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Book:
    """Server-side reference book for one symbol (price string -> size string)."""

    def __init__(self, symbol: str, scale: int = 1) -> None:
        self.symbol = symbol
        self.scale = scale
        self.bids: dict[str, str] = {}
        self.asks: dict[str, str] = {}

    def apply(self, bids: list[list[str]], asks: list[list[str]], *, reset: bool = False) -> None:
        if reset:
            self.bids, self.asks = {}, {}
        for side, levels in ((self.bids, bids), (self.asks, asks)):
            for p, s in levels:
                if Decimal(s) == 0:
                    side.pop(p, None)
                else:
                    side[p] = s

    def top(self, depth: int) -> tuple[dict[str, str], dict[str, str]]:
        b = sorted(self.bids, key=Decimal, reverse=True)[:depth]
        a = sorted(self.asks, key=Decimal)[:depth]
        return {p: self.bids[p] for p in b}, {p: self.asks[p] for p in a}


class Source:
    """`SnapshotSource` fake: book state per symbol, or a fixed structured body per family."""

    def __init__(self) -> None:
        self.books: dict[str, Book] = {}
        self.bodies: dict[str, SnapshotBody] = {}
        self.gen = 0
        self.builds = 0
        self.stale = False
        self.covered_from_ts: int | None = None
        self.unavailable: set[str] = set()

    def build(self, sub: Subscription) -> SnapshotBody | None:
        self.builds += 1
        sym = sub.topic.symbol or ""
        if sym in self.unavailable:
            return None
        fam = sub.topic.family.family
        if fam != "book":
            return self.bodies[fam]
        book = self.books[sym]
        depth = sub.topic.depth or 50
        bids, asks = book.top(depth)
        structured = {
            "symbol": sym,
            "depth": depth,
            "bids": [[p, s] for p, s in bids.items()],
            "asks": [[p, s] for p, s in asks.items()],
        }
        scale = 10**book.scale
        recs = tuple((0, int(Decimal(p) * scale), int(Decimal(s) * 1000)) for p, s in bids.items())
        recs += tuple((1, int(Decimal(p) * scale), int(Decimal(s) * 1000)) for p, s in asks.items())
        part = Frame(BOOK_SNAPSHOT, records=recs, trailer=(1, 1))
        return SnapshotBody(
            structured, (part,), price_scale=book.scale, qty_scale=3, stale=self.stale
        )

    def generation(self, sub: Subscription) -> int:
        return self.gen

    def continuity(self, sub: Subscription, from_ts_ms: int | None) -> bool:
        return (
            from_ts_ms is not None
            and self.covered_from_ts is not None
            and from_ts_ms >= self.covered_from_ts
        )


class Conn:
    """One connection: authz + emitter writing into `out` (every frame schema-validated)."""

    def __init__(
        self,
        source: Source,
        *accounts: uuid.UUID,
        cache: SnapshotCache | None = None,
        clock: Clock | None = None,
        max_frame_bytes: int | None = None,
    ) -> None:
        self.out: list[dict[str, Any]] = []
        self.clock = clock or Clock()
        services = SubscriptionServices(upstream=UpstreamRefs(), snapshots=source)
        if cache is not None:
            services.snapshot_cache = cache
        self.authz = ConnectionAuthz(principal(*accounts or (ACC_A,)), services)
        kw: dict[str, Any] = {}
        if max_frame_bytes is not None:
            kw["max_frame_bytes"] = max_frame_bytes
        self.emitter = TopicEmitter(
            self.push,
            connection_id="ws_test",
            wall_ms=lambda: 1_789_132_262_000,
            clock=self.clock,
            source=source,
            cache=services.snapshot_cache,
            **kw,
        )

    def push(self, frame: dict[str, Any]) -> None:
        validate(frame)
        self.out.append(frame)

    def sub(self, entry: Any, **kw: Any) -> tuple[dict[str, Any], Subscription]:
        result, sub = self.authz.admit(entry, **kw)
        assert sub is not None, result
        sub.announced = True  # the gateway's `sub_ok` is queued (#2831)
        self.emitter.flush_pending([sub])
        return result, sub

    def take(self) -> list[dict[str, Any]]:
        out, self.out = self.out, []
        return out
