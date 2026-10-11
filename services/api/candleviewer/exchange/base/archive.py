"""`TradeArchiveSource` port (E16-T10): public historical trade archives.

The venue adapter implements it; the importer consumes a structurally identical protocol
(the recorder module may not import `exchange.base`, CONSTITUTION §3 M11). Unauthenticated
and read-only: no account or key concept exists on this port.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import date
from typing import Protocol, runtime_checkable

from candleviewer.domain.archive import ArchiveFile, ArchiveTrade

__all__ = ["TradeArchiveSource"]


@runtime_checkable
class TradeArchiveSource(Protocol):
    def list_files(self, symbol: str, start: date, end: date) -> list[ArchiveFile]:
        """Daily files for `[start, end]` inclusive. Raises `ArchiveRangeInvalid` for an
        unknown symbol shape, an inverted range or a range above the adapter's cap."""
        ...

    async def fetch(self, file: ArchiveFile) -> bytes:
        """Bounded (timeout, size cap, rate limit) download of the raw file."""
        ...

    def verify_checksum(self, file: ArchiveFile, raw: bytes) -> str:
        """Verify integrity; return the SHA-256 hex of `raw`. Raises `ArchiveChecksumFailed`."""
        ...

    def parse(
        self, file: ArchiveFile, raw: bytes, batch_rows: int
    ) -> Iterator[Sequence[ArchiveTrade]]:
        """Stream normalised rows in batches; raises `ArchiveParseFailed` / `ArchiveTooLarge`
        on schema, ordering, nominal-date or decompressed-size violations."""
        ...
