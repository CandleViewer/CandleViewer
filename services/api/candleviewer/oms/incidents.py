"""The stuck-order detector's incident (E29-T08 #916; 24-internal-schemas.md Sec.8.13, Sec.15.5;
the ruling of record on #916, BQ-3 to BQ-6).

`OmsIncident` is the one shape an incident takes in every sink: the write-ahead `oms.incident`
audit record's `after_state`, the log line, the `system_events` row's `details` and the event on
the bus topic `{env}.oms.incident`. It is frozen and closed (`extra="forbid"`) and validated where
it is built (`incident`): the severity is its kind's, an order kind names its order by
`order_link_id` (24 Sec.8.3's form or its `ext-` key) and the other kinds name none, the position
and order kinds name a symbol and `account_stale` none, `detail` is the kind's fixed sentence,
`age_s` is finite and not negative, and `detected_at` is UTC. It carries ids and fixed text only,
never a price, a size, a payload or a credential (C-12.6); the `order_link_id` is its only order
identifier, and it is opaque.

Only `error` and `critical` form incidents (BQ-6): `unknown`, `naked` and `account_stale` are
critical, `in_flight` and `pending` error. Pure: no I/O, no clock.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Annotated, Final, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from candleviewer.domain.order_link import EXT_ID, OUR_ID

__all__ = [
    "AUDIT_ACTION",
    "BUS_DOMAIN",
    "BUS_NAME",
    "DETAILS",
    "KINDS",
    "ORDER_KINDS",
    "RANK",
    "SEVERITY",
    "IncidentKind",
    "IncidentSeverity",
    "OmsIncident",
    "OrderKind",
    "audit_state",
    "event_details",
    "event_kind",
    "incident",
]

#: The detector's kinds (24 Sec.8.13's table), in its order.
type IncidentKind = Literal["in_flight", "unknown", "pending", "naked", "account_stale"]
#: The kinds that name an order (by its `order_link_id`), whose rows `oms_stuck_orders` counts.
type OrderKind = Literal["in_flight", "unknown", "pending"]
type IncidentSeverity = Literal["error", "critical"]

KINDS: Final[tuple[IncidentKind, ...]] = get_args(IncidentKind.__value__)
ORDER_KINDS: Final[tuple[OrderKind, ...]] = get_args(OrderKind.__value__)
#: Each kind's severity (BQ-6): only `error` and `critical` form incidents.
SEVERITY: Final[Mapping[IncidentKind, IncidentSeverity]] = MappingProxyType(
    {
        "in_flight": "error",
        "unknown": "critical",
        "pending": "error",
        "naked": "critical",
        "account_stale": "critical",
    }
)
#: An order's kinds by rank: one that outranks the kind raised is raised at once, the cool-down
#: notwithstanding (`unknown` keeps `in_flight`, so it outranks it).
RANK: Final[Mapping[OrderKind, int]] = MappingProxyType(
    {"in_flight": 1, "pending": 1, "unknown": 2}
)
#: Each kind's one fixed sentence: the `system_events` message and the incident's `detail`; it
#: names a condition, never an id or a value.
DETAILS: Final[Mapping[IncidentKind, str]] = MappingProxyType(
    {
        "in_flight": "An order's create was sent and has had no answer for longer than its bound.",
        "unknown": "An order has been in unknown for longer than one reconciliation cycle.",
        "pending": "An order's cancel or amend has been pending for longer than its bound.",
        "naked": "An open position has had no exchange-side stop-loss past its deadline.",
        "account_stale": "An account's reconciliation is locked stale; its order entry is refused.",
    }
)
#: The audited action (24 Sec.15.5), registered in `audit/actions.py` before its first emitter.
AUDIT_ACTION: Final = "oms.incident"
#: The bus topic's segments: `{env}.oms.incident` (20 Sec.3.5's `bus: oms.*`).
BUS_DOMAIN: Final = "oms"
BUS_NAME: Final = "incident"
#: A symbol as the stores hold one (`domain.primitives.Symbol`'s alphabet), never free text.
_SYMBOL: Final = r"^[A-Z0-9]{1,32}$"
_UTC: Final = timedelta(0)


class OmsIncident(BaseModel):
    """One incident (24 Sec.8.13 "The incident"); build it with `incident`, which fills the
    kind's severity and sentence."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    kind: IncidentKind
    severity: IncidentSeverity
    order_link_id: str | None = None
    account_id: UUID
    symbol: Annotated[str, Field(pattern=_SYMBOL)] | None = None
    age_s: float
    detected_at: datetime
    detail: str

    @field_validator("age_s")
    @classmethod
    def _an_age(cls, value: float) -> float:
        """Finite and not negative, to the millisecond."""
        if not math.isfinite(value) or value < 0:
            raise ValueError("age_s is a finite number of seconds, at least 0")
        return round(value, 3)

    @field_validator("detected_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != _UTC:
            raise ValueError("detected_at is a UTC time")
        return value

    @model_validator(mode="after")
    def _closed(self) -> OmsIncident:
        """The kind decides the rest: its severity, its sentence, and which ids it names."""
        if self.severity != SEVERITY[self.kind]:
            raise ValueError("an incident's severity is its kind's")
        if self.detail != DETAILS[self.kind]:
            raise ValueError("an incident's detail is its kind's fixed sentence")
        names_order = self.kind in ORDER_KINDS
        link = self.order_link_id
        if names_order != (link is not None):
            raise ValueError("an order kind names its order_link_id, and only an order kind")
        if link is not None and not (OUR_ID.fullmatch(link) or EXT_ID.fullmatch(link)):
            raise ValueError("an order_link_id of 24 Sec.8.3's form or an ext- key")
        if (self.kind == "account_stale") != (self.symbol is None):
            raise ValueError("an order or a position names its symbol; an account none")
        return self


def incident(
    kind: IncidentKind,
    *,
    account_id: UUID,
    age_s: float,
    detected_at: datetime,
    order_link_id: str | None = None,
    symbol: str | None = None,
) -> OmsIncident:
    """The incident of `kind`, its severity and sentence the kind's; a `ValidationError` for
    anything `OmsIncident` refuses."""
    return OmsIncident(
        kind=kind,
        severity=SEVERITY[kind],
        order_link_id=order_link_id,
        account_id=account_id,
        symbol=symbol,
        age_s=float(age_s),
        detected_at=detected_at,
        detail=DETAILS[kind],
    )


def _seconds(age_s: float) -> str:
    return f"{age_s:.3f}"


def audit_state(found: OmsIncident) -> dict[str, str | None]:
    """The `oms.incident` record's `after_state` (24 Sec.15.5): the incident's fields, `age_s` in
    decimal seconds and `detected_at` in ISO form; ids and fixed text only."""
    return {
        "kind": found.kind,
        "severity": found.severity,
        "order_link_id": found.order_link_id,
        "account_id": str(found.account_id),
        "symbol": found.symbol,
        "age_s": _seconds(found.age_s),
        "detected_at": found.detected_at.isoformat(),
        "detail": found.detail,
    }


def event_kind(kind: IncidentKind) -> str:
    """The `system_events` row's `kind` (21 Sec.3.10.2): `incident_<kind>`."""
    return f"incident_{kind}"


def event_details(found: OmsIncident) -> dict[str, str]:
    """The `system_events` row's `details` (21 Sec.3.10.2): strings only, the keys an incident has
    (`order_link_id` for an order kind, `symbol` but for an account), never a value."""
    details = {"kind": found.kind, "account_id": str(found.account_id)}
    details["age_s"] = _seconds(found.age_s)
    if found.order_link_id is not None:
        details["order_link_id"] = found.order_link_id
    if found.symbol is not None:
        details["symbol"] = found.symbol
    return details
