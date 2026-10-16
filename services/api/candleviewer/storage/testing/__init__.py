"""In-memory fakes for every M10 repository Protocol.

Shipped as part of the package's public test surface (ticket "Scope /
Deliverables": "shipped as part of the package's public test surface so
other modules import them") — any other module's tests may
`from candleviewer.storage.testing import FakeMarketDataRepository` without
reaching into `services/api/tests/`.

Every fake is a plain class satisfying its Protocol structurally
(`isinstance(fake, MarketDataRepository)` is `True` at runtime because the
Protocols are `@runtime_checkable`) — no inheritance required.
"""

from __future__ import annotations

from candleviewer.storage.testing.fakes import (
    FakeColdTierRepository,
    FakeMarketDataRepository,
    FakeRelationalRepository,
    FakeRetentionRepository,
    FakeUnitOfWork,
)
from candleviewer.storage.testing.recorded import (
    InMemoryRecordedTier,
    StaticGapReader,
    StaticManifestCoverage,
)

__all__ = [
    "FakeColdTierRepository",
    "FakeMarketDataRepository",
    "FakeRelationalRepository",
    "FakeRetentionRepository",
    "FakeUnitOfWork",
    "InMemoryRecordedTier",
    "StaticGapReader",
    "StaticManifestCoverage",
]
