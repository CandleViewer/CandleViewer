"""User lifecycle metrics (E42-T04 S4, #965 Observability, R7), via the facade; label values are
closed sets fixed in `admin/user_disable.py`."""

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
