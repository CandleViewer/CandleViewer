"""Settings → KEK sources (e27-kek.md §4 hard rules). Private to M2.

`validate_kek_settings` is the fatal pre-boot check (run before any module starts);
`sources_from_settings` builds the current/previous sources and the optional ack target.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog

from candleviewer.secrets._kek import LIVE_FILE_PREFIX, KekSource, NoKekSource, PathKekSource
from candleviewer.secrets.errors import KekSourceNotPermitted
from candleviewer.settings import Environment, Settings


@dataclass(frozen=True)
class KekSources:
    current: KekSource
    previous: KekSource | None
    ack_path: Path | None


def _kind(settings: Settings) -> str:
    return "handle" if settings.kek_source == "host-keychain" else settings.kek_source


def validate_kek_settings(settings: Settings) -> None:
    """Fatal (`kek_source_not_permitted`): `file` in live. Warns for `file` in demo/testnet."""
    kind = _kind(settings)
    live = settings.environment is Environment.LIVE
    if kind == "file" and live:
        raise KekSourceNotPermitted("kek_source_not_permitted")
    systemd = settings.kek_handle.startswith(LIVE_FILE_PREFIX)
    if live and kind == "handle" and not systemd and not settings.kek_ack_path:
        # Outside the systemd credential dir a live handle is the read-once launcher FIFO:
        # refuse the missing ack path *before* the FIFO is drained (else a config error would
        # look like KEK theft to the launcher's anomaly check).
        raise KekSourceNotPermitted("kek_source_not_permitted")
    if kind == "file":
        structlog.get_logger(__name__).warning(
            "secrets.kek_file_source", environment=settings.environment.value
        )


def sources_from_settings(settings: Settings) -> KekSources:
    validate_kek_settings(settings)
    kind = _kind(settings)
    live = settings.environment is Environment.LIVE
    if kind == "none" or not settings.kek_handle:
        return KekSources(NoKekSource(), None, None)

    def src(path: str, version: int) -> PathKekSource:
        return PathKekSource(
            Path(path),
            version,
            allow_fifo=kind == "handle",
            env_name=settings.environment.value,
            live=live,
        )

    prev = settings.kek_prev_handle
    ack = settings.kek_ack_path if kind == "handle" else None
    return KekSources(
        src(settings.kek_handle, settings.kek_version),
        src(prev, settings.kek_version - 1) if prev else None,
        Path(ack) if ack else None,
    )
