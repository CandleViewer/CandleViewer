# Fixture for cv-oms-order-events-unredacted in a module with PEP 695 syntax, which Semgrep parses
# another way (#3549), as `oms/` holds.
from candleviewer.db.models import order_events
from candleviewer.storage.repositories.exchange_payload import redact_exchange_payload

type Values = dict[str, object]


def raw[E](event: E) -> Values:
    return {"seq": 0, "payload": event.payload}  # ruleid: cv-oms-order-events-unredacted


def redacted[E](event: E) -> Values:
    return {"seq": 0, "payload": redact_exchange_payload(event.payload)}  # ok: cv-oms-order-events-unredacted


def changed[E](event: E, values: Values) -> Values:
    values["payload"].update(event.payload)  # ruleid: cv-oms-order-events-unredacted
    values.setdefault("payload", event.payload)  # ruleid: cv-oms-order-events-unredacted
    values["payload"]["seq"] = event.seq  # ruleid: cv-oms-order-events-unredacted
    values.setdefault("payload", redact_exchange_payload(event.payload))  # ok: cv-oms-order-events-unredacted
    return values


_TABLE = order_events
