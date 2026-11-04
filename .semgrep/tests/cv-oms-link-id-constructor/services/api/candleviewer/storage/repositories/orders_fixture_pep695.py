# Fixture for cv-oms-link-id-constructor outside the OMS (the rule covers every product module), in
# a file with PEP 695 syntax (#3549).
from candleviewer.oms.order_link_allocator import AllocatedOrderLinkId

type Row = dict[str, object]


def restore[R](row: R) -> AllocatedOrderLinkId:
    return AllocatedOrderLinkId(parts=row)  # ruleid: cv-oms-link-id-constructor


def read(row: Row) -> object:
    return row["order_link_id"]  # ok: cv-oms-link-id-constructor
