"""Public-surface convention test (E02-T05 acceptance criterion 4).

Given a module's `__init__.py`, when it re-exports an internal
implementation symbol not listed in its public interface manifest, then the
public-surface test fails, citing the Sec.3 convention
(`docs/plan/20-architecture.md`: "`__init__.py` exporting only the public
interface").

Concretely: every name in `__init__.py`'s `__all__` must be something the
module's own `service.py`/`models.py`/`errors.py` deliberately exposes (a
`*Service`, `*Error`, or an explicitly allow-listed helper) — never a bare
internal name that was only meant for use within the package.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

_SERVICES_API_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_PATH = _SERVICES_API_ROOT / "tests" / "module_manifest.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))

# Modules with a richer public surface than "Service/Error" (allow-listed
# here, not guessed): each entry names exactly what may appear in __all__.
_ALLOWED_EXTRA_EXPORTS: dict[str, set[str]] = {
    "M10": {
        "ColdTierRepository",
        "ExportRun",
        "MarketDataRepository",
        "RelationalRepository",
        "RetentionDecision",
        "RetentionRepository",
        "StorageDiskCritical",
        "StorageExportVerifyFailed",
        "StorageHealthReport",
        "StorageRetentionBlockedByPin",
        "StorageSchemaDrift",
        "StorageTier",
        "StorageTierUnavailable",
        "StreamKind",
        "SymbolStream",
        "TierHealth",
        "TierHint",
        "TierState",
        "TimeRange",
        "UnitOfWork",
    },
    "M23a": {
        "make_health_report_router",
        "make_health_router",
        "make_auth_router",
        "make_audit_router",
        "make_market_router",
        "make_instruments_router",
        "make_orderbook_router",
        "make_ticker_router",
        "make_trades_router",
        "make_rules_router",
        # E04-T02: runtime log-level override router.
        "make_log_level_router",
        # E04-S02: support-bundle router.
        "make_support_bundle_router",
        # E24-T02: funding-rate router.
        "make_funding_router",
    },
    # E09-T02: the audit writer/query surface M21/M23 consume (C-3.3).
    "M19": {
        "AuditAccessDenied",
        "AuditEntry",
        "AuditOutcome",
        "AuditPage",
        "AuditPrincipal",
        "AuditQueryService",
        "AuditWriter",
        "ExportResult",
        "Severity",
        "VerifyResult",
    },
    "M24": {
        "HealthReport",
        "HealthStatus",
        # E04-T01: the logging entry point + its supporting public surface
        # (`docs/plan/20-architecture.md` Sec.12.2).
        "BodyLoggingGate",
        "RedactionFilter",
        "Secret",
        "configure_logging",
        # E04-T02: correlation context.
        "bind_context",
        "spawn",
    },
    # E08-T03: the bus's public pub/sub surface — `Bus`/`Subscription` are
    # not `*Service`/`*Error` by name but are the module's documented public
    # interface (docs/plan/20-architecture.md Sec.3 bus contract).
    "M5": {
        "Bus",
        "Subscription",
        "Topic",
        "TopicPattern",
        "QueuePolicy",
        "StreamInvalidated",
    },
    # E02-T12: the normalised domain-event shapes (C-2.3) the synthetic feed
    # generator and, later, the real Bybit adapter (E08) both publish.
    # E08-T01 adds the full ExchangeAdapter interface, capability record,
    # in-memory fake, and error taxonomy.
    "M3": {
        "Trade",
        "Ticker",
        "TradeSide",
        "MarketDataPort",
        "TradingPort",
        "ExchangeCapabilities",
        "FakeExchange",
        "OmsErrorCode",
        "translate_exchange_error",
    },
    # E09-T04: `Validator`/`ReadOnlyCheck` are the always-on read-only
    # degradation boundary (docs/plan/20-architecture.md Sec.3.x Validator) —
    # not `*Service`/`*Error` by name, but the module's documented public
    # interface alongside `OmsService`.
    "M14": {"Validator", "ReadOnlyCheck", "OrderPlacementRefused"},
    # E27-T01 (#2495): the accounts facade and the domain types it returns, consumed by the
    # E27-S01 routes. No store, row type or SQL adapter is exported (SR-051 scoping stays in
    # M10), and no model carries an envelope column (C-3.2).
    "M13": {
        "AccountsRepository",
        "AccountKind",
        "ApiKeyMetadata",
        "ApiKeyRotation",
        "ExchangeAccount",
        "ExchangeEnv",
        "KeyStatus",
        "PermissionSet",
        "PermissionSnapshot",
    },
    # E27-T02: metadata-only results and capability Protocols `admin` consumes (C-3.2), the
    # caller-bound borrow capability minted at wiring time for M4, and the `Secret` wrapper.
    # #2339: the capability signs inside M2 (C-2.7); M4 gets the `KEY_ID_SLOT` marker, the
    # `Purpose` values and the `RequestSignature` result (hex MAC + key id, never the secret).
    # No key/DEK type and no broker is exported.
    "M2": {
        "Secret",
        "KekCheckResult",
        "RewrapReport",
        "StoredCredential",
        "KekUnavailable",
        "CredentialUnavailable",
        "KekSourceNotPermitted",
        "WithdrawPermissionRejected",
        "SecretsMetadata",
        "SecretsLifecycle",
        "CredentialBorrower",
        "mint_borrower",
        # E09-S11 (#2119): the offline break-glass KEK proof (metadata only, admin only).
        "prove_kek_possession",
        "KEY_ID_SLOT",
        "Purpose",
        "RequestSignature",
        "export_secrets_metrics",
        "AuditSink",
        "CredentialStore",
        "KcvStore",
        "SecretsLifecycleFacade",
        "SecretsMetadataFacade",
    },
    # E26-T02: the replay read path's request, in-stream gap marker, storage ports and typed
    # errors (docs/plan/24-internal-schemas.md Sec.13.7).
    "M12": {
        "ReplayGap",
        "ReplayItem",
        "ReplayMemoryCeilingExceeded",
        "ReplayRequest",
        "ReplayRequestInvalid",
        "ReplaySourceUnavailable",
        "ReplayTierStraddle",
        "ReplayTiers",
        "SourceTier",
    },
}


def _dotted(package_dir: str) -> str:
    return package_dir.replace("/", ".")


@pytest.mark.parametrize(
    "entry",
    [e for e in _MANIFEST["modules"] if e["id"] != "M1"],
    ids=lambda e: e["id"],
)
def test_init_exports_only_public_surface(entry: dict[str, str]) -> None:
    module = importlib.import_module(_dotted(entry["path"]))
    exported = set(getattr(module, "__all__", []))
    allowed_suffixes = ("Service", "Error")
    allowed_extra = _ALLOWED_EXTRA_EXPORTS.get(entry["id"], set())
    for name in exported:
        assert name in allowed_extra or name.endswith(allowed_suffixes), (
            f"{entry['path']}.__init__ exports {name!r}, which is not a "
            f"*Service/*Error symbol or an allow-listed public helper — "
            f"see docs/plan/20-architecture.md Sec.3 convention"
        )


def test_public_surface_rule_rejects_a_leaked_internal_symbol() -> None:
    """Proves the rule actually fires, independent of today's clean tree."""
    leaked_exports = {"_internal_helper", "RawConnection"}
    allowed_extra: set[str] = set()
    allowed_suffixes = ("Service", "Error")
    violations = [
        name
        for name in leaked_exports
        if not (name in allowed_extra or name.endswith(allowed_suffixes))
    ]
    assert violations == ["_internal_helper", "RawConnection"] or violations == [
        "RawConnection",
        "_internal_helper",
    ]
