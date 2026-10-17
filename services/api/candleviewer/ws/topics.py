"""Declarative WS topic registry, parser and option validator (E17-S02; `23-ws-protocol.md` §5-§6).

The registry is DATA, not code branches: one `TopicFamily` row per family gives the name shape,
the option schema (types, ranges), the required permission and scope, the default throttle,
whether a binary form exists, the payload schema and which options change state identity
(`ctl` -> `resnapshot`). `sub_ok.effective`, error messages and the conformance tests are all
derived from `FAMILIES`, so a new topic is one table row.

Topic strings are parsed ONCE at subscribe time (`parse_topic`, a dict hit on the family plus a
segment-shape check); nothing on the data path ever re-parses them.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final, Literal

from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import Allow, Deny, PrincipalSnapshot, decide

#: §13 `common.schema.json#/$defs/symbol`: a USDT linear perpetual (the only product, C-1.3).
SYMBOL_RE: Final = re.compile(r"^[A-Z0-9]{2,20}USDT$")
#: §6.4 `uuid` ids: the lowercase canonical form only, so each machine has one topic name.
_UUID_RE: Final = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_DECIMAL_RE: Final = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")
#: Accepted characters of a bars/footprint `param`; dots are illegal (§6.1, use a colon).
_PARAM_RE: Final = re.compile(r"^[A-Za-z0-9:]{1,24}$")
_SEGMENT_RE: Final = re.compile(r"^[A-Za-z0-9:_]+$")
TOPIC_MAX_LEN: Final = 120
#: §13 `common.schema.json#/$defs/topic`: the shape of a topic name, before it is looked up (§6).
TOPIC_NAME_RE: Final = re.compile(r"^[a-z_]+(\.[A-Za-z0-9:_-]+)*$")
MIN_THROTTLE_MS: Final = 50
DEPTHS: Final = frozenset({1, 50, 200, 500})
BAR_TYPES: Final = frozenset(
    {"time", "tick", "volume", "range", "delta", "renko", "pnf", "heikin_ashi"}
)
PROFILE_KINDS: Final = frozenset({"volume", "delta", "tpo"})
#: §5.4: options whose change invalidates the state -> `ctl_ok.resnapshot`.
IDENTITY_OPTIONS: Final = frozenset({"depth", "price_grouping", "metrics", "time_bucket_ms"})
#: §13.6 `ctl` schema keys (universal + identity + the two tunables).
CTL_KEYS: Final = frozenset({"throttle_ms", "coalesce", "paused", "min_size"} | IDENTITY_OPTIONS)
#: Options that select WHICH data a subscription may see (accounts, symbols, rules). They are
#: fixed at `sub` time, where they are authorised; `ctl` must never change them (no scope
#: widening by retune). Disjoint from `CTL_KEYS` by construction (asserted in tests).
SCOPE_OPTIONS: Final = frozenset({"exchange_account_ids", "symbols", "rule_ids"})

#: `state` is the literal suffix of `machines.{entity}.state`; every other segment is a variable.
Segment = Literal["symbol", "depth", "bar_type", "param", "profile_kind", "entity", "state"]
OptKind = Literal["int", "number", "bool", "enum", "decimal", "uuids", "symbols", "strings", "str"]


def is_topic_name(ch: Any) -> bool:
    """`ch` has the §13 topic shape; it may still name no topic in the catalogue (§6)."""
    return (
        isinstance(ch, str)
        and 0 < len(ch) <= TOPIC_MAX_LEN
        and TOPIC_NAME_RE.fullmatch(ch) is not None
    )


class TopicError(Exception):
    """A per-topic rejection carrying a §10.2 catalogue code (and the offending `field`)."""

    def __init__(self, code: str, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


@dataclass(frozen=True)
class Opt:
    """One option's schema (mirrors §13.5 `sub.schema.json#/$defs/options`)."""

    kind: OptKind
    lo: float | None = None
    hi: float | None = None
    choices: frozenset[Any] = frozenset()
    min_items: int = 0
    max_items: int | None = None

    def check(self, name: str, value: Any) -> Any:
        """Return the validated value or raise `invalid_options` naming `name`."""
        ok = _CHECKS[self.kind](self, value)
        if not ok:
            raise TopicError("invalid_options", f"Option '{name}' is out of range.", name)
        if self.kind == "uuids":
            return sorted({str(uuid.UUID(str(v))) for v in value})
        return value


