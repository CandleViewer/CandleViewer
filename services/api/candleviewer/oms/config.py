"""The OMS's fixed bounds that are no setting (#913 L1d-2b; the orchestrator's ruling of 2026-10-26
16:50Z): the order lane's bridge to the private streams (`oms_streams`, 20-architecture.md Sec.6.2),
which L1d-3's timing of the hop may tune. Constants only, so the bridge, on C-2.20's hot-path
contract, reads them with nothing else."""

from __future__ import annotations

from typing import Final

#: The items one hop carries from a private stream's queue on the serving loop to the order lane,
#: at most: the stream's next item, awaited, and what is already queued behind it, never more.
HOP_BATCH: Final = 64
#: A read's hop is cut at this bound, finite (C-2.18) and above the consumer's 30 s silence bound
#: (`stream_consumer.STREAM_SILENCE_S`), so it never cuts an idle read: past it the stream ends.
STREAM_READ_BOUND_S: Final = 120.0
#: How long the lane waits for a stream's close on the serving loop: the adapter's socket close
#: (1 s) plus 1 s, as long as a revoke's close waits there; past it the close runs on, logged.
STREAM_CLOSE_BOUND_S: Final = 2.0
