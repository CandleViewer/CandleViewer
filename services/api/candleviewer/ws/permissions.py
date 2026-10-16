"""WS authorisation + subscriptions (E09-T03, E17-S02; `23-ws-protocol.md` §4.3, §5, §6, §9.5).

- `auth_ok_payload`: identity, roles, resolved permissions, account scope.
- `check_subscribe`: per-family permission check against the §6.3 matrix (fail-closed), backed by
  the declarative registry in `topics.FAMILIES`. Every decision is `auth.scopes.decide` (E09's
  RBAC service) - never a local copy of the rules.
- `ConnectionAuthz`: per-connection subscription manager. `sub` (partial success, results in
  request order, clamped `effective`), idempotent `unsub`, `ctl` (retune / resnapshot), the §16.2
  limits and §6.2 silent account-scope narrowing. `apply_snapshot` re-evaluates every live
  subscription after a role/grant change and returns the `revoked` frames (§9.5, S7).
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
from candleviewer.bars.spec import check_param_bounds, from_wire
from candleviewer.observability.metrics import Counter, Histogram
from candleviewer.ws.errors import build_ws_error
from candleviewer.ws.limits import (
    FANOUT_SEND_TIMEOUT_S,
    MAX_BARS_SUBSCRIPTIONS,
    MAX_SUBSCRIPTIONS,
    MAX_SYMBOLS_PER_CONNECTION,
    MAX_TOPICS_PER_SUB,
)
from candleviewer.ws.machines import MachineStateRegistry
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


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class BarLeases(Protocol):
    """`BarBuilderSet` lease surface (E12-T03). `user` is ALWAYS the authenticated principal."""

    async def register(
        self, spec: BarSpec, symbol: str, consumer: str, user: str | None = None
    ) -> None: ...

    def release(self, spec_hash: str, symbol: str, consumer: str) -> None: ...


class AuditSink(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


@dataclass
class SubscriptionServices:
    """Process-wide collaborators shared by every connection (injected; never a global)."""

    upstream: UpstreamRefs = field(default_factory=UpstreamRefs)
    bars: BarLeases | None = None
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
    machines: MachineStateRegistry | None = None


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
    #: §7.4 reason the pending `snap` will carry (E17-S03).
    pending_reason: SnapReason = "initial"
    #: §6.4 `machines`: the entity's scope, read from its entry at `sub`, so every RBAC change
    #: re-checks it without a lookup.
    entity: EntityScope | None = None
    #: #2831: whether its `sub_ok` is queued; no `snap` goes out before it (§7.1). `_admit`
    #: records it False and `handle_sub` sets it once that reply is queued. It holds the `snap`
    #: only: a `d` for a §7.6 continuity attach can still precede `sub_ok` (#2909).
    announced: bool = True
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
        bookkeeping: upstream refs and bar leases are taken by `subscribe_upstream`."""
        ch = entry.get("ch") if isinstance(entry, dict) else entry
        try:
            return self._admit(entry, ch, snapshot, replay_session_id)
        except TopicError as exc:
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
            raise TopicError(refusal[0], _REFUSED[refusal[0]])
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
        """Take the shared upstream refs (live public topics) and, for live bars/footprint, the
        `BarBuilderSet` lease with `user=` the authenticated principal id - never a client
        value. Returns a failure result (and drops the subscription) on refusal."""
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
        for sid in list(ids):
            self._drop(self.by_id[sid])
        return True

    def _drop(self, sub: Subscription) -> None:
        self.by_id.pop(sub.sub_id, None)
        ids = self._by_topic.get(sub.ch)
        if ids is not None:
            ids.discard(sub.sub_id)
            if not ids:
                del self._by_topic[sub.ch]
        consumer = self._consumer(sub)
        now = self.services.clock()
        for key in sub.upstream:
            self.services.upstream.release(key, consumer, now)
        if sub.bar_lease is not None and self.services.bars is not None:
            self.services.bars.release(sub.bar_lease[0], sub.bar_lease[1], consumer)
        sub.upstream, sub.bar_lease = (), None

    def release_all(self) -> None:
        """Connection closed: release every upstream ref / bar lease (the 30 s grace applies).
        Each subscription is released under its own guard: one whose release raises (`BarsError`,
        for a lease another connection's failed `register` dropped) is logged and the
        subscriptions after it are still released, not left holding their leases for good."""
        for sub in list(self.by_id.values()):
            try:
                self._drop(sub)
            except Exception:
                _log().error(
                    "ws subscription release failed", consumer=self._consumer(sub), exc_info=True
                )

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
        for sub in sorted(self.by_id.values(), key=lambda s: (s.ch, s.sub_id)):
            frame = self._reevaluate(sub, now_ms)
            if frame is not None:
                frames.append(frame)
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
        frames = authz.apply_snapshot(snap, now_ms)
        if frames is not None:
            return frames
        cv_ws_permission_snapshots_refused_total.labels(event=event).inc()
        versions = {"applied_version": authz.version, "refused_version": snap.version}
        if (audit := authz.services.audit) is not None:
            try:
                await audit.emit(
                    "ws.permission_snapshot.refused",
                    actor_label="ws",
                    actor_user_id=authz.principal.user_id,
                    object_kind="ws_connection",
                    object_id=authz.connection_id,
                    outcome=AuditOutcome.DENIED,
                    severity=Severity.WARNING,
                    reason="stale",
                    after_state={"event": event, **versions},
                )
            except Exception:
                _log().warning("ws refused-snapshot audit not written", exc_info=True)
        return []

    async def recheck(self, authz: ConnectionAuthz) -> None:
        """SR-189, right after `register` and before `auth_ok`: a change (any user's; one extra
        read at worst) begun after `authz`'s read may have fanned out before it was registered."""
        if authz.version >= self._changed_at:
            return
        snap = await self.resolve(authz.principal.user_id)
        await self.apply(authz, snap, self._clock_ms(), event="handshake")

    async def roles_changed(self, user_id: uuid.UUID) -> None:
        """Role / permission / account-grant change: push `permission_change` and the `revoked`
        frames to every live socket of `user_id`."""
        # SR-189: before the early return, so a mid-handshake socket's `recheck` sees it.
        self._changed_at = version = next(self._versions)
        entries = list(self._conns.get(user_id, ()))
        if not entries:
            return
        snap = VersionedSnapshot(await self._resolve(user_id), version)
        for authz, send, close in entries:
            # Subscriptions are dropped/narrowed synchronously here, before any I/O.
            frames = await self.apply(authz, snap, self._clock_ms(), event="grant_change")
            try:
                async with asyncio.timeout(self.send_timeout_s):
                    for frame in frames:
                        await send(frame)
            except (TimeoutError, OSError, RuntimeError):
                # C-2.18: a stalled/broken client must not block the change or other sockets.
                self.unregister(authz)
                if close is not None:
                    with contextlib.suppress(Exception):
                        async with asyncio.timeout(self.send_timeout_s):
                            await close()
            await _audit_revocations(authz, frames)

    async def grants_changed(self, user_id: uuid.UUID) -> None:
        """Account-grant change: same re-evaluation path as a role change."""
        await self.roles_changed(user_id)

    async def kill_switch_changed(self) -> None:
        """§9.5: kill-switch transitions re-evaluate every connected user."""
        self._changed_at = next(self._versions)  # SR-189: also for a socket mid-handshake
        for user_id in list(self._conns):
            await self.roles_changed(user_id)

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
    is not a non-empty array, an entry that is neither an object nor a string, or a `ch` that is
    not a topic name. `field` is built here and never echoes client input."""
    if not isinstance(body, dict):
        return TopicError("invalid_options", "sub needs an object payload.", "p")
    if not set(body) <= SUB_KEYS:
        return TopicError("invalid_options", "Unknown sub field.", "p")
    topics = body.get("topics")
    if not isinstance(topics, list) or not topics:
        return TopicError("invalid_options", "topics must be a non-empty array.", "topics")
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
    whole instead: one `err`, no `sub_ok`, nothing subscribed and no strike (#2396, #2399).

    #2831: the new subscriptions are announced only once the `sub_ok` is queued, so no hub
    flush or resnapshot during the awaits below can send a `snap` ahead of it; the gateway's
    flush then sends it. A refused topic is dropped unannounced. One left unannounced by a
    raise or a cancellation never gets a `snap`: the connection ends (a raise closes it 1011)
    and its teardown releases the subscription."""
    body: Any = frame.get("p")  # a dict once `sub_shape_error` passes it
    fid = _frame_id(frame)
    shape = sub_shape_error(body)
    if shape is not None:
        await send(build_ws_error(shape.code, id=fid, message=shape.message, field=shape.field))
        return
    results: list[dict[str, Any]] = []
    admitted: list[Subscription] = []
    snapshot = body.get("snapshot", True)
    replay = body.get("replay_session_id")
    for index, entry in enumerate(body["topics"]):
        ch: str = entry["ch"] if isinstance(entry, dict) else entry  # a topic name, by the shape
        if index >= MAX_TOPICS_PER_SUB:
            result = _fail(ch, "too_many_topics", "More than 50 topics in one sub.")
        else:
            result, sub = authz.admit(entry, snapshot=snapshot, replay_session_id=replay)
            if sub is not None:
                result = await authz.subscribe_upstream(sub) or result
                if result["ok"]:
                    admitted.append(sub)
        results.append(result)
        _observe(ch, result)
        if not result["ok"]:
            await _audit_denial(authz, ch, result["error"]["code"])
    cv_ws_client_topics_depth.observe(len(authz.by_id))
    out: dict[str, Any] = {"t": "sub_ok", "p": {"results": results}}
    if fid is not None:
        out["id"] = fid
    if now_ms is not None:
        out["ts"] = now_ms
    await send(out)
    for sub in admitted:  # with no await since `send` queued the reply
        sub.announced = True


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


