"""One run, from the command line to the summary (#843 A4).

The online and offline runs differ only at the edges (`open_harness`): online, `Settings()` from
the container's environment, the Postgres stores, httpx's transport and production's private
connector; offline, demo settings over a KEK file made for the run, the stack in memory
(`offline.offline_stack`), the corpus venue behind both seams. Everything between is the same
composition, the same recording seams, the same scrubbed outputs.

Whatever ends the mode (completion, SIGINT, SIGTERM, a refusal or an error), a mode that places
orders runs `cancel_all` and a reduce-only flatten before M2 and audit stop, and the summary
records why it ended and what the flatten did. Exit codes: 0 completed, 1 an error, 2 refused.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final, cast
from uuid import UUID

import httpx
import structlog

from candleviewer.admin.wiring import AuditHandle, SecretsBundle, secrets_audit_sink, secrets_bundle
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import AccountRef
from candleviewer.exchange.bybit.config import PRIVATE_WS_URLS, SIGNED_REST_BASES
from candleviewer.exchange.bybit.key_ws_probe import connect_private_stream
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.secrets import (
    AuthKeyStore,
    CredentialStore,
    KcvStore,
    KekCheckResult,
    SecretsService,
    prove_kek_possession,
)
from candleviewer.settings import Settings
from spike.oms_demo_path import report
from spike.oms_demo_path.compose import (
    BuildM2,
    Prove,
    Stores,
    app_context,
    close,
    compose,
    postgres_stores,
    production_m2,
)
from spike.oms_demo_path.config import BUCKET_UID, RunConfig
from spike.oms_demo_path.cycles import run_cycles
from spike.oms_demo_path.harness import Harness, PublicReads
from spike.oms_demo_path.measure import ClockOffset, Timings, stats
from spike.oms_demo_path.metrics import export
from spike.oms_demo_path.modes import run_retention, run_shapes, run_soak
from spike.oms_demo_path.offline import (
    Corpus,
    CorpusVenue,
    MemoryAuditRepository,
    as_audit_repository,
    assume_hardened,
    default_accounts_fixture,
    default_corpus,
    offline_settings,
    offline_stack,
)
from spike.oms_demo_path.outputs import RunOutputs
from spike.oms_demo_path.recorder import RecordingConnector, RecordingTransport
from spike.oms_demo_path.safety import (
    GuardedPort,
    Refused,
    Shutdown,
    check_audit_dir,
    check_environment,
    check_no_proxy,
    check_online_args,
    check_venue_urls,
    confirm,
    flatten,
)
from spike.oms_demo_path.scrub import Scrubber

SCHEMA: Final = "e29-k01-harness/1"
MODES: Final = {
    "cycles": run_cycles,
    "soak": run_soak,
    "shapes": run_shapes,
    "retention": run_retention,
}
#: Budget #4 (`06-performance-and-load-standard.md` §5.2), demo: p95 < 300 ms end to end, of
#: which <= 250 ms is the venue's REST round trip and <= 50 ms is ours.
BUDGET_RTT_MS: Final = 250.0
BUDGET_OVERHEAD_MS: Final = 50.0
BUDGET_TOTAL_MS: Final = 300.0
#: The decision rule #843 agreed up front (Technical notes), as the record prints it.
BUDGET4_RULE: Final = (
    "p95 create RTT > 250 ms ⇒ budget #4 renegotiated in `06` §5.2, never absorbed by our 50 ms"
)
#: Where a run falls on that rule.
WITHIN: Final = "within"
RENEGOTIATE: Final = "renegotiate"
NO_DATA: Final = "no data"
MOUNTINFO: Final = Path("/proc/self/mountinfo")


def _wall_ms() -> int:
    return int(time.time() * 1000)


def _mountinfo() -> str:  # pragma: no cover - online only
    try:
        return MOUNTINFO.read_text(encoding="utf-8")
    except OSError:
        return ""


def configure_logging(scrubber: Scrubber) -> None:
    """JSON lines on stderr, every event scrubbed: the adapter's warnings name account and order
    ids, and a container's log is a file too."""

    def scrub_event(_logger: object, _method: str, event: Any) -> Any:
        return scrubber.scrub(event)

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            scrub_event,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(sys.stderr),
        cache_logger_on_first_use=False,
    )
    for noisy in ("httpx", "httpcore", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def offline_m2(
    store: CredentialStore, kcv: KcvStore, audit: AuditHandle, auth_keys: AuthKeyStore | None
) -> SecretsBundle:
    """`build_secrets_service`'s body over the harden seam (`assume_hardened`): offline only."""
    svc = SecretsService(
        store=store,
        kcv_store=kcv,
        audit=secrets_audit_sink(audit),
        auth_keys=auth_keys,
        harden=assume_hardened,
    )
    return secrets_bundle(svc, serving=(store, audit))


async def offline_proof(settings: Settings, kcv: KcvStore) -> KekCheckResult:
    return await prove_kek_possession(settings, kcv, harden=assume_hardened)


def budget4_verdict(create_rtt_p95_ms: float | None) -> str:
    """The side of `BUDGET4_RULE` a run fell on, from its p95 create RTT as printed (0.1 ms):
    above 250 ms `renegotiate`, else `within`; `no data` when no create was timed."""
    if create_rtt_p95_ms is None:
        return NO_DATA
    return RENEGOTIATE if create_rtt_p95_ms > BUDGET_RTT_MS else WITHIN


def budget(timings: Timings, *, offline: bool) -> dict[str, object]:
    """Budget #4's table: the three p95s (create RTT at the seam, our overhead, end to end at the
    port), the signing share beside our overhead, the rule and the run's verdict. An offline
    run's numbers are never evidence (`evidence: false`)."""
    rtt = stats(timings.rtt_ms.get("create", [])).get("p95")
    overhead = stats(timings.overhead_ms.get("create", [])).get("p95")
    total = stats(timings.port_ms.get("create", [])).get("p95")
    signing = stats(timings.signing_ms.get("create", []))
    return {
        "rule": BUDGET4_RULE,
        "verdict": budget4_verdict(rtt),
        "evidence": not offline,
        "create_rtt_p95_ms": rtt,
        "create_overhead_p95_ms": overhead,
        "create_signing_ms": {k: signing.get(k) for k in ("n", "p50", "p95", "max")},
        "create_end_to_end_p95_ms": total,
        "rtt_within_250ms": None if rtt is None else rtt <= BUDGET_RTT_MS,
        "overhead_within_50ms": None if overhead is None else overhead <= BUDGET_OVERHEAD_MS,
        "end_to_end_within_300ms": None if total is None else total < BUDGET_TOTAL_MS,
    }


def public_config(cfg: RunConfig) -> dict[str, object]:
    """The run's settings for the summary: no id, no path."""
    hidden = {"account_id", "key_ref", "out", "run_dir", "corpus", "stack_audit_wal"}
    return {k: v for k, v in asdict(cfg).items() if k not in hidden}


@asynccontextmanager
async def open_harness(
    cfg: RunConfig,
    outputs: RunOutputs,
    scrubber: Scrubber,
    shutdown: Shutdown,
    notes: dict[str, Any],
    venue: CorpusVenue | None = None,
) -> AsyncIterator[Harness]:
    timings, offset = Timings(), ClockOffset()
    scratch: tempfile.TemporaryDirectory[str] | None = None
    stores: Stores | None = None
    recorder: RecordingTransport | None = None
    build: BuildM2
    prove: Prove
    try:
        if cfg.online:  # pragma: no cover - the online path runs on the demo host only
            settings = Settings()
            check_environment(settings)
            check_audit_dir(
                settings.audit_wal_path,
                stack_wal=cfg.stack_audit_wal,
                stack_volume=cfg.stack_volume,
                mountinfo=_mountinfo(),
            )
            stores = postgres_stores(settings)
            inner: httpx.AsyncBaseTransport = httpx.AsyncHTTPTransport(
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=20)
            )
            connect: Callable[[str], Any] = connect_private_stream
            account_id, key_ref = cast("UUID", cfg.account_id), cast("str", cfg.key_ref)
            build, prove = production_m2, prove_kek_possession
        else:
            scratch = tempfile.TemporaryDirectory(prefix="spike-843-")
            state = Path(scratch.name)
            settings = offline_settings(state)
            stack_wal = state / "stack-audit" / "audit.wal"
            (stack_wal.parent / "lane").mkdir(parents=True)  # the stack's lane, as cv-api's
            check_environment(settings)
            check_audit_dir(
                settings.audit_wal_path,
                stack_wal=str(stack_wal),
                stack_volume=cfg.stack_volume,
                mountinfo="",
            )
            stack = await offline_stack(
                settings,
                app_context(settings, ReadOnlyGate()),
                accounts_fixture=default_accounts_fixture(),
            )
            stores = Stores(
                credentials=stack.store,
                kcv=stack.store,
                auth_keys=None,
                audit=as_audit_repository(MemoryAuditRepository()),
            )
            venue = venue or CorpusVenue(
                Corpus(cfg.corpus or default_corpus()),
                drop_every=cfg.drop_every,
                reorder_every=cfg.reorder_every,
            )
            inner = httpx.MockTransport(venue.handle)
            connect = venue.connect
            account_id, key_ref = stack.account_id, stack.key_ref
            build, prove = offline_m2, offline_proof
        scrubber.secret(str(account_id))
        scrubber.secret(key_ref)
        recorder = RecordingTransport(inner, scrubber=scrubber, outputs=outputs, timings=timings)
        connector = RecordingConnector(connect, scrubber=scrubber, outputs=outputs)
        composed = await compose(
            settings,
            stores,
            rest_transport=recorder,
            private_ws_connect=connector,
            clock_offset_ms=offset.read,
            build_m2=build,
            prove=prove,
            timings=timings,
        )
    except BaseException:  # nothing composed: what was opened for it is closed here
        if recorder is not None:
            await recorder.aclose()
        for closer in [] if stores is None else stores.closers:
            await closer()  # pragma: no cover - only the online stores hold pools
        if scratch is not None:
            scratch.cleanup()
        raise
    public_close: Callable[[], Any] | None = None
    try:
        if venue is None:  # pragma: no cover - online only
            client = composed.venue.public_rest_client("demo")
            get_public: Any = client.get_public
            public_close = client.aclose
        else:
            get_public = venue.get_public
        account = AccountRef(
            account_id=AccountId(account_id), uid=BUCKET_UID, environment="demo", key_ref=key_ref
        )
        yield Harness(
            port=GuardedPort(composed.port, timings),
            account=account,
            public=PublicReads(get_public, lambda: int(time.time() * 1_000_000)),
            outputs=outputs,
            scrubber=scrubber,
            shutdown=shutdown,
            offset=offset,
            recorder=recorder,
            connector=connector,
            skewed_port=composed.skewed_port,
        )
    finally:
        notes["audit"] = await close(composed)
        notes["kek_version"] = composed.kek_version
        if public_close is not None:  # pragma: no cover - online only
            await public_close()
        if venue is not None:
            notes["offline_venue"] = {
                "injected": {"drop_every": cfg.drop_every, "reorder_every": cfg.reorder_every},
                "withheld_from_stream": venue.dropped,
                "order_before_execution": venue.reordered,
                "venue_fills": venue.fills,
            }
        if scratch is not None:
            scratch.cleanup()


