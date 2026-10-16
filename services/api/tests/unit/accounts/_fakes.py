"""E27-T04 test fakes; `FakeClock` moves monotonic and wall time separately (suspend vs step)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from candleviewer.accounts.order_gate import KeyStanding

T0 = datetime(2026, 10, 15, 12, tzinfo=UTC)


class FakeClock:
    def __init__(self) -> None:
        self.mono = 1_000.0
        self.wall = T0

    def monotonic(self) -> float:
        return self.mono

    def now(self) -> datetime:
        return self.wall

    def advance(self, seconds: float) -> None:
        self.mono += seconds
        self.wall += timedelta(seconds=seconds)


ACC = UUID("a1000000-0000-4000-8000-000000000001")
ACC_B = UUID("a1000000-0000-4000-8000-000000000002")


class Dms:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str]] = []

    def account_down(self, account_id: UUID, reason: str) -> None:
        self.calls.append((account_id, reason))


class Standings(dict[UUID, KeyStanding]):
    def standing(self, account_id: UUID) -> KeyStanding | None:
        return self.get(account_id)


class Sizing(dict[UUID, bool]):
    """Wallet freshness per account; an account with no entry has no snapshot (`None`)."""

    def risk_sizing_available(self, account_id: UUID) -> bool | None:
        return self.get(account_id)
