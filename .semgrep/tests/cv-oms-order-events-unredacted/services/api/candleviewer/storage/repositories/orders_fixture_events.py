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


_INSERT = sa.text("INSERT INTO order_events (order_id, seq, payload) VALUES (:o, :s, :p)")  # ruleid: cv-oms-order-events-unredacted
_READ = sa.text("SELECT payload FROM order_events WHERE order_id = :o")  # ok: cv-oms-order-events-unredacted