async def _audit_denial(authz: ConnectionAuthz, ch: str, code: str) -> None:
    """`ws.subscribe.denied`: every authorisation denial, plus any rejected private-topic
    attempt on a well-formed topic name (confidential; a malformed `sub` is refused whole before
    any topic is read, #2396). Best effort: the reply is never held hostage to the audit sink."""
    audit = authz.services.audit
    fam = FAMILIES.get(topic_family(ch))
    if audit is None or not (code in _AUDITED_DENIALS or (fam is not None and fam.private)):
        return
    try:
        await audit.emit(
            "ws.subscribe.denied",
            actor_label="ws",
            actor_user_id=authz.principal.user_id,
            object_kind="ws_topic",
            object_id=topic_family(ch)[:40],
            outcome=AuditOutcome.DENIED,
            severity=Severity.WARNING,
            reason=code,
        )
    except Exception:
        _log().warning("ws subscribe-denied audit not written", exc_info=True)


async def _audit_revocations(authz: ConnectionAuthz, frames: list[dict[str, Any]]) -> None:
    audit = authz.services.audit
    if audit is None:
        return
    for f in frames:
        if f["t"] != "revoked":
            continue
        try:
            await audit.emit(
                "ws.subscription.revoked",
                actor_label="ws",
                actor_user_id=authz.principal.user_id,
                object_kind="ws_topic",
                object_id=str(f["ch"])[:40],
                reason=f["p"]["reason"],
                after_state={"removed_accounts": f["p"].get("removed_accounts", [])},
            )
        except Exception:
            _log().warning("ws revocation audit not written", exc_info=True)


def close_connection(registry: ConnectionRegistry, authz: ConnectionAuthz) -> None:
    registry.unregister(authz)
