"""Diagnostic support bundle generator (E04-S02, US-OBS-007, SR-124).

Assembles logs, a metrics snapshot, health report, recent `system_events`,
active alerts, build-info and allow-listed config into a zip. Safety
properties: assembled in a 0700 temp dir on the destination filesystem, scanned
(fail closed) before it is moved into place, size-capped newest-first, never
uploaded. Concurrency 1; hard timeout; free-disk precheck.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import os
import shutil
import tempfile
import uuid
import zipfile
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from candleviewer.observability.bundle_scan import Finding, scan_tree

DEFAULT_CAP_BYTES: Final = 200 * 1024 * 1024
MAX_WINDOW: Final = timedelta(hours=24)
TIMEOUT_S: Final = 120.0

#: Config keys safe to ship verbatim. Everything else becomes `<omitted>`
#: (allow-list, not deny-list: a new secret key is hidden by default).
CONFIG_ALLOW_LIST: Final[frozenset[str]] = frozenset(
    {
        "CV_ENV",
        "CV_ENVIRONMENT",
        "CV_LOG_LEVEL",
        "CV_BIND_HOST",
        "CV_BIND_PORT",
        "CV_FEED",
        "CV_GIT_SHA",
        "CV_VERSION",
        "CV_SUPPORT_BUNDLE_ENABLED",
        "CV_RETENTION_DAYS",
        # #2893: a scenario token, never a secret; a bundle shows the stack is in fixture mode.
        "CV_ACCOUNT_FIXTURE",
    }
)
_FLAG_PREFIX: Final = "CV_FLAG_"
_PIN_SUFFIX: Final = "_VERSION_PIN"


class BundleError(Exception):
    """Carries a stable error code; the message never contains secret values."""

    def __init__(self, code: str, message: str, findings: tuple[Finding, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.findings = findings


def filter_config(config: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in config.items():
        allowed = (
            key in CONFIG_ALLOW_LIST or key.startswith(_FLAG_PREFIX) or key.endswith(_PIN_SUFFIX)
        )
        # Even an allow-listed key must not smuggle a secret through its value.
        out[key] = value if allowed else "<omitted>"
    return out


def validate_window(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None or start > end:
        raise BundleError("BUNDLE_WINDOW_INVALID", "window must be tz-aware with from <= to")
    if end - start > MAX_WINDOW:
        raise BundleError("BUNDLE_WINDOW_TOO_LARGE", "window exceeds 24 h")


def truncate_newest_first(lines: Iterable[str], budget: int) -> tuple[list[str], int | None]:
    """Keep newest lines (input is newest-first) within `budget` bytes.

    Returns lines in chronological order and the count dropped (None if none).
    """
    kept: list[str] = []
    used = 0
    dropped = 0
    full = False
    for line in lines:
        size = len(line.encode("utf-8")) + 1
        if full or used + size > budget:
            full = True
            dropped += 1
            continue
        kept.append(line)
        used += size
    kept.reverse()
    return kept, (dropped or None)


@dataclass
class BundleSources:
    """Injected collectors; `logs` yields lines newest-first for the window."""

    logs: Callable[[datetime, datetime], Iterable[str]]
    metrics: Callable[[], str]
    health: Callable[[], Mapping[str, Any]]
    system_events: Callable[[datetime, datetime], list[dict[str, Any]]]
    alerts: Callable[[], list[dict[str, Any]]]
    build_info: Callable[[], Mapping[str, Any]]
    config: Callable[[], Mapping[str, Any]]


@dataclass(frozen=True)
class BundleResult:
    path: Path
    size_bytes: int
    truncated: bool


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str, sort_keys=True), encoding="utf-8")


def _default_free(path: Path) -> int:
    return shutil.disk_usage(path).free


def _utc_now() -> datetime:
    return datetime.now(UTC)


def build_bundle(
    sources: BundleSources,
    out_dir: Path,
    start: datetime,
    end: datetime,
    *,
    cap_bytes: int = DEFAULT_CAP_BYTES,
    free_bytes: Callable[[Path], int] = _default_free,
    now: Callable[[], datetime] = _utc_now,
) -> BundleResult:
    """Synchronous generation (run in a worker thread). Fails closed."""
    validate_window(start, end)
    out_dir.mkdir(parents=True, exist_ok=True)
    if free_bytes(out_dir) < 2 * cap_bytes:
        raise BundleError("BUNDLE_DISK_INSUFFICIENT", "free disk below 2x the bundle cap")
    work = Path(tempfile.mkdtemp(prefix=".bundle-", dir=out_dir))
    os.chmod(work, 0o700)
    try:
        return _assemble(sources, work, out_dir, start, end, cap_bytes, now)
    except OSError as exc:
        raise BundleError(
            "BUNDLE_DISK_INSUFFICIENT", f"write failed: {type(exc).__name__}"
        ) from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _assemble(
    sources: BundleSources,
    work: Path,
    out_dir: Path,
    start: datetime,
    end: datetime,
    cap: int,
    now: Callable[[], datetime],
) -> BundleResult:
    stage = work / "stage"
    stage.mkdir()
    _write_json(stage / "health.json", dict(sources.health()))
    _write_json(stage / "system_events.json", sources.system_events(start, end))
    _write_json(stage / "alerts.json", sources.alerts())
    _write_json(stage / "build_info.json", dict(sources.build_info()))
    _write_json(stage / "config.json", filter_config(sources.config()))
    (stage / "metrics.prom").write_text(sources.metrics(), encoding="utf-8")
    fixed = sum(p.stat().st_size for p in stage.iterdir())
    budget = max(cap - fixed - 64 * 1024, 0)  # headroom for the manifest
    kept, dropped = truncate_newest_first(sources.logs(start, end), budget)
    (stage / "logs.ndjson").write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    truncation: list[dict[str, Any]] = []
    if dropped:
        truncation.append(
            {
                "artefact": "logs.ndjson",
                "dropped_lines": dropped,
                "policy": "newest-first",
                "window_from": start.isoformat(),
                "window_to": end.isoformat(),
                "note": "oldest lines in the window were dropped; newest preserved",
            }
        )
    manifest = {
        "generated_at": now().isoformat(),
        "window": {"from": start.isoformat(), "to": end.isoformat()},
        "cap_bytes": cap,
        "truncated": truncation,
        "artefacts": [
            {"name": p.name, "bytes": p.stat().st_size, "sha256": _sha256(p)}
            for p in sorted(stage.iterdir())
        ],
    }
    _write_json(stage / "manifest.json", manifest)
    findings = scan_tree(stage)
    if findings:
        shutil.rmtree(work, ignore_errors=True)
        raise BundleError(
            "BUNDLE_SECRET_DETECTED",
            "secret pattern detected: " + ", ".join(f"{f.file}:{f.rule}" for f in findings),
            tuple(findings),
        )
    archive = work / "bundle.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(stage.iterdir()):
            zf.write(p, p.name)
    os.chmod(archive, 0o600)
    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    final = out_dir / f"support-bundle-{stamp}-{uuid.uuid4().hex[:8]}.zip"
    os.replace(archive, final)  # same filesystem: atomic
    return BundleResult(final, final.stat().st_size, bool(truncation))


@dataclass
class BundleJob:
    id: str
    status: str = "running"  # running | succeeded | failed
    error_code: str | None = None
    path: str | None = None
    size_bytes: int | None = None
    truncated: bool = False
    _task: asyncio.Task[None] | None = field(default=None, repr=False)

    def view(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "error_code": self.error_code,
            "download_path": self.path,
            "size_bytes": self.size_bytes,
            "truncated": self.truncated,
        }


class SupportBundleService:
    """Concurrency-1 background runner; a second request raises ALREADY_RUNNING."""

    def __init__(
        self,
        sources: BundleSources,
        out_dir: Path,
        *,
        cap_bytes: int = DEFAULT_CAP_BYTES,
        timeout_s: float = TIMEOUT_S,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._sources = sources
        self._out = out_dir
        self._cap = cap_bytes
        self._timeout = timeout_s
        self._on_event = on_event or (lambda _r, _d: None)
        self._jobs: dict[str, BundleJob] = {}
        self._running: BundleJob | None = None

    def get(self, job_id: str) -> BundleJob | None:
        return self._jobs.get(job_id)

    def start(
        self,
        start: datetime,
        end: datetime,
        on_complete: Callable[[BundleJob], Awaitable[None]] | None = None,
    ) -> BundleJob:
        validate_window(start, end)
        if self._running is not None:
            raise BundleError("BUNDLE_ALREADY_RUNNING", "a bundle is already being generated")
        job = BundleJob(id=str(uuid.uuid4()))
        self._jobs[job.id] = job
        self._running = job
        job._task = asyncio.get_running_loop().create_task(self._run(job, start, end, on_complete))
        return job

    async def _run(
        self,
        job: BundleJob,
        start: datetime,
        end: datetime,
        on_complete: Callable[[BundleJob], Awaitable[None]] | None,
    ) -> None:
        t0 = _utc_now()
        result = "ok"
        try:
            res = await asyncio.wait_for(
                asyncio.to_thread(
                    build_bundle, self._sources, self._out, start, end, cap_bytes=self._cap
                ),
                timeout=self._timeout,
            )
            job.status, job.path = "succeeded", str(res.path)
            job.size_bytes, job.truncated = res.size_bytes, res.truncated
        except BundleError as exc:
            job.status, job.error_code = "failed", exc.code
            result = "secret_detected" if exc.code == "BUNDLE_SECRET_DETECTED" else "error"
            # Log file + rule only, never the matched value.
            findings = [dataclasses.asdict(f) for f in exc.findings]
            self._on_event(result, {"code": exc.code, "findings": findings})
        except TimeoutError:
            job.status, job.error_code = "failed", "BUNDLE_TIMEOUT"
            result = "timeout"
        except Exception:
            job.status, job.error_code = "failed", "BUNDLE_FAILED"
            result = "error"
        finally:
            self._running = None
            if result == "ok":
                secs = (_utc_now() - t0).total_seconds()
                self._on_event("ok", {"size_bytes": job.size_bytes, "seconds": secs})
            if on_complete is not None:
                try:
                    await on_complete(job)
                except Exception:  # audit failure must not wedge the runner
                    job.status, job.error_code = "failed", "BUNDLE_AUDIT_FAILED"
                    if job.path:  # unaudited export must not remain (C-2.9)
                        await asyncio.to_thread(Path(job.path).unlink, missing_ok=True)
                        job.path = None
