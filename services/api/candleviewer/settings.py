"""Typed application settings (M1 `config`).

Loads configuration from the environment only (`.env` file + `CV_*` env vars,
never a checked-in secrets file — C-12.9), per the layering documented in
`docs/plan/20-architecture.md` Sec.7.2: packaged defaults -> `infra/compose/.env`
-> environment variables -> Postgres-stored runtime settings -> per-user
preferences. Only the first two layers are implemented by this class; the
runtime/per-user layers are owned by M21 `admin`.

Security: `__repr__`/`__str__` never print secret values (redacting `__str__`
below) — an early instance of M24's redaction-filter requirement. Any field
whose name matches `(key|secret|token|password|dsn)` (case-insensitive) is a
`SecretStr` so it can never leak into logs, tracebacks or `repr()` by
accident.
"""

from __future__ import annotations

import ipaddress
import re
from enum import StrEnum
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_QUESTDB_DEV_PASSWORD = "quest"  # noqa: S105 - the QuestDB OSS default, refused on live
_REDACT_NAME_RE = re.compile(r"(key|secret|token|password|dsn)", re.IGNORECASE)


class Environment(StrEnum):
    """The three structural exchange environments (P9, `20-architecture.md` Sec.7.1).

    `live` | `demo` | `testnet` select hosts, keys, storage namespace and code
    paths — never inferred, always explicit (arch P9).
    """

    LIVE = "live"
    DEMO = "demo"
    TESTNET = "testnet"


class FeedMode(StrEnum):
    """`CV_FEED` switch (`20-architecture.md` Sec.7.3).

    `synthetic` replays `packages/fixtures/raw` at configurable rates so
    engineers and CI can work without exchange credentials; E2E tests and dev
    defaults never use `live` here (this is a *feed* toggle, orthogonal to
    `Environment`).
    """

    LIVE = "live"
    SYNTHETIC = "synthetic"


class RecorderWalDirError(ValueError):
    """`CV_RECORDER_WAL_DIR` is unsafe (relative, `..`, symlink, or outside the data dir)."""

    code = "recorder_wal_dir_invalid"


#: Ports a browser leaves out of a serialised origin (WHATWG URL "special" schemes).
_DEFAULT_PORTS: dict[str, int] = {"http": 80, "https": 443, "ws": 80, "wss": 443}
_ORIGIN_SCHEME_RE = re.compile(r"[a-z][a-z0-9+.-]*")
_ORIGIN_LABEL = r"[a-z0-9_](?:[a-z0-9_-]*[a-z0-9_])?"
_ORIGIN_HOST_RE = re.compile(rf"{_ORIGIN_LABEL}(?:\.{_ORIGIN_LABEL})*\.?")


def _is_origin_host(host: str) -> bool:
    if ":" in host:  # IPv6 literal; `urlsplit` drops the brackets
        try:
            return str(ipaddress.IPv6Address(host)) == host
        except ValueError:
            return False
    return _ORIGIN_HOST_RE.fullmatch(host) is not None


def is_serialised_origin(entry: str) -> bool:
    """#2239 (SR-042): True when `entry` is spelled exactly as a browser serialises an
    origin: `scheme://host[:port]` with a lowercase scheme and host, an ASCII (punycode)
    host or IP literal, no userinfo/path/query/fragment, and no explicit default port.
    `null` and wildcards never qualify."""
    try:
        parts = urlsplit(entry)
        port = parts.port
    except ValueError:
        return False
    host = parts.hostname or ""
    if not _ORIGIN_SCHEME_RE.fullmatch(parts.scheme) or not _is_origin_host(host):
        return False
    if "@" in parts.netloc or parts.path or parts.query or parts.fragment:
        return False
    if port is not None and (port == 0 or _DEFAULT_PORTS.get(parts.scheme) == port):
        return False
    netloc = f"[{host}]" if ":" in host else host
    return entry == f"{parts.scheme}://{netloc}" + ("" if port is None else f":{port}")


