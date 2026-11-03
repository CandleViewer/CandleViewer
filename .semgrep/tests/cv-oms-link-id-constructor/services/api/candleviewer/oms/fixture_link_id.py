# Fixture for cv-oms-link-id-constructor (E29-X02): an `AllocatedOrderLinkId` made anywhere but the
# allocator. A marker sits on the finding's line.
import copy
import dataclasses
from dataclasses import replace

from candleviewer.oms import order_link_allocator as ola
from candleviewer.oms.order_link import OrderLinkIdParts
from candleviewer.oms.order_link_allocator import AllocatedOrderLinkId


async def forge(candidate: OrderLinkIdParts, allocator, other: OrderLinkIdParts, order_id):
    a = AllocatedOrderLinkId(parts=candidate)  # ruleid: cv-oms-link-id-constructor
    b = ola.AllocatedOrderLinkId(candidate, replaces_order_id=order_id)  # ruleid: cv-oms-link-id-constructor
    c = object.__new__(AllocatedOrderLinkId)  # ruleid: cv-oms-link-id-constructor
    d = AllocatedOrderLinkId.__new__(AllocatedOrderLinkId)  # ruleid: cv-oms-link-id-constructor
    allocated = await allocator.allocate(candidate)  # ok: cv-oms-link-id-constructor
    e = replace(allocated, parts=other)  # ruleid: cv-oms-link-id-constructor
    f = dataclasses.replace(allocated, replaces_order_id=order_id)  # ruleid: cv-oms-link-id-constructor
    g = copy.copy(allocated)  # ruleid: cv-oms-link-id-constructor
    h = allocated.order_link_id  # ok: cv-oms-link-id-constructor
    i = replace(candidate, seq=1)  # ok: cv-oms-link-id-constructor
    j = OrderLinkIdParts.generate(mode="exchange", environment="demo", group_id=None, account_id=None, seq=0, purpose="entry")  # ok: cv-oms-link-id-constructor
    return a, b, c, d, e, f, g, h, i, j


class Forged(AllocatedOrderLinkId):  # ruleid: cv-oms-link-id-constructor
    pass
