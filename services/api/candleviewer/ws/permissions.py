"""WS authorisation + subscriptions (E09-T03, E17-S02; `23-ws-protocol.md` §4.3, §5, §6, §9.5).

- `auth_ok_payload`: identity, roles, resolved permissions, account scope.
- `check_subscribe`: per-family permission check against the §6.3 matrix (fail-closed), backed by
  the declarative registry in `topics.FAMILIES`. Every decision is `auth.scopes.decide` (E09's
  RBAC service) - never a local copy of the rules.
- `ConnectionAuthz`: per-connection subscription manager. `sub` (partial success, results in
  request order, clamped `effective`), idempotent `unsub`, `ctl` (retune / resnapshot), the §16.2
  limits and §6.2 silent account-scope narrowing. `apply_snapshot` re-evaluates every live
  subscription after a role/grant change and returns the `revoked` frames (§9.5, S7). With the
  backpressure flag on, `on_drop` hears of every subscription an operation ends or resets.
- `ConnectionRegistry`: live sockets per user; role/grant change, kill-switch transition and
  user-disabled fan-out.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import itertools
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Protocol

import structlog

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import Allow, Deny, DenyReason, PrincipalSnapshot, decide
from candleviewer.bars.errors import (
    BarParamOutOfRange,
    BarsError,
    BarServiceStopping,
    SpecCapExceeded,
)
from candleviewer.bars.models import BarSpec
from candleviewer.bars.series_store import Hold
from candleviewer.bars.spec import check_param_bounds, from_wire
from candleviewer.observability.context import current_request_id
from candleviewer.observability.metrics import Counter, Histogram
from candleviewer.ws.errors import build_ws_error
from candleviewer.ws.limits import (
    FANOUT_AUDIT_MAX_FAILURES,
    FANOUT_AUDIT_TIMEOUT_S,
    FANOUT_SEND_TIMEOUT_S,
    MAX_BARS_SUBSCRIPTIONS,
    MAX_DENIALS_LISTED,
    MAX_SUBSCRIPTIONS,
    MAX_SYMBOLS_PER_CONNECTION,
    MAX_TOPICS_PER_SUB,
)
from candleviewer.ws.metrics import count_audit_failure
from candleviewer.ws.revocation import (
    Closer,
    RevokedReason,
    revoked_frame,
    user_disabled_bye,
    ws_revoked_total,
)
from candleviewer.ws.sequencing import (
    RESYNC_MAX_PER_WINDOW,
    SequencingHub,
    SnapReason,
    SnapshotCache,
    SnapshotSource,
)
from candleviewer.ws.topics import (
    CTL_KEYS,
    FAMILIES,
    IDENTITY_OPTIONS,
    MACHINE_KINDS,
    SCOPE_OPTIONS,
    UNIVERSAL,
    EntityScope,
    ParsedTopic,
    TopicError,
    effective_options,
    is_topic_name,
    machine_refusal,
    parse_topic,
    validate_options,
)
from candleviewer.ws.upstream import UpstreamKey, UpstreamRefs

#: §13.5 `sub.p` keys; any other key breaks the frame's shape (#2399).
SUB_KEYS: Final = frozenset({"topics", "snapshot", "replay_session_id"})
#: §13.5 `unsub.p` keys; any other key breaks the frame's shape (#2572).
UNSUB_KEYS: Final = frozenset({"topics"})

SYSTEM_TOPIC: Final = "system"

#: §6.3 topic family -> (permission, scope), derived from the registry (the RBAC matrix reads
#: this). `system` is implicit (no check) and therefore absent.
TOPIC_PERMISSIONS: Final[dict[str, tuple[Permission, Scope]]] = {
    name: (fam.permission, fam.scope)
    for name, fam in FAMILIES.items()
    if fam.permission is not None and fam.scope is not None
}

cv_ws_subscribe_total = Counter(
    "cv_ws_subscribe_total",
    "WS sub results; the topic label holds the topic family.",
    labelnames=("topic", "result"),
)
cv_ws_client_topics_depth = Histogram(
    "cv_ws_client_topics_depth",
    "Subscriptions held by a connection, observed after each sub/unsub.",
    buckets=(1, 5, 10, 20, 50, 100, 150, 200),
)
cv_ws_permission_snapshots_refused_total = Counter(
    "cv_ws_permission_snapshots_refused_total",
    "Older WS permission snapshots refused because a newer one was applied (SR-189).",
    labelnames=("event",),
)
SnapshotEvent = Literal["reauth", "grant_change", "handshake"]  # the step that was refused
#: `ws audit rows abandoned` names at most this many users; its `users` counts them all (#2824).
_ABANDONED_USERS_LOGGED: Final = 10
#: SR-186 (#2174): the one `ws.subscribe.granted` record of a `sub` frame lists the `ch` and
#: account ids of at most this many of its new private subscriptions; its `count` holds them all.
MAX_GRANTS_LISTED: Final = 10


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class BarLeases(Protocol):
    """`BarBuilderSet` lease surface (E12-T03). `user` is ALWAYS the authenticated principal."""

    def check(self, spec: BarSpec, symbol: str, user: str | None = None) -> None: ...

    async def register(
        self, spec: BarSpec, symbol: str, consumer: str, user: str | None = None
    ) -> None: ...

    def release(self, spec_hash: str, symbol: str, consumer: str) -> None: ...


class SeriesHolds(Protocol):
    """`SeriesStore.ensure` (E12-T06): a live `bars.*` subscription holds its series."""

    async def ensure(self, symbol: str, spec: BarSpec) -> Hold: ...


class AuditSink(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class EntityScopes(Protocol):
    """What `sub` reads of the §6.4 machine-state registry, which only the publisher writes."""

    def scope(self, ch: str) -> EntityScope | None:
        """The entry's scope; `None` when `ch` has no entry."""


@dataclass
class SubscriptionServices:
    """Process-wide collaborators shared by every connection (injected; never a global)."""

    upstream: UpstreamRefs = field(default_factory=UpstreamRefs)
    bars: BarLeases | None = None
    series: SeriesHolds | None = None  # E12-T06: the `bars` snapshot store; None: no hold
    audit: AuditSink | None = None
    clock: Callable[[], float] = time.monotonic
    instrument_known: Callable[[str], bool] | None = None
    #: E17-S03: owning-module snapshot port and shared render cache; `None` until wired, in
    #: which case subscriptions stay `snapshot_pending` and no `snap` is emitted.
    snapshots: SnapshotSource | None = None
    snapshot_cache: SnapshotCache = field(default_factory=SnapshotCache)
    sequencing: SequencingHub | None = None
    #: §6.1: the deployment runs with `bars_enabled` off, so `bars.*` is refused `unknown_topic`.
    #: Set by the app from settings (a bare `bars=None` only means "no lease to take").
    bars_off: bool = False
    #: E17-T08: the `machines.{entity}.state` entries `sub` is authorised against (§6.4); `None`
    #: means no entity has an entry.
    machines: EntityScopes | None = None
    #: E17-T06: draws each connection's span ids (`sp`, 23 §3.1); the app sets it from
    #: `CV_TELEMETRY_ENABLED`, and `None` (latency telemetry off) means no frame carries one.
    span_ids: Callable[[], str] | None = None


@dataclass(frozen=True, slots=True)
class VersionedSnapshot:
    """A principal plus the registry's monotonic version, taken before the read (SR-189)."""

    principal: PrincipalSnapshot
    version: int


def topic_family(topic: str) -> str:
    return topic.split(".", 1)[0]


def auth_ok_payload(principal: PrincipalSnapshot, **extra: Any) -> dict[str, Any]:
    """`auth_ok` `p` body: roles, resolved permissions and account scope."""
    return {
        "user_id": str(principal.user_id),
        "roles": sorted(principal.roles),
        "permissions": sorted(p.value for p in principal.permissions),
        # Empty for owner = all accounts (ticket); viewable grants otherwise.
        "account_scope": sorted(
            str(g.exchange_account_id) for g in principal.account_grants if g.can_view
        ),
        **extra,
    }


