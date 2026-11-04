# Fixture for cv-oms-link-id-constructor at the allocator's own path, which the rule exempts: the
# one constructor, in a file with PEP 695 syntax (#3549).
from dataclasses import dataclass

type Seq = int


@dataclass(frozen=True, slots=True)
class AllocatedOrderLinkId:
    parts: object
    replaces_order_id: object = None


class OrderLinkIdAllocator:
    async def allocate[P](self, candidate: P, *, replaces_order_id=None) -> AllocatedOrderLinkId:
        return AllocatedOrderLinkId(parts=candidate, replaces_order_id=replaces_order_id)  # ok: cv-oms-link-id-constructor
