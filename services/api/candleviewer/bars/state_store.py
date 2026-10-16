"""Builder-state blobs on disk (E12-T03; `24-internal-schemas.md` §3.2).

Format: versioned orjson, as the merged §3.2 says (#2002). The ticket text says msgpack; that
wording was superseded, and msgpack is not a dependency. One file per series:

    <root>/<symbol>/<spec_hash>.state.json

`symbol` and `spec_hash` are re-validated against fixed patterns here, so no client string ever
reaches a path (SR-E12-12). The envelope holds the builder's own `BuilderState` (its `blob` is
the builder's orjson document, stored as text) plus the set's watermark: the `ts_event` of the
last applied trade and the ids of the trades applied at exactly that timestamp, so the
post-restart replay window is exact. It also records the series' bar `generation` (#2662), so a
restore keeps its epoch and a cold start can start above the epoch of a blob it discards.

Writes are atomic: write `<name>.tmp`, flush + fsync, then `os.replace`. A crash before the
rename leaves the previous blob intact. Reads never raise for bad data: `load()` returns
`(None, reason)` and the caller discards the blob and cold-starts. A blob is refused when it is
larger than `MAX_BLOB_BYTES`, unparseable, for another series, or has an unknown envelope
version. Version 1 (before the generation was recorded) still loads, as generation 0, so an
upgrade restores every series instead of cold-starting it. File I/O runs in a worker thread
(C-2.18: no blocking I/O on the loop).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import orjson

from candleviewer.bars.errors import BarsError
from candleviewer.bars.models import BuilderState
from candleviewer.bars.rows import MAX_GENERATION
from candleviewer.observability.context import run_in_thread

ENVELOPE_VERSION: Final = 2
#: The envelope before `generation` was recorded (#2662); `load` reads it as generation 0.
LEGACY_ENVELOPE_VERSION: Final = 1
MAX_BLOB_BYTES: Final = 8 * 1024 * 1024
_SYMBOL: Final = re.compile(r"^[A-Z0-9]{4,20}$")
_HASH: Final = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class Watermark:
    """Last applied trade: `ts_us`, plus the trade ids applied at exactly `ts_us`."""

    ts_us: int
    ids: frozenset[str]

    def covers(self, ts_us: int, trade_id: str) -> bool:
        """True when a trade at `(ts_us, trade_id)` was already applied."""
        return ts_us < self.ts_us or (ts_us == self.ts_us and trade_id in self.ids)


@dataclass(frozen=True, slots=True)
class StoredState:
    state: BuilderState
    watermark: Watermark | None
    #: The series' bar generation (epoch); a v1 envelope reads as 0. A claim read from an
    #: unauthenticated file: bounded to `MAX_GENERATION`, and from a discarded blob it only raises
    #: the floor. Required: a defaulted 0 would silently move a series back to the legacy epoch.
    generation: int


class StateStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def path(self, symbol: str, spec_hash: str) -> Path:
        if not _SYMBOL.match(symbol) or not _HASH.match(spec_hash):
            raise BarsError("A state blob path needs a valid symbol and spec hash.")
        return self._root / symbol / f"{spec_hash}.state.json"

    async def save(self, stored: StoredState) -> None:
        st, wm = stored.state, stored.watermark
        doc = {
            "v": ENVELOPE_VERSION,
            "symbol": st.symbol,
            "spec_hash": st.spec_hash,
            "state_version": st.state_version,
            "last_trade_seq": st.last_trade_seq,
            "blob": st.blob.decode(),
            "wm": None if wm is None else [wm.ts_us, sorted(wm.ids)],
            "generation": stored.generation,
        }
        await run_in_thread(self._write, self.path(st.symbol, st.spec_hash), orjson.dumps(doc))

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    async def load(self, symbol: str, spec_hash: str) -> tuple[StoredState | None, str]:
        """`(state, "ok")`, `(None, "missing")` or `(None, <discard reason>)`; never raises."""
        return await run_in_thread(self._read, symbol, spec_hash)

    def _read(self, symbol: str, spec_hash: str) -> tuple[StoredState | None, str]:
        path = self.path(symbol, spec_hash)
        try:
            with path.open("rb") as f:
                data = f.read(MAX_BLOB_BYTES + 1)
        except FileNotFoundError:
            return None, "missing"
        except OSError:
            return None, "unreadable"
        if len(data) > MAX_BLOB_BYTES:
            return None, "too_large"
        try:
            doc = orjson.loads(data)
            version = doc["v"]
            if version not in (LEGACY_ENVELOPE_VERSION, ENVELOPE_VERSION):
                return None, "version"
            if (doc["symbol"], doc["spec_hash"]) != (symbol, spec_hash):
                return None, "wrong_series"
            generation = 0 if version == LEGACY_ENVELOPE_VERSION else doc["generation"]
            if type(generation) is not int or not 0 <= generation <= MAX_GENERATION:
                return None, "corrupt"  # a float or bool would break the LONG column on write
            state = BuilderState(
                spec_hash=doc["spec_hash"],
                symbol=doc["symbol"],
                state_version=doc["state_version"],
                last_trade_seq=doc["last_trade_seq"],
                blob=doc["blob"].encode(),
            )
            wm = doc["wm"]
            mark = None if wm is None else Watermark(int(wm[0]), frozenset(map(str, wm[1])))
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            return None, "corrupt"
        return StoredState(state, mark, generation), "ok"

    async def sweep_tmp(self) -> int:
        """Delete `*.state.json.tmp` leftovers of a crash mid-write; returns the count."""
        return await run_in_thread(self._sweep)

    def _sweep(self) -> int:
        n = 0
        if self._root.is_dir():
            for tmp in self._root.glob("*/*.state.json.tmp"):
                tmp.unlink(missing_ok=True)
                n += 1
        return n

    async def delete(self, symbol: str, spec_hash: str) -> None:
        await run_in_thread(self.path(symbol, spec_hash).unlink, missing_ok=True)