def check_subscribe(
    principal: PrincipalSnapshot,
    topic: str,
    *,
    exchange_account_id: uuid.UUID | None = None,
) -> Allow | Deny | None:
    """Decision for a `sub` of `topic`'s family. `None` for the implicit `system` topic; `Deny`
    for unknown families. Account-scoped families REQUIRE an account id (`decide()` denies a
    GRANTED_ACCOUNTS check without one, #1654 IDOR)."""
    family = topic_family(topic)
    if family == SYSTEM_TOPIC:
        return None
    entry = TOPIC_PERMISSIONS.get(family)
    if entry is None:
        return Deny(DenyReason.MISSING_PERMISSION, Permission.MARKETDATA_READ, Scope.NONE)
    permission, scope = entry
    return decide(principal, permission, scope=scope, exchange_account_id=exchange_account_id)


@dataclass
class Subscription:
    """One live subscription. `accounts` is empty for unscoped families."""

    sub_id: str
    topic: ParsedTopic
    opts: dict[str, Any]
    effective: dict[str, Any]
    accounts: frozenset[uuid.UUID] = frozenset()
    replay_session_id: str | None = None
    seq: int = 0
    snapshot_pending: bool = True
    upstream: tuple[UpstreamKey, ...] = ()
    bar_lease: tuple[str, str] | None = None  # (spec_hash, symbol)
    series_hold: Hold | None = None  # a live `bars.*` one's series in the snapshot store
    #: §7.4 reason the pending `snap` will carry (E17-S03).
    pending_reason: SnapReason = "initial"
    #: §6.4 `machines`: the entity's scope, read from its entry at `sub`, so every RBAC change
    #: re-checks it without a lookup.
    entity: EntityScope | None = None
    #: #2831: whether its `sub_ok` is queued; no `snap` goes out before it (§7.1). `_admit`
    #: records it False and `handle_sub` sets it once that reply is queued. It holds the `snap`
    #: only: a `d` for a §7.6 continuity attach can still precede `sub_ok` (#2909).
    announced: bool = True
    #: E17-T03: set when it ends (`_drop`), after which `TopicEmitter` sends nothing of it.
    ended: bool = False
    #: §7.5 client-resync times (monotonic s); bounded to the 5-per-minute window.
    resyncs: collections.deque[float] = field(
        default_factory=lambda: collections.deque(maxlen=RESYNC_MAX_PER_WINDOW)
    )

    @property
    def ch(self) -> str:
        return self.topic.ch

    @property
    def symbols(self) -> frozenset[str]:
        out = set(self.opts.get("symbols") or ())
        if self.topic.symbol is not None:
            out.add(self.topic.symbol)
        return frozenset(out)


def _bar_spec(sub: Subscription) -> tuple[BarSpec | None, dict[str, Any] | None]:
    """A `bars.*`/`footprint.*` topic's spec, or its refusal (§6.1, SR-E12-03): an unbuildable
    spec, or a `param` outside its kind's bounds, naming the bound and never the series."""
    bar_type = sub.topic.bar_type or ""
    try:
        spec = from_wire(bar_type, sub.topic.param or "")
        check_param_bounds(spec, bar_type)
    except BarParamOutOfRange as exc:
        return None, _fail(sub.ch, "invalid_topic_format", str(exc))
    except BarsError:
        return None, _fail(sub.ch, "invalid_topic_format", "This bar series is not available.")
    return spec, None


#: One message per refusal code, whatever the cause: `account_scope_denied` carries §6.2's.
_REFUSED: Final = {
    "forbidden": "Missing permission for this topic.",
    "account_scope_denied": "None of the requested accounts are in scope.",
}


