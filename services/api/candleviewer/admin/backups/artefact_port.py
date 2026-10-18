"""The backup services' artefact port (E42-T05 BK-6a, #966): verification (BK-9) and the download
link (BK-10, BK-11) read a single-file artefact through `ArtefactReader`, which
`storage.backup_artefacts.LocalArtefactStore` implements over the backup root. A refused location
raises `ArtefactMissing` (`artefact_missing`), a failing volume `ArtefactUnreadable`
(`store_unavailable`); neither carries a path. Not wired yet. Beside `ports.py` (BK-7), so neither
slice edits the other's module."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol


class OpenArtefact(Protocol):
    """A regular file inside the backup root, held by the descriptor its reader checked: its
    SHA-256 (hex) and its bytes, read in bounded chunks off the event loop, one read at a time. A
    cancelled digest and a started stream close it when they stop; `close()` releases it exactly
    once, never under a read in flight. The caller bounds every wait."""

    @property
    def size(self) -> int: ...

    async def digest(self) -> str: ...

    def stream(self) -> AsyncIterator[bytes]: ...

    def close(self) -> None: ...


class ArtefactReader(Protocol):
    async def resolve(self, location: str) -> OpenArtefact:
        """The catalogue `location`, opened only once it resolves without a symlink to a regular
        file inside the backup root."""
        ...