def _in_range(o: Opt, v: float) -> bool:
    return (o.lo is None or v >= o.lo) and (o.hi is None or v <= o.hi)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _items(o: Opt, v: Any, item: Callable[[Any], bool]) -> bool:
    if not isinstance(v, list) or len(v) < o.min_items:
        return False
    if o.max_items is not None and len(v) > o.max_items:
        return False
    return all(item(x) for x in v)


def _uuid_ok(v: Any) -> bool:
    try:
        uuid.UUID(str(v))
    except ValueError:
        return False
    return isinstance(v, str)


_CHECKS: Final[dict[str, Callable[[Opt, Any], bool]]] = {
    "int": lambda o, v: _is_int(v) and _in_range(o, v),
    "number": lambda o, v: (_is_int(v) or isinstance(v, float)) and _in_range(o, v),
    "bool": lambda o, v: isinstance(v, bool),
    "enum": lambda o, v: not isinstance(v, bool) and v in o.choices,
    "decimal": lambda o, v: isinstance(v, str) and bool(_DECIMAL_RE.match(v)),
    "uuids": lambda o, v: _items(o, v, _uuid_ok),
    "symbols": lambda o, v: _items(o, v, lambda s: isinstance(s, str) and bool(SYMBOL_RE.match(s))),
    "strings": lambda o, v: _items(o, v, lambda s: isinstance(s, str) and 0 < len(s) <= 64),
    "str": lambda o, v: isinstance(v, str) and bool(_PARAM_RE.match(v)),
}

_INT_MS: Final = Opt("int", 0, 60_000)
UNIVERSAL: Final[Mapping[str, Opt]] = {
    "throttle_ms": _INT_MS,
    "encoding": Opt("enum", choices=frozenset({"binary", "structured"})),
    "coalesce": Opt("bool"),
    "from_seq": Opt("int", 0),
    "from_ts_ms": Opt("int", 0),
}
_ACCOUNTS: Final = Opt("uuids", min_items=1, max_items=25)
_SYMBOLS: Final = Opt("symbols", min_items=1, max_items=40)
_DEC: Final = Opt("decimal")
_GROUPING: Final = Opt("int", 1, 1000)


@dataclass(frozen=True)
class TopicFamily:
    """One row of the §6 catalogue."""

    family: str
    shapes: tuple[tuple[Segment, ...], ...]
    permission: Permission | None
    scope: Scope | None
    default_throttle_ms: int
    binary: bool
    payload_schema: str
    options: Mapping[str, Opt] = field(default_factory=dict)
    private: bool = False
    never_throttled: bool = False
    required: frozenset[str] = frozenset()

    @property
    def patterns(self) -> tuple[str, ...]:
        """Human-readable name patterns, e.g. `book.{symbol}.{depth}`."""
        return tuple(
            ".".join((self.family, *(s if s == "state" else f"{{{s}}}" for s in shape)))
            for shape in self.shapes
        )

    @property
    def account_scoped(self) -> bool:
        return self.scope is Scope.GRANTED_ACCOUNTS


def _md(
    fam: str,
    shapes: tuple[tuple[Segment, ...], ...],
    throttle: int,
    binary: bool,
    schema: str,
    options: Mapping[str, Opt] | None = None,
    required: frozenset[str] = frozenset(),
) -> TopicFamily:
    return TopicFamily(
        fam,
        shapes,
        Permission.MARKETDATA_READ,
        Scope.NONE,
        throttle,
        binary,
        schema,
        dict(options or {}),
        required=required,
    )


def _pv(
    fam: str,
    perm: Permission,
    scope: Scope,
    throttle: int,
    schema: str,
    options: Mapping[str, Opt],
    *,
    never_throttled: bool = False,
) -> TopicFamily:
    return TopicFamily(
        fam,
        ((),),
        perm,
        scope,
        throttle,
        False,
        schema,
        dict(options),
        private=True,
        never_throttled=never_throttled,
    )


_ACC_SYM: Final = {"exchange_account_ids": _ACCOUNTS, "symbols": _SYMBOLS}
_G = Scope.GRANTED_ACCOUNTS

