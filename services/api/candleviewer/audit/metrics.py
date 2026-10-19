"""The journal-first audit lane's metrics and the writer's refusals (ADR-0037 S4a, #3009), read at
the scrape, in a worker thread beside the event loop, from in-memory values only: no I/O, no lock,
no iteration over a dict the loop resizes. Names, kinds, labels and HELP are the catalogue's
(C-16.5); no label carries a record id, user, address, path or lane id (SR-125)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any

from candleviewer.audit.lane import REFUSALS, AuditLane, LaneFacade
from candleviewer.audit.lane_journal import ANOMALY_REASONS
from candleviewer.audit.writer import AUDIT_DOMAINS, AuditWriter
from candleviewer.observability.metrics import CollectorRegistry, ScrapeCollector, ScrapedFamily
from candleviewer.observability.metrics_catalogue import CATALOGUE

if TYPE_CHECKING:
    from candleviewer.audit.service import AuditService

CLASSES, STATES = ("reserved", "shared"), ("open", "held", "stopped")
DRAIN_FAILURES = ("held", "stopped")  # a hold a running scan met; the drain's death
_SPECS = {s.name: s for s in CATALOGUE if s.name.startswith(("cv_audit_lane_", "cv_audit_writer_"))}
EXPORTED_NAMES = frozenset(_SPECS)  # every family `lane_families` serves
_LANE_COUNTERS = "drained_total paused_batches_total created_total boot_overshoot_frames_total"


def _family(name: str, samples: Iterable[tuple[tuple[str, ...], float]]) -> ScrapedFamily:
    spec = _SPECS[name]
    return ScrapedFamily(name, spec.kind, spec.help, spec.labels, tuple(samples))


def _by(name: str, keys: Iterable[str], counts: Mapping[Any, float]) -> ScrapedFamily:
    return _family(name, (((key,), counts.get(key, 0)) for key in keys))


def lane_families(audit: AuditService, journal_first: Callable[[], bool]) -> list[ScrapedFamily]:
    """Every family, read now; `journal_first` returns the flag's cached value, never a store read.
    A writer, lane or façade that is not the real one (a test's stand-in) reads as unwired."""
    writer, lane, facade = audit.lane_parts()
    domains = writer.refused_by_domain if isinstance(writer, AuditWriter) else {}
    refused = facade.refused if isinstance(facade, LaneFacade) else {}
    lane = lane if isinstance(lane, AuditLane) else None
    journal = None if lane is None else lane.journal
    pairs = (((c, r), refused.get((c, r), 0)) for c in CLASSES for r in REFUSALS)
    appended = {} if journal is None else journal.appended
    anomalies, failures = ({}, {}) if lane is None else (lane.anomalies, lane.drain_failures)
    families = [
        _by("cv_audit_writer_refused_total", AUDIT_DOMAINS, domains),
        _family("cv_audit_lane_refused_total", pairs),
        _by("cv_audit_lane_appended_total", CLASSES, appended),
        _by("cv_audit_lane_anomalies_total", ANOMALY_REASONS, anomalies),
        _by("cv_audit_lane_drain_failures_total", DRAIN_FAILURES, failures),
        _family("cv_audit_lane_lock_failures_total", [((), audit.lane_lock_failures)]),
        _family("cv_audit_lane_link_failures_total", [((), audit.lane_link_failures)]),
        _family("cv_audit_lane_journal_first", [((), journal_first())]),
    ]
    names = _LANE_COUNTERS.split()
    if lane is None or journal is None:
        return families + [_family(f"cv_audit_lane_{name}", [((), 0)]) for name in names]
    counts = (lane.drained, lane.paused_batches, journal.created, journal.boot_overshoot_frames)
    families += [
        _family(f"cv_audit_lane_{n}", [((), v)]) for n, v in zip(names, counts, strict=True)
    ]
    refusal = journal.refusal
    state = "open" if refusal is None else ("held" if refusal == "held" else "stopped")
    gauges = {"depth": journal.depth, "oldest_age_seconds": journal.oldest_age()}
    gauges["quarantine_bytes"] = journal.quarantine_bytes
    if journal.lane.int and refusal != "held":  # opened, and its head read to the end
        gauges["last_seq"] = journal.head[0]
    families += [_family(f"cv_audit_lane_{name}", [((), v)]) for name, v in gauges.items()]
    shares = dict(zip(CLASSES, journal.class_bytes, strict=True))
    return [
        *families,
        _by("cv_audit_lane_bytes", CLASSES, shares),
        _by("cv_audit_lane_state", STATES, {state: 1}),
    ]


def export_audit_lane_metrics(
    registry: CollectorRegistry, *, env: str, audit: AuditService, journal_first: Callable[[], bool]
) -> ScrapeCollector:
    """Serve the families on the scraped `registry` with `env` (the composition root's call)."""
    return ScrapeCollector(registry, env=env, read=lambda: lane_families(audit, journal_first))
