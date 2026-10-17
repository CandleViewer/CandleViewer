"""User lifecycle metrics (E42-T04 S4, #965 Observability, R7), via the facade. The label values are
closed sets, each fixed by the module that writes it: the cascade's steps and outcomes in
`admin/user_disable.py`, and the grants push (`step` `grants_push`, `outcome` `pushed`, `timeout`
or `failed`) in `admin/account_access.py` (#2648)."""

from __future__ import annotations

from candleviewer.observability.metrics import Counter

user_lifecycle_total = Counter(
    "cv_user_lifecycle_total",
    "User lifecycle calls by action and result (refusals and failures included).",
    ["action", "result"],
)
user_lifecycle_steps_total = Counter(
    "cv_user_lifecycle_steps_total",
    "User lifecycle cascade steps after the transaction, by outcome (R7).",
    ["step", "outcome"],
)
