"""`--instrumentation off`: the fixture backend without E17-T06's hot-path series (#571).

#571's DoD line, "instrumentation overhead under 2 % of the fan-out path, measured against an
uninstrumented build", needs the same build with E17-T06 taken out. `CV_TELEMETRY_ENABLED` only
drops the span ids and the telemetry router, so this bench-only switch does the rest, in the
fixture's own process and nowhere else: while `uninstrumented()` is entered, each module attribute
below, the very name the gateway's code reads at run time, holds a stand-in of the same interface
that does nothing, and on exit every one holds its original again. No production module is edited.

What is taken out (E17-T06 and its slices #2891, #2921, #3251, #3409): the 1-in-32 sampler that
stamps a frame with its receipt time (`sequencing.SAMPLE_MASK`: with every bit set no `s` is a
multiple of it, so no frame is stamped and every one takes the unstamped path, as 31 in 32 do with
it on: no clock read, no timed encode, no `sp`, no span log); the fan-out, encode-time and frame-
size histograms where the writers and the encoder read them; the class gauge, the conflation
counter, the coalesced-updates histogram, the probe RTT and the two queue-depth histograms. The
fixture also passes `span_ids=None`. What stays: every series of another ticket (E17-T02's
`cvwb_*_encoded_total`, E17-T03's `cv_ws_overflow_total`, E17-S01's connection series), which the
harness reads to judge a run, and the harness's own (`process_*`, loop lag, the feeder counters).
The residue is one `seq & SAMPLE_MASK` test per frame, which an uninstrumented build would not do.
"""

from __future__ import annotations

import contextlib
import importlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Final

#: `--instrumentation`: E17-T06's series as built (`on`), or stood in by no-ops (`off`).
MODES: Final = ("on", "off")
#: The mode of an artefact that records none: every run before the switch was instrumented.
LEGACY: Final = "on"
#: `seq & SAMPLE_MASK` is never 0 for a sequence number of 1 or more: no frame is ever sampled.
NEVER_SAMPLED: Final = -1


class Noop:
    """A metric that records nothing: every call a `Counter`, a `Gauge`, a `Histogram`, one of
    their children or a `FastHistogramChild` takes on the hot path, and `labels()` is itself."""

    __slots__ = ()

    def observe(self, *_: Any, **__: Any) -> None:
        return None

    def inc(self, *_: Any, **__: Any) -> None:
        return None

    def dec(self, *_: Any, **__: Any) -> None:
        return None

    def set(self, *_: Any, **__: Any) -> None:
        return None

    def labels(self, *_: Any, **__: Any) -> Noop:
        return self


NOOP: Final = Noop()


def no_frame_bytes(payload: str | bytes, sp: str | None, *, msgpack: bool) -> int:
    """`metrics.frame_bytes`'s stand-in: the size only `cv_ws_frame_bytes` reads, never computed."""
    return 0


def no_span_log(
    connection_id: str, sp: str, ch: str | None, s: int | None, fanout_s: float
) -> None:
    """`gateway._log_span`'s stand-in: no sampled frame's debug record."""
    return None


@dataclass(frozen=True, slots=True)
class Target:
    """One hot-path instrument: the module attribute its reader looks up, and what E17-T06 does
    with it there (the inventory in `docs/qa/perf/e17-ws-load-report.md`)."""

    module: str
    attr: str
    what: str


def _gw(attr: str, what: str) -> Target:
    return Target("candleviewer.ws.gateway", attr, what)


def _pipe(attr: str, what: str) -> Target:
    return Target("candleviewer.ws.pipeline", attr, what)


def _pace(attr: str, what: str) -> Target:
    return Target("candleviewer.ws.pacing", attr, what)


#: Every E17-T06 instrument on the WS hot path, at the name its reader looks up at run time.
TARGETS: Final[tuple[Target, ...]] = (
    Target("candleviewer.ws.sequencing", "SAMPLE_MASK", "the 1-in-32 sampler: receipt stamp, sp"),
    _gw("FANOUT_SECONDS", "cv_ws_fanout_seconds, the writer"),
    _gw("_log_span", "the sampled frame's debug span record"),
    _pipe("JSON_ENCODE_SECONDS", "cv_ws_frame_encode_seconds{json}, at push"),
    _pipe("JSON_FRAME_BYTES", "cv_ws_frame_bytes{json}, at push"),
    _pipe("MSGPACK_ENCODE_SECONDS", "cv_ws_frame_encode_seconds{msgpack}, at push"),
    _pipe("MSGPACK_FRAME_BYTES", "cv_ws_frame_bytes{msgpack}, at push"),
    _pipe("frame_bytes", "a stamped frame's size less its sp, at push"),
    _pipe("cv_ws_queue_bytes", "queue depth in bytes, per classification"),
    _pipe("cv_ws_queue_frames", "queue depth in frames, per classification"),
    _pipe("CLASS_COUNTS", "cv_ws_connection_class{state}, per class change"),
    _pace("CONFLATED", "cv_ws_conflated_total{topic}, per merged window"),
    _pace("COALESCED_UPDATES", "cv_ws_coalesced_updates, per merged window"),
    _pace("cv_ws_rtt_seconds", "the probe RTT, per sample"),
    Target("candleviewer.ws.binary", "ENCODE_COST", "a stamped CVWB delta's encode time and size"),
)


def stand_in(original: Any) -> Any:
    """What replaces `original`: the same interface, recording nothing."""
    if isinstance(original, int):
        return NEVER_SAMPLED
    if isinstance(original, Mapping):  # same keys, so a lookup fails where it failed before
        return {k: (NOOP, NOOP) if isinstance(v, tuple) else NOOP for k, v in original.items()}
    name = getattr(original, "__name__", "")
    if name == "frame_bytes":
        return no_frame_bytes
    if name == "_log_span":
        return no_span_log
    return NOOP


def originals() -> list[tuple[Any, str, Any]]:
    """`(module, attr, value)` of every target as it is now."""
    out = []
    for t in TARGETS:
        module = importlib.import_module(t.module)
        out.append((module, t.attr, getattr(module, t.attr)))
    return out


@contextlib.contextmanager
def uninstrumented() -> Iterator[None]:
    """Every `TARGETS` attribute holds its stand-in while entered, and its original again after,
    however the body ends."""
    saved = originals()
    try:
        for module, attr, value in saved:
            setattr(module, attr, stand_in(value))
        yield
    finally:
        for module, attr, value in saved:
            setattr(module, attr, value)