#: §6.4: permission and scope are per entity kind (`MACHINE_KINDS`), not per family.
_MACHINES: Final = TopicFamily("machines", (("entity", "state"),), None, None, 100, False,
                               "MachineStateUpdate", private=True)  # fmt: skip

#: The §6.1/§6.2 catalogue. `system` is implicit (no permission; auto-subscribed at `auth_ok`).
FAMILIES: Final[Mapping[str, TopicFamily]] = {
    f.family: f
    for f in (
        _md("book", (("symbol", "depth"),), 50, True, "BookSnapshot"),
        _md(
            "trades",
            (("symbol",),),
            100,
            True,
            "TradesBatch",
            {
                "min_size": _DEC,
                "cluster_window_ms": Opt("int", 0, 5000),
                "cluster_tolerance_ticks": Opt("int", 0, 20),
            },
        ),
        _md(
            "bars",
            (("symbol", "bar_type", "param"),),
            250,
            True,
            "BarsBatch",
            {
                "include_delta": Opt("bool"),
                "history": Opt("int", 0, 1000),
            },  # defaults: BARS_DEFAULTS
        ),
        _md(
            "footprint",
            (("symbol", "bar_type", "param"),),
            250,
            True,
            "FootprintUpdate",
            {
                "price_grouping": _GROUPING,
                "imbalance_ratio": Opt("number", 1.5, 20),
                "min_stack": Opt("int", 2, 10),
                "min_imbalance_volume": _DEC,
                "history": Opt("int", 0, 200),
            },
        ),
        _md(
            "heatmap",
            (("symbol",),),
            500,
            True,
            "HeatmapColumn",
            {
                "time_bucket_ms": Opt("enum", choices=frozenset({100, 250, 500, 1000, 5000})),
                "price_grouping": _GROUPING,
                "depth": Opt("enum", choices=DEPTHS),
                "window_seconds": Opt("int", 10, 900),
            },
        ),
        _md(
            "profile",
            (("symbol", "profile_kind"),),
            1000,
            False,
            "ProfileUpdate",
            {
                "split": Opt("enum", choices=frozenset({"composite", "session", "fixed"})),
                "session_anchor": Opt(
                    "enum", choices=frozenset({"utc_day", "funding_8h", "custom"})
                ),
                "price_grouping": _GROUPING,
                "value_area_pct": Opt("number", 50, 95),
            },
        ),
        _md(
            "metrics",
            (("symbol",),),
            250,
            False,
            "MetricsUpdate",
            {
                "metrics": Opt("strings", min_items=1, max_items=12),
                "bar_type": Opt("enum", choices=BAR_TYPES),
                "param": Opt("str"),
            },
        ),
        _md("ticker", (("symbol",), ()), 250, False, "TickerUpdate", {"symbols": _SYMBOLS}),
        _md(
            "liquidations",
            (("symbol",), ()),
            500,
            False,
            "LiquidationBatch",
            {
                "symbols": _SYMBOLS,
                "min_notional_usd": _DEC,
                "cluster_window_ms": Opt("int", 0, 5000),
            },
        ),
        _pv(
            "orders",
            Permission.ORDERS_READ,
            _G,
            0,
            "OrderUpdate",
            {**_ACC_SYM, "open_only": Opt("bool")},
            never_throttled=True,
        ),
        _pv("positions", Permission.POSITIONS_READ, _G, 100, "PositionUpdate", _ACC_SYM),
        _pv(
            "executions",
            Permission.EXECUTIONS_READ,
            _G,
            0,
            "ExecutionUpdate",
            _ACC_SYM,
            never_throttled=True,
        ),
        _pv(
            "wallet",
            Permission.ACCOUNTS_READ,
            _G,
            500,
            "WalletUpdate",
            {"exchange_account_ids": _ACCOUNTS},
        ),
        _pv(
            "trade_groups",
            Permission.ORDERS_READ,
            _G,
            100,
            "TradeGroupUpdate",
            {"exchange_account_ids": _ACCOUNTS, "status": Opt("strings", max_items=16)},
        ),
        _pv(
            "rules",
            Permission.RULES_READ,
            _G,
            250,
            "RuleUpdate",
            {
                "exchange_account_ids": _ACCOUNTS,
                "rule_ids": Opt("uuids", max_items=100),
                "include_events": Opt("bool"),
            },
        ),
        _pv(
            "alerts",
            Permission.ALERTS_READ,
            Scope.SELF,
            250,
            "AlertUpdate",
            {"unacked_only": Opt("bool")},
        ),
        _pv(
            "recorder",
            Permission.RECORDING_READ,
            Scope.NONE,
            1000,
            "RecorderUpdate",
            {"symbols": _SYMBOLS},
        ),
        TopicFamily("system", ((),), None, None, 1000, False, "SystemUpdate", private=True),
        _MACHINES,
    )
}


