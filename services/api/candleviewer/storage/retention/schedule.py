"""Scheduler registration behind a flag, off by default in dev (E07-T05)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


class _RetentionSettings(Protocol):
    retention_enabled: bool
    retention_cron: str
    export_cron: str
    compact_cron: str


@dataclass(frozen=True, slots=True)
class RetentionSchedule:
    enabled: bool
    retention_cron: str
    export_cron: str
    compact_cron: str

    @classmethod
    def from_settings(cls, settings: _RetentionSettings) -> RetentionSchedule:
        return cls(
            enabled=settings.retention_enabled,
            retention_cron=settings.retention_cron,
            export_cron=settings.export_cron,
            compact_cron=settings.compact_cron,
        )

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> RetentionSchedule:
        """Build from an explicit mapping (never reads os.environ)."""
        return cls(
            enabled=env.get("CV_RETENTION_ENABLED", "false").lower() == "true",
            retention_cron=env.get("CV_RETENTION_CRON", "0 3 * * *"),
            export_cron=env.get("CV_EXPORT_CRON", "15 2 * * *"),
            compact_cron=env.get("CV_COMPACT_CRON", "0 3 * * 0"),
        )

    def jobs(self) -> dict[str, str]:
        """Cron per job name; empty when the feature flag is off."""
        if not self.enabled:
            return {}
        return {
            "export": self.export_cron,
            "retention": self.retention_cron,
            "compact": self.compact_cron,
        }

    def rule_jobs(self) -> dict[str, str]:
        """Rule-run pruning job (E35-T02): shares the retention cron; empty when off."""
        if not self.enabled:
            return {}
        return {"rule_runs_prune": self.retention_cron}

    def alert_jobs(self) -> dict[str, str]:
        """`alert_deliveries` purge (E40-T01).

        180 d hot, archive_parquet, archives to Parquet, runs on the cv_owner DSN
        (CV_PG_OWNER_DSN).
        """
        if not self.enabled:
            return {}
        return {"alert_deliveries_purge": self.retention_cron}

    def drawings_jobs(self) -> dict[str, str]:
        """Soft-deleted `drawings` purge (E14-T01): 90 d, empty when off.

        The value is the retention cron for reference only: the task is a fixed 24 h
        interval loop (`DrawingsPurgeTask`), not cron-driven, like `alert_jobs()`.
        """
        if not self.enabled:
            return {}
        return {"drawings_purge": self.retention_cron}

    def workspaces_jobs(self) -> dict[str, str]:
        """Soft-deleted `workspaces`/`layouts` purge (E15-T01): 90 d, empty when off.

        The value is the retention cron for reference only: the task is a fixed 24 h
        interval loop (`WorkspacesPurgeTask`), not cron-driven, like `drawings_jobs()`.
        """
        if not self.enabled:
            return {}
        return {"workspaces_purge": self.retention_cron}
