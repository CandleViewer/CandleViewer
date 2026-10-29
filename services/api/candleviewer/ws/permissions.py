"""WS authorisation + subscriptions (E09-T03, E17-S02; `23-ws-protocol.md` §4.3, §5, §6, §9.5).

- `auth_ok_payload`: identity, roles, resolved permissions, account scope.
- `check_subscribe`: per-family permission check against the §6.3 matrix (fail-closed), backed by
  the declarative registry in `topics.FAMILIES`. Every decision is `auth.scopes.decide` (E09's
  RBAC service) - never a local copy of the rules.
- `ConnectionAuthz`: per-connection subscription manager. `sub` (partial success, results in
  request order, clamped `effective`), idempotent `unsub`, `ctl` (retune / resnapshot), the §16.2
  limits and §6.2 silent account-scope narrowing. `apply_snapshot` re-evaluates every live
  subscription after a role/grant change and returns the `revoked` frames (§9.5, S7); it
  refuses another user's snapshot (`SnapshotUserMismatch`, #415). With the backpressure
  flag on, `on_drop` hears of every subscription an operation ends or resets.
  Whatever the flag, `on_purge` drops the queued frames of what a change revokes (#415).
- `ConnectionRegistry`: live sockets per user; role/grant change, kill-switch transition and
  user-disabled fan-out. A disabled user is also remembered for one access-token lifetime, so a
  socket that registers after the per-user close is refused (#3413).
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import itertools
import math
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final, Literal, Protocol

import structlog

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.metrics import auth_revocation_latency_seconds
from candleviewer.auth.scopes import (
    Allow,
    Deny,
    DenyReason,
    PrincipalSnapshot,
    decide,
    scoped_account_ids,
)
from candleviewer.bars.errors import (
    BarParamOutOfRange,
    BarsError,
    BarServiceStopping,
    SpecCapExceeded,
)
from candleviewer.bars.models import BarSpec
from candleviewer.bars.series_store import Hold
from candleviewer.bars.spec import check_param_bounds, from_wire, qty_step_for
from candleviewer.observability.metrics import Counter, Gauge, Histogram
from candleviewer.orderflow.errors import (
    InstanceCapError,
    InstanceRefusedError,
    RecomputeRefusedError,
)
from candleviewer.orderflow.heatmap import HeatmapLease, HeatmapSpec, HeatmapSpecCapError, spec_of
from candleviewer.orderflow.indicators.engine import Requested, resolve_instances
from candleviewer.ws.errors import WsError, build_ws_error, topic_error
from candleviewer.ws.lifecycle import bye_frame as lifecycle_bye
from candleviewer.ws.limits import (
    DEEP_BOOK_MIN_DEPTH,
    DENIAL_AUDIT_WINDOW_S,
    DENIAL_AUDITS_PER_WINDOW,
    FANOUT_AUDIT_MAX_FAILURES,
    FANOUT_AUDIT_TIMEOUT_S,
    FANOUT_SEND_TIMEOUT_S,
    MAX_BARS_SUBSCRIPTIONS,
    MAX_DEEP_BOOK_SUBSCRIPTIONS,
    MAX_DENIALS_LISTED,
    MAX_SUBSCRIPTIONS,
    MAX_SYMBOLS_PER_CONNECTION,
    MAX_TOPICS_PER_SUB,
    SUB_ID_MAX_LEN,
)
from candleviewer.ws.metrics import (
    count_audit_failure,
    cv_ws_recorder_subscriptions_in_use,
    cv_ws_subscribe_denied_unaudited_total,
    cv_ws_subscribe_granted_unaudited_total,
    cv_ws_subscribe_narrowed_total,
)
from candleviewer.ws.rebuild_budget import RebuildBudget, UserRebuilds, topic_key
from candleviewer.ws.rebuild_budget import Scope as BudgetScope
from candleviewer.ws.revocation import (
    ACCOUNT_REVOKED_REASONS,
    CLOSE_FAILURE_LOG_EVERY_S,
    EVICTION_LOG_EVERY_S,
    AccountRevokedReason,
    Closer,
    RevokedReason,
    revoked_frame,
    user_disabled_bye,
    ws_revocation_close_failures_total,
    ws_revoked_total,
)
from candleviewer.ws.sequencing import (
    SequencingHub,
    SnapReason,
    SnapshotCache,
    SnapshotSource,
)
from candleviewer.ws.topics import (
    CTL_KEYS,
    FAMILIES,
    IDENTITY_OPTIONS,
    INDICATORS_DEFAULTS,
    MACHINE_KINDS,
    OPTION_NAMES,
    SCOPE_OPTIONS,
    UNIVERSAL,
    EntityScope,
    ParsedTopic,
    TopicError,
    check_instruments,
    effective_options,
    is_topic_name,
    machine_refusal,
    parse_replay_session_id,
    parse_topic,
    validate_options,
)
from candleviewer.ws.trades_publish import (
    TradesLease,
    note_option_refusal,
    options_of,
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
#: E40-T04: live `alerts` subscriptions across all connections (inc at admit, dec when dropped).
cv_ws_alerts_subscriptions_in_use = Gauge(
    "cv_ws_alerts_subscriptions_in_use",
    "Live WS subscriptions of the alerts topic (each its user's own deliveries).",
)
#: The family the gauge above counts.
_ALERTS: Final = "alerts"
_RECORDER: Final = "recorder"  # `cv_ws_recorder_subscriptions_in_use` (ws/metrics.py) counts it
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
#: Fair scheduling between connections (C-2.17): `handle_sub` yields to the loop after this many
#: entries, so one task step of a `sub` reads at most this many, refused or not.
SUB_ENTRIES_PER_STEP: Final = 10
#: #3413: an access token's lifetime in seconds, ADR-0020's 12 minutes: `auth.session_service.
#: ACCESS_TOKEN_TTL`, which the composition root passes (a test pins the equality). A token expires
#: at its issue instant plus at most this, so `issued_before_disable` can date a token, which the
#: gateway knows only by its expiry, no later than that expiry less this.
ACCESS_TOKEN_TTL_S: Final = 720.0
#: Seconds a disabled user is remembered: one access-token lifetime, the least that works. By then
#: every token issued before the disable has expired, so no `auth` with one can pass. A registry
#: refuses a span below its own `access_token_ttl_s`.
DISABLED_MEMORY_S: Final = ACCESS_TOKEN_TTL_S
#: At most this many disabled users are remembered (C-2.18); the oldest is forgotten first. A
#: live entry goes early only once 1024 other users are disabled within one `DISABLED_MEMORY_S`.
MAX_DISABLED_USERS: Final = 1024


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


class IndicatorInstances(Protocol):
    """`IndicatorEngine` (E13-T02): a live `indicators.*` subscription holds its instances.
    `user` is ALWAYS the authenticated principal; `consumer` the subscription's own id."""

    def check(
        self,
        symbol: str,
        spec: BarSpec,
        requested: tuple[Requested, ...],
        user: str | None,
        *,
        history: int,
        consumer: str | None = None,
    ) -> None: ...

    def admit(
        self,
        symbol: str,
        spec: BarSpec,
        requested: tuple[Requested, ...],
        consumer: str,
        user: str | None,
        *,
        history: int,
        replacing: tuple[str, ...] = (),
        reason: Literal["param_change"] | None = None,
    ) -> None: ...

    def release(self, symbol: str, keys: tuple[str, ...], consumer: str) -> None: ...