@dataclass(frozen=True)
class MachineKind:
    """One §6.4 entity kind: its id format and the read rule `machine_refusal` applies."""

    id_format: Literal["uuid", "symbol", "singleton"]
    permission: Permission | None
    scope: Scope
    #: `deny_pending_decision` (§16.6 W6-W8): `forbidden` for every non-Owner, every entity.
    pending: bool = False


_U: Final = "uuid"
_SELF: Final = Scope.SELF
#: The closed §6.4 kind set (B8, B9, B13 and B15 have no public id yet, §16.6 W9).
MACHINE_KINDS: Final[Mapping[str, MachineKind]] = {
    "order": MachineKind(_U, Permission.ORDERS_READ, _G),
    "trade_group": MachineKind(_U, Permission.ORDERS_READ, _G, pending=True),
    "leg": MachineKind(_U, Permission.ORDERS_READ, _G),
    "algo": MachineKind(_U, Permission.ORDERS_READ, _G),
    "alert": MachineKind(_U, Permission.ALERTS_READ, _SELF),
    "recording": MachineKind("symbol", Permission.RECORDING_READ, Scope.NONE),
    "replay": MachineKind(_U, Permission.REPLAY_READ, _SELF),
    "book": MachineKind("symbol", Permission.MARKETDATA_READ, Scope.NONE),
    "session": MachineKind(_U, None, _SELF),
    "live_gate": MachineKind("singleton", None, Scope.NONE, pending=True),
    "kill_switch": MachineKind("singleton", Permission.ORDERS_READ, Scope.NONE),
    "reconciliation": MachineKind(_U, None, _G, pending=True),
    "risk_lockout": MachineKind(_U, Permission.POSITIONS_READ, _G),
}


@dataclass(frozen=True, slots=True)
class EntityScope:
    """The immutable scope a registry entry carries (§6.4 scope binding): the entity's accounts
    (B2: every leg's), or its user. Empty for an unscoped kind, and for a missing binding."""

    accounts: frozenset[uuid.UUID] = frozenset()
    user: uuid.UUID | None = None


#: Checked for an entity that has no entry, so it costs what a foreign one does (no oracle).
_NO_ACCOUNT: Final = frozenset({uuid.UUID(int=0)})


def _granted(principal: PrincipalSnapshot, permission: Permission | None, acc: uuid.UUID) -> bool:
    if permission is None:  # B19 has no read rule yet: only the Owner reaches this step (W8)
        return principal.is_owner
    decision = decide(principal, permission, scope=_G, exchange_account_id=acc)
    return isinstance(decision, Allow)


def machine_refusal(
    principal: PrincipalSnapshot, kind: str, scope: EntityScope | None
) -> tuple[str, str] | None:
    """§6.4 check order: permission, role, then registry and scope (`scope`: the entry's, `None`
    without one). Returns (§10.2 code, internal audit reason), or `None` when allowed. The code
    depends only on the kind and the caller: unknown, unscoped and foreign get the same one."""
    rule = MACHINE_KINDS[kind]
    if rule.permission is not None and isinstance(decide(principal, rule.permission), Deny):
        return "forbidden", "role"
    if rule.pending and not principal.is_owner:
        return "forbidden", "role"
    if rule.scope == Scope.NONE:
        return None
    accounts = scope.accounts if scope is not None else frozenset()
    user = scope.user if scope is not None else None
    if rule.scope == _G:
        granted = all(_granted(principal, rule.permission, a) for a in accounts or _NO_ACCOUNT)
        code, held = "account_scope_denied", bool(accounts) and granted
    else:  # user-scoped: the caller's own entity only, Owner included (D2)
        code, held = "forbidden", user is not None and user == principal.user_id
    if held:
        return None
    return code, "unknown" if scope is None else "foreign" if accounts or user else "unscoped"


