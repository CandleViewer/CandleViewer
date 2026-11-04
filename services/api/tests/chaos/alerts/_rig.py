"""In-process stand-ins shared by the alert chaos scenarios: a relay that records the keys it was
sent, the settle-win counter (`cv_alert_delivery_total{status="sent"}`), and the dispatcher on the
in-memory dispatch store (`tests.alerts._dispatch_env`)."""

from __future__ import annotations

from typing import Any, cast

from candleviewer.alerts.dispatcher import AlertDispatcher, DispatchStore, default_adapters
from tests.alerts._dispatch_env import MemStore
from tests.alerts._owners_env import allow


class Relay:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def send(self, *, user_id: str, subject: str, body: str, idempotency_key: str) -> None:
        self.keys.append(idempotency_key)


class Wins:
    """`cv_alert_delivery_total{status="sent"}` increments: one per winning settle."""

    def __init__(self) -> None:
        self.sent = 0

    def __call__(self, name: str, labels: tuple[str, ...]) -> Any:
        wins = self

        class _C:
            def inc(self, amount: float = 1) -> None:
                if name == "cv_alert_delivery_total" and labels[1] == "sent":
                    wins.sent += 1

            def observe(self, amount: float) -> None: ...
            def set(self, value: float) -> None: ...

        return _C()


def dispatch(store: MemStore, relay: Any, **kw: Any) -> AlertDispatcher:
    """The dispatcher on *store*: `MemStore` settles its own `Job` rows, hence the cast."""
    return AlertDispatcher(cast(DispatchStore, store), default_adapters(relay), now=store.clock,
                           owners=allow(), **kw)  # fmt: skip
