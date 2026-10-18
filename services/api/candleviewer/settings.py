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
accident. A setting that holds no secret keeps its name clear of the pattern
and, where its documented variable carries one of those words, reads that
variable through an alias (`rotation_policy_days` for
`CV_KEY_ROTATION_POLICY_DAYS`), so `repr()` shows it.
"""

from __future__ import annotations

import ipaddress
import math
import os
import re
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_QUESTDB_DEV_PASSWORD = "quest"  # noqa: S105 - the QuestDB OSS default, refused on live
_REDACT_NAME_RE = re.compile(r"(key|secret|token|password|dsn)", re.IGNORECASE)
#: QuestDB PGWire default port, for a `questdb_pg` `host[:port]` that omits the port.
QUESTDB_PG_DEFAULT_PORT = 8812
#: US-ACCT-010's caps on `account_heartbeat_s` and `account_down_s`, which are also their defaults.
#: Written once, here: M1 may not import `accounts`, and `accounts/health.py` imports them, so the
#: bounds below and `HealthThresholds` share one value.
ACCOUNT_HEARTBEAT_MAX_S: Final = 10.0
ACCOUNT_DOWN_MAX_S: Final = 30.0
#: US-ACCT-008's windows for `wallet_stale_s` (the `balance_stale` flag) and `wallet_reconcile_s`
#: (the REST truth-check after this long without a refresh): their defaults, and their caps too.
#: Written once, here, for the same reason as the account windows: `accounts/wallet.py` imports
#: them, so the bounds below and `WalletThresholds` share one value.
WALLET_STALE_S: Final = 10.0
WALLET_RECONCILE_S: Final = 60.0

# #2565: timings of the planned shutdown that are code constants, not settings. They live in M1
# because `Settings` checks them against the configured terms (`_refuse_unfittable_stop_budget` sums
# them; the declared ranges of the drain and the budget are derived from them) and M1 may not import
# `ws` (its import contract) or `app` (a cycle). The code that spends them imports them from here,
# so the check and the shutdown share one value.
#: The grace `Supervisor.stop_all` gives each module's `stop()`.
TEARDOWN_BUDGET_S: Final = 15.0
#: What `Supervisor._stop_each` adds to that grace before it cuts a module's stop off. One hung
#: module therefore costs `TEARDOWN_STOP_CAP_S`, not the grace alone.
STOP_SLACK_S: Final = 1.0
TEARDOWN_STOP_CAP_S: Final = TEARDOWN_BUDGET_S + STOP_SLACK_S
#: How long a closing WS connection, and `WsRuntime.stop`, wait for `bye` and the close frame to
#: flush.
CLOSE_FLUSH_TIMEOUT_S: Final = 2.0
#: Upper bound on writing a closing WS connection's `ws.connection.closed` row; the teardown never
#: waits longer on the audit sink.
CLOSE_AUDIT_TIMEOUT_S: Final = 2.0
#: The two fixed 0.1 s ticks of the exit path: uvicorn's main loop sees the exit request within
#: 0.1 s, and `Server.shutdown` sleeps 0.1 s before its drain. `PlannedShutdownServer`'s poll and
#: uvicorn's drain poll add nothing to the worst case: `asyncio.wait` returns on completion and
#: `wait_for` cuts at its timeout.
SHUTDOWN_TICKS_S: Final = 0.2
#: The shortest uvicorn drain `Settings` accepts: what one close can need after `WsRuntime.stop()`
#: stopped waiting. A writer stalled on a peer that stopped reading frees its handler only when
#: uvicorn's `connection.shutdown()` runs, after `stop()`'s flush wait. The handler then spends its
#: own flush wait and then the audit write. At the floor only the 0.1 s settle sleep before the
#: drain is the margin (the 5 s default leaves 1.1 s).
MIN_DRAIN_TIMEOUT_S: Final = math.ceil(CLOSE_FLUSH_TIMEOUT_S + CLOSE_AUDIT_TIMEOUT_S)
#: The smallest stop budget `Settings` accepts: no grace, the shortest drain, one module cut at its
#: hard bound, and the ticks.
MIN_STOP_BUDGET_S: Final = math.ceil(
    CLOSE_FLUSH_TIMEOUT_S + MIN_DRAIN_TIMEOUT_S + TEARDOWN_STOP_CAP_S + SHUTDOWN_TICKS_S
)


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
#: An HTTP field name (RFC 9110 `token`), lowercase.
_FIELD_NAME_RE = re.compile(r"[!#$%&'*+.^_`|~0-9a-z-]+")


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


def _keyless_testnet_refusal(
    switch: str,
    environment: Environment | None,
    bybit_api_key: SecretStr | None,
    bybit_api_secret: SecretStr | None,
) -> str | None:
    """The one rule for every test or perf switch (#2086 `CV_TEST_CLOCK`, #2097
    `CV_AUTH_PERF_ENABLED`): why *switch* may not be on, or None on testnet with no exchange
    key (`CV_BYBIT_API_KEY` and `CV_BYBIT_API_SECRET` both unset). The message names the
    switch and the rule only, never a value."""
    if environment is not Environment.TESTNET:
        return f"{switch} is refused unless CV_ENVIRONMENT=testnet"
    if bybit_api_key is not None or bybit_api_secret is not None:
        return f"{switch} is refused while an exchange key (CV_BYBIT_API_*) is configured"
    return None


#: #2893: a fixture scenario name: lowercase letters, digits and `_`, at most 64 characters.
_ACCOUNT_FIXTURE_SCENARIO_RE = re.compile(r"[a-z0-9_]{1,64}")
#: #2893 ruling 2's rider: every variable of this family counts, declared or not.
_EXCHANGE_KEY_VARIABLE_PREFIX = "CV_BYBIT_API_"


def _account_fixture_refusal(
    scenario: str | None,
    environment: Environment | None,
    feed: FeedMode | None,
    test_clock: bool,
    bybit_api_key: SecretStr | None,
    bybit_api_secret: SecretStr | None,
) -> str | None:
    """#2893 rulings 2 and 10: why `CV_ACCOUNT_FIXTURE` may not be on, or None in dev/test: demo,
    the synthetic feed, no test clock (it needs testnet) and no `CV_BYBIT_API_*` variable at all.
    The rider: a set variable refuses, never is ignored, including a name `Settings` does not
    declare and would otherwise drop; only names are read, never a value. The message names the
    switch and the rule only."""
    if test_clock:
        return (
            "CV_ACCOUNT_FIXTURE is refused while CV_TEST_CLOCK is on: the fixture needs "
            "CV_ENVIRONMENT=demo and the test clock needs testnet"
        )
    if environment is not Environment.DEMO:
        return "CV_ACCOUNT_FIXTURE is refused unless CV_ENVIRONMENT=demo"
    if feed is not FeedMode.SYNTHETIC:
        return "CV_ACCOUNT_FIXTURE is refused unless CV_FEED=synthetic"
    if (
        bybit_api_key is not None
        or bybit_api_secret is not None
        or any(name.upper().startswith(_EXCHANGE_KEY_VARIABLE_PREFIX) for name in os.environ)
    ):
        return "CV_ACCOUNT_FIXTURE is refused while any CV_BYBIT_API_* variable is set"
    if scenario is None:
        return "CV_ACCOUNT_FIXTURE is not set (CV_ACCOUNT_FIXTURE_DIR needs it)"
    if _ACCOUNT_FIXTURE_SCENARIO_RE.fullmatch(scenario) is None:
        return "CV_ACCOUNT_FIXTURE must be a scenario token: 1 to 64 of a-z, 0-9 and _"
    return None


def key_file_path_refusal(value: str) -> str | None:
    """ADR-0037 decision 6 (`24-internal-schemas.md` §15.6): why a key file path is refused, as
    a rule, or None. The rules of `CV_TEST_CLOCK_FILE` (#2728): absolute, without `..`, and
    neither the file nor a directory above it a symlink. A path it may not inspect (under a
    directory it may not search) is left to the open, whose `O_NOFOLLOW` also guards the last
    component against a swap after this check."""
    path = Path(value)
    if not path.is_absolute():
        return "must be an absolute path"
    if ".." in path.parts:
        return "must not contain '..'"
    if os.path.islink(path):
        return "must not be a symlink"
    if os.path.realpath(path) != str(path):
        return "must not be under a symlinked directory"
    return None


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
        # #2086: hides the input from a refusal's message (`str()`) only. `errors()` and `json()`
        # still carry it, and a model validator's input is every setting, CV_BYBIT_API_KEY
        # included, so the test-clock gate is a field validator (#2728). The other model
        # validators still echo every setting there; #2778 tracks that.
        hide_input_in_errors=True,
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
    # own immediate peer address is trusted to supply the header. Set both or
    # neither, the address as an IP literal: anything else fails startup (#2275).
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
    # #2097: perf instrumentation for the k6 auth profile (`candleviewer.api.auth_perf`): the
    # owner-only `GET /auth/_perf/argon2-params` route and `Server-Timing` on the login challenge.
    # Refused at startup unless testnet with no exchange key (the #2086 gate).
    auth_perf_enabled: bool = False
    # #2090 (SR-041): dedicated CSRF-token HMAC key (hex, 32 bytes), separate from
    # the TOTP / recovery keys and the refresh tokens. Rotatable: move the old
    # value to `auth_csrf_previous_key_hex` (verify-only) for one refresh lifetime.
    auth_csrf_key_hex: SecretStr | None = None
    auth_csrf_previous_key_hex: SecretStr | None = None
    # #2086: server test clock for the seeded e2e stack (`candleviewer.auth.testnet_clock`).
    # Auth time = UTC + the offset in `CV_TEST_CLOCK_FILE`. Both are set together, and only on
    # testnet with no exchange key; anything else refuses startup (E16-FR-11). #2728: the file
    # path is absolute, without `..`, and no component of it is a symlink.
    test_clock: bool = False
    # Explicit validate_default: the gate must also run on the default (CV_TEST_CLOCK alone).
    test_clock_file: str | None = Field(default=None, validate_default=True)
    # #2893: the dev/test account fixture transport for the E27 fault-injection pack, a scenario
    # token. Its code is the dev-only `cvdev` package, outside the wheel and the image, reached
    # only through `candleviewer.account_fixture_wiring`. Allowed only on demo with the synthetic
    # feed, no test clock and no exchange key variable; anything else refuses startup (rulings 2
    # and 10). The optional state dir follows the test clock's path rules. Declared after every
    # setting the gate reads, so its field validator sees them in `info.data`.
    account_fixture: str | None = None
    # Explicit validate_default: the gate must also run on the default (CV_ACCOUNT_FIXTURE alone).
    account_fixture_dir: str | None = Field(default=None, validate_default=True)

    # E03-T10: bounds `pg_advisory_lock` acquisition in the boot-time
    # migration runner (`candleviewer.migrations.boot`). A deadlocked
    # migration in another process turns into a clear `CI-DEP-004` error at
    # this timeout instead of hanging startup indefinitely (ADR-0013 rule 9).
    migration_lock_timeout_s: float = Field(default=300.0, gt=0.0)

    # #2111 (E09-X04 R-5): the start-up and nightly audit chain verify job, `cv-audit-verify`
    # (24-internal-schemas.md section 15.4): the UTC hour of the daily run, and the deadline of
    # one run, at most 6 h (past it the run stops: recorded as stopped, never a success).
    audit_verify_nightly_hour_utc: int = Field(default=4, ge=0, le=23)
    audit_verify_nightly_deadline_s: float = Field(
        default=1800.0, gt=0.0, le=21600.0, allow_inf_nan=False
    )

    # E09-T02: `audit.emit` durably buffers to an on-disk WAL before writing
    # to `audit_log` (F8 — survives a Postgres outage), and the daily
    # checkpoint job appends the head hash to a file outside the database
    # volume so tail truncation is detectable even if Postgres data is lost.
    audit_wal_path: str = "var/audit/audit.wal"
    audit_checkpoint_path: str = "var/audit/checkpoints.ndjson"
    # ADR-0037 decision 6 (#3009): the audit lane's key files, read once at boot by the composition
    # root (`candleviewer.audit_lane_wiring`). The key makes every lane frame, marker and note; the
    # previous key, set during a rotation, only verifies. Paths, not secrets: their names stay
    # clear of the redaction pattern and `repr()` shows them; the aliases keep the documented
    # variables, and are also the keywords `Settings(...)` takes. An explicit value is checked at
    # load like `CV_TEST_CLOCK_FILE`; the default only by the loader (`BaseSettings` validates
    # defaults unless told not to), so no boot changes here.
    audit_lane_mac_file: str = Field(
        default="/run/secrets/cv_audit_lane_key",
        alias="CV_AUDIT_LANE_KEY_FILE",
        validate_default=False,
    )
    audit_lane_previous_mac_file: str | None = Field(
        default=None, alias="CV_AUDIT_LANE_PREVIOUS_KEY_FILE"
    )

    # E42-T02 (contract #2392): per-user limits for `GET /admin/audit`.
    audit_query_rate_per_minute: int = Field(default=60, ge=1)
    audit_query_max_concurrent: int = Field(default=2, ge=1)
    # Capped at the relational pool's own 30 s statement timeout.
    audit_query_timeout_ms: int = Field(default=4000, ge=1, le=30_000)
    # Audit page reads in flight in the process; past it a read is 503 at once. At most the
    # audit pool's 10 base connections, so the audit writer always has connections left.
    # One slot is kept for the Owner, so at least 2: one for the Owner, one for others.
    audit_query_global_max_concurrent: int = Field(default=4, ge=2, le=10)
    # Per-user audit record budget (same contract). The owner has a separate, larger cap.
    audit_record_budget_per_hour: int = Field(default=120, ge=1)
    audit_record_budget_owner_per_hour: int = Field(default=600, ge=1)
    audit_read_flush_pages: int = Field(default=50, ge=1)
    audit_read_flush_seconds: float = Field(default=300.0, gt=0.0)
    audit_budget_tracked_users: int = Field(default=1024, ge=64)
    audit_inflight_writes: int = Field(default=64, ge=1)
    # E42-T02 verify (contract #2392/#2446): the most ids one `POST /admin/audit/verify` spans.
    audit_verify_max_span: int = Field(default=1_000_000, ge=1)
    # Runs per user in a rolling hour (only runs that start count), and each run's time bounds:
    # per statement (capped like the query budget) and overall (past it: 503, slot freed).
    audit_verify_rate_per_hour: int = Field(default=30, ge=1)
    audit_verify_statement_timeout_ms: int = Field(default=10_000, ge=1, le=30_000)
    audit_verify_deadline_s: float = Field(default=60.0, gt=0.0, le=600.0)
    # The most rendered UTF-8 bytes one entry may have for verify to fetch it (4 MiB; at most
    # the 8 MiB batch budget). A larger entry stops the run (503, `entry_too_large@<id>`).
    audit_verify_max_entry_bytes: int = Field(default=4_194_304, ge=65_536, le=8_388_608)
    # Structure one Owner audit page serves, as the `{`, `[` and `,` of its states'
    # renderings; past it the remaining states are withheld (`detail.elided`). The page is
    # serialized on the event loop (C-2.17): the costliest page measured, 4-byte UTF-8
    # strings and then 17-digit floats up to the budget, renders in 29-35 ms at the
    # default and 33-37 ms at the maximum (#2467). The floor, two states at the 16 Ki-character
    # field cap, leaves budget room for one row's states.
    audit_page_structure_budget: int = Field(default=50_000, ge=32_768, le=65_536)

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

    # The exchange's receive window for signed calls; the REST client takes (0, 10000] only, so
    # anything else fails startup instead of leaving every stored key's self-check inconclusive.
    recv_window_ms: int = Field(default=5000, gt=0, le=10_000)
    # E27-T03 (#836): the deployment's egress IP, the one address a stored key's whitelist may
    # hold (SR-E27-04); configuration only, never a request header. Unset while keys are stored,
    # the key self-check latches order entry off.
    egress_ip: str | None = None
    # E27-T03: stored-key self-check cadence. C-12.2 asks for start-up and hourly, so no value
    # may lengthen it (C-4.14); the floor keeps a typo from flooding the audit log and the venue.
    # It is no secret, so its name stays clear of the redaction pattern and `repr()` shows it; the
    # alias keeps the documented variable, and is also the keyword `Settings(...)` takes.
    selfcheck_interval_s: float = Field(
        default=3600.0, ge=60.0, le=3600.0, alias="CV_KEY_SELFCHECK_INTERVAL_S"
    )
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
    # E16-T07 disk budget (ADR-0015 d6, 24-internal-schemas §13.4.1). 600 GB is the E16-K01
    # recommendation for <= 2 symbols at depth 200 (provisional until its live re-measure).
    disk_cap_gb: int = Field(default=600, gt=0)
    disk_warn_pct: int = Field(default=80, gt=0, le=100)
    disk_autostop_pct: int = Field(default=90, gt=0, le=100)
    disk_halt_pct: int = Field(default=95, gt=0, le=100)
    disk_sample_interval_s: float = Field(default=60.0, gt=0)
    # SR-096 escape hatch (recording volume shared with the backend): testnet only (E16-FR-11).
    allow_shared_volume: bool = False
    # E26-T01 replay sessions (24-internal-schemas §13.7): idle reclaim DESTROYs a session after
    # `CV_REPLAY_IDLE_TTL_S` with no control call (ticket: 2 h), checked every
    # `CV_REPLAY_RECLAIM_INTERVAL_S`; per-user open-session quota and window cap use the
    # ticket's keys `CV_REPLAY_MAX_SESSIONS_PER_USER` (2) and `CV_REPLAY_MAX_WINDOW_HOURS` (24).
    replay_idle_ttl_s: float = Field(default=7200.0, ge=60.0, le=86400.0)
    replay_reclaim_interval_s: float = Field(default=60.0, ge=1.0, le=3600.0)
    replay_max_sessions_per_user: int = Field(default=2, ge=1, le=16)
    replay_max_window_hours: int = Field(default=24, ge=1, le=24 * 31)
    # E08-T04: public WS ingestion skeleton flag (C-4.13: off by default;
    # removal tracked by E08-T05). Public data only — no credentials.
    ingestion_ws_enabled: bool = False
    # E17 client WS gateway (`23-ws-protocol.md` §4, §9.4): `CV_WS_*`. Defaults = the doc.
    ws_auth_timeout_s: float = Field(default=10.0, gt=0, le=60)
    ws_max_inbound_frame_bytes: int = Field(default=262_144, ge=1024, le=1_048_576)
    # E17-T03 (#412): the WS backpressure pipeline (coalescing, adaptive throttling and the §8.4
    # outbound budget) behind `CV_WS_BACKPRESSURE_ENABLED` (C-4.13: off by default; removal ticket
    # #2900). It swaps the mechanism that bounds a connection's outbound frames and never removes
    # the bound (C-2.18): off keeps today's 1 024-frame push bound, so it gates no safety invariant
    # (C-4.14). With it on, `create_app` passes a `BackpressureConfig` and every frame goes through
    # `ws/pipeline.py`; `welcome.features.coalescing` mirrors it (`23-ws-protocol.md` §4.2).
    # Rollout precondition: keep it off until the slow-consumer and burst chaos scenarios pass and
    # the open items of `23-ws-protocol.md` §8.6 close (§8.4 Rollout; `tests/chaos/ws/SCENARIOS.md`,
    # #410).
    ws_backpressure_enabled: bool = False
    # The per-connection outbound budget (§8.4) and the classification cadence (§8.3). The contract
    # values (`ws.outbound.QUEUE_BYTES` / `QUEUE_FRAMES`) are the ceilings, so either may be lowered
    # and never raised (a raise needs a security review: E17 threat model §6). M1 may not import
    # `ws`, so the numbers are spelled out here and a test pins them. With the flag on, `create_app`
    # reads them into a `BackpressureConfig`. The floors are typo guards, not sizing:
    # a byte budget under one maximum outbound frame (4 MiB, as in `welcome.limits`) or a frame
    # budget under the 200 allowed subscriptions (256 leaves room for control replies) would close
    # a connection at its first large frame or round of snapshots. At a floor one maximum frame
    # fits (a test pins it) and nothing more is promised.
    ws_queue_bytes: int = Field(default=8_388_608, ge=4_194_304, le=8_388_608)
    ws_queue_frames: int = Field(default=2_000, ge=256, le=2_000)
    ws_classify_interval_ms: int = Field(default=1_000, ge=500, le=10_000)
    ws_max_connections_per_user: int = Field(default=8, ge=1, le=64)
    # #2558: new sockets one user may authenticate per sliding 60 s (§4.3). The excess is refused
    # `bye client_rate_limited` + 4429 before `auth_ok`. Default = `ws.lifecycle` constant of the
    # same name, upper-cased.
    ws_max_auths_per_user_per_min: int = Field(default=20, ge=1, le=600)
    ws_shutdown_grace_ms: int = Field(default=5000, ge=0, le=60_000)
    ws_shutdown_expected_downtime_ms: int = Field(default=20_000, ge=0, le=600_000)
    # #2565: the api container's SIGTERM -> SIGKILL budget (`CV_API_STOP_BUDGET_S`; the compose
    # files set `stop_grace_period` to the same value) and the bound on uvicorn's drain of open
    # connections (`timeout_graceful_shutdown`). With the WS grace they are the terms
    # `_refuse_unfittable_stop_budget` sums; it is a field validator on the drain, so the drain is
    # declared last. The declared minimums are the smallest values that can ever validate
    # (`MIN_STOP_BUDGET_S`, `MIN_DRAIN_TIMEOUT_S`).
    api_stop_budget_s: int = Field(default=30, ge=MIN_STOP_BUDGET_S, le=120)
    uvicorn_drain_timeout_s: int = Field(default=5, ge=MIN_DRAIN_TIMEOUT_S, le=30)
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
    # E27-T04: account health windows, configurable as the ticket's Technical notes name them
    # (`CV_ACCOUNT_DOWN_S`, `CV_ACCOUNT_HEARTBEAT_S`). A heartbeat is the private WS's successful
    # auth reply, then any pong or topic message on that socket; the client pings every
    # account_heartbeat_s / 2 (5 s), not at the exchange's suggested 20 s.
    # The caps are US-ACCT-010's NFRs, not tuning room: a heartbeat older than 10 s must not show
    # healthy, and order entry must close within 30 s of the last WS or REST success. No value
    # switches either check off (C-4.14).
    account_heartbeat_s: float = Field(
        default=ACCOUNT_HEARTBEAT_MAX_S, gt=0.0, le=ACCOUNT_HEARTBEAT_MAX_S
    )
    account_down_s: float = Field(default=ACCOUNT_DOWN_MAX_S, gt=0.0, le=ACCOUNT_DOWN_MAX_S)
    # E27-T04 (US-ACCT-008): a wallet snapshot is `balance_stale` once older than
    # `CV_WALLET_STALE_S`, and a REST read truth-checks it after `CV_WALLET_RECONCILE_S` without a
    # refresh (while the private WS is down, every `CV_ACCOUNT_HEARTBEAT_S` instead). Two
    # thresholds, not one: the display flag and the reconciliation cadence. The caps are the
    # contract's, not tuning room: config may tighten a window, never loosen it, so that no value
    # (an infinite window, or milliseconds mistaken for seconds) switches the stale flag or the
    # truth-check off (C-4.14). The stale flag comes before the truth-check.
    wallet_stale_s: float = Field(
        default=WALLET_STALE_S, gt=0.0, le=WALLET_STALE_S, allow_inf_nan=False
    )
    wallet_reconcile_s: float = Field(
        default=WALLET_RECONCILE_S, gt=0.0, le=WALLET_RECONCILE_S, allow_inf_nan=False
    )
    # E27-T04: key-age policy (US-ACCT-005), deployment config for v1 (decision Q4 on #837).
    # Bounded so that no value switches the reminder off (C-4.14): overdue within a year, and a
    # warning window of at least a day that ends before the due date (Settings and the policy
    # check that). Age never disables a key. The day counts are no secret, so their names stay
    # clear of the redaction pattern and `repr()` shows them; the aliases keep the documented
    # variables, and are also the keywords `Settings(...)` takes.
    rotation_policy_days: int = Field(default=90, ge=2, le=365, alias="CV_KEY_ROTATION_POLICY_DAYS")
    rotation_warn_days: int = Field(default=14, ge=1, le=364, alias="CV_KEY_ROTATION_WARN_DAYS")

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

    @property
    def data_dir(self) -> Path:
        """The data dir: the parent of `parquet_root`, with `~` expanded and the path resolved, so
        it is absolute and holds no `..`. The recorder WAL anchors in it (SR-097 pattern) and so
        does the lost-jobs count (E42-T05), whatever form `CV_PARQUET_ROOT` is given in."""
        return Path(self.parquet_root).expanduser().resolve().parent

    @model_validator(mode="after")
    def _refuse_shared_volume_outside_testnet(self) -> Settings:
        """E16-FR-11 (#1741, SR-096): live and demo never boot with the shared-volume hatch."""
        if self.allow_shared_volume and self.environment is not Environment.TESTNET:
            raise ValueError(
                "CV_ALLOW_SHARED_VOLUME is refused when CV_ENVIRONMENT is live or demo"
            )
        return self

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
        root = self.data_dir
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

    @field_validator("audit_lane_mac_file", "audit_lane_previous_mac_file")
    @classmethod
    def _check_audit_lane_key_files(cls, value: str | None, info: ValidationInfo) -> str | None:
        """ADR-0037 decision 6: an explicit key file path obeys `key_file_path_refusal`; a blank
        one counts as unset (a compose passthrough), as an empty `CV_TEST_CLOCK_FILE` does. A
        field validator, so a refusal carries only this field's input (#2728, C-12.6)."""
        field = cls.model_fields[str(info.field_name)]
        if value is None or not value.strip():
            return field.default if isinstance(field.default, str) else None
        refusal = key_file_path_refusal(value)
        if refusal is not None:
            raise ValueError(f"{field.alias} {refusal}")
        return value

    def test_clock_refusal(self) -> str | None:
        """#2086: why the server test clock may not run here, or None on a keyless testnet."""
        return _keyless_testnet_refusal(
            "CV_TEST_CLOCK", self.environment, self.bybit_api_key, self.bybit_api_secret
        )

    @field_validator("test_clock_file")
    @classmethod
    def _refuse_test_clock_outside_keyless_testnet(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        """#2086 Q1 (E16-FR-11, E49 T-E1): the test clock moves auth time, so live, demo or a
        configured exchange key refuses startup before any module starts. #2728: the file path
        is absolute, without `..`, and neither it nor a directory above it is a symlink.

        A field validator, not a model one (#2728): a refusal's `errors()` and `json()` carry
        only this field's input, never another setting such as `CV_BYBIT_API_KEY` (C-12.6). It
        also runs on the default, so `CV_TEST_CLOCK` alone is refused; `info.data` holds the
        fields declared above."""
        enabled = info.data.get("test_clock", False)
        if not enabled and not value:
            return value
        refusal = _keyless_testnet_refusal(
            "CV_TEST_CLOCK",
            info.data.get("environment"),
            info.data.get("bybit_api_key"),
            info.data.get("bybit_api_secret"),
        )
        if refusal is not None:
            raise ValueError(refusal)
        if not (enabled and value):
            raise ValueError("CV_TEST_CLOCK and CV_TEST_CLOCK_FILE must be set together")
        path = Path(value)
        if not path.is_absolute():
            raise ValueError("CV_TEST_CLOCK_FILE must be an absolute path")
        if ".." in path.parts:
            raise ValueError("CV_TEST_CLOCK_FILE must not contain '..'")
        if path.is_symlink():
            raise ValueError("CV_TEST_CLOCK_FILE must not be a symlink")
        if os.path.realpath(path) != str(path):
            raise ValueError("CV_TEST_CLOCK_FILE must not be under a symlinked directory")
        return value

    def auth_perf_refusal(self) -> str | None:
        """#2097: why `CV_AUTH_PERF_ENABLED` may not be on here, or None on a keyless testnet.
        The app checks this again at build time (`api.auth_perf.auth_perf_enabled`)."""
        return _keyless_testnet_refusal(
            "CV_AUTH_PERF_ENABLED", self.environment, self.bybit_api_key, self.bybit_api_secret
        )

    @field_validator("auth_perf_enabled")
    @classmethod
    def _refuse_auth_perf_outside_keyless_testnet(cls, value: bool, info: ValidationInfo) -> bool:
        """#2097 Q1, the #2086 gate: perf instrumentation never runs in live or demo, or next
        to an exchange key; startup fails before any module starts. A field validator, not a
        model one: `hide_input_in_errors` hides input only from the message, and a model
        validator's `ValidationError.errors()` would still carry the whole input, the raw
        `CV_BYBIT_API_KEY` included (C-12.6). `info.data` holds the fields declared above."""
        if not value:
            return value
        refusal = _keyless_testnet_refusal(
            "CV_AUTH_PERF_ENABLED",
            info.data.get("environment"),
            info.data.get("bybit_api_key"),
            info.data.get("bybit_api_secret"),
        )
        if refusal is not None:
            raise ValueError(refusal)
        return value

    def account_fixture_refusal(self) -> str | None:
        """#2893: why the account fixture transport may not run here, or None in dev/test. The
        dev package re-checks it, as `build_test_clock` does; the dir's path rules run at load."""
        return _account_fixture_refusal(
            self.account_fixture,
            self.environment,
            self.feed,
            self.test_clock,
            self.bybit_api_key,
            self.bybit_api_secret,
        )

    @field_validator("account_fixture_dir")
    @classmethod
    def _refuse_account_fixture_outside_dev_test(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        """#2893 rulings 2 and 10: the fixture transport answers exchange calls for fabricated
        keys, so outside dev/test it refuses startup before any module starts, and a dir without
        the switch is refused rather than ignored. The dir is absolute, without `..`, and neither
        it nor a directory above it is a symlink (the test clock's rules, #2728).

        A field validator, not a model one (#2728): a refusal's `errors()` and `json()` carry only
        the dir's input, never another setting such as `CV_BYBIT_API_KEY` (C-12.6). It also runs
        on the default, so `CV_ACCOUNT_FIXTURE` alone is gated; `info.data` holds the fields
        declared above. An empty dir alone counts as unset, as an empty `CV_TEST_CLOCK_FILE`
        does, so a blank passthrough never stops a boot; an empty switch is still refused."""
        scenario = info.data.get("account_fixture")
        if scenario is None and not value:
            return None
        refusal = _account_fixture_refusal(
            scenario,
            info.data.get("environment"),
            info.data.get("feed"),
            info.data.get("test_clock", False),
            info.data.get("bybit_api_key"),
            info.data.get("bybit_api_secret"),
        )
        if refusal is not None:
            raise ValueError(refusal)
        if value is None:
            return value
        path = Path(value)
        if not path.is_absolute():
            raise ValueError("CV_ACCOUNT_FIXTURE_DIR must be an absolute path")
        if ".." in path.parts:
            raise ValueError("CV_ACCOUNT_FIXTURE_DIR must not contain '..'")
        if path.is_symlink():
            raise ValueError("CV_ACCOUNT_FIXTURE_DIR must not be a symlink")
        if Path(os.path.realpath(path)) != path:  # Path equality ignores a trailing `/`
            raise ValueError("CV_ACCOUNT_FIXTURE_DIR must not be under a symlinked directory")
        return value

    @field_validator("uvicorn_drain_timeout_s", mode="before")
    @classmethod
    def _explain_a_drain_below_the_floor(cls, value: Any) -> Any:
        """#2565: the floor is the declared range (`ge=MIN_DRAIN_TIMEOUT_S`); this runs first so
        a refusal says why. When the drain ends uvicorn cancels what is still running and sends
        the lifespan `shutdown` without awaiting the cancelled handlers, so a drain shorter than
        one close can need would cancel a handler that is still writing its
        `ws.connection.closed` row. Names and numbers only in the message."""
        try:
            seconds = int(value)  # an environment value arrives as a str
        except (TypeError, ValueError, OverflowError):  # OverflowError: `int(float("inf"))`
            return value  # not a number: the field's own check refuses it
        if seconds < MIN_DRAIN_TIMEOUT_S:
            raise ValueError(
                f"CV_UVICORN_DRAIN_TIMEOUT_S={seconds} is shorter than the {MIN_DRAIN_TIMEOUT_S} s "
                f"one WS close can need: CLOSE_FLUSH_TIMEOUT_S ({CLOSE_FLUSH_TIMEOUT_S:g} s) + "
                f"CLOSE_AUDIT_TIMEOUT_S ({CLOSE_AUDIT_TIMEOUT_S:g} s). uvicorn would cancel a "
                "handler that is still writing its ws.connection.closed row"
            )
        return value

    @field_validator("uvicorn_drain_timeout_s")
    @classmethod
    def _refuse_unfittable_stop_budget(cls, drain_s: int, info: ValidationInfo) -> int:
        """#2565: refuse a config whose planned shutdown cannot finish inside the container's stop
        budget. `candleviewer.server.PlannedShutdownServer` runs the WS grace, the close flush,
        uvicorn's drain and then the lifespan teardown one after another; a sum above
        `api_stop_budget_s` means the runtime SIGKILLs the teardown, so storage flushes and
        secrets zeroing never run. Only names and numbers go into the message, never a value that
        could be a secret.

        A field validator on the last of the three terms, not a model one (#2728 did the same
        for the test clock): a refusal's `errors()` and `json()` carry only this field's input,
        never every setting, `CV_BYBIT_API_KEY` included (C-12.6). `info.data` holds the other two
        terms; one whose own check failed is absent, and its error is the one to report.

        The sum is the worst case of ONE hung module: `Supervisor._stop_each` cuts a stop off at
        its grace plus `STOP_SLACK_S` (`TEARDOWN_STOP_CAP_S`), and the two fixed ticks of the exit
        path add `SHUTDOWN_TICKS_S`. Several modules that each hang to their own bound would still
        outrun any budget, and the lifespan's own stops before `Supervisor.stop_all` are outside
        it: most are short, but `BarsRuntime.stop` (up to 30 s with bars on) and the metrics
        listener's unbounded drain can use the whole budget alone (#2878); the account health
        runtime's stop is bounded, at 25 s in three steps: `STOP_TIMEOUT_S` (11 s) for the loops
        and for the drain, `RELEASE_TIMEOUT_S` (3 s) for its pool. A sum exactly at the
        budget passes and leaves the other modules' normal stop time nothing, so the largest
        grace is a limit, not a recommendation. Integer milliseconds, so a boundary is not a
        float error.

        That cut is cooperative (#3361): `asyncio.timeout` cancels the stop once. A stop that
        swallows that cancellation and keeps waiting, or that blocks the event loop, holds
        `_stop_each`, and every stop after it, `secrets.stop()` zeroing the KEK included, until
        the runtime's SIGKILL at the budget; no in-process bound can cut it. That is accepted,
        not bounded: every module stop is our own code, which, with what it awaits, must honour
        cancellation and never block the loop (`.claude/rules/20-python-backend.md`, AGENTS.md
        §5.2), and an unzeroed KEK then lives no longer than the process, which the runtime
        kills at the budget."""
        grace_ms = info.data.get("ws_shutdown_grace_ms")
        budget_s = info.data.get("api_stop_budget_s")
        if grace_ms is None or budget_s is None:
            return drain_s  # that term's own check failed: its error is the one to report
        fixed_s = CLOSE_FLUSH_TIMEOUT_S + TEARDOWN_STOP_CAP_S + SHUTDOWN_TICKS_S
        needed_ms = grace_ms + drain_s * 1000 + round(fixed_s * 1000)
        if needed_ms > budget_s * 1000:
            raise ValueError(
                f"the planned shutdown needs {needed_ms / 1000:g} s but "
                f"CV_API_STOP_BUDGET_S={budget_s}: "
                f"CV_WS_SHUTDOWN_GRACE_MS={grace_ms} ({grace_ms / 1000:g} s) "
                f"+ WS close flush CLOSE_FLUSH_TIMEOUT_S ({CLOSE_FLUSH_TIMEOUT_S:g} s) "
                f"+ CV_UVICORN_DRAIN_TIMEOUT_S={drain_s} "
                f"+ one module's hard stop bound TEARDOWN_BUDGET_S + STOP_SLACK_S "
                f"({TEARDOWN_STOP_CAP_S:g} s) + SHUTDOWN_TICKS_S ({SHUTDOWN_TICKS_S:g} s). "
                "Lower the grace or the drain timeout, or raise CV_API_STOP_BUDGET_S together "
                "with the api service's stop_grace_period (infra/compose)"
            )
        return drain_s

    @field_validator("account_down_s")
    @classmethod
    def _refuse_unordered_account_windows(cls, down_s: float, info: ValidationInfo) -> float:
        """E27-T04: the heartbeat window must end inside the down window, as `HealthThresholds`
        requires. A bad pair refuses startup here rather than failing wherever the wiring first
        builds one.

        A field validator on the second window, not a model one (#2728, #2565): a refusal's
        `errors()` and `json()` carry only this field's input, never every setting,
        `CV_BYBIT_API_KEY` included (C-12.6). `info.data` holds the heartbeat window, declared
        first; one whose own check failed is absent, and its error is the one to report."""
        heartbeat_s = info.data.get("account_heartbeat_s")
        if heartbeat_s is not None and not heartbeat_s < down_s:
            raise ValueError("CV_ACCOUNT_HEARTBEAT_S must be less than CV_ACCOUNT_DOWN_S")
        return down_s

    @field_validator("wallet_reconcile_s")
    @classmethod
    def _refuse_unordered_wallet_windows(cls, reconcile_s: float, info: ValidationInfo) -> float:
        """E27-T04: the stale flag comes before the REST truth-check, as `WalletThresholds`
        requires. A field validator on the second window, as for the account windows, so a
        refusal never carries another setting (#2728, C-12.6); a stale window whose own check
        failed is absent from `info.data` and its error is the one to report."""
        stale_s = info.data.get("wallet_stale_s")
        if stale_s is not None and not stale_s < reconcile_s:
            raise ValueError("CV_WALLET_STALE_S must be less than CV_WALLET_RECONCILE_S")
        return reconcile_s

    @field_validator("rotation_warn_days")
    @classmethod
    def _refuse_unordered_key_rotation_windows(cls, warn_days: int, info: ValidationInfo) -> int:
        """E27-T04: the key-rotation warning must end inside the policy, as `KeyRotationPolicy`
        requires. A bad pair refuses startup here rather than failing wherever the wiring first
        builds one.

        A field validator on the second window, not a model one (#2728, #2565): a refusal's
        `errors()` and `json()` carry only this field's input, never every setting,
        `CV_BYBIT_API_KEY` included (C-12.6). `info.data` holds the policy days, declared first and
        keyed by field name, not by alias; a value whose own check failed is absent, and its error
        is the one to report."""
        policy_days = info.data.get("rotation_policy_days")
        if policy_days is not None and not warn_days < policy_days:
            raise ValueError(
                "CV_KEY_ROTATION_WARN_DAYS must be less than CV_KEY_ROTATION_POLICY_DAYS"
            )
        return warn_days

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

    @field_validator("mesh_trusted_proxy_header")
    @classmethod
    def _trusted_proxy_header_is_a_field_name(cls, value: str | None) -> str | None:
        """#2275: an HTTP field name, lowercased as ASGI delivers it; blank means unset. A
        misspelt name (`X-Forwarded-For:`) would silently never be read: it fails startup."""
        name = (value or "").strip().lower()
        if not name:
            return None
        if _FIELD_NAME_RE.fullmatch(name) is None:
            raise ValueError(f"CV_MESH_TRUSTED_PROXY_HEADER {value!r} is not an HTTP header name")
        return name

    @field_validator("egress_ip")
    @classmethod
    def _egress_ip_is_one_address(cls, value: str | None) -> str | None:
        """E27-T03: one IP literal, normalised; blank means unset. A typo fails startup instead
        of failing every stored key's whitelist check."""
        text = (value or "").strip()
        if not text:
            return None
        try:
            return str(ipaddress.ip_address(text))
        except ValueError:
            raise ValueError(f"CV_EGRESS_IP {value!r} is not an IP address") from None

    @field_validator("mesh_trusted_proxy_address")
    @classmethod
    def _trusted_proxy_address_is_an_ip(cls, value: str | None) -> str | None:
        """#2275: the proxy's TCP peer address as an IP literal, normalised (an IPv4-mapped
        IPv6 address becomes IPv4, as `CidrAllowList` matches it); blank means unset. A
        hostname, `host:port` or CIDR never equals the peer, so the header would silently
        never be read and every client recorded as the proxy: it fails startup instead."""
        text = (value or "").strip()
        if not text:
            return None
        try:
            address = ipaddress.ip_address(text)
        except ValueError:
            raise ValueError(
                f"CV_MESH_TRUSTED_PROXY_ADDRESS {value!r} is not an IP address "
                "(the proxy's address as the API sees it, e.g. 127.0.0.1)"
            ) from None
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        return str(address)

    @model_validator(mode="after")
    def _trusted_proxy_set_together(self) -> Settings:
        """#2275: with only one of the pair set the header is never read, so every request
        through the proxy would be recorded as the proxy: it fails startup instead."""
        if (self.mesh_trusted_proxy_header is None) != (self.mesh_trusted_proxy_address is None):
            raise ValueError(
                "CV_MESH_TRUSTED_PROXY_HEADER and CV_MESH_TRUSTED_PROXY_ADDRESS "
                "must be set together"
            )
        return self

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
