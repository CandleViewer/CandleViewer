"""Project the MetricRegistry + IR enums into the `RuleVocabulary` response (E35-T03)."""

from __future__ import annotations

import hashlib
import json
import typing
from collections.abc import Collection
from typing import Any

import structlog

from candleviewer.rules.ir import models as ir_models
from candleviewer.rules.vocabulary.catalogue import (
    ACTIONS,
    ARM_LIVE_PERMISSION,
    OPERATORS,
    TARGET_SEMANTICS,
    TRIGGERS,
)
from candleviewer.rules.vocabulary.metrics import DEFAULT_DOCS, kernel_params_schema
from candleviewer.rules.vocabulary.registry import RECORDED_INPUTS, MetricRegistry


def log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


VOCABULARY_VERSION = 1
RECORDER_ACTION = {"method": "POST", "path": "/api/v1/recording/symbols"}
_TYPE_BY_UNIT = {
    "price": "price",
    "qty": "quantity",
    "ms": "duration",
    "bool": "boolean",
    "enum": "enum",
}
_SIM_TEXT = "Requires orders:write on at least one account; available in simulate mode only."


class VocabularyUnavailableError(RuntimeError):
    """The engine has no metrics registered (SCR-081 'engine offline')."""


def undescribed_metrics(registry: MetricRegistry) -> list[str]:
    return [n for n in registry.names() if n not in DEFAULT_DOCS]


def _signal(d: Any, symbol: str | None, recorded: Collection[str] | None) -> dict[str, Any]:
    desc, rng = DEFAULT_DOCS.get(d.name, ("", ""))
    needs = sorted(set(d.inputs) & RECORDED_INPUTS)
    schema = kernel_params_schema(d.name)  # a kernel-bound metric: its indicator's schema
    if schema is None:
        schema = {"type": "object", "properties": {k: {"default": v} for k, v in d.params.items()}}
    entry: dict[str, Any] = {
        "id": d.name,
        "display_name": d.title,
        "description": desc,
        "type": _TYPE_BY_UNIT.get(d.unit, "number"),
        "unit": d.unit,
        "valid_range": rng or None,
        "enum_values": list(d.enum_values),
        "params_schema": schema,
        "warmup_bars": d.warmup_bars,
        "deterministic": d.deterministic,
        "confidence": d.confidence,
        "estimated": d.confidence != "exact",
        "dependencies": sorted(d.inputs),
        "requires_recording": bool(needs),
        "when_unavailable": d.nullable_when,
        "available": True,
    }
    if needs and symbol is not None and symbol not in (recorded or ()):
        entry["available"] = False
        entry["unavailable_reason"] = f"{symbol} is not on the recorded-symbol list"
        entry["missing_dependency"] = {"kind": "recording", "symbol": symbol, "inputs": needs}
        entry["recorder_action"] = {**RECORDER_ACTION, "body": {"symbol": symbol}}
    return entry


def _action(a: Any, perms: Collection[str]) -> dict[str, Any]:
    missing = [p for p in a.permissions if p not in perms and "*" not in perms]
    simulate_only = a.places_orders and "orders:write" in missing
    out: dict[str, Any] = {
        "id": a.type,
        "display_name": a.title,
        "params_schema": a.params_schema,
        "required_permissions": list(a.permissions),
        "requires_step_up": False,
        "loosens_risk": a.loosens_risk,
        "idempotent": a.idempotent,
        "guarded": a.guarded,
        "targets": dict(TARGET_SEMANTICS),
        "available": not missing,
        "simulate_only": bool(simulate_only),
        "notes": a.note,
    }
    if missing:
        out["restriction"] = _SIM_TEXT if simulate_only else f"Requires {', '.join(missing)}."
    return out


def build_vocabulary(
    registry: MetricRegistry,
    *,
    permissions: Collection[str] = (),
    symbol: str | None = None,
    recorded_symbols: Collection[str] | None = None,
) -> dict[str, Any]:
    if len(registry) == 0:
        raise VocabularyUnavailableError("metric registry is empty")
    for name in undescribed_metrics(registry):
        log().warning("rule vocabulary: registry metric %s has no descriptor docs", name)
    ops = [
        {"id": op, "arity": ar, "operand_types": list(units), "units": list(units),
         "result_type": "boolean"}
        for op, (ar, units) in OPERATORS.items()
    ]  # fmt: skip
    triggers = [
        {"id": t, "description": d, "required_fields": list(req)}
        for t, (d, req) in TRIGGERS.items()
    ]
    return {
        "ir_version": "1",
        "vocabulary_version": VOCABULARY_VERSION,
        "signals": [_signal(d, symbol, recorded_symbols) for d in registry],
        "operators": ops,
        "actions": [_action(a, permissions) for a in ACTIONS],
        "triggers": triggers,
        "guards": [],
        "arm_live_permission": ARM_LIVE_PERMISSION,
    }


def content_hash(registry: MetricRegistry) -> str:
    payload = build_vocabulary(registry)  # permission-independent base content
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def etag_for(body: dict[str, Any], permissions: Collection[str], symbol: str | None) -> str:
    """Strong ETag over content + the caller's permission set + symbol scope."""
    h = hashlib.sha256(json.dumps(body, sort_keys=True).encode())
    h.update(b"|" + ",".join(sorted(permissions)).encode() + b"|" + (symbol or "").encode())
    return f'"{h.hexdigest()}"'


def ir_enum_values(name: str) -> tuple[str, ...]:
    return typing.get_args(getattr(ir_models, name))