class AuditSink(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class EntityScopes(Protocol):
    """What `sub` reads of the §6.4 machine-state registry, which only the publisher writes."""

    def scope(self, ch: str) -> EntityScope | None:
        """The entry's scope; `None` when `ch` has no entry."""


class TradesLeases(Protocol):
    """`TradesTopic` (E22-T02, #654): a live `trades.*` subscription holds a lease on its symbol's
    tape and its option set's (`trades_publish.py`); each refusal is a `TopicError`."""

    def hold(self, consumer: str, user: str, symbol: str, options: Any) -> TradesLease: ...

    def check_retune(self, lease: TradesLease, options: Any) -> None: ...

    def retune(self, lease: TradesLease, options: Any) -> TradesLease: ...

    def release(self, lease: TradesLease) -> None: ...

    def echo(self, symbol: str) -> dict[str, Any]: ...


class HeatmapLeases(Protocol):
    """`HeatmapTopic` (E21-T02, #605): a live `heatmap.*` subscription holds a lease on its spec
    (`orderflow/heatmap.py`); a G-02 cap refuses it with `HeatmapSpecCapError`."""

    def hold(self, consumer: str, spec: HeatmapSpec) -> HeatmapLease: ...

    def check_retune(self, lease: HeatmapLease, spec: HeatmapSpec) -> None: ...

    def retune(self, lease: HeatmapLease, spec: HeatmapSpec) -> HeatmapLease: ...

    def release(self, lease: HeatmapLease) -> None: ...


@dataclass
class SubscriptionServices:
    """Process-wide collaborators shared by every connection (injected; never a global)."""

    upstream: UpstreamRefs = field(default_factory=UpstreamRefs)
    bars: BarLeases | None = None
    series: SeriesHolds | None = None  # E12-T06: the `bars` snapshot store; None: no hold
    #: E13-T02: the indicator engine an `indicators.*` subscription holds instances of (with
    #: `bars_enabled`); None: its instances are validated and echoed, and nothing is held.
    indicators: IndicatorInstances | None = None
    #: E22-T02: the `trades` tapes a live `trades.*` subscription leases; None: it holds none.
    trades: TradesLeases | None = None
    #: E21-T02: the heatmap spec a live `heatmap.*` subscription leases; None: it holds none.
    heatmap: HeatmapLeases | None = None
    audit: AuditSink | None = None
    clock: Callable[[], float] = time.monotonic
    instrument_known: Callable[[str], bool] | None = None
    #: SR-E12-03 (#2720): a symbol's lot step from the instrument catalogue, `None` when unknown.
    #: `volume`/`delta` bars floor at 10 x it; unwired or unknown, they are refused (never 1).
    qty_step: Callable[[str], Decimal | None] | None = None
    #: E17-S03: owning-module snapshot port and shared render cache; `None` until wired, in
    #: which case subscriptions stay `snapshot_pending` and no `snap` is emitted.
    snapshots: SnapshotSource | None = None
    snapshot_cache: SnapshotCache = field(default_factory=SnapshotCache)
    sequencing: SequencingHub | None = None
    #: §6.1: the deployment runs with `bars_enabled` off, so `bars.*` is refused `unknown_topic`.
    #: Set by the app from settings (a bare `bars=None` only means "no lease to take").
    bars_off: bool = False
    #: E21-T01 (§6.1, §16.2): the deep-book cap (`ws.max_deep_book_subs`) and whether depth 500
    #: is offered (`heatmap_depth_500`, C-4.13, off: `book.*.500` is `invalid_topic_format`).
    max_deep_book_subs: int = MAX_DEEP_BOOK_SUBSCRIPTIONS
    depth_500: bool = False
    #: E21-T02 (G-04, §6.1): `heatmap.*` is served only with the byte budget on
    #: (`CV_WS_BACKPRESSURE_ENABLED`); the app sets this from it, and while it is True every
    #: `heatmap.*` `sub`, live and replay, is refused `unknown_topic`.
    heatmap_off: bool = False
    #: E17-T08: the `machines.{entity}.state` entries `sub` is authorised against (§6.4); `None`
    #: means no entity has an entry.
    machines: EntityScopes | None = None
    #: E17-T06: draws each connection's span ids (`sp`, 23 §3.1); the app sets it from
    #: `CV_TELEMETRY_ENABLED`, and `None` (latency telemetry off) means no frame carries one.
    span_ids: Callable[[], str] | None = None
    #: #3476 (§7.5): the rebuild limit per user, which every connection's budget draws on too.
    user_rebuilds: UserRebuilds = field(default_factory=UserRebuilds)
    #: §9.5 (E27-S04, #898): whether an account is closed to new subscriptions, its account
    #: disabled or its last signable key revoked (`KeyStandings.closed`, synchronous, bound late
    #: by the app); `None` closes none.
    account_closed: Callable[[uuid.UUID], bool] | None = None


@dataclass(frozen=True, slots=True)
class VersionedSnapshot:
    """A principal plus the registry's monotonic version, taken before the read (SR-189)."""

    principal: PrincipalSnapshot
    version: int


class SnapshotUserMismatch(WsError):
    """#415 (§4.3): a permission snapshot whose principal is another user than the connection's
    (at a first `auth`, the token's). `apply_snapshot` raises it before it changes anything, and
    the gateway before a first `auth` builds a connection from it; an `auth` that meets it is
    refused as the gateway refuses another user's token (`user_mismatch`)."""


def topic_family(topic: str) -> str:
    return topic.split(".", 1)[0]


def auth_ok_payload(principal: PrincipalSnapshot, **extra: Any) -> dict[str, Any]:
    """`auth_ok` `p` body: roles, resolved permissions and account scope."""
    return {
        "user_id": str(principal.user_id),
        "roles": sorted(principal.roles),
        "permissions": sorted(p.value for p in principal.permissions),
        # The one scope rule (C-12.4): the grants that currently permit access, so not a frozen
        # one. An owner's scope has no ids: `[]` means every account.
        "account_scope": sorted(str(a) for a in scoped_account_ids(principal)),
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
    #: A live `indicators.*` one's instance keys in the indicator engine (E13-T02).
    indicator_keys: tuple[str, ...] = ()
    #: A live `trades.*` one's lease on its tape and option set (E22-T02).
    trades_lease: TradesLease | None = None
    #: A live `heatmap.*` one's lease on its spec (E21-T02).
    heatmap_lease: HeatmapLease | None = None
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
    #: #3476: `_admit` holds one of its user's draws, which its start draws (`handle_sub`) or
    #: its end lets go (`_drop`): its draw comes after an await, so the check is not enough.
    rebuild_held: bool = False
    #: #2521 (E40-T04): the server-side owner of a SELF-scoped subscription (`alerts`), the
    #: principal's user id recorded at admit, never a client value; None for every other scope.
    #: Its snapshot is built for this user alone and its deltas reach it only when they name this
    #: user (`sequencing.in_scope`). A connection's principal never changes user
    #: (`apply_snapshot`), so it holds for the subscription's life.
    owner: uuid.UUID | None = None
    #: #492 (ruling Q6): the principal was not the Owner at admit or at a later §9.5
    #: re-evaluation (`apply_snapshot`), never a client value; the `recorder` topic serves such a
    #: subscription its role-restricted view (R-I2). Only a new `sub` widens it again.
    role_restricted: bool = False

    @property
    def ch(self) -> str:
        return self.topic.ch

    @property
    def symbols(self) -> frozenset[str]:
        out = set(self.opts.get("symbols") or ())
        if self.topic.symbol is not None:
            out.add(self.topic.symbol)
        return frozenset(out)


def _bar_spec(
    sub: Subscription, qty_step: Callable[[str], Decimal | None] | None
) -> tuple[BarSpec | None, dict[str, Any] | None]:
    """The spec of a topic that names a bar series (`bars.*`, `footprint.*`, ...), or its refusal
    (§6.1, SR-E12-03): an unbuildable spec, or a `param` outside its kind's bounds (`volume`/`delta`
    floor at 10 x the symbol's `qty_step`), naming the bound and never the series."""
    bar_type = sub.topic.bar_type or ""
    try:
        spec = from_wire(bar_type, sub.topic.param or "")
        step = qty_step_for(bar_type, sub.topic.symbol or "", qty_step)
        check_param_bounds(spec, bar_type, qty_step=step)
    except BarParamOutOfRange as exc:
        return None, _fail(sub.ch, "invalid_topic_format", str(exc))
    except BarsError:
        return None, _fail(sub.ch, "invalid_topic_format", "This bar series is not available.")
    return spec, None


def _indicator_history(sub: Subscription) -> int:
    """An `indicators.*` subscription's `history` (§6.1), its default when left out."""
    return int(sub.effective.get("history", INDICATORS_DEFAULTS["history"]))


#: `unknown_topic` for a topic in the catalogue that this server does not serve (§6.1, §10.2).
_UNSERVED: Final = "This topic is not available on this server."
#: E21-T02: the `heatmap` options a spec is keyed by (§6.1, G-02); a `ctl` of one moves the lease.
_HEATMAP_SPEC: Final = frozenset({"depth", "price_grouping", "time_bucket_ms"})
#: One message per refusal code, whatever the cause: `account_scope_denied` carries §6.2's.
_REFUSED: Final = {
    "forbidden": "Missing permission for this topic.",
    "account_scope_denied": "None of the requested accounts are in scope.",
}


def _fail(ch: Any, code: str, message: str, fld: str | None = None) -> dict[str, Any]:
    err = topic_error(code, message, fld)
    return {"ch": ch if isinstance(ch, str) else str(ch)[:120], "ok": False, "error": err}


def _bad_replay() -> str:
    raise TopicError("invalid_options", "replay_session_id must be a uuid.", "replay_session_id")


def _replay_id(raw: Any) -> str | None:
    """A `sub`'s `replay_session_id` (§5.2), read as §7.5 reads a uuid (#3218)."""
    if raw is None:
        return None
    return parse_replay_session_id(raw) or _bad_replay()


def _named_session(rs: object) -> str | None:
    """A request's envelope `rs` (§7.5, W10): None when absent, else its canonical session id. One
    that is not a uuid raises `invalid_options` naming the field, never the value."""
    if rs is None:
        return None
    if (session := parse_replay_session_id(rs)) is None:
        raise TopicError("invalid_options", "rs must be a uuid.", "rs")
    return session


def _upstream_keys(sub: Subscription) -> tuple[UpstreamKey, ...]:
    """(symbol, family, params) per symbol the topic needs from the exchange."""
    t = sub.topic
    symbols = [t.symbol] if t.symbol is not None else sorted(sub.opts.get("symbols") or ())
    return tuple((s, t.family.family, t.params) for s in symbols)


class ConnectionAuthz:
    """Authorisation + subscription state of one authenticated WS connection.

    Indexes: `by_id` (sub_id -> Subscription) and a reverse index by topic name, so `unsub`,
    `ctl` and grant re-evaluation resolve in O(affected). `held_symbols` counts the subscriptions
    holding each symbol, kept with `by_id` (`_record`, `_drop`), so the 40-symbol test costs
    O(the entry's symbols) and the 200-subscription test one bounded lookup of its name."""

    @property
    def actor_user_id(self) -> uuid.UUID:
        """§9.6 (#3085): who acts on the socket: the viewer while it views as another user, else
        its principal's user. Its audit rows name the actor, and the per-user quotas key by it,
        so a viewer cannot spend the target's."""
        return self.principal.user_id if self.viewer_user_id is None else self.viewer_user_id

    @property
    def viewing(self) -> bool:
        return self.viewer_user_id is not None

    def __init__(
        self,
        principal: PrincipalSnapshot,
        services: SubscriptionServices | None = None,
        *,
        connection_id: str | None = None,
        version: int = 0,
        clock: Callable[[], float] | None = None,
        viewer_user_id: uuid.UUID | None = None,
        request_id: uuid.UUID | None = None,
    ) -> None:
        self.principal = principal
        #: The connection's correlation id, bound at its upgrade (`CorrelationMiddleware`): each
        #: audit row of the socket carries it as `request_id`, whatever request or job writes the
        #: row (#3990).
        self.request_id = request_id
        #: §9.6 (#3085): the viewer while the socket views as another user, whose principal it
        #: holds; `None` otherwise (`actor_user_id`).
        self.viewer_user_id = viewer_user_id
        self.version = version  # SR-189: the applied snapshot's; 0 = not from the registry
        #: The session the socket is authenticated on (`do_auth` sets it at each accepted `auth`):
        #: the revocation and denial rows carry it in their `session_id` column (#415, E17-R-16).
        self.session_id: str | None = None
        self.services = services if services is not None else SubscriptionServices()
        self.connection_id = connection_id or f"c-{uuid.uuid4().hex[:12]}"
        self.by_id: dict[str, Subscription] = {}
        self._by_topic: dict[str, set[str]] = {}
        #: symbol -> how many subscriptions in `by_id` hold it; never a zero count (read-only).
        self.held_symbols: dict[str, int] = {}
        self._ids = itertools.count(1)
        #: SR-193 (§7.5): the connection's rebuild budget, on its clock (`do_auth` passes it),
        #: and its user's, which all of the user's connections share (#3476).
        user = (self.services.user_rebuilds, self.actor_user_id)
        self.rebuilds = RebuildBudget(self.services.clock if clock is None else clock, user=user)
        #: §6.4: the internal reason (`role`, `unknown`, `foreign` or `unscoped`) of the last
        #: `admit` that refused a `machines` entity, else `None`. `handle_sub` reads it right
        #: after that `admit`, for the audit row only; it never reaches the client.
        self.refusal_reason: str | None = None
        #: §6.2: how many requested accounts the last `admit` narrowed away, silently. `handle_sub`
        #: reads it right after that `admit`, for its count and record only (#415, E17-R-15).
        self.narrowed = 0
        #: E17-T03 (flag on, the outbound pipeline): called once per operation, before its reply
        #: or `revoked` is queued, with every subscription whose queued frames and throttle
        #: window it made stale (§8.4 Lanes, §9.5). While it is set, a narrowing re-pends what it
        #: kept (`settling`), for `on_settle` after the change's frames (the registry's `settle`).
        self.on_drop: Callable[[list[Subscription]], None] | None = None
        self.on_settle: Callable[[list[Subscription]], None] | None = None
        self.settling: list[Subscription] = []
        #: #415 (§9.5), whatever the flag: called once per change, before its `permission_change`
        #: is queued, with every subscription it revokes (a grant or a permission withdrawn); it
        #: drops their queued frames and returns their keys `(ch, rs)` that had any.
        self.on_purge: Callable[[list[Subscription]], set[tuple[str, str | None]]] | None = None
        #: #3185 (§4.3): when the connection's last `DENIAL_AUDITS_PER_WINDOW` `ws.subscribe.denied`
        #: records were handed to the writer (monotonic s, oldest first), and when the warning for
        #: a record kept back was last logged.
        self._denial_audits: collections.deque[float] = collections.deque(
            maxlen=DENIAL_AUDITS_PER_WINDOW
        )
        self._denial_skip_logged: float | None = None
        #: #415 (E17-R-14): the same budget, kept apart, for its `ws.subscribe.granted` records.
        self._grant_audits: collections.deque[float] = collections.deque(
            maxlen=DENIAL_AUDITS_PER_WINDOW
        )
        #: SR-193: the limit that refused the last `admit` for the rebuild budget (its log line).
        self.refusal_scope: BudgetScope | None = None

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

    def named(self, ch: str | None, rs: object, sub_id: object = None) -> Subscription | None:
        """§7.5 (#3218): the subscription a `resync` or `ctl` of `ch` names, among this connection's
        own only: the one of `ch` in the replay session `rs` names, else (no `rs`) the live one,
        never a replay one. A `resync`'s `sub_id` is a pin: when sent, it must be that one's, or
        none is named. In this order, an `rs` that is not a uuid and a `sub_id` that is not a
        string of 1 to `SUB_ID_MAX_LEN` characters raise `invalid_options` naming the field, never
        the value. `None` counts as absent for `rs` and `sub_id`; with no `ch`, none is named."""
        session = _named_session(rs)
        if sub_id is not None and not (
            isinstance(sub_id, str) and 0 < len(sub_id) <= SUB_ID_MAX_LEN
        ):
            message = f"sub_id must be a string of 1 to {SUB_ID_MAX_LEN} characters."
            raise TopicError("invalid_options", message, "sub_id")
        sub = None if ch is None else self.find(ch, session)
        return sub if sub is not None and sub_id in (None, sub.sub_id) else None

    def at_capacity(self, needed: int = 1) -> bool:
        """True when `needed` more subscriptions would exceed `MAX_SUBSCRIPTIONS` (C-2.18)."""
        return len(self.by_id) + needed > MAX_SUBSCRIPTIONS

    def _over_capacity(self, ch: Any, replay_session_id: Any) -> bool:
        """The 200-subscription test of a `sub` entry, bounded and before the entry is read: at the
        cap, every entry adds a subscription but `system` (§6.2) and one naming a subscription held
        in the stream its `replay_session_id` names, which `_admit` answers as below the cap."""
        if ch == SYSTEM_TOPIC or not self.at_capacity():
            return False
        return (
            not isinstance(ch, str)
            or self.find(ch, parse_replay_session_id(replay_session_id)) is None
        )

    def may_submit_order(self) -> bool:
        return isinstance(decide(self.principal, Permission.ORDERS_WRITE), Allow)

    # -- the denial records' budget (#3185) -------------------------------------------------

    def take_denial_audit(self) -> bool:
        """True, and stamped, while this connection may write one more `ws.subscribe.denied`
        record: at most `DENIAL_AUDITS_PER_WINDOW` in any sliding `DENIAL_AUDIT_WINDOW_S` on
        `services.clock`. A stamp leaves the window once it is a full window old (the edge of
        `lifecycle.ConnectRateLimiter`). O(1): with the deque full, its oldest stamp decides. A
        record refused here leaves no stamp, so a connection past its budget cannot lengthen
        its own wait."""
        return self._take(self._denial_audits)

    def take_grant_audit(self) -> bool:
        """`take_denial_audit`'s rule for `ws.subscribe.granted` records, on a budget of their own
        of the same size and window (#415, E17-R-14)."""
        return self._take(self._grant_audits)

    def _take(self, stamps: collections.deque[float]) -> bool:
        now = self.services.clock()
        if len(stamps) >= DENIAL_AUDITS_PER_WINDOW and now - stamps[0] < DENIAL_AUDIT_WINDOW_S:
            return False
        stamps.append(now)
        return True

    def first_denial_skip(self) -> bool:
        """True for the first record kept back in a window since the last one logged: the caller
        logs its warning for that one only and counts every record (the connect-rate refusal's
        `first_refusal` cap, here per connection). One float of state."""
        now, last = self.services.clock(), self._denial_skip_logged
        if last is not None and now - last < DENIAL_AUDIT_WINDOW_S:
            return False
        self._denial_skip_logged = now
        return True

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
        self.refusal_reason = self.refusal_scope = None
        self.narrowed = 0
        try:
            return self._admit(entry, ch, snapshot, replay_session_id)
        except TopicError as exc:
            self.refusal_reason = exc.reason
            note_option_refusal(ch, exc.code, exc.field)  # SR-E22-04 on `trades` (E22-T02)
            return _fail(ch, exc.code, exc.message, exc.field), None

    def _admit(
        self, entry: Any, ch: Any, snapshot: Any, replay_session_id: Any
    ) -> tuple[dict[str, Any], Subscription | None]:
        if isinstance(entry, dict) and set(entry) - {"ch", "opts"}:
            raise TopicError("invalid_options", "Unknown topic entry field.", "topics")
        # The 200 test, bounded and before the entry is read: it holds at `_record` below only
        # while `_admit` stays synchronous (an await between the two would need a re-check).
        if self._over_capacity(ch, replay_session_id):
            raise TopicError("subscription_limit", "200 subscriptions reached.")
        topic = parse_topic(ch, instrument_known=self.services.instrument_known)
        fam = topic.family
        if fam.family == SYSTEM_TOPIC:  # §6.2: implicit and permanent - already attached
            return {"ch": SYSTEM_TOPIC, "ok": True, "sub_id": SYSTEM_TOPIC}, None
        opts = validate_options(fam, entry.get("opts") if isinstance(entry, dict) else None)
        if fam.family == "ticker" and topic.symbol is None:  # E08-T08: instruments, as named
            check_instruments(opts.get("symbols") or (), self.services.instrument_known)
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
            # #2521: SELF families are owned by the principal (by value: a test may reload the
            # generated `Scope`, a StrEnum, which leaves two classes behind).
            owner=self.principal.user_id if fam.scope == Scope.SELF else None,
            role_restricted=not self.principal.is_owner,
        )
        if not snapshot and not self._continuity(sub):
            sub.snapshot_pending = forced = True  # §7.6: continuity unproven -> snap anyway
        fresh = sum(1 for s in sub.symbols if s not in self.held_symbols)  # O(the entry's)
        if len(self.held_symbols) + fresh > MAX_SYMBOLS_PER_CONNECTION:
            raise TopicError("subscription_limit", "40 symbols per connection reached.")
        key = topic_key(topic, rs)
        if (scope := self.rebuilds.refusal(key, "sub")) is not None:
            self.refusal_scope = scope  # SR-193: after every refusal decided from the entry (§5.2)
            spent = self.rebuilds.count_refusal("sub", scope, key)
            raise TopicError("resync_rate_limited", f"{spent}; not subscribed.")
        sub.rebuild_held = self.rebuilds.hold()  # #3476: the user's draw, until it starts or ends
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

    def revoke(
        self, sub: Subscription, reason: RevokedReason, now_ms: int, *, resubscribe: bool = False
    ) -> dict[str, Any]:
        """Drop one subscription and return its `revoked` frame (§7.5 resync loop, §6.4 removal)."""
        self._drop(sub)
        self._dropped([sub])
        return self._revoked(sub, reason, now_ms, resubscribe=resubscribe)

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
        self.narrowed = len(set(requested) - allowed)  # E17-R-15: silent in the reply only
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
        """The grant decides, and an account closed by its disable or last key's revoke is out of
        scope for every caller (§9.5): a `sub` naming it alone is `account_scope_denied`, and
        one naming others too is narrowed to them. The standing is read only for an account the
        grant admits, so an id outside the scope reads nothing more than an unknown one (E17-X02
        AC-05)."""
        decision = decide(
            self.principal,
            permission,
            scope=Scope.GRANTED_ACCOUNTS,
            exchange_account_id=account,
        )
        if not isinstance(decision, Allow):
            return False
        closed = self.services.account_closed
        return closed is None or not closed(account)

    def _record(self, sub: Subscription) -> None:
        self.by_id[sub.sub_id] = sub
        self._by_topic.setdefault(sub.ch, set()).add(sub.sub_id)
        if sub.topic.family.family == _ALERTS:
            cv_ws_alerts_subscriptions_in_use.inc()
        elif sub.topic.family.family == _RECORDER:
            cv_ws_recorder_subscriptions_in_use.inc()
        for symbol in sub.symbols:  # fixed for its life: `symbols` is a scope option (no `ctl`)
            self.held_symbols[symbol] = self.held_symbols.get(symbol, 0) + 1

    def _consumer(self, sub: Subscription) -> str:
        return f"{self.connection_id}/{sub.sub_id}"

    async def subscribe_upstream(self, sub: Subscription) -> dict[str, Any] | None:
        """Take what a subscription needs upstream, or refuse it (drop it, return the failure). A
        topic of a family nothing serves yet (`served`) is refused `unknown_topic` first (§6.1). A
        `bars.*` one first passes `_bars_refusal`, an `indicators.*` one `_indicators` (its
        instances against the catalogue); a `bars.*` or `footprint.*` spec is bounded
        (`_bar_spec`, SR-E12-03) wherever a builder could serve it, live or replay. Only a live
        public one takes anything, in order: for `indicators.*`, once the engine's `check` passes
        (SR-E13-03/04, before anything is held); for `bars.*` and `indicators.*`, once the set's
        `check` passes, a hold on its series (`ensure`: a restoring builder's closes reach it); the
        `BarBuilderSet` lease (`register` checks again; `user=` the authenticated principal id,
        never a client value); the upstream refs (`bars.*` and `indicators.*`: its symbol's
        trades); for `indicators.*`, its instance leases (`admit`, which can still refuse a read
        with no recompute slot free). `_drop` releases what was taken, on a refusal, an `unsub`, a
        revocation or the socket's end.
        A topic that names a bar series (`bars.*`, `footprint.*`, ...) is bounded and leased alike.

        #2896: a change that ends `sub` during these awaits (a revocation, §9.5, or the socket's
        end) releases only what was taken before it, and `release_all` no longer sees `sub`. What
        was taken after it is released here, on a return, a raise or a cancellation, and a return
        refuses `sub` (`ended_result`), after the `revoked` that the change queued already."""
        try:
            refused = await self._upstream(sub)
        except BaseException:
            self._release_ended(sub)
            raise
        if refused is not None:  # what was queued of it meanwhile goes too (`on_drop`)
            self._dropped([sub])
            return refused
        return self.ended_result(sub) if self._release_ended(sub) else None

    def _release_ended(self, sub: Subscription) -> bool:
        """#2896: True when a change ended `sub` (`_drop`) during `subscribe_upstream`, so it is not
        the one `by_id` holds under its id (never reused); dropping it again releases only what was
        taken after that end. A release that raises (#2735) is logged as `release_all` logs one,
        and never replaces a raise in flight."""
        if self.by_id.get(sub.sub_id) is sub:
            return False
        try:
            self._drop(sub)
        except Exception:
            with contextlib.suppress(Exception):  # a failing logger must not replace that raise
                _log().error(
                    "ws subscription release failed", consumer=self._consumer(sub), exc_info=True
                )
        return True

    def ended_result(self, sub: Subscription) -> dict[str, Any]:
        """#2896: the `sub_ok` result of `sub`, which a change ended before its reply was queued:
        the refusal a `sub` of it gets now, which for the change's `permission_revoked` is
        `forbidden` and for `account_scope_changed` (its last account) `account_scope_denied`
        (§10.2); else `forbidden` (the socket ended, or a later change gave it back). No `sub_id`,
        as on any refusal (§5.2)."""
        try:
            if (kind := sub.topic.entity_kind) is not None:
                self._authorise_entity(sub.ch, kind)
            else:
                self._authorise(sub.topic, sub.opts)
        except TopicError as exc:
            return _fail(sub.ch, exc.code, exc.message)
        return _fail(sub.ch, "forbidden", _REFUSED["forbidden"])

    async def _upstream(self, sub: Subscription) -> dict[str, Any] | None:
        family = sub.topic.family.family
        if not sub.topic.family.served:  # §6.1: the contract lists it, nothing produces it yet
            self._drop(sub)
            return _fail(sub.ch, "unknown_topic", _UNSERVED)
        spec: BarSpec | None = None
        requested: tuple[Requested, ...] = ()
        if family == "indicators":
            spec, requested, refused = self._indicators(sub)
            if refused is not None:
                self._drop(sub)
                return refused
        # E21-T01: the flag-off depth 500 and the deep-book cap, before anything is held.
        elif family == "book" and (refused := self._book_refusal(sub)) is not None:
            self._drop(sub)
            return refused
        # E21-T02: G-04, then the flag-off depth 500, before anything is held (live and replay).
        elif family == "heatmap" and (refused := self._heatmap_refusal(sub)) is not None:
            self._drop(sub)
            return refused
        # The topic has a `bar_type` segment (`bars`, `footprint`): its spec is bounded and, where a
        # builder serves it, leased. A series that only an option names (`metrics`) is not seen.
        elif sub.topic.bar_type is not None:
            refused = self._bars_refusal(sub) if family == "bars" else None
            # SR-E12-03 for live and replay alike, wherever a builder could serve the series.
            served = sub.replay_session_id is not None or self.services.bars is not None
            if refused is None and served:
                spec, refused = _bar_spec(sub, self.services.qty_step)
            if refused is not None:
                self._drop(sub)
                return refused
        if sub.replay_session_id is not None or sub.topic.family.private:
            return None
        consumer, user, symbol = self._consumer(sub), str(self.actor_user_id), sub.topic.symbol
        engine = self.services.indicators if requested else None  # `indicators.*` alone has any
        history = _indicator_history(sub) if engine is not None else 0
        try:
            heatmap = self.services.heatmap
            if family == "heatmap" and heatmap is not None:  # E21-T02 G-02: before anything else
                sub.heatmap_lease = heatmap.hold(consumer, spec_of(symbol or "", sub.opts))
            if engine is not None and spec is not None:  # before anything is held
                engine.check(symbol or "", spec, requested, user, history=history)
            bars = self.services.bars
            if spec is not None and bars is not None:
                if family in {"bars", "indicators"} and self.services.series is not None:
                    bars.check(spec, symbol or "", user=user)
                    sub.series_hold = await self.services.series.ensure(symbol or "", spec)
                await bars.register(spec, symbol or "", consumer, user=user)
                sub.bar_lease = (spec.spec_hash, symbol or "")
            keys = _upstream_keys(sub)
            for key in keys:
                await self.services.upstream.acquire(key, consumer)
                sub.upstream = (*sub.upstream, key)
            if engine is not None and spec is not None:  # all or nothing: `admit` undoes a raise
                engine.admit(symbol or "", spec, requested, consumer, user, history=history)
                sub.indicator_keys = tuple(r.key for r in requested)
            trades = self.services.trades
            if family == "trades" and trades is not None:  # E22-T02: refused with nothing held
                sub.trades_lease = trades.hold(consumer, user, symbol or "", options_of(sub.opts))
                sub.effective.update(trades.echo(symbol or ""))
        except TopicError as exc:  # E22-T02: a `trades` bound (SR-E22-03/06/07)
            self._drop(sub)
            return _fail(sub.ch, exc.code, exc.message, exc.field)
        except HeatmapSpecCapError as exc:  # E21-T02 G-02, naming the cap
            self._drop(sub)
            return _fail(sub.ch, "subscription_limit", str(exc))
        except SpecCapExceeded:
            self._drop(sub)
            return _fail(sub.ch, "subscription_limit", "Too many distinct bar series.")
        except InstanceCapError as exc:  # SR-E13-03, naming the cap
            self._drop(sub)
            return _fail(sub.ch, "subscription_limit", str(exc))
        except RecomputeRefusedError as exc:  # SR-E13-04: refused, never queued; retryable
            self._drop(sub)
            return _fail(sub.ch, "internal_error", str(exc))
        except BarServiceStopping:
            self._drop(sub)
            return _fail(sub.ch, "internal_error", "The bar service is restarting; retry.")
        except BarsError:
            self._drop(sub)
            return _fail(sub.ch, "invalid_topic_format", "This bar series is not available.")
        return None

    def _indicators(
        self, sub: Subscription
    ) -> tuple[BarSpec | None, tuple[Requested, ...], dict[str, Any] | None]:
        """§6.1 for `indicators.*`, before anything is held: `unknown_topic` while the bars feature
        is off and for a replay (the topic is live only); the series' spec, bounded as `bars.*`
        bounds it (SR-E12-03); the instances against the catalogue (`resolve_instances`, IR-24,
        IR-41), refused `invalid_options` on `instances`. The accepted ones are echoed in
        `effective`, every param written out, each with its `key`."""
        if self.services.bars_off or sub.replay_session_id is not None:
            return None, (), _fail(sub.ch, "unknown_topic", _UNSERVED)
        spec, refused = _bar_spec(sub, self.services.qty_step)
        if spec is None:
            return None, (), refused
        try:
            requested = resolve_instances(sub.opts.get("instances") or (), spec)
        except InstanceRefusedError as exc:
            return None, (), _fail(sub.ch, "invalid_options", str(exc), "instances")
        sub.effective["instances"] = [r.echo() for r in requested]
        return spec, requested, None

    def _bars_refusal(self, sub: Subscription) -> dict[str, Any] | None:
        """§6.1: `unknown_topic` while the bars feature is off, and `subscription_limit` past
        SR-E12-07's per-connection cap (live and replay `bars.*` count alike). `footprint.*`
        keeps §7.7 until #2197, but its spec is still bounded (`_bar_spec`)."""
        if self.services.bars_off:
            return _fail(sub.ch, "unknown_topic", _UNSERVED)
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

    def _heatmap_refusal(self, sub: Subscription) -> dict[str, Any] | None:
        """E21-T02 (§6.1, §10.2): `unknown_topic` while the byte budget is off (G-04), live and
        replay alike, never `snapshot_pending`; then depth 500 is `invalid_topic_format` while
        `heatmap_depth_500` is off (#604 BQ-9). The spec caps (G-02) come at the lease."""
        if self.services.heatmap_off:
            return _fail(sub.ch, "unknown_topic", _UNSERVED)
        if int(sub.opts.get("depth", 0)) >= 500 and not self.services.depth_500:
            return _fail(sub.ch, "invalid_topic_format", "Heatmap depth 500 is not offered.")
        return None

    def _book_refusal(self, sub: Subscription) -> dict[str, Any] | None:
        """E21-T01 (§6.1): depth 500 is `invalid_topic_format` while `heatmap_depth_500` is off,
        never served at another depth; past `max_deep_book_subs` distinct deep (depth >= 200)
        `book` subscriptions on the connection, each (symbol, depth) live and in each replay
        session counted apart, `subscription_limit`."""
        depth, symbol = sub.topic.depth or 0, sub.topic.symbol
        if depth >= 500 and not self.services.depth_500:
            return _fail(sub.ch, "invalid_topic_format", "Book depth 500 is not offered.")
        if depth < DEEP_BOOK_MIN_DEPTH:
            return None
        held = {
            (s.topic.symbol, s.topic.depth, s.replay_session_id)
            for s in self.by_id.values()
            if s is not sub
            and s.topic.family.family == "book"
            and (s.topic.depth or 0) >= DEEP_BOOK_MIN_DEPTH
        }
        cap = self.services.max_deep_book_subs
        if (symbol, depth, sub.replay_session_id) not in held and len(held) >= cap:
            return _fail(
                sub.ch,
                "subscription_limit",
                f"At most {cap} deep book subscriptions (depth 200 or more) per connection.",
            )
        return None

    # -- unsub / ctl ------------------------------------------------------------------------

    def unsubscribe(self, topic: str, rs: str | None = None) -> Subscription | None:
        """§5.3 (W10, #3218): end the subscription an `unsub` entry of `topic` names and return it,
        else None: the one in the replay session `rs` (canonical), else (no `rs`) the live one,
        never a replay one. `system` is never held as a subscription (§6.2), so it never ends."""
        sub = self.find(topic, rs)
        if sub is not None:
            self._drop(sub)
            self._dropped([sub])
        return sub

    def _dropped(self, subs: list[Subscription]) -> None:
        if self.on_drop is not None:
            self.on_drop(subs)

    def _drop(self, sub: Subscription) -> None:
        """Bookkeeping only: each operation that calls it reports through `_dropped`, once."""
        sub.ended = True
        if (held := self.by_id.pop(sub.sub_id, None)) is not None:  # once, if dropped twice
            if held.topic.family.family == _ALERTS:  # with `by_id`: exact, whatever raises below
                cv_ws_alerts_subscriptions_in_use.dec()
            elif held.topic.family.family == _RECORDER:
                cv_ws_recorder_subscriptions_in_use.dec()
            for symbol in held.symbols:  # with `by_id`, before a release below can raise
                if (count := self.held_symbols.pop(symbol, 1) - 1) > 0:  # never a KeyError
                    self.held_symbols[symbol] = count
        ids = self._by_topic.get(sub.ch)
        if ids is not None:
            ids.discard(sub.sub_id)
            if not ids:
                del self._by_topic[sub.ch]
        consumer = self._consumer(sub)
        now = self.services.clock()
        if sub.rebuild_held:  # #3476: it never started, so no draw; before a release can raise
            sub.rebuild_held = False
            self.rebuilds.unhold()
        hold, sub.series_hold = sub.series_hold, None
        if hold is not None:  # first: a lease release below can raise (#2735)
            # A lease never taken (refused, or the connection ended mid-subscribe): no grace.
            hold.release(grace=sub.bar_lease is not None)
        lease, sub.trades_lease = sub.trades_lease, None
        if lease is not None and self.services.trades is not None:  # before a raise below
            self.services.trades.release(lease)
        held_spec, sub.heatmap_lease = sub.heatmap_lease, None
        if held_spec is not None and self.services.heatmap is not None:
            self.services.heatmap.release(held_spec)
        keys, sub.indicator_keys = sub.indicator_keys, ()
        if keys and self.services.indicators is not None:
            self.services.indicators.release(sub.topic.symbol or "", keys, consumer)
        for key in sub.upstream:
            self.services.upstream.release(key, consumer, now)
        if sub.bar_lease is not None and self.services.bars is not None:
            self.services.bars.release(sub.bar_lease[0], sub.bar_lease[1], consumer)
        sub.upstream, sub.bar_lease = (), None
        if sub.announced:  # SR-193: a `sub` of its topic within the window counts toward it
            self.rebuilds.released(topic_key(sub.topic, sub.replay_session_id))

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

    def ctl(
        self, ch: Any, body: Any, rs: object = None
    ) -> tuple[dict[str, Any], bool, Subscription]:
        """§5.4: retune the subscription a `ctl` names (W10, #3218): the one of `ch` in the replay
        session of the envelope `rs`, else (no `rs`) the live one, never a replay one. Returns
        (`effective`, resnapshot, the subscription retuned) or raises `TopicError`, in this order:
        `invalid_options` for a non-null `ch` that is no topic name (#2572) or a malformed `rs`,
        `not_subscribed`, `invalid_options` for the options; or `resync_rate_limited` for a
        re-snapshot past the rebuild budget, which changes nothing (SR-193)."""
        if ch is not None and not is_topic_name(ch):
            raise TopicError("invalid_options", "ch must be a topic name.", "ch")
        sub = self.named(ch, rs)
        if sub is None:
            raise TopicError("not_subscribed", "No subscription for this topic.")
        if not isinstance(body, dict) or not body:
            raise TopicError("invalid_options", "ctl needs at least one option.", "p")
        allowed = {**UNIVERSAL, **sub.topic.family.options}
        changes: dict[str, Any] = {}
        for key in sorted(body):
            if key == "paused":  # a boolean on every topic, though no family lists it (§5.4, #2517)
                if not isinstance(body[key], bool):
                    raise TopicError("invalid_options", "Option 'paused' is out of range.", key)
                changes[key] = body[key]
                continue
            if key in SCOPE_OPTIONS:  # scope is authorised at `sub` only; never widened here
                raise TopicError("invalid_options", f"'{key}' cannot be changed by ctl.", key)
            spec = allowed.get(key) if key in CTL_KEYS else None
            if spec is None:  # a key the server does not know is never echoed (§5.4, #3370)
                named = key if key in OPTION_NAMES else "p"
                raise TopicError("invalid_options", "Unknown ctl option.", named)
            changes[key] = spec.check(key, body[key])
        retune = self._retune(sub, changes["instances"]) if "instances" in changes else None
        opts = {**sub.opts, **{k: v for k, v in changes.items() if k != "paused"}}
        moved = self._retune_trades(sub, opts) if "min_size" in changes else None
        respec = self._retune_heatmap(sub, opts) if _HEATMAP_SPEC.intersection(changes) else None
        effective = effective_options(sub.topic, opts)
        if sub.topic.family.family == "indicators":  # the canonical echo, never the raw entries
            effective["instances"] = sub.effective.get("instances") if retune is None else retune[2]
        # #2517: a pause holds until a ctl lifts it (`opts` never holds it, so carry it over).
        # A delta suppressed while paused never took a sequence number, so a resume
        # re-snapshots like an identity change instead of losing that state silently.
        was_paused = sub.effective.get("paused") is True
        paused = changes.get("paused", was_paused)
        resnapshot = (was_paused and not paused) or any(
            k in IDENTITY_OPTIONS and sub.effective.get(k) != effective.get(k) for k in changes
        )
        if resnapshot:  # SR-193: drawn before any change, so a refused `ctl` changes nothing
            key = topic_key(sub.topic, sub.replay_session_id)
            if (scope := self.rebuilds.take(key, "ctl")) is not None:
                # `rs=`: the subscription's own canonical id, never the raw `rs` argument
                self.rebuilds.log(
                    "ctl", scope, self.connection_id, sub.ch, rs=sub.replay_session_id
                )
                spent = self.rebuilds.count_refusal("ctl", scope, key)
                raise TopicError("resync_rate_limited", f"{spent}; nothing was changed.")
        if retune is not None and effective["instances"] != sub.effective.get("instances"):
            self._hold_instances(sub, retune[0], retune[1])
        if respec is not None and self.services.heatmap is not None:  # E21-T02: after the budget
            sub.heatmap_lease = self.services.heatmap.retune(respec[0], respec[1])
        if sub.topic.family.family == "trades":  # E22-T02: the threshold echo stays (§6.1)
            if moved is not None and self.services.trades is not None:
                sub.trades_lease = self.services.trades.retune(moved[0], moved[1])
            for key in ("big_trade_threshold", "big_trade_mode"):
                if key in sub.effective:
                    effective[key] = sub.effective[key]
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
        return echoed, resnapshot, sub

    def _retune_trades(
        self, sub: Subscription, opts: Mapping[str, Any]
    ) -> tuple[TradesLease, Any] | None:
        """A `ctl` of `min_size` on a held `trades.*` one (§6.1): its new option set, checked
        against the floor and the option-set cap before anything changes (`check_retune`; the
        commit's `retune` moves the lease), or `TopicError`. None when it holds no lease (a
        replay one, or no tape wired)."""
        lease, trades = sub.trades_lease, self.services.trades
        if lease is None or trades is None:
            return None
        options = options_of(opts)
        trades.check_retune(lease, options)
        return lease, options

    def _retune_heatmap(
        self, sub: Subscription, opts: Mapping[str, Any]
    ) -> tuple[HeatmapLease, HeatmapSpec] | None:
        """A `ctl` of `depth`, `price_grouping` or `time_bucket_ms` on a held `heatmap.*` one
        (§5.4, E21-T02): depth 500 while `heatmap_depth_500` is off is `invalid_topic_format`, and
        a new spec past a G-02 cap `subscription_limit`, both before anything changes; the commit's
        `retune` moves the lease. None when it holds no lease (a replay one, or none wired)."""
        lease, heatmap = sub.heatmap_lease, self.services.heatmap
        if lease is None or heatmap is None:
            return None
        spec = spec_of(lease.spec.symbol, opts)
        if spec.depth >= 500 and not self.services.depth_500:
            raise TopicError("invalid_topic_format", "Heatmap depth 500 is not offered.", "depth")
        try:
            heatmap.check_retune(lease, spec)
        except HeatmapSpecCapError as exc:
            raise TopicError("subscription_limit", str(exc)) from None
        return lease, spec

    def _retune(
        self, sub: Subscription, raw: list[dict[str, Any]]
    ) -> tuple[BarSpec, tuple[Requested, ...], list[dict[str, Any]]]:
        """A `ctl` of `instances` (§6.1), checked as a `sub` is and before anything changes:
        `invalid_options` (`resolve_instances`), then the engine's caps and executor
        (`subscription_limit`, `internal_error`). The series is the one `sub` admitted, built from
        the topic alone and not bounded again (`_bar_spec`): a qty step the catalogue changed since
        cannot refuse a retune of a series that stays subscribed. Returns the series, the
        instances and their echo."""
        try:
            spec = from_wire(sub.topic.bar_type or "", sub.topic.param or "")
        except BarsError:  # admitted, so its spec was built once from this topic: never here
            raise TopicError(
                "invalid_options", "This bar series is not available.", "instances"
            ) from None
        try:
            requested = resolve_instances(raw, spec)
        except InstanceRefusedError as exc:
            raise TopicError("invalid_options", str(exc), "instances") from None
        engine = self.services.indicators
        if engine is not None and sub.replay_session_id is None:
            user, consumer = str(self.actor_user_id), self._consumer(sub)
            try:
                engine.check(
                    sub.topic.symbol or "",
                    spec,
                    requested,
                    user,
                    history=_indicator_history(sub),
                    consumer=consumer,
                )
            except InstanceCapError as exc:
                raise TopicError("subscription_limit", str(exc)) from None
            except RecomputeRefusedError as exc:
                raise TopicError("internal_error", str(exc)) from None
        return spec, requested, [r.echo() for r in requested]

    def _hold_instances(
        self, sub: Subscription, spec: BarSpec, requested: tuple[Requested, ...]
    ) -> None:
        """Swap the instances a `ctl` changed (after `_retune` and the rebuild budget): the new
        ones are held, then the old ones the new set leaves out are released (`param_change`).
        One admitted with no engine holds none, and holds none after."""
        engine = self.services.indicators
        if engine is None or not sub.indicator_keys:
            return
        engine.admit(
            sub.topic.symbol or "", spec, requested, self._consumer(sub),
            str(self.actor_user_id), history=_indicator_history(sub),
            replacing=sub.indicator_keys, reason="param_change",
        )  # fmt: skip
        sub.indicator_keys = tuple(r.key for r in requested)

    # -- live revocation (§9.5, S7) -----------------------------------------------------------

    def apply_snapshot(self, new: VersionedSnapshot, now_ms: int) -> list[dict[str, Any]] | None:
        """Swap in `new`; return one `permission_change` then a `revoked` per affected
        subscription. Lost permission or every account -> the subscription is removed; a partial
        scope loss narrows it in place (`removed_accounts`, `resubscribe_allowed: true`) and the
        rest of the connection continues untouched. SR-189: `None`, and nothing changes, when
        `new` is older than the applied snapshot (a read begun before a grant change). #415:
        `SnapshotUserMismatch`, and nothing changes, when `new` is another user's, whatever its
        version: a connection keeps the user it authenticated as (§4.3). The queued frames of
        each affected subscription are dropped before any of these frames is queued (`on_purge`)."""
        if new.principal.user_id != self.principal.user_id:
            raise SnapshotUserMismatch("a permission snapshot of another user")
        if new.version < self.version:
            return None
        self.principal, self.version = new.principal, new.version
        frames: list[dict[str, Any]] = [
            {
                "t": "permission_change",
                "ts": now_ms,
                # §9.5: the identity `auth_ok` gave, the session's own user when viewing.
                "p": auth_ok_payload(new.principal, user_id=str(self.actor_user_id)),
            }
        ]
        affected: list[Subscription] = []
        for sub in sorted(self.by_id.values(), key=lambda s: (s.ch, s.sub_id)):
            frame = self._reevaluate(sub, now_ms)
            if frame is not None:
                frames.append(frame)
                affected.append(sub)
        # #492 (ruling Q6): a principal no longer the Owner narrows the recorded view now, and a
        # `recorder` subscription is re-snapped in it; a new Owner keeps it until a new `sub`
        viewed: set[str] = set()
        if not new.principal.is_owner:
            known = {s.sub_id for s in affected}
            for sub in sorted(self.by_id.values(), key=lambda s: (s.ch, s.sub_id)):
                if not sub.role_restricted:
                    sub.role_restricted = True
                    if sub.topic.family.family == _RECORDER and sub.sub_id not in known:
                        affected.append(sub)
                        viewed.add(sub.sub_id)
        self._withdraw(affected, viewed)
        return frames

    def revoke_account(
        self, account_id: uuid.UUID, reason: AccountRevokedReason, now_ms: int
    ) -> list[dict[str, Any]]:
        """23 §9.5 (E27-S04, #898): the account's last signable key revoked, or the account
        disabled. Each subscription naming it on an account-scoped topic (`orders`, `positions`,
        `executions`, `wallet`, `trade_groups`, `rules`) narrows (`removed_accounts`,
        `resubscribe_allowed: true`) when it names other accounts too, and ends
        (`resubscribe_allowed: false`) when it named only this one; the `machines.*` rows wait
        for B4. Returns `permission_change` then one `revoked` per subscription, in `ch` order,
        or nothing when no subscription names the account. The queued frames are withdrawn as a
        grant change withdraws them, before any of these is queued."""
        if reason not in ACCOUNT_REVOKED_REASONS:
            raise ValueError("not an account revocation reason")
        removed = frozenset({account_id})
        affected: list[Subscription] = []
        revoked: list[dict[str, Any]] = []
        for sub in sorted(self.by_id.values(), key=lambda s: (s.ch, s.sub_id)):
            if sub.topic.entity_kind is not None or account_id not in sub.accounts:
                continue
            kept = sub.accounts - removed
            if kept:
                sub.accounts = kept
                sub.effective["exchange_account_ids"] = sorted(str(a) for a in kept)
            else:
                self._drop(sub)
            revoked.append(self._revoked(sub, reason, now_ms, removed, resubscribe=bool(kept)))
            affected.append(sub)
        if not affected:
            return []
        change = {
            "t": "permission_change",
            "ts": now_ms,
            "p": auth_ok_payload(self.principal, user_id=str(self.actor_user_id)),
        }
        self._withdraw(affected, set())
        return [change, *revoked]

    def _withdraw(self, affected: list[Subscription], viewed: set[str]) -> None:
        """#415: a grant or a permission withdrawn alike, one rule at the sending boundary
        (C-12.4): the affected subscriptions' queued frames are discarded first (§9.5), then a
        narrowed one is re-pended unless paused (its resume re-snapshots it, §5.4, §8.4 step 1):
        flag on always, flag off once its frames went."""
        purged = self.on_purge(affected) if self.on_purge is not None and affected else set()
        self._dropped(affected)
        for sub in affected:
            gone = (sub.ch, sub.replay_session_id) in purged
            if self.on_drop is None and not gone and sub.sub_id not in viewed:
                continue
            paused = sub.effective.get("paused") is True
            if sub.sub_id in self.by_id and not (sub.snapshot_pending or paused):
                sub.snapshot_pending, sub.pending_reason = True, "reconfigure"
                self.settling.append(sub)

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
            sub_id=sub.sub_id,
            rs=sub.replay_session_id,
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

    #3413 (SR-029, UL1-E2): `user_disabled` also remembers the user with the disable instant for
    `disabled_memory_s`, so the gateway refuses a socket that registers after the per-user close
    on a token issued at or before it (`issued_before_disable`). The memory is bounded (C-2.18) as
    `RevocationHub`'s is: entries expire on `monotonic`, and past `max_disabled` the oldest is
    forgotten first, which reopens that window for that user only and is logged (throttled).

    Two spans, kept apart. `access_token_ttl_s` is how long a token lives: the gateway knows a
    token only by its expiry, and expiry less this is how that token is dated. It must not be
    shorter than the tokens' real lifetime, or a token issued before a disable is dated after it
    and let in, and not longer, or a token issued after the disable is refused. `disabled_memory_s`
    is how long a disable is remembered, and must be at least `access_token_ttl_s`, or a disable
    is forgotten while a token issued before it is still live. The constructor refuses a shorter
    memory (fail closed); a longer one only keeps an entry longer. The composition root passes
    both from `ACCESS_TOKEN_TTL`.
    """

    def __init__(
        self,
        resolve: Callable[[uuid.UUID], Awaitable[PrincipalSnapshot]],
        clock_ms: Callable[[], int],
        services: SubscriptionServices | None = None,
        *,
        disabled_memory_s: float = DISABLED_MEMORY_S,
        access_token_ttl_s: float = ACCESS_TOKEN_TTL_S,
        max_disabled: int = MAX_DISABLED_USERS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        spans = (disabled_memory_s, access_token_ttl_s)
        if not all(math.isfinite(s) and s > 0 for s in spans) or max_disabled < 1:
            raise ValueError(
                "disabled_memory_s and access_token_ttl_s must be finite and > 0, "
                "and max_disabled >= 1"
            )
        if disabled_memory_s < access_token_ttl_s:
            raise ValueError(
                "disabled_memory_s must be at least access_token_ttl_s: a shorter memory forgets "
                "a disable while a token issued before it is still live"
            )
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
        self._disabled_memory_s = disabled_memory_s
        self._access_token_ttl_s = access_token_ttl_s
        # Rounded up: float error must never leave it below the real lifetime (a token let in).
        self._token_ttl_ms = math.ceil(access_token_ttl_s * 1000)
        self._max_disabled = max_disabled
        self._monotonic = monotonic
        #: user id -> (monotonic expiry, disable instant in wall ms), oldest first. Every entry
        #: lives the same span from a non-decreasing clock, so insertion order is expiry order.
        self._disabled: collections.OrderedDict[uuid.UUID, tuple[float, int]] = (
            collections.OrderedDict()
        )
        #: Live entries forgotten at the cap, and when that was last logged.
        self._disabled_evicted = 0
        self._disabled_evicted_logged_at: float | None = None
        #: Per-user closes that failed (raised or hit `send_timeout_s`) since this registry
        #: started, all users together, and when one was last logged (#3635).
        self._close_failures = 0
        self._close_failure_logged_at: float | None = None

    @property
    def disabled_memory_s(self) -> float:
        """Seconds a disabled user is remembered: at least `access_token_ttl_s`."""
        return self._disabled_memory_s

    @property
    def access_token_ttl_s(self) -> float:
        """Seconds an access token lives, by which a token's expiry is dated."""
        return self._access_token_ttl_s

    @property
    def max_disabled(self) -> int:
        """Most disabled users remembered at once; past it the oldest is forgotten first."""
        return self._max_disabled

    def _prune_disabled(self, now: float) -> None:
        while self._disabled:
            user_id, (expires_at, _) = next(iter(self._disabled.items()))
            if expires_at > now:
                return
            del self._disabled[user_id]

    def _remember_disabled(self, user_id: uuid.UUID) -> None:
        now = self._monotonic()
        self._prune_disabled(now)
        self._disabled.pop(user_id, None)  # a repeat renews the entry and its instant
        self._disabled[user_id] = (now + self._disabled_memory_s, self._clock_ms())
        while len(self._disabled) > self._max_disabled:
            self._disabled.popitem(last=False)  # pruned above, so this one was still live
            self._disabled_evicted += 1
            logged_at = self._disabled_evicted_logged_at
            if logged_at is None or now - logged_at >= EVICTION_LOG_EVERY_S:
                self._disabled_evicted_logged_at = now
                # A failing log sink must never skip the closes that follow (C-2.12).
                with contextlib.suppress(Exception):
                    _log().warning(
                        "ws disabled-user memory full; oldest live entry forgotten",
                        evicted_total=self._disabled_evicted,
                        max_disabled=self._max_disabled,
                    )

    def issued_before_disable(self, user_id: uuid.UUID, token_expires_ms: int) -> bool:
        """Whether `user_id` was disabled, within the last `disabled_memory_s`, at or after the
        instant its access token was issued. The token expires at `token_expires_ms`, which is
        its issue instant plus `ACCESS_TOKEN_TTL` capped by the session's absolute expiry
        (`access_token_expires_at`), so the expiry less `access_token_ttl_s` is never later than
        the issue: every token issued at or before the disable is refused, and one issued after
        it (a user re-enabled who signed in again) is not. Both instants are UTC wall-clock ms:
        the disable is read from `clock_ms`, the token's from the session service's clock. The
        keyless testnet's `CV_TEST_CLOCK` (#2086) offsets that clock and not this one, as it
        leaves the gateway's deadlines alone: there the comparison is skewed by the offset."""
        self._prune_disabled(self._monotonic())
        entry = self._disabled.get(user_id)
        return entry is not None and token_expires_ms - self._token_ttl_ms <= entry[1]

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
        effort, like every WS audit write) and yields no frames (SR-189). A snapshot of another
        user raises `SnapshotUserMismatch` first, with no count and no row (#415). A viewing
        socket never takes an Owner's snapshot: its view ends instead (§9.6, `_end_views`)."""
        if authz.viewing and snap.principal.is_owner:  # §9.6: never an Owner's snapshot
            await self._end_views([(authz, None, None)])
            return []
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
            "actor_user_id": authz.actor_user_id,
            "session_id": authz.session_id,
            "object_kind": "ws_connection",
            "object_id": authz.connection_id,
            "outcome": AuditOutcome.DENIED,
            "severity": Severity.WARNING,
            "reason": "stale",
            "after_state": {"event": event, **versions},
            "request_id": authz.request_id,
        }
        return [], [_AuditRow(audit, "ws.permission_snapshot.refused", fields)]

    async def recheck(self, authz: ConnectionAuthz) -> None:
        """SR-189, right after `register` and before `auth_ok`: a change (any user's; one extra
        read at worst) begun after `authz`'s read may have fanned out before it was registered."""
        if authz.version >= self._changed_at:
            return
        snap = await self.resolve(authz.principal.user_id)
        await self.apply(authz, snap, self._clock_ms(), event="handshake")  # ends an Owner's view

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
        if snap.principal.is_owner:  # §9.6: a target is never an Owner, so the views end
            entries = await self._end_views(entries)
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

    async def _end_views(self, entries: list[Any]) -> list[Any]:
        """§9.6 (#3085): a socket viewing as a user who became an Owner never applies the Owner's
        snapshot: it is unregistered and released, then closed `view_as_expired` (4403, sealed),
        each bounded, a failure ignored as an eviction's is. The service ends the context itself
        (the target is no longer eligible). Returns the entries that are not viewing."""
        kept: list[Any] = []
        for entry in entries:
            authz = entry[0]
            if not authz.viewing:
                kept.append(entry)
                continue
            closer = self._closers.get(id(authz))
            self.unregister(authz)  # released there
            if closer is not None:
                with contextlib.suppress(Exception):
                    async with asyncio.timeout(self.send_timeout_s):
                        await closer(
                            lifecycle_bye("view_as_expired", now_ms=self._clock_ms()), 4403
                        )
        return kept

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
        loop's (§7.5; SR-187, #2174) and an in-place re-`auth`'s, once its `auth_ok` and frames are
        queued (#415, E17-R-13), through the same bounded writer as a fan-out's."""
        await self._write_rows(_revocation_rows(authz, frames))

    async def audit_revoked_many(
        self, revoked: list[tuple[ConnectionAuthz, dict[str, Any]]]
    ) -> None:
        """The rows of one §6.4 removal's `revoked` frames, each with its connection: written as one
        run, in order, one at a time, under one failure budget (`_write_rows`)."""
        rows = [r for authz, frame in revoked for r in _revocation_rows(authz, [frame])]
        await self._write_rows(rows)

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

    async def account_revoked(self, account_id: uuid.UUID, reason: AccountRevokedReason) -> int:
        """23 §9.5 (E27-S04, #898): every live socket whose subscriptions name the account gets
        `permission_change`, then a `revoked` (`key_revoked` or `account_disabled`) per
        subscription (`ConnectionAuthz.revoke_account`), sent as a grant change's are: each
        socket's subscriptions change synchronously before any send, a socket that stalls or
        breaks is evicted, and the `ws.subscription.revoked` rows are written after the sends,
        on any exit. Returns how many sockets got frames. Another reason is refused
        (`ValueError`) before anything changes."""
        if reason not in ACCOUNT_REVOKED_REASONS:
            raise ValueError("not an account revocation reason")
        rows: list[_AuditRow] = []
        try:
            now_ms = self._clock_ms()
            entries = [e for group in list(self._conns.values()) for e in group]
            changed: list[tuple[ConnectionAuthz, Any, Any, list[dict[str, Any]]]] = []
            evicted: list[Any] = []
            for authz, send, close in entries:  # every socket changes before any I/O
                try:
                    frames = authz.revoke_account(account_id, reason, now_ms)
                except Exception:  # half changed: evicted as a failed swap is (`_swap_or_evict`)
                    with contextlib.suppress(Exception):
                        _log().error(
                            "ws account revocation failed; socket evicted",
                            connection_id=authz.connection_id,
                            exc_info=True,
                        )
                    self.unregister(authz)
                    evicted.append(close)
                    continue
                if frames:
                    rows.extend(_revocation_rows(authz, frames))
                    changed.append((authz, send, close, frames))
            for close in evicted:  # closed before any send
                await self._close_evicted(close)
            for authz, send, close, frames in changed:
                try:
                    async with asyncio.timeout(self.send_timeout_s):
                        for frame in frames:
                            await send(frame)
                except (TimeoutError, OSError, RuntimeError):
                    self.unregister(authz)  # C-2.18: a stalled client never holds the others
                    await self._close_evicted(close)
                else:
                    await self.settle(authz, close)
        finally:
            await self._write_rows(rows)
        return len(changed)

    async def user_disabled(self, user_id: uuid.UUID) -> int:
        """§9.5: a disabled user gets `bye user_disabled` + close 4403 on every socket, including
        one on which it views as another user (#3085). That socket is registered under its
        target, so it is found by its viewer (`_pop_views_by`) and is closed and counted as the
        user's own are. A socket viewing as the disabled user ends its view instead, with `bye
        view_as_expired` (§9.6), and is not counted. #3413: first the user is remembered and the
        version advances, so a socket still in its handshake reads its principal again (SR-189)
        and the gateway refuses its registration.

        One observation of `auth_revocation_latency_seconds` when there is any socket (SR-029,
        #3415), on `services.clock`, as the revocation hub makes one for a session's closes:
        from this call to the last close initiated or failed, however many sockets there are. The
        gateway's closer queues the `bye` and seals the connection, and its writer closes the
        socket later, which is not measured. Made in a `finally`, so a close that raised, one cut
        off at `send_timeout_s` and a caller that cancelled mid-batch (the disable cascade bounds
        this step at 2 s and does not shield it) are timed too.

        A close that raised or was cut off at `send_timeout_s` is a failed close (#3635). It is
        counted on `ws_session_revocation_close_failures_total`, the hub's counter, and logged at
        most once per `CLOSE_FAILURE_LOG_EVERY_S` with the registry's running total
        (`_close_failed`); the user's other sockets are still closed. The call still returns how
        many sockets it tried and the disable cascade's `socket_close` step still ends `ok`, so
        the counter and its log line are the only signs. The socket can stay open until its access
        token expires (12 minutes at most); REST has refused the user since the disable, and
        orders are REST only. A cancellation (the cascade's 2 s cut, which opens before
        `send_timeout_s` and so ends a hung closer first) is not a failed close: it is not counted,
        and it propagates."""
        self._changed_at = next(self._versions)  # SR-189: also for a socket mid-handshake
        self._remember_disabled(user_id)  # before the closes, which suspend
        entries = [*self._conns.pop(user_id, []), *self._pop_views_by(user_id)]
        if not entries:
            return 0
        started = self.services.clock()
        try:
            for authz, _send, close in entries:
                closer = self._closers.pop(id(authz), None)
                authz.release_all()
                try:
                    # §9.6: the viewed target is gone, the viewer is not; a socket the disabled
                    # user views with is its own, under whichever target it is registered
                    if authz.viewing and authz.viewer_user_id != user_id:
                        bye = lifecycle_bye("view_as_expired", now_ms=self._clock_ms())
                    else:
                        ws_revoked_total.labels(reason="user_disabled").inc()
                        bye = user_disabled_bye(self._clock_ms())
                    async with asyncio.timeout(self.send_timeout_s):
                        if closer is not None:
                            await closer(bye, 4403)
                        elif close is not None:
                            await close()
                except Exception:
                    # Raised or cut off at the bound: counted, and the next socket is still closed.
                    # A cancellation is no `Exception`, so it propagates, uncounted.
                    self._close_failed(user_id)
        finally:
            auth_revocation_latency_seconds.observe(self.services.clock() - started)
        return len(entries)

    def _pop_views_by(self, viewer_id: uuid.UUID) -> list[tuple[ConnectionAuthz, Any, Any]]:
        """§9.6 (#3085): the sockets on which `viewer_id` views as another user, under whichever
        target they are registered (`register` keys a viewing socket by its target), removed from
        their lists as `user_disabled` removes the user's own. One pass over the registry: a
        disable is rare, and the gateway bounds each user's sockets. Their closers are popped
        with the closes, as the user's own are."""
        found: list[tuple[ConnectionAuthz, Any, Any]] = []
        for key, entries in list(self._conns.items()):
            kept = [e for e in entries if e[0].viewer_user_id != viewer_id]
            if len(kept) == len(entries):
                continue
            found += [e for e in entries if e[0].viewer_user_id == viewer_id]
            if kept:
                self._conns[key] = kept
            else:
                del self._conns[key]
        return found

    def _close_failed(self, user_id: uuid.UUID) -> None:
        """One failed per-user close, called from the handler of its exception (#3635). Counted
        first, so nothing after it can lose the count, then logged with that traceback at most
        once per `CLOSE_FAILURE_LOG_EVERY_S` on `monotonic`: a window opens at a logged line, not
        at a counted failure, and the line carries this registry's running total of failures."""
        ws_revocation_close_failures_total.inc()
        self._close_failures += 1
        now = self._monotonic()
        logged_at = self._close_failure_logged_at
        if logged_at is None or now - logged_at >= CLOSE_FAILURE_LOG_EVERY_S:
            self._close_failure_logged_at = now
            # A failing log sink must never skip the closes that follow (C-2.12); the counter
            # above still records the failure.
            with contextlib.suppress(Exception):
                _log().error(
                    "ws revocation close failed; disabled user's socket may remain open",
                    user_id=str(user_id),
                    failed_total=self._close_failures,
                    exc_info=True,
                )


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
    refusals the audit keeps are written as ONE record for the frame (`_audit_denials`). Fair
    scheduling between connections: it yields to the loop after every `SUB_ENTRIES_PER_STEP`
    entries, an await of the frame like any other below.

    #2831: the new subscriptions are announced only once the `sub_ok` is queued, so no hub
    flush or resnapshot during the awaits below can send a `snap` ahead of it; the gateway's
    flush then sends it. A refused topic is dropped unannounced. One left unannounced by a
    raise or a cancellation never gets a `snap`: the connection ends (a raise closes it 1011)
    and its teardown releases the subscription. Its private ones are audited next (SR-186).

    #2896: one that a change (§9.5) ends before the reply is queued, in its own
    `subscribe_upstream` or a later await of the frame, is refused in it (`ended_result`), after
    that change's `permission_change` and `revoked`; it is never announced. The change records it
    (`ws.subscription.revoked`), so it is no `ws.subscribe.denied` refusal: only `admit`'s are."""
    body: Any = frame.get("p")  # a dict once `sub_shape_error` passes it
    fid = _frame_id(frame)
    shape = sub_shape_error(body)
    if shape is not None:
        await send(build_ws_error(shape.code, id=fid, message=shape.message, field=shape.field))
        return
    results: list[dict[str, Any]] = []
    admitted: list[Subscription] = []
    denials: list[tuple[str, str, str]] = []  # (object_id, code, reason) of each kept refusal
    spent: list[tuple[str, BudgetScope]] = []  # SR-193: each budget refusal's `ch` and limit
    snapshot = body.get("snapshot", True)
    replay = body.get("replay_session_id")
    rs = parse_replay_session_id(replay)  # §5.2 (#3218): on each result but `system`'s, refused too
    try:
        for i, entry in enumerate(body["topics"]):  # at most `MAX_TOPICS_PER_SUB`, by the shape
            if i and not i % SUB_ENTRIES_PER_STEP:  # fair scheduling: a bounded step (C-2.17)
                await asyncio.sleep(0)
            ch: str = entry["ch"] if isinstance(entry, dict) else entry  # a topic name, by shape
            result, sub = authz.admit(entry, snapshot=snapshot, replay_session_id=replay)
            why = authz.refusal_reason  # a refused entity's internal reason; read before any await
            narrowed = authz.narrowed  # E17-R-15: accounts narrowed away; read before any await
            if authz.refusal_scope is not None:
                spent.append((ch, authz.refusal_scope))
            if sub is not None:
                result = await authz.subscribe_upstream(sub) or result
                if result["ok"]:
                    admitted.append(sub)
                    key, held = topic_key(sub.topic, sub.replay_session_id), sub.rebuild_held
                    sub.rebuild_held = False  # #3476: its hold becomes the draw, in one step
                    authz.rebuilds.draw(key, "sub", held=held)
            if rs is not None and ch != SYSTEM_TOPIC:
                result["rs"] = rs
            results.append(result)
            # `admit`'s refusals (§5.2): `subscribe_upstream` refuses public bar topics, which
            # `_audited` keeps none of, and one a change ended, which that change records (#2896).
            if not result["ok"] and sub is None:
                code = result["error"]["code"]
                if _audited(ch, code):
                    denials.append(_denial(ch, code, why))
            elif result["ok"] and narrowed:  # §6.2: silent in the reply, counted and recorded
                cv_ws_subscribe_narrowed_total.inc(narrowed)
                denials.append(_denial(ch, "account_scope_denied", "narrowed"))
    finally:  # a raise or a cancellation mid-loop still records the refusals before it (C-2.9)
        await _audit_denials(authz, denials)
    _refuse_ended(authz, admitted, results, rs)  # #2896: no await from here to the reply
    # each topic once, as the reply answers it (§6.2); none if the frame raised or was cancelled
    for r in results:
        _observe(r["ch"], r)
    if spent:  # SR-193: one line for the frame, naming its first budget refusal (§7.7)
        authz.rebuilds.log(
            "sub", spent[0][1], authz.connection_id, spent[0][0], rs=rs, count=len(spent)
        )
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
    await audit_rebuild_refusal(authz)  # #3476: a user's first `user` refusal in a window


def _refuse_ended(
    authz: ConnectionAuthz,
    admitted: list[Subscription],
    results: list[dict[str, Any]],
    rs: str | None,
) -> None:
    """#2896: an admitted subscription that a change ended after its own `subscribe_upstream`, in a
    later await of the frame (another topic's, the denial record's), took nothing after that end,
    and the change queued its `revoked`: its result becomes `ended_result`, which follows, and it
    is no longer admitted (no `snap`, no grant record). Its draw stays, as a start's does."""
    for sub in [s for s in admitted if authz.by_id.get(s.sub_id) is not s]:
        admitted.remove(sub)
        refused = authz.ended_result(sub)
        if rs is not None:  # as on each result of the frame but `system`'s (§5.2)
            refused["rs"] = rs
        results[next(i for i, r in enumerate(results) if r.get("sub_id") == sub.sub_id)] = refused


def handle_unsub(authz: ConnectionAuthz, frame: dict[str, Any], now_ms: int) -> dict[str, Any]:
    """§5.3 `unsub` -> `unsub_ok`: idempotent. Unknown/already-removed -> `ok: true, noop: true`;
    `system` is permanent -> `ok: false` and stays attached. A frame whose shape breaks §13.5 is
    refused whole instead: one `err`, nothing unsubscribed and no strike (#2572), a `topics` array
    over `MAX_TOPICS_PER_SUB` included (#2875), and so is one whose envelope `rs` is not a uuid
    (W10, #3218: an `rs` names each `ch`'s stream in that session; no `rs`, the live one)."""
    fid = _frame_id(frame)
    body: Any = frame.get("p")  # a dict once `unsub_shape_error` passes it
    shape = unsub_shape_error(body)
    if shape is not None:
        return build_ws_error(shape.code, id=fid, message=shape.message, field=shape.field)
    try:
        rs = _named_session(frame.get("rs"))  # W10: one `rs` names the stream of every entry
    except TopicError as exc:
        return build_ws_error(exc.code, id=fid, message=exc.message, field=exc.field)
    results: list[dict[str, Any]] = []
    for ch in body["topics"]:  # topic names, by the shape
        if ch == SYSTEM_TOPIC:
            results.append({"ch": ch, "ok": False})
        elif (ended := authz.unsubscribe(ch, rs)) is not None:  # §5.3 (#3218): the one it ended
            results.append({"ch": ch, "ok": True, "ended": [_name(ended)]})
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
        effective, resnapshot, sub = authz.ctl(ch, frame.get("p"), frame.get("rs"))
    except TopicError as exc:
        return build_ws_error(
            exc.code,
            id=fid,
            ch=ch if is_topic_name(ch) else None,
            rs=parse_replay_session_id(frame.get("rs")),  # §7.5: beside a `ch`, when it is a uuid
            message=exc.message,
            field=exc.field,
        )
    p: dict[str, Any] = {"effective": effective}
    if resnapshot:
        p["resnapshot"] = True
    p["sub_id"] = sub.sub_id  # §5.4 (#3218): the one retuned; a replay one's `rs` is below
    out: dict[str, Any] = {"t": "ctl_ok", "ch": ch, "ts": now_ms, "p": p}
    if sub.replay_session_id is not None:
        out["rs"] = sub.replay_session_id
    if fid is not None:
        out["id"] = fid
    return out


def _name(sub: Subscription) -> dict[str, str]:
    """An `unsub_ok` `ended` entry (§5.3): the `sub_id`, and a replay subscription's `rs`."""
    name = {"sub_id": sub.sub_id}
    if sub.replay_session_id is not None:
        name["rs"] = sub.replay_session_id
    return name


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


def _kept_back(authz: ConnectionAuthz) -> None:
    """A `ws.subscribe.denied` record past the connection's budget (#3185): counted every time,
    deliberately not a `count_audit_failure`; the warning names the socket and the user, once a
    window (`first_denial_skip`)."""
    cv_ws_subscribe_denied_unaudited_total.inc()
    if authz.first_denial_skip():
        _log().warning(
            "ws subscribe-denied audit over budget",
            connection_id=authz.connection_id,
            actor_user_id=authz.actor_user_id,
            limit=DENIAL_AUDITS_PER_WINDOW,
            window_s=DENIAL_AUDIT_WINDOW_S,
        )


async def _audit_denials(authz: ConnectionAuthz, denials: list[tuple[str, str, str]]) -> None:
    """`ws.subscribe.denied`: ONE record for the refusals `_audited` keeps in a `sub` frame,
    never one per entry (SR-192, #2292), written in `handle_sub`'s `finally`, so a frame that
    raises or is cancelled part way still records those before the fault. Its `object_id` and
    `reason` are the first one's, so a frame with one writes the row that refusal writes alone.
    It names the socket: its session in the `session_id` column, as the close row's; its
    `connection_id` in `after_state` (#415, E17-R-16), since the row's `object_id` is the topic;
    its upgrade's `request_id` (#3990).
    With more than one refusal, `after_state` also
    holds the `count` of them all, every code among them (`codes`, sorted) and the
    `[object_id, reason]` of the first `MAX_DENIALS_LISTED` in request order (`refusals`). An
    entry narrowed to fewer accounts than it named is one, with code `account_scope_denied` and
    reason `narrowed` (§6.2, E17-R-15). An internal reason goes only in `reason` and
    `after_state`, which the non-Owner projection drops (SR-067), so no other field varies with it
    (the non-Owner projection is being narrowed by E42-T02 F9). Best effort, bounded at
    `FANOUT_AUDIT_TIMEOUT_S`: a record not confirmed is logged and counted, and so is a
    cancellation, which still propagates.

    #3185 (§4.3): within the connection's budget only (`ConnectionAuthz.take_denial_audit`),
    checked before the emit. A record past it reaches no writer and the frame waits for none:
    it counts once in `cv_ws_subscribe_denied_unaudited_total`, and `_kept_back` logs it at
    most once a window."""
    audit = authz.services.audit
    if audit is None or not denials:
        return
    if not authz.take_denial_audit():
        _kept_back(authz)
        return
    object_id, _, reason = denials[0]
    after: dict[str, Any] = {"connection_id": authz.connection_id}
    if len(denials) > 1:
        after["count"] = len(denials)
        after["codes"] = sorted({c for _, c, _ in denials})
        after["refusals"] = [[o, r] for o, _, r in denials[:MAX_DENIALS_LISTED]]
    try:
        await _emit_bounded(
            audit,
            "ws.subscribe.denied",
            actor_label="ws",
            actor_user_id=authz.actor_user_id,
            session_id=authz.session_id,
            object_kind="ws_topic",
            object_id=object_id,
            outcome=AuditOutcome.DENIED,
            severity=Severity.WARNING,
            reason=reason,
            after_state=after,
            request_id=authz.request_id,
        )
    except Exception:
        count_audit_failure()  # SR-E17-04: `timeout` (it may still land) or `error`
        _log().warning(
            "ws subscribe-denied audit not confirmed",
            connection_id=authz.connection_id,
            actor_user_id=authz.actor_user_id,
            exc_info=True,
        )
    except asyncio.CancelledError:
        count_audit_failure()  # lost unless its append had begun; the cancel still propagates
        raise


async def audit_rebuild_refusal(authz: ConnectionAuthz) -> None:
    """#3476 (§7.7): the one `ws.rebuild.refused` record of a user's window, for the `user` refusal
    the connection's last request left due (`RebuildBudget.audit_due`): written after that
    request's reply, by `handle_sub` and by the gateway after a `ctl` or `resync`. The window is
    marked here, as the write starts (`first_user_refusal`), so a request that ended first leaves
    it to the user's next refusal. Its object is named as `ws.subscribe.denied`'s (`_denial`),
    never with the client's text, and it names the socket as that row does: its session in the
    `session_id` column, its `connection_id` in `after_state` (#415, E17-R-16), its upgrade's
    `request_id` (#3990). Best effort,
    bounded at `FANOUT_AUDIT_TIMEOUT_S`: a record not confirmed is counted and logged, and a
    cancellation is counted and propagates; neither changes the refusal, which already went out."""
    key, authz.rebuilds.audit_due = authz.rebuilds.audit_due, None
    audit = authz.services.audit
    if key is None or audit is None or not authz.rebuilds.first_user_refusal():
        return
    object_id, _, reason = _denial(key[0], "resync_rate_limited", "user")
    try:
        await _emit_bounded(
            audit,
            "ws.rebuild.refused",
            actor_label="ws",
            actor_user_id=authz.actor_user_id,
            session_id=authz.session_id,
            object_kind="ws_topic",
            object_id=object_id,
            outcome=AuditOutcome.DENIED,
            severity=Severity.WARNING,
            reason=reason,
            after_state={"connection_id": authz.connection_id},
            request_id=authz.request_id,
        )
    except Exception:
        count_audit_failure()  # SR-E17-04: `timeout` (it may still land) or `error`
        with contextlib.suppress(Exception):  # a failing logger must not reach the request
            _log().warning(
                "ws audit not confirmed",
                action="ws.rebuild.refused",
                object_id=object_id,
                actor_user_id=authz.actor_user_id,
                exc_info=True,
            )
    except asyncio.CancelledError:
        count_audit_failure()  # lost unless its append had begun; the cancel still propagates
        raise


#: §6.4: a `machines` revocation's internal reason. `_reevaluate_entity` revokes with
#: `permission_revoked` exactly when the row refuses on `role`; otherwise the subscription held
#: its entity at `sub`, so the refusal is `foreign`. A removed entry's `topic_removed` is `evicted`.
_MACHINE_REVOKED: Final = {
    "permission_revoked": "role",
    "account_scope_changed": "foreign",
    "topic_removed": "evicted",
}


def _revocation_rows(authz: ConnectionAuthz, frames: list[dict[str, Any]]) -> list[_AuditRow]:
    """`ws.subscription.revoked`: one row per `revoked` frame, in frame order (WS-R02), naming the
    socket: its session in the `session_id` column, as the close row's; its `connection_id` in
    `after_state` (#415, E17-R-16), since the row's `object_id` is the topic; its upgrade's
    `request_id` (#3990). A `machines` row
    names the full `ch` and its internal §6.4 reason, in `reason` only (SR-067), as a refusal's
    row does."""
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
                    "actor_user_id": authz.actor_user_id,
                    "session_id": authz.session_id,
                    "object_kind": "ws_topic",
                    "object_id": ch if machines else ch[:40],
                    "reason": _MACHINE_REVOKED.get(reason, reason) if machines else reason,
                    "after_state": {  # §7.5 (#3218): it names the subscription, as `f` does
                        "removed_accounts": f["p"].get("removed_accounts", []),
                        "sub_id": f["p"]["sub_id"],
                        **({"rs": f["rs"]} if "rs" in f else {}),
                        "connection_id": authz.connection_id,
                    },
                    "request_id": authz.request_id,
                },
            )
        )
    return rows