def _fail(ch: Any, code: str, message: str, fld: str | None = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if fld is not None:
        err["field"] = fld
    return {"ch": ch if isinstance(ch, str) else str(ch)[:120], "ok": False, "error": err}


def _bad_replay() -> str:
    raise TopicError("invalid_options", "replay_session_id must be a uuid.", "replay_session_id")


def _replay_id(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        return _bad_replay()
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        return _bad_replay()


def _upstream_keys(sub: Subscription) -> tuple[UpstreamKey, ...]:
    """(symbol, family, params) per symbol the topic needs from the exchange."""
    t = sub.topic
    symbols = [t.symbol] if t.symbol is not None else sorted(sub.opts.get("symbols") or ())
    return tuple((s, t.family.family, t.params) for s in symbols)


class ConnectionAuthz:
    """Authorisation + subscription state of one authenticated WS connection.

    Indexes: `by_id` (sub_id -> Subscription) and a reverse index by topic name, so `unsub`,
    `ctl` and grant re-evaluation resolve in O(affected)."""

    def __init__(
        self,
        principal: PrincipalSnapshot,
        services: SubscriptionServices | None = None,
        *,
        connection_id: str | None = None,
        version: int = 0,
    ) -> None:
        self.principal = principal
        self.version = version  # SR-189: the applied snapshot's; 0 = not from the registry
        self.services = services if services is not None else SubscriptionServices()
        self.connection_id = connection_id or f"c-{uuid.uuid4().hex[:12]}"
        self.by_id: dict[str, Subscription] = {}
        self._by_topic: dict[str, set[str]] = {}
        self._ids = itertools.count(1)
        #: §6.4: the internal reason (`role`, `unknown`, `foreign` or `unscoped`) of the last
        #: `admit` that refused a `machines` entity, else `None`. `handle_sub` reads it right
        #: after that `admit`, for the audit row only; it never reaches the client.
        self.refusal_reason: str | None = None
        #: E17-T03 (flag on, the outbound pipeline): called once per operation, before its reply
        #: or `revoked` is queued, with every subscription whose queued frames and throttle
        #: window it made stale (§8.4 Lanes, §9.5). While it is set, a narrowing re-pends what it
        #: kept (`settling`), for `on_settle` after the change's frames (the registry's `settle`).
        self.on_drop: Callable[[list[Subscription]], None] | None = None
        self.on_settle: Callable[[list[Subscription]], None] | None = None
        self.settling: list[Subscription] = []

    # -- views ------------------------------------------------------------------------------

    @property
    def subs(self) -> set[tuple[str, uuid.UUID | None]]:
        """(topic, account or None) pairs of every live subscription (diagnostic view)."""
        out: set[tuple[str, uuid.UUID | None]] = set()
        for s in self.by_id.values():
            if s.accounts:
                out.update((s.ch, a) for a in s.accounts)
            else:
                out.add((s.ch, None))
        return out

    @property
    def topics(self) -> set[str]:
        return set(self._by_topic)

    def find(self, ch: str, replay_session_id: str | None = None) -> Subscription | None:
        for sid in self._by_topic.get(ch, ()):
            sub = self.by_id[sid]
            if sub.replay_session_id == replay_session_id:
                return sub
        return None

    def at_capacity(self, needed: int = 1) -> bool:
        """True when `needed` more subscriptions would exceed `MAX_SUBSCRIPTIONS` (C-2.18)."""
        return len(self.by_id) + needed > MAX_SUBSCRIPTIONS

    def may_submit_order(self) -> bool:
        return isinstance(decide(self.principal, Permission.ORDERS_WRITE), Allow)

    # -- sub --------------------------------------------------------------------------------

    def admit(
        self,
        entry: Any,
        *,
        snapshot: Any = True,
        replay_session_id: Any = None,
    ) -> tuple[dict[str, Any], Subscription | None]:
        """Validate, authorise and record one topic entry. Returns the `sub_ok` result and the
        new subscription (`None` when rejected or for the implicit `system` topic). Pure
        bookkeeping: upstream refs and bar leases are taken by `subscribe_upstream`. A refused
        `machines` entity leaves its internal §6.4 reason in `refusal_reason`."""
        ch = entry.get("ch") if isinstance(entry, dict) else entry
        self.refusal_reason = None
        try:
            return self._admit(entry, ch, snapshot, replay_session_id)
        except TopicError as exc:
            self.refusal_reason = exc.reason
            return _fail(ch, exc.code, exc.message, exc.field), None

    def _admit(
        self, entry: Any, ch: Any, snapshot: Any, replay_session_id: Any
    ) -> tuple[dict[str, Any], Subscription | None]:
        if isinstance(entry, dict) and set(entry) - {"ch", "opts"}:
            raise TopicError("invalid_options", "Unknown topic entry field.", "topics")
        topic = parse_topic(ch, instrument_known=self.services.instrument_known)
        fam = topic.family
        if fam.family == SYSTEM_TOPIC:  # §6.2: implicit and permanent - already attached
            return {"ch": SYSTEM_TOPIC, "ok": True, "sub_id": SYSTEM_TOPIC}, None
        opts = validate_options(fam, entry.get("opts") if isinstance(entry, dict) else None)
        rs = _replay_id(replay_session_id)
        if rs is not None and fam.private:
            raise TopicError("invalid_options", "Private topics cannot be replayed.", "ch")
        if not isinstance(snapshot, bool):
            raise TopicError("invalid_options", "snapshot must be a boolean.", "snapshot")
        if not snapshot and "from_seq" not in opts:
            raise TopicError("invalid_options", "snapshot false needs from_seq.", "from_seq")
        kind = topic.entity_kind
        entity = self._authorise_entity(topic.ch, kind) if kind is not None else None
        accounts = self._authorise(topic, opts) if entity is None else frozenset()
        forced = False
        effective = effective_options(topic, opts)
        if accounts:
            effective["exchange_account_ids"] = sorted(str(a) for a in accounts)
        if self.find(topic.ch, rs) is not None:
            raise TopicError("duplicate_subscription", "Already subscribed; use ctl to retune.")
        if self.at_capacity():
            raise TopicError("subscription_limit", "200 subscriptions reached.")
        sub = Subscription(
            f"s_{next(self._ids):02d}",
            topic,
            opts,
            effective,
            accounts,
            rs,
            snapshot_pending=snapshot,
            entity=entity,
            announced=False,
        )
        if not snapshot and not self._continuity(sub):
            sub.snapshot_pending = forced = True  # §7.6: continuity unproven -> snap anyway
        held: set[str] = set()
        for s in self.by_id.values():
            held |= s.symbols
        if len(held | sub.symbols) > MAX_SYMBOLS_PER_CONNECTION:
            raise TopicError("subscription_limit", "40 symbols per connection reached.")
        self._record(sub)
        result = {
            "ch": topic.ch,
            "ok": True,
            "sub_id": sub.sub_id,
            "snapshot_pending": sub.snapshot_pending,
            "effective": effective,
        }
        if forced:
            result["snapshot_forced"] = True
        return result, sub

    def _continuity(self, sub: Subscription) -> bool:
        source = self.services.snapshots
        if source is None:
            return False
        from_ts = sub.opts.get("from_ts_ms")
        return source.continuity(sub, from_ts if isinstance(from_ts, int) else None)

    def subscriptions_named(self, ch: str) -> list[Subscription]:
        return [self.by_id[sid] for sid in sorted(self._by_topic.get(ch, ()))]

    def revoke(self, sub: Subscription, reason: RevokedReason, now_ms: int) -> dict[str, Any]:
        """Drop one subscription and return its `revoked` frame (e.g. §7.5 resync loop)."""
        self._drop(sub)
        self._dropped([sub])
        return self._revoked(sub, reason, now_ms)

    def _authorise(self, topic: ParsedTopic, opts: Mapping[str, Any]) -> frozenset[uuid.UUID]:
        """Permission, then §6.2 silent narrowing. Raises `forbidden` / `account_scope_denied`."""
        fam = topic.family
        if fam.permission is None:  # pragma: no cover - only `system`, handled by the caller
            raise TopicError("forbidden", "Missing permission for this topic.")
        if isinstance(decide(self.principal, fam.permission), Deny):
            raise TopicError("forbidden", "Missing permission for this topic.")
        if not fam.account_scoped:
            return frozenset()
        requested = [uuid.UUID(a) for a in opts.get("exchange_account_ids") or ()]
        allowed = frozenset(a for a in requested if self._may_view(fam.permission, a))
        if not allowed:
            # One message for "absent", "not yours" and "does not exist": no account probing.
            raise TopicError("account_scope_denied", "None of the requested accounts are in scope.")
        return allowed

    def _authorise_entity(self, ch: str, kind: str) -> EntityScope:
        """§6.4 per-entity authorisation, read synchronously from the in-memory entry (SR-189).
        The code and its fixed message depend only on the kind and the caller (no oracle)."""
        registry = self.services.machines
        scope = registry.scope(ch) if registry is not None else None
        refusal = machine_refusal(self.principal, kind, scope)
        if refusal is not None:
            raise TopicError(refusal[0], _REFUSED[refusal[0]], reason=refusal[1])
        return scope or EntityScope()

    def _may_view(self, permission: Permission, account: uuid.UUID) -> bool:
        decision = decide(
            self.principal,
            permission,
            scope=Scope.GRANTED_ACCOUNTS,
            exchange_account_id=account,
        )
        return isinstance(decision, Allow)

    def _record(self, sub: Subscription) -> None:
        self.by_id[sub.sub_id] = sub
        self._by_topic.setdefault(sub.ch, set()).add(sub.sub_id)

    def _consumer(self, sub: Subscription) -> str:
        return f"{self.connection_id}/{sub.sub_id}"

    async def subscribe_upstream(self, sub: Subscription) -> dict[str, Any] | None:
        """Take what a subscription needs upstream, or refuse it (drop it, return the failure). A
        `bars.*` one first passes `_bars_refusal`; a `bars.*` or `footprint.*` spec is bounded
        (`_bar_spec`, SR-E12-03) wherever a builder could serve it, live or replay. Only a live
        public one takes anything, in order: for `bars.*`, once the set's `check` passes, a hold on
        its series (`ensure`: a restoring builder's closes reach it); the `BarBuilderSet` lease
        (`register` checks again; `user=` the authenticated principal id, never a client value);
        the upstream refs (`bars.*`: its symbol's trades). `_drop` releases what was taken, on a
        refusal, an `unsub`, a revocation (one during these awaits: #2896) or the socket's end."""
        refused = await self._upstream(sub)
        if refused is not None:  # what was queued of it meanwhile goes too (`on_drop`)
            self._dropped([sub])
        return refused

    async def _upstream(self, sub: Subscription) -> dict[str, Any] | None:
        family = sub.topic.family.family
        spec: BarSpec | None = None
        if family in {"bars", "footprint"}:
            refused = self._bars_refusal(sub) if family == "bars" else None
            # SR-E12-03 for live and replay alike, wherever a builder could serve the series.
            served = sub.replay_session_id is not None or self.services.bars is not None
            if refused is None and served:
                spec, refused = _bar_spec(sub)
            if refused is not None:
                self._drop(sub)
                return refused
        if sub.replay_session_id is not None or sub.topic.family.private:
            return None
        consumer = self._consumer(sub)
        try:
            bars = self.services.bars
            if spec is not None and bars is not None:
                symbol = sub.topic.symbol or ""
                if family == "bars" and self.services.series is not None:
                    bars.check(spec, symbol, user=str(self.principal.user_id))
                    sub.series_hold = await self.services.series.ensure(symbol, spec)
                await bars.register(spec, symbol, consumer, user=str(self.principal.user_id))
                sub.bar_lease = (spec.spec_hash, symbol)
            keys = _upstream_keys(sub)
            for key in keys:
                await self.services.upstream.acquire(key, consumer)
                sub.upstream = (*sub.upstream, key)
        except SpecCapExceeded:
            self._drop(sub)
            return _fail(sub.ch, "subscription_limit", "Too many distinct bar series.")
        except BarServiceStopping:
            self._drop(sub)
            return _fail(sub.ch, "internal_error", "The bar service is restarting; retry.")
        except BarsError:
            self._drop(sub)
            return _fail(sub.ch, "invalid_topic_format", "This bar series is not available.")
        return None

    def _bars_refusal(self, sub: Subscription) -> dict[str, Any] | None:
        """§6.1: `unknown_topic` while the bars feature is off, and `subscription_limit` past
        SR-E12-07's per-connection cap (live and replay `bars.*` count alike). `footprint.*`
        keeps §7.7 until #2197, but its spec is still bounded (`_bar_spec`)."""
        if self.services.bars_off:
            return _fail(sub.ch, "unknown_topic", "This topic is not available on this server.")
        held = sum(
            1 for s in self.by_id.values() if s is not sub and s.topic.family.family == "bars"
        )
        if held >= MAX_BARS_SUBSCRIPTIONS:
            return _fail(
                sub.ch,
                "subscription_limit",
                f"At most {MAX_BARS_SUBSCRIPTIONS} bars subscriptions per connection.",
            )
        return None

    # -- unsub / ctl ------------------------------------------------------------------------

    def unsubscribe(self, topic: str) -> bool:
        """Drop every subscription named `topic` (live and replay); False when none existed.
        `system` is permanent and never removed (§6.2)."""
        if topic == SYSTEM_TOPIC:
            return False
        ids = self._by_topic.get(topic)
        if not ids:
            return False
        subs = [self.by_id[sid] for sid in sorted(ids)]
        for sub in subs:
            self._drop(sub)
        self._dropped(subs)
        return True

    def _dropped(self, subs: list[Subscription]) -> None:
        if self.on_drop is not None:
            self.on_drop(subs)

    def _drop(self, sub: Subscription) -> None:
        """Bookkeeping only: each operation that calls it reports through `_dropped`, once."""
        sub.ended = True
        self.by_id.pop(sub.sub_id, None)
        ids = self._by_topic.get(sub.ch)
        if ids is not None:
            ids.discard(sub.sub_id)
            if not ids:
                del self._by_topic[sub.ch]
        consumer = self._consumer(sub)
        now = self.services.clock()
        hold, sub.series_hold = sub.series_hold, None
        if hold is not None:  # first: a lease release below can raise (#2735)
            # A lease never taken (refused, or the connection ended mid-subscribe): no grace.
            hold.release(grace=sub.bar_lease is not None)
        for key in sub.upstream:
            self.services.upstream.release(key, consumer, now)
        if sub.bar_lease is not None and self.services.bars is not None:
            self.services.bars.release(sub.bar_lease[0], sub.bar_lease[1], consumer)
        sub.upstream, sub.bar_lease = (), None

    def release_all(self) -> None:
        """Connection closed: release every upstream ref, bar lease and series hold, as in `_drop`.
        Each subscription is released under its own guard: one whose release raises (`BarsError`,
        for a lease another connection's failed `register` dropped) is logged and the
        subscriptions after it are still released, not left holding their leases for good."""
        subs = list(self.by_id.values())
        for sub in subs:
            try:
                self._drop(sub)
            except Exception:
                with contextlib.suppress(Exception):  # a failing logger must not stop the rest
                    _log().error(
                        "ws subscription release failed",
                        consumer=self._consumer(sub),
                        exc_info=True,
                    )
        self._dropped(subs)

    def ctl(self, ch: Any, body: Any) -> tuple[dict[str, Any], bool]:
        """§5.4: retune a live subscription. Returns (`effective`, resnapshot) or raises
        `TopicError` (`not_subscribed`, `invalid_options`; a non-null `ch` that is no topic name
        is the latter, #2572)."""
        if ch is not None and not is_topic_name(ch):
            raise TopicError("invalid_options", "ch must be a topic name.", "ch")
        ids = self._by_topic.get(ch) if isinstance(ch, str) else None
        if not ids:
            raise TopicError("not_subscribed", "No subscription for this topic.")
        sub = self.find(ch) or self.by_id[min(ids)]
        if not isinstance(body, dict) or not body:
            raise TopicError("invalid_options", "ctl needs at least one option.", "p")
        allowed = {**UNIVERSAL, **sub.topic.family.options}
        changes: dict[str, Any] = {}
        for key in sorted(body):
            if key == "paused" and isinstance(body[key], bool):
                changes[key] = body[key]
                continue
            if key in SCOPE_OPTIONS:  # scope is authorised at `sub` only; never widened here
                raise TopicError("invalid_options", f"'{key}' cannot be changed by ctl.", key)
            spec = allowed.get(key) if key in CTL_KEYS else None
            if spec is None:
                raise TopicError("invalid_options", f"Unknown ctl option '{str(key)[:40]}'.", key)
            changes[key] = spec.check(key, body[key])
        opts = {**sub.opts, **{k: v for k, v in changes.items() if k != "paused"}}
        effective = effective_options(sub.topic, opts)
        # #2517: a pause holds until a ctl lifts it (`opts` never holds it, so carry it over).
        # A delta suppressed while paused never took a sequence number, so a resume
        # re-snapshots like an identity change instead of losing that state silently.
        was_paused = sub.effective.get("paused") is True
        paused = changes.get("paused", was_paused)
        resnapshot = (was_paused and not paused) or any(
            k in IDENTITY_OPTIONS and sub.effective.get(k) != effective.get(k) for k in changes
        )
        if paused or "paused" in changes:
            effective["paused"] = paused
        if sub.accounts:
            effective["exchange_account_ids"] = sorted(str(a) for a in sub.accounts)
        sub.opts, sub.effective = opts, effective
        if resnapshot:
            # S3: the sequence continues (never reused); the gateway emits the `snap`. A reason
            # already pending (`initial`, an incident) says more than `reconfigure`, so it stays.
            if not sub.snapshot_pending:
                sub.pending_reason = "reconfigure"
            sub.snapshot_pending = True
            self._dropped([sub])  # its old stream is stale before `ctl_ok` (§8.4 Lanes)
        echoed = {
            k: v for k, v in effective.items() if k in changes or k in ("throttle_ms", "paused")
        }
        return echoed, resnapshot

    # -- live revocation (§9.5, S7) -----------------------------------------------------------

    def apply_snapshot(self, new: VersionedSnapshot, now_ms: int) -> list[dict[str, Any]] | None:
        """Swap in `new`; return one `permission_change` then a `revoked` per affected
        subscription. Lost permission or every account -> the subscription is removed; a partial
        scope loss narrows it in place (`removed_accounts`, `resubscribe_allowed: true`) and the
        rest of the connection continues untouched. SR-189: `None`, and nothing changes, when
        `new` is older than the applied snapshot (a read begun before a grant change)."""
        if new.version < self.version:
            return None
        self.principal, self.version = new.principal, new.version
        frames: list[dict[str, Any]] = [
            {"t": "permission_change", "ts": now_ms, "p": auth_ok_payload(new.principal)}
        ]
        affected: list[Subscription] = []
        for sub in sorted(self.by_id.values(), key=lambda s: (s.ch, s.sub_id)):
            frame = self._reevaluate(sub, now_ms)
            if frame is not None:
                frames.append(frame)
                affected.append(sub)
        self._dropped(affected)  # the discard comes first (§9.5)
        if self.on_drop is not None:  # flag on: then a narrowed subscription is re-pended
            for sub in affected:  # unless paused: its resume re-snapshots it (§5.4, §8.4 step 1)
                paused = sub.effective.get("paused") is True
                if sub.sub_id in self.by_id and not (sub.snapshot_pending or paused):
                    sub.snapshot_pending, sub.pending_reason = True, "reconfigure"
                    self.settling.append(sub)
        return frames

    def _reevaluate(self, sub: Subscription, now_ms: int) -> dict[str, Any] | None:
        if sub.topic.entity_kind is not None:
            return self._reevaluate_entity(sub, sub.topic.entity_kind, now_ms)
        permission = sub.topic.family.permission
        if permission is None:  # pragma: no cover - `system` is never a Subscription
            return None
        if isinstance(decide(self.principal, permission), Deny):
            self._drop(sub)
            return self._revoked(sub, "permission_revoked", now_ms)
        if not sub.accounts:
            return None
        kept = frozenset(a for a in sub.accounts if self._may_view(permission, a))
        removed = sub.accounts - kept
        if not removed:
            return None
        if not kept:
            self._drop(sub)
            return self._revoked(sub, "account_scope_changed", now_ms, removed, resubscribe=False)
        sub.accounts = kept
        sub.effective["exchange_account_ids"] = sorted(str(a) for a in kept)
        return self._revoked(sub, "account_scope_changed", now_ms, removed, resubscribe=True)

    def _reevaluate_entity(
        self, sub: Subscription, kind: str, now_ms: int
    ) -> dict[str, Any] | None:
        """§6.4 on a change: the kind's whole row, on the scope stored at `sub` (no lookup)."""
        entity = sub.entity or EntityScope()
        refusal = machine_refusal(self.principal, kind, entity)
        if refusal is None:
            return None
        self._drop(sub)
        if refusal[1] == "role":  # permission or role lost
            return self._revoked(sub, "permission_revoked", now_ms)
        perm = MACHINE_KINDS[kind].permission
        lost = frozenset(a for a in entity.accounts if perm is None or not self._may_view(perm, a))
        return self._revoked(sub, "account_scope_changed", now_ms, lost)

    def _revoked(
        self,
        sub: Subscription,
        reason: RevokedReason,
        now_ms: int,
        removed: frozenset[uuid.UUID] = frozenset(),
        *,
        resubscribe: bool = False,
    ) -> dict[str, Any]:
        ws_revoked_total.labels(reason=reason).inc()
        return revoked_frame(
            sub.ch,
            reason,
            now_ms=now_ms,
            removed_accounts=sorted(str(a) for a in removed),
            resubscribe_allowed=resubscribe,
        )


@dataclass(frozen=True, slots=True)
class _AuditRow:
    """One WS audit write, held until every socket of a change has its frames (#2824)."""

    sink: AuditSink
    action: str
    fields: dict[str, Any]


def _log_abandoned(
    lost: list[_AuditRow],
    cause: Literal["cancelled", "writer_down"],
    in_flight: _AuditRow | None = None,
) -> None:
    """`ws audit rows abandoned`: `rows` counts the `lost` rows, never handed to the writer, and
    `in_flight` names the row a cancellation interrupted, which still lands if it already held
    the writer's lock. `actor_user_ids` names the users of both, the first
    `_ABANDONED_USERS_LOGGED` (`users` counts them): ids, never a row's content (C-12.6). Both
    are counted in `cv_ws_audit_failures_total`, as `cancelled` or, for `writer_down`, `abandoned`
    (SR-E17-04). Nothing may replace the cancellation, so a failing logger is ignored."""
    with contextlib.suppress(Exception):
        n = len(lost) + (0 if in_flight is None else 1)
        count_audit_failure(n, "abandoned" if cause == "writer_down" else "cancelled")
        users = list(dict.fromkeys(r.fields.get("actor_user_id") for r in [in_flight, *lost] if r))
        _log().warning(
            "ws audit rows abandoned",
            rows=len(lost),
            cause=cause,
            in_flight=None if in_flight is None else in_flight.fields.get("object_id"),
            actor_user_ids=users[:_ABANDONED_USERS_LOGGED],
            users=len(users),
        )


class ConnectionRegistry:
    """Live authenticated sockets; implements `PermissionChangeNotifier`.

    The WS gateway registers a `ConnectionAuthz` plus a `send` coroutine at `auth_ok`, routes
    `sub`/`unsub`/`ctl` through this module and unregisters on close.
    """

    def __init__(
        self,
        resolve: Callable[[uuid.UUID], Awaitable[PrincipalSnapshot]],
        clock_ms: Callable[[], int],
        services: SubscriptionServices | None = None,
    ) -> None:
        self._resolve = resolve
        self._clock_ms = clock_ms
        self.services = services if services is not None else SubscriptionServices()
        self._conns: dict[uuid.UUID, list[tuple[ConnectionAuthz, Any, Any]]] = {}
        self._closers: dict[int, Closer] = {}
        self.send_timeout_s = FANOUT_SEND_TIMEOUT_S
        self.audit_timeout_s = FANOUT_AUDIT_TIMEOUT_S
        self.audit_max_failures = FANOUT_AUDIT_MAX_FAILURES
        #: SR-189: one version source for every snapshot; `_changed_at`: the latest change's.
        self._versions = itertools.count(1)
        self._changed_at = 0

    def register(
        self, authz: ConnectionAuthz, send: Any, close: Any = None, closer: Closer | None = None
    ) -> None:
        """`close` (async, no args) evicts a stalled socket; `closer(bye, code)` closes it with
        a specific `bye` (user disabled -> 4403)."""
        self._conns.setdefault(authz.principal.user_id, []).append((authz, send, close))
        if closer is not None:
            self._closers[id(authz)] = closer

    def unregister(self, authz: ConnectionAuthz) -> None:
        uid = authz.principal.user_id
        remaining = [e for e in self._conns.get(uid, []) if e[0] is not authz]
        if remaining:
            self._conns[uid] = remaining
        else:
            self._conns.pop(uid, None)
        self._closers.pop(id(authz), None)
        authz.release_all()

    async def resolve(self, user_id: uuid.UUID) -> VersionedSnapshot:
        """The principal, stamped with a version taken before the read starts (SR-189)."""
        version = next(self._versions)
        return VersionedSnapshot(await self._resolve(user_id), version)

    async def apply(
        self, authz: ConnectionAuthz, snap: VersionedSnapshot, now_ms: int, *, event: SnapshotEvent
    ) -> list[dict[str, Any]]:
        """`authz.apply_snapshot`. An older snapshot is refused, counted and audited (best
        effort, like every WS audit write) and yields no frames (SR-189)."""
        frames, refused = self._swap(authz, snap, now_ms, event)
        await self._write_rows(refused)
        return frames

    def _swap(
        self, authz: ConnectionAuthz, snap: VersionedSnapshot, now_ms: int, event: SnapshotEvent
    ) -> tuple[list[dict[str, Any]], list[_AuditRow]]:
        """`apply` without its I/O: the frames, or none and the counted refusal's audit row."""
        frames = authz.apply_snapshot(snap, now_ms)
        if frames is not None:
            return frames, []
        cv_ws_permission_snapshots_refused_total.labels(event=event).inc()
        if (audit := authz.services.audit) is None:
            return [], []
        versions = {"applied_version": authz.version, "refused_version": snap.version}
        fields = {
            "actor_label": "ws",
            "actor_user_id": authz.principal.user_id,
            "object_kind": "ws_connection",
            "object_id": authz.connection_id,
            "outcome": AuditOutcome.DENIED,
            "severity": Severity.WARNING,
            "reason": "stale",
            "after_state": {"event": event, **versions},
        }
        return [], [_AuditRow(audit, "ws.permission_snapshot.refused", fields)]

    async def recheck(self, authz: ConnectionAuthz) -> None:
        """SR-189, right after `register` and before `auth_ok`: a change (any user's; one extra
        read at worst) begun after `authz`'s read may have fanned out before it was registered."""
        if authz.version >= self._changed_at:
            return
        snap = await self.resolve(authz.principal.user_id)
        await self.apply(authz, snap, self._clock_ms(), event="handshake")

    async def roles_changed(self, user_id: uuid.UUID) -> None:
        """Role / permission / account-grant change: push `permission_change` and the `revoked`
        frames to every live socket of `user_id`, then write their audit rows."""
        rows: list[_AuditRow] = []
        try:
            await self._fan_out(user_id, rows)
        finally:  # also when the fan-out raised or was cancelled (see `_write_rows`)
            await self._write_rows(rows)

    async def _fan_out(self, user_id: uuid.UUID, rows: list[_AuditRow]) -> None:
        """Swap `user_id`'s new snapshot into every live socket, then send each its frames. Each
        socket's audit rows join `rows` at its swap, before any I/O, and the caller writes them
        after the sends, so socket k's revocation never waits for the audit writes of sockets
        1..k-1 and a later step that raises or is cancelled cannot drop them (#2824)."""
        # SR-189: before the early return, so a mid-handshake socket's `recheck` sees it.
        self._changed_at = version = next(self._versions)
        entries = list(self._conns.get(user_id, ()))
        if not entries:
            return
        snap = VersionedSnapshot(await self._resolve(user_id), version)
        # Every socket's subscriptions are dropped/narrowed synchronously here, before any I/O.
        swapped = [self._swap_or_evict(e[0], snap, rows) for e in entries]
        for (_authz, _send, close), frames in zip(entries, swapped, strict=True):
            if frames is None:  # evicted at its swap: closed before any send, so on every exit,
                await self._close_evicted(close)  # as `close` (`_Connection.evict`) never suspends
        for (authz, send, close), frames in zip(entries, swapped, strict=True):
            if frames is None:
                continue
            try:
                async with asyncio.timeout(self.send_timeout_s):
                    for frame in frames:
                        await send(frame)
            except (TimeoutError, OSError, RuntimeError):
                # C-2.18: a stalled/broken client must not block the change or other sockets.
                self.unregister(authz)
                await self._close_evicted(close)
            else:
                await self.settle(authz, close)  # the snapshots that follow them (§9.5)

    async def settle(self, authz: ConnectionAuthz, close: Any) -> None:
        """Once a change's frames are queued: `authz.on_settle` with what it re-pended (§9.5).
        One that raises evicts its socket like a stalled send; the fan-out goes on (C-2.18)."""
        subs, authz.settling = authz.settling, []
        try:
            if authz.on_settle is not None:
                authz.on_settle(subs)
        except Exception:
            with contextlib.suppress(Exception):  # a failing logger must not skip the eviction
                _log().error("ws settle failed", connection_id=authz.connection_id, exc_info=True)
            self.unregister(authz)
            await self._close_evicted(close)

    def _swap_or_evict(
        self, authz: ConnectionAuthz, snap: VersionedSnapshot, rows: list[_AuditRow]
    ) -> list[dict[str, Any]] | None:
        """`_swap` for one socket of a fan-out, appending its audit rows to `rows`.

        A swap that raises (`_drop` -> `BarsError` for a bar lease that another connection's
        failed build dropped, the case `release_all` guards) leaves the socket half
        re-evaluated, possibly still holding a withdrawn subscription. So it is evicted the way
        a stalled socket is: unregistered and released here, then closed before any send, and
        its client re-authenticates against the new snapshot. The other sockets still get
        their frames and rows. Returns the frames, or `None` for an evicted socket."""
        try:
            frames, refused = self._swap(authz, snap, self._clock_ms(), "grant_change")
        except Exception:
            with contextlib.suppress(Exception):  # a failing logger must not skip the eviction
                _log().error(
                    "ws permission swap failed; socket evicted",
                    connection_id=authz.connection_id,
                    exc_info=True,
                )
            self.unregister(authz)
            return None
        rows.extend(refused + _revocation_rows(authz, frames))
        return frames

    async def _close_evicted(self, close: Any) -> None:
        """Close a socket already dropped from the registry; bounded, and a failure is ignored."""
        if close is not None:
            with contextlib.suppress(Exception):
                async with asyncio.timeout(self.send_timeout_s):
                    await close()

    async def _write_rows(self, rows: list[_AuditRow]) -> None:
        """Write `rows` in order, one at a time, each under `audit_timeout_s` (#2824).

        Best effort, like every WS audit write (threat model WS-R04): a row that raises or times
        out is logged and the next one is still written; only a cancellation leaves here. One at
        a time on purpose: `AuditWriter` appends each row under one lock with an fsync, so
        concurrent rows would only queue on that lock, where a row's own bound runs out while it
        waits and a cancelled wait appends nothing. Bounded as a whole too: once
        `audit_max_failures` rows in a row have raised or timed out, the rest are abandoned, so
        a stalled WAL costs that many bounds and log lines, not one per row, and a writer only
        slow for that long loses them as well (threat model WS-R04 as built, WS-D15).

        The fan-out calls this in a `finally`: a change that raised or was cancelled still writes
        the rows of the revocations it already made before that propagates, as the old per-socket
        writes did for the sockets done before the failure. So a cancellation that lands before
        the writes is held only for them, never swallowed, and one that lands during them ends
        them at once. Not a shielded task: it would outlive its caller with no owner to stop or
        drain it (C-2.18). Abandoned rows are logged with a count."""
        failed = 0
        for tried, row in enumerate(rows, 1):
            try:
                async with asyncio.timeout(self.audit_timeout_s):
                    await row.sink.emit(row.action, **row.fields)
            except asyncio.CancelledError:
                _log_abandoned(rows[tried:], "cancelled", in_flight=row)
                raise
            except Exception:
                failed += 1
                count_audit_failure()  # SR-E17-04: `timeout` or `error`
                with contextlib.suppress(Exception):  # a failing logger must not stop the rows
                    # "Not confirmed": a timed-out row may still land (the writer shields it).
                    _log().warning(
                        "ws audit not confirmed",
                        action=row.action,
                        object_id=row.fields.get("object_id"),
                        actor_user_id=row.fields.get("actor_user_id"),
                        exc_info=True,
                    )
                if failed >= self.audit_max_failures:
                    _log_abandoned(rows[tried:], "writer_down")
                    return
            else:
                failed = 0

    async def audit_revoked(self, authz: ConnectionAuthz, frames: list[dict[str, Any]]) -> None:
        """The `ws.subscription.revoked` rows of `revoked` frames made outside a change, a resync
        loop's (§7.5; SR-187, #2174), through the same bounded writer as a fan-out's."""
        await self._write_rows(_revocation_rows(authz, frames))

    async def grants_changed(self, user_id: uuid.UUID) -> None:
        """Account-grant change: same re-evaluation path as a role change."""
        await self.roles_changed(user_id)

    async def kill_switch_changed(self) -> None:
        """§9.5: kill-switch transitions re-evaluate every connected user. The audit rows wait
        until every user's sockets have their frames, and are written on any exit (#2824)."""
        self._changed_at = next(self._versions)  # SR-189: also for a socket mid-handshake
        rows: list[_AuditRow] = []
        try:
            for user_id in list(self._conns):
                await self._fan_out(user_id, rows)
        finally:
            await self._write_rows(rows)

    async def user_disabled(self, user_id: uuid.UUID) -> int:
        """§9.5: a disabled user gets `bye user_disabled` + close 4403 on every socket."""
        entries = self._conns.pop(user_id, [])
        for authz, _send, close in entries:
            closer = self._closers.pop(id(authz), None)
            authz.release_all()
            ws_revoked_total.labels(reason="user_disabled").inc()
            with contextlib.suppress(Exception):
                async with asyncio.timeout(self.send_timeout_s):
                    if closer is not None:
                        await closer(user_disabled_bye(self._clock_ms()), 4403)
                    elif close is not None:
                        await close()
        return len(entries)


Send = Any  # async (frame: dict) -> None


def sub_shape_error(body: Any) -> TopicError | None:
    """#2396, #2399: what breaks a `sub` frame's §13.5 shape, refused whole (orchestrator
    decision, 2026-10-15): a payload that is not an object or has an unknown key, `topics` that
    is not a non-empty array of at most `MAX_TOPICS_PER_SUB` entries (`too_many_topics`, SR-192,
    #2292), an entry that is neither an object nor a string, or a `ch` that is not a topic name.
    The first that applies, in that order (entry by entry for the last two), names the code and
    the `field`, which is built here and never echoes client input. The length is checked before
    any entry is read, so that check costs the same however long the array is."""
    if not isinstance(body, dict):
        return TopicError("invalid_options", "sub needs an object payload.", "p")
    if not set(body) <= SUB_KEYS:
        return TopicError("invalid_options", "Unknown sub field.", "p")
    topics = body.get("topics")
    if not isinstance(topics, list) or not topics:
        return TopicError("invalid_options", "topics must be a non-empty array.", "topics")
    if len(topics) > MAX_TOPICS_PER_SUB:
        message = f"At most {MAX_TOPICS_PER_SUB} topics in one sub; split the request."
        return TopicError("too_many_topics", message, "topics")
    for i, entry in enumerate(topics):
        if isinstance(entry, str):
            if not is_topic_name(entry):
                return TopicError("invalid_options", "Not a topic name.", f"topics[{i}]")
        elif not isinstance(entry, dict):
            return TopicError("invalid_options", "A topic is an object or a name.", f"topics[{i}]")
        elif not is_topic_name(entry.get("ch")):
            return TopicError("invalid_options", "Missing or malformed ch.", f"topics[{i}].ch")
    return None


def unsub_shape_error(body: Any) -> TopicError | None:
    """#2572, #2875: what breaks an `unsub` frame's §13.5 shape, refused whole like a `sub`: a
    payload that is not an object or has an unknown key, `topics` that is not a non-empty array of
    at most `MAX_TOPICS_PER_SUB` entries, or an entry that is not a topic name. The first that
    applies, in that order, names the `field`, which is built here and never echoes client
    input. The length is checked before any entry is read, so that check costs the same
    however long the array is."""
    if not isinstance(body, dict):
        return TopicError("invalid_options", "unsub needs an object payload.", "p")
    if not set(body) <= UNSUB_KEYS:
        return TopicError("invalid_options", "Unknown unsub field.", "p")
    topics = body.get("topics")
    if not isinstance(topics, list) or not topics:
        return TopicError("invalid_options", "topics must be a non-empty array.", "topics")
    if len(topics) > MAX_TOPICS_PER_SUB:
        message = f"At most {MAX_TOPICS_PER_SUB} topics in one unsub."
        return TopicError("invalid_options", message, "topics")
    for i, ch in enumerate(topics):
        if not is_topic_name(ch):
            return TopicError("invalid_options", "Not a topic name.", f"topics[{i}]")
    return None


def _frame_id(frame: Mapping[str, Any]) -> str | None:
    """The request `id` a reply echoes: a string, as the gateway has dropped any other (§13.1)."""
    raw_id = frame.get("id")
    return raw_id if isinstance(raw_id, str) else None


async def handle_sub(
    authz: ConnectionAuthz, frame: dict[str, Any], send: Send, *, now_ms: int | None = None
) -> None:
    """Gateway hook for a `sub` frame: exactly one result per topic, in request order (S1);
    one bad topic never fails the batch (§5.2). A frame whose shape breaks §13.5 is refused
    whole instead: one `err`, no `sub_ok`, nothing subscribed and no strike (#2396, #2399), a
    `topics` array over `MAX_TOPICS_PER_SUB` included (`too_many_topics`, SR-192, #2292). The
    refusals the audit keeps are written as ONE record for the frame (`_audit_denials`).

    #2831: the new subscriptions are announced only once the `sub_ok` is queued, so no hub
    flush or resnapshot during the awaits below can send a `snap` ahead of it; the gateway's
    flush then sends it. A refused topic is dropped unannounced. One left unannounced by a
    raise or a cancellation never gets a `snap`: the connection ends (a raise closes it 1011)
    and its teardown releases the subscription. Its private ones are audited next (SR-186)."""
    body: Any = frame.get("p")  # a dict once `sub_shape_error` passes it
    fid = _frame_id(frame)
    shape = sub_shape_error(body)
    if shape is not None:
        await send(build_ws_error(shape.code, id=fid, message=shape.message, field=shape.field))
        return
    results: list[dict[str, Any]] = []
    admitted: list[Subscription] = []
    denials: list[tuple[str, str, str]] = []  # (object_id, code, reason) of each kept refusal
    snapshot = body.get("snapshot", True)
    replay = body.get("replay_session_id")
    try:
        for entry in body["topics"]:  # at most `MAX_TOPICS_PER_SUB`, by the shape
            ch: str = entry["ch"] if isinstance(entry, dict) else entry  # a topic name, by shape
            result, sub = authz.admit(entry, snapshot=snapshot, replay_session_id=replay)
            why = authz.refusal_reason  # a refused entity's internal reason; read before any await
            if sub is not None:
                result = await authz.subscribe_upstream(sub) or result
                if result["ok"]:
                    admitted.append(sub)
            results.append(result)
            _observe(ch, result)
            if not result["ok"]:
                code = result["error"]["code"]
                if _audited(ch, code):
                    denials.append(_denial(ch, code, why))
    finally:  # a raise or a cancellation mid-loop still records the refusals before it (C-2.9)
        await _audit_denials(authz, denials)
    cv_ws_client_topics_depth.observe(len(authz.by_id))
    out: dict[str, Any] = {"t": "sub_ok", "p": {"results": results}}
    if fid is not None:
        out["id"] = fid
    if now_ms is not None:
        out["ts"] = now_ms
    await send(out)
    for sub in admitted:  # with no await since `send` queued the reply
        sub.announced = True
    await _audit_grants(authz, admitted)  # after the reply is queued, never ahead of it


def handle_unsub(authz: ConnectionAuthz, frame: dict[str, Any], now_ms: int) -> dict[str, Any]:
    """§5.3 `unsub` -> `unsub_ok`: idempotent. Unknown/already-removed -> `ok: true, noop: true`;
    `system` is permanent -> `ok: false` and stays attached. A frame whose shape breaks §13.5 is
    refused whole instead: one `err`, nothing unsubscribed and no strike (#2572), a `topics` array
    over `MAX_TOPICS_PER_SUB` included (#2875)."""
    fid = _frame_id(frame)
    body: Any = frame.get("p")  # a dict once `unsub_shape_error` passes it
    shape = unsub_shape_error(body)
    if shape is not None:
        return build_ws_error(shape.code, id=fid, message=shape.message, field=shape.field)
    results: list[dict[str, Any]] = []
    for ch in body["topics"]:  # topic names, by the shape
        if ch == SYSTEM_TOPIC:
            results.append({"ch": ch, "ok": False})
        elif authz.unsubscribe(ch):
            results.append({"ch": ch, "ok": True})
        else:
            results.append({"ch": ch, "ok": True, "noop": True})
    cv_ws_client_topics_depth.observe(len(authz.by_id))
    out: dict[str, Any] = {"t": "unsub_ok", "ts": now_ms, "p": {"results": results}}
    if fid is not None:
        out["id"] = fid
    return out


def handle_ctl(authz: ConnectionAuthz, frame: dict[str, Any], now_ms: int) -> dict[str, Any]:
    """§5.4 `ctl` -> `ctl_ok` (or a topic-scoped `err`, which echoes `ch` only if it is a topic
    name: the envelope `ch` is one, §13.1)."""
    fid = _frame_id(frame)
    ch = frame.get("ch")
    try:
        effective, resnapshot = authz.ctl(ch, frame.get("p"))
    except TopicError as exc:
        return build_ws_error(
            exc.code,
            id=fid,
            ch=ch if is_topic_name(ch) else None,
            message=exc.message,
            field=exc.field,
        )
    p: dict[str, Any] = {"effective": effective}
    if resnapshot:
        p["resnapshot"] = True
    out: dict[str, Any] = {"t": "ctl_ok", "ch": ch, "ts": now_ms, "p": p}
    if fid is not None:
        out["id"] = fid
    return out


def _observe(ch: str, result: Mapping[str, Any]) -> None:
    fam = topic_family(ch)
    label = fam if fam in FAMILIES else "unknown"
    outcome = "ok" if result["ok"] else str(result["error"]["code"])
    cv_ws_subscribe_total.labels(topic=label, result=outcome).inc()


_AUDITED_DENIALS: Final = frozenset({"forbidden", "account_scope_denied"})


def _audited(ch: str, code: str) -> bool:
    """A refusal `ws.subscribe.denied` keeps: every authorisation denial, plus any rejected
    private-topic attempt on a well-formed topic name (confidential; a malformed `sub` is refused
    whole before any topic is read, #2396)."""
    fam = FAMILIES.get(topic_family(ch))
    return code in _AUDITED_DENIALS or (fam is not None and fam.private)


def _denial(ch: str, code: str, why: str | None) -> tuple[str, str, str]:
    """The `object_id`, code and `reason` of one kept refusal (§6.4): a `machines` row names the
    full `ch` (a topic name, at most 120 characters) and, when its entity was refused, puts the
    internal reason `why` in `reason`; any other row names the family, never the name the client
    sent, and gives its code."""
    family = topic_family(ch)
    return (ch if family == "machines" else family[:40]), code, why or code


async def _emit_bounded(audit: AuditSink, action: str, **row: Any) -> None:
    """One record of a `sub` frame, waited for at most `FANOUT_AUDIT_TIMEOUT_S` (SR-E17-04)."""
    async with asyncio.timeout(FANOUT_AUDIT_TIMEOUT_S):
        await audit.emit(action, **row)


async def _audit_denials(authz: ConnectionAuthz, denials: list[tuple[str, str, str]]) -> None:
    """`ws.subscribe.denied`: ONE record for the refusals `_audited` keeps in a `sub` frame,
    never one per entry (SR-192, #2292), written in `handle_sub`'s `finally`, so a frame that
    raises or is cancelled part way still records those before the fault. Its `object_id` and
    `reason` are the first one's, so a frame with one writes the row that refusal writes alone.
    With more, `after_state` holds the `count` of them all, every code among them (`codes`,
    sorted) and the `[object_id, reason]` of the first `MAX_DENIALS_LISTED` in request order
    (`refusals`). An internal reason goes only in `reason` and `after_state`, which the non-Owner
    projection drops (SR-067), so no other field varies with it (the non-Owner projection is
    being narrowed by E42-T02 F9). Best effort, bounded at `FANOUT_AUDIT_TIMEOUT_S`: a record
    not confirmed is logged and counted, and so is a cancellation, which still propagates."""
    audit = authz.services.audit
    if audit is None or not denials:
        return
    object_id, _, reason = denials[0]
    detail: dict[str, Any] = {}
    if len(denials) > 1:
        detail["after_state"] = {
            "count": len(denials),
            "codes": sorted({c for _, c, _ in denials}),
            "refusals": [[o, r] for o, _, r in denials[:MAX_DENIALS_LISTED]],
        }
    try:
        await _emit_bounded(
            audit,
            "ws.subscribe.denied",
            actor_label="ws",
            actor_user_id=authz.principal.user_id,
            object_kind="ws_topic",
            object_id=object_id,
            outcome=AuditOutcome.DENIED,
            severity=Severity.WARNING,
            reason=reason,
            **detail,
        )
    except Exception:
        count_audit_failure()  # SR-E17-04: `timeout` (it may still land) or `error`
        _log().warning(
            "ws subscribe-denied audit not confirmed",
            connection_id=authz.connection_id,
            actor_user_id=authz.principal.user_id,
            exc_info=True,
        )
    except asyncio.CancelledError:
        count_audit_failure()  # lost unless its append had begun; the cancel still propagates
        raise


#: §6.4: a `machines` revocation's internal reason. `_reevaluate_entity` revokes with
#: `permission_revoked` exactly when the row refuses on `role`; otherwise the subscription held
#: its entity at `sub`, so the refusal is `foreign`. (`evicted` comes with entry removal.)
_MACHINE_REVOKED: Final = {"permission_revoked": "role", "account_scope_changed": "foreign"}


def _revocation_rows(authz: ConnectionAuthz, frames: list[dict[str, Any]]) -> list[_AuditRow]:
    """`ws.subscription.revoked`: one row per `revoked` frame, in frame order (WS-R02). A
    `machines` row names the full `ch` and its internal §6.4 reason, in `reason` only (SR-067),
    as a refusal's row does."""
    audit = authz.services.audit
    if audit is None:
        return []
    rows: list[_AuditRow] = []
    for f in frames:
        if f["t"] != "revoked":
            continue
        ch, reason = str(f["ch"]), f["p"]["reason"]
        machines = topic_family(ch) == "machines"
        rows.append(
            _AuditRow(
                audit,
                "ws.subscription.revoked",
                {
                    "actor_label": "ws",
                    "actor_user_id": authz.principal.user_id,
                    "object_kind": "ws_topic",
                    "object_id": ch if machines else ch[:40],
                    "reason": _MACHINE_REVOKED.get(reason, reason) if machines else reason,
                    "after_state": {"removed_accounts": f["p"].get("removed_accounts", [])},
                },
            )
        )
    return rows


async def _audit_grants(authz: ConnectionAuthz, subs: list[Subscription]) -> None:
    """`ws.subscribe.granted` (SR-186, WS-R01): ONE record for the private-topic subscriptions a
    `sub` frame made, never one per topic (as SR-192, #2292, makes the denial record). Its
    `object_id` is the connection, and `after_state` holds their `count` and the `ch` and account
    ids of the first `MAX_GRANTS_LISTED` in request order (`subscriptions`). Written once the
    `sub_ok` is queued, best effort (threat model WS-R04) and bounded at `FANOUT_AUDIT_TIMEOUT_S`:
    a row not confirmed is logged and counted, and so is a cancellation, which still propagates."""
    audit = authz.services.audit
    private = [s for s in subs if s.topic.family.private]
    if audit is None or not private:
        return
    listed = [[s.ch, sorted(str(a) for a in s.accounts)] for s in private[:MAX_GRANTS_LISTED]]
    try:
        await _emit_bounded(
            audit,
            "ws.subscribe.granted",
            actor_label="ws",
            actor_user_id=authz.principal.user_id,
            object_kind="ws_connection",
            object_id=authz.connection_id,
            outcome=AuditOutcome.SUCCESS,
            severity=Severity.INFO,
            after_state={"count": len(private), "subscriptions": listed},
            request_id=current_request_id(),
        )
    except asyncio.CancelledError:
        count_audit_failure()
        raise
    except Exception:
        count_audit_failure()  # `timeout` (it may still land) or `error`
        _log().warning(
            "ws subscribe-granted audit not confirmed",
            connection_id=authz.connection_id,
            exc_info=True,
        )


def close_connection(registry: ConnectionRegistry, authz: ConnectionAuthz) -> None:
    registry.unregister(authz)