class Settings(BaseSettings):
    """Root application settings, populated from the environment only.

    `git_sha`/`version` are build-time metadata (E02-T08 packaging injects
    `CV_GIT_SHA`; defaults are `"unknown"`/the package version) surfaced by
    `/healthz` and `/readyz` (E02-T05 acceptance criterion 3).
    """

    model_config = SettingsConfigDict(
        env_prefix="CV_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        frozen=True,
    )

    environment: Environment = Environment.DEMO
    feed: FeedMode = FeedMode.SYNTHETIC
    feed_rate_hz: float = Field(default=2.0, gt=0.0)
    feed_sample_path: str = "packages/fixtures/raw/synthetic_sample.jsonl"

    bybit_api_key: SecretStr | None = None
    bybit_api_secret: SecretStr | None = None

    # E04-T03: private-bind-only `/metrics` listener (`CV_METRICS_ENABLED`,
    # `CV_METRICS_BIND`). Non-private hosts are refused at startup.
    metrics_enabled: bool = True
    metrics_bind: str = "127.0.0.1:9108"

    # E04-T06: latency instrumentation + frontend telemetry push
    # (`CV_TELEMETRY_ENABLED`, `CV_TELEMETRY_SAMPLE_N`) and OpenTelemetry spans
    # on the ADR-0014 §5 paths only (`CV_OTEL_ENABLED`, `CV_OTEL_ENDPOINT`).
    telemetry_enabled: bool = True
    telemetry_sample_n: int = Field(default=100, ge=1)
    otel_enabled: bool = False
    otel_endpoint: str | None = None

    bind_host: str = "127.0.0.1"
    bind_port: int = 8080

    # E09-T04: Tailscale-only reachability guard (US-ONB-008). Comma-joined
    # CIDR list (e.g. "100.64.0.0/10,192.168.1.0/24"); loopback/`::1` are
    # always allowed in addition (see `candleviewer.net.cidr.CidrAllowList`).
    # A plain string (not a JSON array) so the deployment runbook/`.env` can
    # set it without quoting a JSON list. Empty by default so a forgotten env
    # var fails closed to loopback-only rather than silently allowing
    # everything.
    mesh_cidrs_csv: str = ""
    # Boot + hourly re-check cadence (Performance notes: must not block the
    # event loop; runs in a thread executor with a 2s timeout — see
    # `candleviewer.net.scheduler`).
    mesh_self_check_interval_s: float = Field(default=3600.0, gt=0.0)
    # No trusted proxy by default: `X-Forwarded-For` and friends are always
    # ignored unless both are set, and even then only the configured proxy's
    # own immediate peer address is trusted to supply the header.
    mesh_trusted_proxy_header: str | None = None
    mesh_trusted_proxy_address: str | None = None

    # E09-S03: CSRF allow-list for cookie-authenticated `POST /auth/refresh`
    # (`CV_ALLOWED_ORIGINS`, comma separated, e.g. "http://127.0.0.1:5173").
    # Empty (default) fails closed: every cookie refresh is refused.
    # #2239 (SR-042/SR-183): also the WS upgrade allow-list (`23-ws-protocol.md`
    # §2.5); empty refuses every WS upgrade. Every entry must be a serialised
    # origin (`is_serialised_origin`); a bad entry fails startup.
    allowed_origins: str = ""

    pg_dsn: SecretStr = SecretStr("postgresql+asyncpg://cv:cv@localhost:5432/candleviewer")
    # E40-T01: `cv_owner` DSN used ONLY by the alert_deliveries retention purge
    # (trg_ad_append refuses DELETE for every other role). Unset => purge off.
    pg_owner_dsn: SecretStr | None = None
    questdb_ilp: str = "questdb:9009"
    questdb_pg: str = "questdb:8812"
    # PG-wire credentials for the bars ILP sink probes (#2037).
    questdb_pg_user: str = "admin"
    questdb_pg_password: SecretStr = SecretStr("quest")
    parquet_root: str = "/data/parquet"

    # E07-T01: selects the M10 `storage` tier client implementations.
    # `"fake"` (the default) wires the in-memory fakes from
    # `candleviewer.storage.testing` and performs no I/O — this is what lets
    # `create_app()`/the supervisor boot with no database containers running
    # (ticket acceptance criterion 1). `"real"` is reserved for E07-T02/T03/
    # T04's engine clients; selecting it before those land is a configuration
    # error the storage service surfaces via `StorageTierUnavailable`.
    storage_backend: Literal["fake", "real"] = "fake"

    # QA #1658: auth key material (hex, 32 bytes each) resolved by the
    # composition root until E27-T02's M2 KEK loader lands. Required when
    # `storage_backend="real"` and environment is live (AuthService also
    # refuses a live start without them).
    auth_totp_key_hex: SecretStr | None = None
    auth_recovery_hmac_key_hex: SecretStr | None = None
    auth_pepper: SecretStr = SecretStr("")
    # #2090 (SR-041): dedicated CSRF-token HMAC key (hex, 32 bytes), separate from
    # the TOTP / recovery keys and the refresh tokens. Rotatable: move the old
    # value to `auth_csrf_previous_key_hex` (verify-only) for one refresh lifetime.
    auth_csrf_key_hex: SecretStr | None = None
    auth_csrf_previous_key_hex: SecretStr | None = None

    # E03-T10: bounds `pg_advisory_lock` acquisition in the boot-time
    # migration runner (`candleviewer.migrations.boot`). A deadlocked
    # migration in another process turns into a clear `CI-DEP-004` error at
    # this timeout instead of hanging startup indefinitely (ADR-0013 rule 9).
    migration_lock_timeout_s: float = Field(default=300.0, gt=0.0)

    # E09-T02: `audit.emit` durably buffers to an on-disk WAL before writing
    # to `audit_log` (F8 — survives a Postgres outage), and the daily
    # checkpoint job appends the head hash to a file outside the database
    # volume so tail truncation is detectable even if Postgres data is lost.
    audit_wal_path: str = "var/audit/audit.wal"
    audit_checkpoint_path: str = "var/audit/checkpoints.ndjson"

    # E42-T02 (contract #2392): per-user limits for `GET /admin/audit`.
    audit_query_rate_per_minute: int = Field(default=60, ge=1)
    audit_query_max_concurrent: int = Field(default=2, ge=1)
    # Capped at the relational pool's own 30 s statement timeout.
    audit_query_timeout_ms: int = Field(default=4000, ge=1, le=30_000)
    # Per-user audit record budget (same contract). The owner has a separate, larger cap.
    audit_record_budget_per_hour: int = Field(default=120, ge=1)
    audit_record_budget_owner_per_hour: int = Field(default=600, ge=1)
    audit_read_flush_pages: int = Field(default=50, ge=1)
    audit_read_flush_seconds: float = Field(default=300.0, gt=0.0)
    audit_budget_tracked_users: int = Field(default=1024, ge=64)
    audit_inflight_writes: int = Field(default=64, ge=1)

    # E27-T02 / e27-kek.md §4: KEK source vocabulary. `host-keychain` is a deprecated alias
    # of `handle` for one release. The KEK itself never enters Settings or os.environ.
    kek_source: Literal["handle", "file", "none", "host-keychain"] = "handle"
    kek_handle: str = "/run/secrets/cv_kek"
    kek_prev_handle: str | None = None  # only during a KEK rotation window
    kek_version: int = Field(default=1, ge=1)
    # Nonce-ack file: separate writable path (the handoff dir is mounted read-only).
    kek_ack_path: str | None = None
    dek_cache_ttl_s: float = Field(default=300.0, ge=0.0, le=300.0)

    # E04-T01: `configure_logging()` inputs. `log_format="console"` is only
    # permitted in dev/CI contexts — enforced by
    # `candleviewer.observability.logging.configure_logging`, not here.
    log_level: str = "info"
    log_format: Literal["json", "console"] = "json"
    # RFC 3339 instant; absent (`None`) means body logging is off (SR-123
    # default-off requirement). Kept as `str | None` rather than `datetime`
    # so an unparsable value fails fast at settings-load time with a clear
    # `CV_LOG_BODIES_UNTIL` error rather than silently becoming `None`.
    log_bodies_until: str | None = None

    recv_window_ms: int = 5000
    max_ws_topics_per_conn: int = 64
    heatmap_cadence_ms: int = 100
    book_depth: int = 200
    recorder_retention_days: int = 30
    recorder_hot_days: int = 7
    # E16-T03: StreamWriter spill WAL (bounded; SR-096 — a volume separate from the backend).
    # Empty (default) = `<data dir>/recorder-wal`, data dir = parent of `parquet_root`.
    recorder_wal_dir: str = ""
    recorder_wal_max_bytes: int = Field(default=1 << 30, ge=1 << 20)
    # #2048: max concurrent DuckDB scans for the /market/klines cold tier (C-2.18).
    cold_kline_concurrency: int = 2
    # #2060: seconds between reloads of the klines hot-retention rule (rules are editable).
    kline_boundary_refresh_s: int = 600
    disk_cap_gb: int = 500
    # E08-T04: public WS ingestion skeleton flag (C-4.13: off by default;
    # removal tracked by E08-T05). Public data only — no credentials.
    ingestion_ws_enabled: bool = False
    # E17 client WS gateway (`23-ws-protocol.md` §4, §9.4): `CV_WS_*`. Defaults = the doc.
    ws_auth_timeout_s: float = Field(default=10.0, gt=0, le=60)
    ws_max_inbound_frame_bytes: int = Field(default=262_144, ge=1024, le=1_048_576)
    ws_max_connections_per_user: int = Field(default=8, ge=1, le=64)
    ws_shutdown_grace_ms: int = Field(default=5000, ge=0, le=60_000)
    ws_shutdown_expected_downtime_ms: int = Field(default=20_000, ge=0, le=600_000)
    # E12 #2031: run the BarBuilderSet + BarWriter in the app (C-4.13: off by default; removal
    # with E12-T05 #398 / E12-T06 #399, the first consumers). Never gates a safety invariant.
    # `bars_state_root` holds the 60 s state blobs, created owner-only (0700) where the platform
    # allows. Empty (default) = `<data dir>/bars/state`, where the data dir is the parent of
    # `parquet_root` (the app's only data-dir setting). Otherwise it must be absolute and not a
    # symlink; it is normalised with expanduser().resolve() at settings load.
    bars_enabled: bool = False
    bars_state_root: str = ""
    # E12-S04: renko builders (`bars.renko`, C-4.13: off by default; on in staging; the
    # descoping switch, removal at R2). Never gates a safety invariant (C-4.14).
    bars_renko_enabled: bool = False
    # E35-S02-B1 (#1809): run the deterministic rule evaluator in the app (C-4.13: off by
    # default). Never gates a safety invariant (C-4.14): native SL / scope checks stay on.
    rules_evaluator_enabled: bool = False
    # E40-T03: run the server-side alert evaluator (C-4.13: off by default until E40-T04's
    # dispatcher ships; removal with E40-Q02). Never gates a safety invariant (C-4.14).
    alerts_evaluator_enabled: bool = False
    # E40-T04: webhook alert delivery (`alerts.webhook_enabled`). Must stay off until E40-S03
    # ships the egress allow-list; the dispatcher refuses to build with it on.
    alerts_webhook_enabled: bool = False
    # E07-T05: retention scheduler flag (off by default) and cron expressions.
    retention_enabled: bool = False
    retention_cron: str = "0 3 * * *"
    export_cron: str = "15 2 * * *"
    compact_cron: str = "0 3 * * 0"
    # E16-T10: public trade-archive import (20-architecture.md §7.2). Concurrency and bandwidth
    # bound every download so an import never starves live ingestion (C-12.7); the archive base
    # is host-pinned by the adapter's allow-list; decompressed size is capped per file.
    import_max_concurrency: int = Field(default=2, ge=1, le=16)
    import_max_mbps: float = Field(default=50.0, gt=0.0, le=10_000.0)
    import_max_uncompressed_mb: int = Field(default=2048, ge=1)
    # `CV_BYBIT_ARCHIVE_BASE`: None = the adapter's pinned default origin.
    bybit_archive_base: str | None = None
    # E07-X02 (SR-094): weekly cold-tier checksum scrub (off by default, C-4.13).
    scrub_enabled: bool = False
    scrub_interval_s: int = 7 * 24 * 3600
    # E24-T02-F1: supervised settled-funding backfill/refresh (C-4.13: on by default; it only
    # runs when a hot-tier funding store and a REST fetcher exist; on the real backend no store
    # exists yet, so it is a no-op until #1939). Never gates a safety invariant.
    # funding_refresh_interval_s: seconds between refresh passes (also the failure-backoff cap).
    # funding_backfill_days: depth of the first (startup) backfill; later passes cover 2 days.
    funding_enabled: bool = True
    funding_refresh_interval_s: int = Field(default=3600, ge=60)
    funding_backfill_days: int = Field(default=30, ge=1, le=400)
    order_rate_per_uid: int = 8
    native_sl_deadline_ms: int = 3000
    killswitch_on_disconnect_s: int = 30

    git_sha: str = "unknown"
    version: str = "0.1.0"

    @property
    def mesh_cidrs(self) -> tuple[str, ...]:
        """`CV_MESH_CIDRS_CSV` split on commas, trimmed, empties dropped."""
        return tuple(part.strip() for part in self.mesh_cidrs_csv.split(",") if part.strip())

    @property
    def allowed_origin_set(self) -> frozenset[str]:
        """`CV_ALLOWED_ORIGINS` split on commas, trimmed, trailing `/` dropped."""
        return frozenset(
            o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()
        )

    @model_validator(mode="after")
    def _refuse_file_kek_on_live(self) -> Settings:
        """E27-T02 / e27-kek.md §4: fatal before any module starts (`kek_source_not_permitted`)."""
        if self.environment is Environment.LIVE and self.kek_source == "file":
            raise ValueError("kek_source_not_permitted: CV_KEK_SOURCE=file is refused in live")
        return self

    @model_validator(mode="after")
    def _refuse_dev_questdb_password_on_live(self) -> Settings:
        """#2037 S1: live on the real backend must not use the QuestDB dev default password."""
        if (
            self.environment is Environment.LIVE
            and self.storage_backend == "real"
            and self.questdb_pg_password.get_secret_value() == _QUESTDB_DEV_PASSWORD
        ):
            raise ValueError(
                "CV_QUESTDB_PG_PASSWORD must be set to a non-default value "
                "(environment=live, storage_backend=real)"
            )
        return self

    @model_validator(mode="after")
    def _anchor_recorder_wal_dir(self) -> Settings:
        """E16-T03 (SR-097 pattern): `CV_RECORDER_WAL_DIR` must be absolute, have no `..`
        segment, not be a symlink, and resolve inside the data dir (the parent of
        `parquet_root`). It is created with `mkdir(parents=True)`, so a traversal here would
        create directories anywhere."""
        root = Path(self.parquet_root).expanduser().resolve().parent
        text = self.recorder_wal_dir.strip()
        raw = Path(text).expanduser() if text else root / "recorder-wal"
        if not raw.is_absolute():
            raise RecorderWalDirError("CV_RECORDER_WAL_DIR must be an absolute path")
        if ".." in raw.parts:
            raise RecorderWalDirError("CV_RECORDER_WAL_DIR must not contain '..'")
        if raw.is_symlink():
            raise RecorderWalDirError("CV_RECORDER_WAL_DIR must not be a symlink")
        resolved = raw.resolve()
        if resolved == root or not resolved.is_relative_to(root):
            raise RecorderWalDirError(f"CV_RECORDER_WAL_DIR must be inside the data dir {root}")
        object.__setattr__(self, "recorder_wal_dir", str(resolved))
        return self

    @model_validator(mode="after")
    def _anchor_bars_state_root(self) -> Settings:
        raw = self.bars_state_root.strip()
        if not raw:
            root = Path(self.parquet_root).expanduser().parent / "bars" / "state"
        else:
            root = Path(raw).expanduser()
            if not root.is_absolute():
                raise ValueError("CV_BARS_STATE_ROOT must be an absolute path")
        if root.is_symlink():
            raise ValueError("CV_BARS_STATE_ROOT must not be a symlink")
        object.__setattr__(self, "bars_state_root", str(root.resolve()))
        return self

    @field_validator("bind_host")
    @classmethod
    def _bind_host_not_wildcard(cls, value: str) -> str:
        """`CV_BIND_HOST` must never be `0.0.0.0` (C-12.9, no public exposure)."""
        if value == "0.0.0.0":  # noqa: S104  # nosec B104
            raise ValueError(
                "CV_BIND_HOST must not be 0.0.0.0 (see docs/plan/20-architecture.md Sec.7.2)"
            )
        return value

    @field_validator("feed_rate_hz")
    @classmethod
    def _feed_rate_positive(cls, value: float) -> float:
        """`CV_FEED_RATE_HZ` must be positive (acceptance criterion 2)."""
        if value <= 0:
            raise ValueError("CV_FEED_RATE_HZ must be > 0")
        return value

    @field_validator("allowed_origins")
    @classmethod
    def _allowed_origins_are_serialised(cls, value: str) -> str:
        """#2239 (SR-042): REST and the WS upgrade compare browser `Origin` headers exactly,
        so each entry (after `allowed_origin_set`'s trim and trailing-`/` drop) must be a
        serialised origin. A bad entry fails startup instead of silently never matching;
        blank segments between commas are ignored."""
        for part in value.split(","):
            entry = part.strip()
            if entry and not is_serialised_origin(entry.rstrip("/")):
                raise ValueError(
                    f"CV_ALLOWED_ORIGINS entry {entry!r} is not a serialised origin "
                    "(scheme://host[:port]: lowercase, ASCII host, no path, no default port)"
                )
        return value

    def model_post_init(self, __context: object) -> None:
        """Fail fast on `CV_FEED=live` without credentials (acceptance criterion 3).

        A half-configured live feed must never start — this raises before any
        module is constructed, with a message that names the missing env vars
        and never echoes any credential material (C-12.6/C-12.9).
        """
        if self.feed is FeedMode.LIVE and (
            self.bybit_api_key is None or self.bybit_api_secret is None
        ):
            raise ValueError(
                "CV_FEED=live requires CV_BYBIT_API_KEY and CV_BYBIT_API_SECRET to be "
                "set; refusing to start half-configured (see "
                "docs/plan/20-architecture.md Sec.7.3). Use CV_FEED=synthetic for local "
                "development without exchange credentials."
            )

    def __repr_args__(self) -> list[tuple[str | None, object]]:
        """Redact any field whose name looks like a secret before it is ever printed.

        Applies to `repr()`, `str()` and pydantic's own `__repr__` machinery,
        so `Settings` can never leak a DSN/key/token/password/secret into a
        log line, exception message or debugger dump (C-12.6/C-12.9).
        """
        redacted: list[tuple[str | None, object]] = []
        for name, value in super().__repr_args__():
            if name is not None and _REDACT_NAME_RE.search(name):
                redacted.append((name, "**redacted**"))
            else:
                redacted.append((name, value))
        return redacted


def get_settings() -> Settings:
    """Return a fresh `Settings` instance built from the current environment.

    Not cached (`functools.lru_cache`) on purpose: tests construct many
    independent instances with different env vars (`monkeypatch.setenv`) and
    must not see a stale cached instance from an earlier test.
    """
    return Settings()