def _summarise(h: Harness, summary: dict[str, Any]) -> None:
    timings = h.port.timings
    summary |= timings.summary()
    summary["budget4"] = budget(timings, offline=bool(summary.get("offline")))
    summary["private"] = h.stream.summary()
    summary["clock"] = {
        "offset_ms": h.offset.value,
        "best_rtt_ms": None if h.offset.best_rtt_ms is None else round(h.offset.best_rtt_ms, 2),
        "samples": h.offset.samples,
    }
    summary["safety"] = {
        "openers": h.port.openers,
        "openers_with_native_stop": h.port.openers,
        "closes_reduce_only": h.port.closes,
    }
    if h.recorder is not None:
        summary["error_codes"] = {str(k): v for k, v in sorted(h.recorder.codes.items())}
        summary["error_shapes"] = {str(k): v for k, v in sorted(h.recorder.shapes.items())}
    if h.connector is not None:
        summary["private"]["socket"] = {
            "dials": h.connector.dials,
            "frames": dict(sorted(h.connector.counts.items())),
            "max_silence_s": round(h.connector.max_silence_s, 3),
        } | h.connector.gaps()


async def run(
    cfg: RunConfig,
    *,
    read_line: Callable[[str], str] = input,
    clock_ms: Callable[[], int] = _wall_ms,
    venue: CorpusVenue | None = None,
) -> int:
    """One run (see the module docstring); `venue` is a test's own corpus venue."""
    started = clock_ms()
    if cfg.mode == "report":
        run_dir = cfg.run_dir or cfg.out
        sys.stdout.write(report.render(run_dir))
        report.write_addendum(run_dir, cfg.out)
        return 0
    check_online_args(cfg, now_ms=started)
    check_venue_urls(SIGNED_REST_BASES, PRIVATE_WS_URLS)
    check_no_proxy(os.environ)
    if cfg.out.exists() and any(cfg.out.iterdir()):
        raise Refused("--out holds an earlier run: give each run a directory of its own")
    if cfg.online:
        confirm(read_line)
    scrubber = Scrubber()
    outputs = RunOutputs(cfg.out, scrubber)
    configure_logging(scrubber)
    shutdown = Shutdown()
    remove = shutdown.install(asyncio.get_running_loop())
    summary: dict[str, Any] = {
        "schema": SCHEMA,
        "mode": cfg.mode,
        "offline": not cfg.online,
        "started_at_ms": started,
        "config": public_config(cfg),
    }
    notes: dict[str, Any] = {}
    metrics_text = ""
    code = 0
    try:
        async with open_harness(cfg, outputs, scrubber, shutdown, notes, venue) as h:
            try:
                summary[cfg.mode] = await MODES[cfg.mode](h, cfg)
                if (shutdown.reason or "").startswith("error:"):
                    code = 1  # the mode ended itself on repeated failures
            except Exception as exc:
                shutdown.trip(f"error:{type(exc).__name__}")
                code = 2 if isinstance(exc, Refused) else 1
                summary["error"] = type(exc).__name__
                structlog.get_logger("spike").error("mode_failed", exc_info=True)
            finally:
                ending: dict[str, Any] = {"reason": shutdown.reason or "completed"}
                if cfg.places_orders:
                    ending |= await flatten(h.port, h.account, h.links.flatten, sleep=h.sleep)
                summary["shutdown"] = ending
                _summarise(h, summary)
                outcomes = summary.get("cycles", {}).get("outcomes", {})
                metrics_text = export(h.port.timings, h.stream, outcomes, h.offset.value)
    except Refused as exc:
        code = 2
        summary["refused"] = str(exc)
    finally:
        remove()
        summary |= notes
        summary["ended_at_ms"] = clock_ms()
        summary["outputs"] = {"events": outputs.events, "refused_by_scrub": outputs.refused}
        outputs.write_summary(summary)
        if metrics_text:
            outputs.write_metrics(metrics_text)
        outputs.close()
    return code


def summary_of(out: Path) -> Mapping[str, Any]:
    loaded: Mapping[str, Any] = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    return loaded
