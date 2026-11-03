# Fixture for cv-oms-order-events-unredacted (E29-X02): what a module that imports the
# `order_events` table writes under `payload`. A marker sits on the value's line.
import sqlalchemy as sa

from candleviewer.db.models import order_events, orders
from candleviewer.storage.repositories import exchange_payload as xp
from candleviewer.storage.repositories.exchange_payload import redact_exchange_payload


def _event_values(event):
    return {
        "kind": event.kind,
        "payload": redact_exchange_payload(event.payload),  # ok: cv-oms-order-events-unredacted
        "ret_msg": xp.redact_exchange_text(event.ret_msg, message=True),
    }


def raw(event, safe):
    return [
        {"payload": event.payload},  # ruleid: cv-oms-order-events-unredacted
        {"payload": dict(event.payload)},  # ruleid: cv-oms-order-events-unredacted
        {"payload": xp.redact_exchange_payload(event.payload)},  # ok: cv-oms-order-events-unredacted
        {"payload": redact_exchange_payload(event.payload) if safe else event.payload},  # ruleid: cv-oms-order-events-unredacted
        {"payload": {}},  # ok: cv-oms-order-events-unredacted
    ]


def subscript(event, row):
    row["payload"] = event.payload  # ruleid: cv-oms-order-events-unredacted
    row["payload"] = redact_exchange_payload(event.payload)  # ok: cv-oms-order-events-unredacted
    return row


def keyword(order_id, event):
    yield sa.insert(order_events).values(order_id=order_id, payload=event.payload)  # ruleid: cv-oms-order-events-unredacted
    yield sa.insert(order_events).values(order_id=order_id, payload=redact_exchange_payload(event.payload))  # ok: cv-oms-order-events-unredacted


def calls(values, event, raw):
    row = dict(kind=event.kind, payload=raw)  # ruleid: cv-oms-order-events-unredacted
    row = dict(kind=event.kind, payload=redact_exchange_payload(raw))  # ok: cv-oms-order-events-unredacted
    row = dict(kind=event.kind, payload=xp.redact_exchange_payload(raw))  # ok: cv-oms-order-events-unredacted
    row = dict(kind=event.kind, payload={})  # ok: cv-oms-order-events-unredacted
    values.update(payload=raw)  # ruleid: cv-oms-order-events-unredacted
    values.update(payload=redact_exchange_payload(raw))  # ok: cv-oms-order-events-unredacted
    values.update(payload=xp.redact_exchange_payload(raw))  # ok: cv-oms-order-events-unredacted
    values.setdefault("payload", raw)  # ruleid: cv-oms-order-events-unredacted
    values.setdefault("payload", redact_exchange_payload(raw))  # ok: cv-oms-order-events-unredacted
    values.setdefault("payload", xp.redact_exchange_payload(raw))  # ok: cv-oms-order-events-unredacted
    return row, values


def in_place(event, headers):
    """A redacted payload is a plain dict: a value written into it later skips the redactor."""
    values = {"payload": redact_exchange_payload(event.payload)}  # ok: cv-oms-order-events-unredacted
    values["payload"]["sign"] = headers["sign"]  # ruleid: cv-oms-order-events-unredacted
    values["payload"]["extra"] = redact_exchange_payload(headers)  # ok: cv-oms-order-events-unredacted
    values["payload"]["extra"] = xp.redact_exchange_payload(headers)  # ok: cv-oms-order-events-unredacted
    values["payload"].update(event.payload)  # ruleid: cv-oms-order-events-unredacted
    values["payload"].update(redact_exchange_payload(headers))  # ok: cv-oms-order-events-unredacted
    values["payload"].update(xp.redact_exchange_payload(headers))  # ok: cv-oms-order-events-unredacted
    return values


def bulk(rows):
    yield sa.insert(order_events).from_select(["order_id", "payload"], rows)  # ruleid: cv-oms-order-events-unredacted
    yield sa.select(order_events.c.payload).where(order_events.c.order_id == rows)  # ok: cv-oms-order-events-unredacted


_INSERT = sa.text("INSERT INTO order_events (order_id, seq, payload) VALUES (:o, :s, :p)")  # ruleid: cv-oms-order-events-unredacted
_READ = sa.text("SELECT payload FROM order_events WHERE order_id = :o")  # ok: cv-oms-order-events-unredacted