_ID_PATTERNS: Final = {"uuid": ":{uuid}", "symbol": ":{symbol}", "singleton": ""}
#: (topic pattern, permission string) - the surface the E09-Q03 RBAC matrix discovers;
#: `machines` contributes one pattern per §6.4 kind, with that kind's read permission.
TOPIC_REGISTRY: Final[tuple[tuple[str, str | None], ...]] = tuple(
    (pattern, f.permission.value if f.permission else None)
    for f in FAMILIES.values()
    if f.family != "machines"
    for pattern in f.patterns
) + tuple(
    (f"machines.{k}{_ID_PATTERNS[m.id_format]}.state", m.permission and m.permission.value)
    for k, m in MACHINE_KINDS.items()
)


@dataclass(frozen=True)
class ParsedTopic:
    """A topic string parsed once at subscribe time."""

    ch: str
    family: TopicFamily
    symbol: str | None = None
    depth: int | None = None
    bar_type: str | None = None
    param: str | None = None
    kind: str | None = None
    #: §6.4 `machines`: the `MACHINE_KINDS` key of the entity (its symbol, if any, is `symbol`).
    entity_kind: str | None = None

    @property
    def params(self) -> tuple[str, ...]:
        return tuple(
            str(v) for v in (self.depth, self.bar_type, self.param, self.kind) if v is not None
        )


def parse_topic(ch: Any, *, instrument_known: Callable[[str], bool] | None = None) -> ParsedTopic:
    """Parse a §6 topic name or raise `TopicError` (`unknown_topic`, `invalid_topic_format`,
    `unsupported_symbol`)."""
    if not isinstance(ch, str) or not 0 < len(ch) <= TOPIC_MAX_LEN:
        raise TopicError("invalid_topic_format", "Topic name is malformed.")
    head, *rest = ch.split(".")
    family = FAMILIES.get(head)
    if family is None:
        raise TopicError("unknown_topic", "Topic is not in the catalogue.")
    shape = next((s for s in family.shapes if len(s) == len(rest)), None)
    if shape is None or not all(
        kind == "entity" or _SEGMENT_RE.match(seg) for kind, seg in zip(shape, rest, strict=True)
    ):  # an entity may hold `-` (uuid); `_entity` checks it against its own grammar
        raise TopicError("invalid_topic_format", f"Expected {' or '.join(family.patterns)}.")
    values: dict[str, Any] = {}
    for kind, seg in zip(shape, rest, strict=True):
        if kind == "entity":
            values["entity_kind"], values["symbol"] = _entity(seg, instrument_known)
        else:
            values[kind] = _segment(kind, seg, instrument_known)
    return ParsedTopic(
        ch,
        family,
        symbol=values.get("symbol"),
        depth=values.get("depth"),
        bar_type=values.get("bar_type"),
        param=values.get("param"),
        kind=values.get("profile_kind"),
        entity_kind=values.get("entity_kind"),
    )


_BAD_ENTITY: Final = "Unknown machine kind, or an id that does not fit it."


def _entity(seg: str, instrument_known: Callable[[str], bool] | None) -> tuple[str, str | None]:
    """§6.4 `{entity}`: `{kind}` for a singleton, otherwise `{kind}:{id}`. Returns the kind and,
    for a symbol-keyed kind, the symbol. An unknown kind or an id that does not fit its kind is
    `invalid_topic_format`; a well-formed symbol of no known instrument, `unsupported_symbol`."""
    name, sep, ident = seg.partition(":")
    rule = MACHINE_KINDS.get(name)
    if rule is None or (rule.id_format == "singleton") == bool(sep):
        raise TopicError("invalid_topic_format", _BAD_ENTITY)
    if rule.id_format == "singleton":
        return name, None
    if not (_UUID_RE if rule.id_format == "uuid" else SYMBOL_RE).fullmatch(ident):
        raise TopicError("invalid_topic_format", _BAD_ENTITY)
    if rule.id_format == "uuid":
        return name, None
    if instrument_known is not None and not instrument_known(ident):
        raise TopicError("unsupported_symbol", "Not a supported USDT linear perpetual.")
    return name, ident


