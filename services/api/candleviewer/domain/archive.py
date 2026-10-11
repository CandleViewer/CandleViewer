"""Normalised public trade-archive types (E16-T10).

Exchange-neutral: the adapter that knows the archive host, file naming, CSV schema and
integrity check maps its files onto `ArchiveFile` and its rows onto `ArchiveTrade`. Every
consumer (recorder importer, storage writer) sees only these shapes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from candleviewer.domain.primitives import Side


@dataclass(frozen=True, slots=True)
class ArchiveFile:
    """One daily archive file. `name` is built by the adapter from the validated symbol and
    ISO date only (SR-097) - never from a server-supplied name."""

    symbol: str
    day: date
    name: str


@dataclass(frozen=True, slots=True)
class ArchiveTrade:
    """One public trade, normalised. `ts_us` is exchange event time (UTC, microseconds)."""

    ts_us: int
    symbol: str
    side: Side
    price: Decimal
    size: Decimal
    trade_id: str
    tick_dir: str | None = None


class ArchiveError(Exception):
    """Base for per-file archive failures; `code` is the summary/error-code slug."""

    code = "import_parse_failed"


class ArchiveChecksumFailed(ArchiveError):
    code = "import_checksum_failed"


class ArchiveParseFailed(ArchiveError):
    code = "import_parse_failed"


class ArchiveDownloadFailed(ArchiveError):
    """Non-200 (incl. 5xx), refused redirect or content-encoding: transport-level failure."""

    code = "import_download_failed"


class ArchiveNotFound(ArchiveError):
    code = "import_file_not_found"


class ArchiveTooLarge(ArchiveError):
    """Download or decompressed size exceeded its cap (zip-bomb guard)."""

    code = "import_file_too_large"


class ArchiveRangeInvalid(ValueError):
    code = "import_range_invalid"
