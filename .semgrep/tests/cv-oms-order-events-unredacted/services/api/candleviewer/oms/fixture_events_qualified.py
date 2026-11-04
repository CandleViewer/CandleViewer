# Fixture for cv-oms-order-events-unredacted: the table named through its module, and a `payload`
# in a module that writes no `order_events` row (a WS frame's), which the dict arm leaves alone.
import sqlalchemy as sa

from candleviewer.db import models as m
from candleviewer.storage.repositories.exchange_payload import redact_exchange_payload


def write(order_id, event):
    yield sa.insert(m.order_events).values(order_id=order_id, payload=event.payload)  # ruleid: cv-oms-order-events-unredacted
    yield sa.insert(m.order_events).values(payload=redact_exchange_payload(event.payload))  # ok: cv-oms-order-events-unredacted
    yield {"topic": "orders", "payload": event.view}  # ok: cv-oms-order-events-unredacted
