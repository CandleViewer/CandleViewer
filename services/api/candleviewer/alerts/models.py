"""Domain models for the alerts module (M22, E40-T02).

`AlertCondition` is `AlertConditionIr` from `22-api-openapi.yaml`: the condition half of the
E35 rule IR with **no** `actions` block. `extra="forbid"` makes an `actions` key a schema error,
never a silently ignored field (the structural allow-list in `compiler.py` runs first anyway).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from candleviewer.rules.ir import ConditionNode, Operand, RuleLimits, Trigger
from candleviewer.rules.ir.models import storable_text


class AlertCondition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ir_version: Literal[1]
    trigger: Trigger
    conditions: ConditionNode
    variables: dict[str, Operand] = Field(default_factory=dict)
    limits: RuleLimits | None = None

    @model_validator(mode="before")
    @classmethod
    def _storable(cls, data: Any) -> Any:
        return storable_text(data)


@dataclass(frozen=True, slots=True)
class CompiledAlert:
    """Output of `AlertCompiler.compile`: the validated condition and its shared hash."""

    condition: AlertCondition
    condition_ir: dict[str, object]
    condition_hash: str
    metrics: tuple[str, ...]
    #: Detector metrics with `confidence="estimated"`: the UI renders "(estimated)".
    estimated_metrics: tuple[str, ...]