def _segment(kind: Segment, seg: str, instrument_known: Callable[[str], bool] | None) -> Any:
    if kind == "symbol":
        if not SYMBOL_RE.match(seg) or (instrument_known is not None and not instrument_known(seg)):
            raise TopicError("unsupported_symbol", "Not a supported USDT linear perpetual.")
        return seg
    if kind == "depth":
        if not seg.isdigit() or int(seg) not in DEPTHS:
            raise TopicError("invalid_topic_format", "Book depth must be 1, 50, 200 or 500.")
        return int(seg)
    if kind == "bar_type":
        if seg not in BAR_TYPES:
            raise TopicError("invalid_topic_format", "Unknown bar type.")
        return seg
    if kind == "param":
        if not _PARAM_RE.match(seg):
            raise TopicError("invalid_topic_format", "Bar param is malformed.")
        return seg
    if kind == "state":
        if seg != "state":
            raise TopicError("invalid_topic_format", "Expected machines.{entity}.state.")
        return seg
    if seg not in PROFILE_KINDS:
        raise TopicError("invalid_topic_format", "Profile kind must be volume, delta or tpo.")
    return seg


def validate_options(family: TopicFamily, opts: Any) -> dict[str, Any]:
    """Validate `opts` against the family schema: unknown keys are REJECTED (S12)."""
    if opts is None:
        opts = {}
    if not isinstance(opts, dict):
        raise TopicError("invalid_options", "opts must be an object.", "opts")
    schema = {**UNIVERSAL, **family.options}
    out: dict[str, Any] = {}
    for name in sorted(opts):
        spec = schema.get(name) if isinstance(name, str) else None
        if spec is None:
            raise TopicError(
                "invalid_options", f"Unknown option '{str(name)[:40]}'.", str(name)[:40]
            )
        out[name] = spec.check(name, opts[name])
    for name in sorted(family.required - set(out)):
        raise TopicError("invalid_options", f"Option '{name}' is required.", name)
    return out


def default_throttle_ms(topic: ParsedTopic) -> int:
    if topic.family.family == "book":
        return {1: 20, 50: 50}.get(topic.depth or 50, 100)
    return topic.family.default_throttle_ms


def effective_throttle_ms(topic: ParsedTopic, requested: int | None) -> int:
    """§5.1: requested values are floored at `MIN_THROTTLE_MS`; orders/executions are never
    throttled (§6.2), so they always report 0."""
    if topic.family.never_throttled:
        return 0
    if requested is None:
        return default_throttle_ms(topic)
    return max(requested, MIN_THROTTLE_MS)


#: §6.1: the `bars` options when the client leaves them out, echoed in `effective`.
BARS_DEFAULTS: Final[Mapping[str, Any]] = MappingProxyType({"history": 500, "include_delta": False})


def effective_options(topic: ParsedTopic, opts: Mapping[str, Any]) -> dict[str, Any]:
    """The `sub_ok.effective` / `ctl_ok.effective` block: options AFTER clamping."""
    fam = topic.family
    if opts.get("encoding") == "binary" and not fam.binary:
        raise TopicError("encoding_unsupported", "This topic has no binary form.", "encoding")
    eff: dict[str, Any] = {
        k: v for k, v in opts.items() if k not in {"from_seq", "from_ts_ms", "exchange_account_ids"}
    }
    eff["throttle_ms"] = effective_throttle_ms(topic, opts.get("throttle_ms"))
    eff["encoding"] = opts.get("encoding", "binary" if fam.binary else "structured")
    eff["coalesce"] = False if fam.never_throttled else opts.get("coalesce", True)
    if topic.depth is not None:
        eff["depth"] = topic.depth
    if fam.family == "bars":
        for key, value in BARS_DEFAULTS.items():
            eff.setdefault(key, value)
    if fam.family == "heatmap":
        eff.setdefault("time_bucket_ms", 500)
        eff["throttle_ms"] = (
            max(opts["throttle_ms"], MIN_THROTTLE_MS)
            if "throttle_ms" in opts
            else eff["time_bucket_ms"]
        )
    return eff