def _confidential(sub: Subscription) -> bool:
    """#415 (E17-R-14, WS-R01): a subscription `ws.subscribe.granted` records: one of a private
    family, but not of a `machines` kind that no account or user scopes (§6.4: `book`,
    `recording`, `kill_switch`, `live_gate`), whose state every holder of its permission reads."""
    kind = sub.topic.entity_kind
    unscoped = kind is not None and MACHINE_KINDS[kind].scope is Scope.NONE
    return sub.topic.family.private and not unscoped


async def _audit_grants(authz: ConnectionAuthz, subs: list[Subscription]) -> None:
    """`ws.subscribe.granted` (SR-186, WS-R01): ONE record for the private-topic subscriptions a
    `sub` frame made, never one per topic (as SR-192, #2292, makes the denial record). Its
    `object_id` is the connection, and `after_state` holds their `count` and the `ch` and account
    ids of the first `MAX_GRANTS_LISTED` in request order (`subscriptions`). Written once the
    `sub_ok` is queued, best effort (threat model WS-R04) and bounded at `FANOUT_AUDIT_TIMEOUT_S`:
    a row not confirmed is logged and counted, and so is a cancellation, which still propagates.

    #415 (E17-R-14): only the subscriptions `_confidential` names, and within the connection's own
    budget (`take_grant_audit`, the size and window of the denial records'); a record past it is
    counted in `cv_ws_subscribe_granted_unaudited_total`, not written."""
    audit = authz.services.audit
    private = [s for s in subs if _confidential(s)]
    if audit is None or not private:
        return
    if not authz.take_grant_audit():
        cv_ws_subscribe_granted_unaudited_total.inc()
        return
    listed = [[s.ch, sorted(str(a) for a in s.accounts)] for s in private[:MAX_GRANTS_LISTED]]
    try:
        await _emit_bounded(
            audit,
            "ws.subscribe.granted",
            actor_label="ws",
            actor_user_id=authz.actor_user_id,
            session_id=authz.session_id,
            object_kind="ws_connection",
            object_id=authz.connection_id,
            outcome=AuditOutcome.SUCCESS,
            severity=Severity.INFO,
            after_state={"count": len(private), "subscriptions": listed},
            request_id=authz.request_id,  # the socket's upgrade id, wherever this runs
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
