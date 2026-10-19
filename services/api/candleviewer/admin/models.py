"""Domain models for the admin module (M21)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class KekRewrapResult:
    """`rewrapKek`'s answer (`22-api-openapi.yaml` `KekRewrapResult`, #2266): the counts of one
    KEK re-wrap run, never a key id or a key check value (KCV)."""

    run_id: UUID
    environment: str
    from_version: int
    to_version: int
    resumed: bool
    rewrapped: int
    remaining: int
    failed: int
    complete: bool
