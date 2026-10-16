"""Shape of a generated `order_link_id` (`docs/plan/24-internal-schemas.md` §8.3).

`OUR_ID` is the first arm of the `orders.ord_link_fmt` CHECK
(`docs/plan/21-database-schema.md` §3.3.4). It lives here, beside the
`OrderLinkId` primitive, because the exchange adapter (M4) applies it and may
not import the OMS (M14, CONSTITUTION.md §3). Apply it with `re.fullmatch`:
`re.match` with `$` also accepts a trailing newline, and Postgres `~` does not.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ["OUR_ID"]

OUR_ID: Final = re.compile(
    r"^cv[ldtp]-[0-7][0-9A-Za-z]{21}-[0-9A-Za-z]{4}-[0-9A-Za-z]{2}(en|sl|tp|sc|fl|ac)$"
)
"""An id the §8.3 generator produces."""
