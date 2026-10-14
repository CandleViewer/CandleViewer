"""The limiter/budget defaults must match the merged contract text (#2392)."""

from __future__ import annotations

from pathlib import Path

from candleviewer.settings import Settings

_SPEC = Path(__file__).resolve().parents[4] / "docs" / "plan" / "22-api-openapi.yaml"


def test_settings_defaults_are_named_in_the_contract() -> None:
    text = _SPEC.read_text(encoding="utf-8")
    missing = [
        name
        for name in (
            "audit_query_rate_per_minute",
            "audit_query_max_concurrent",
            "audit_query_timeout_ms",
        )
        if name not in text
    ]
    assert not missing, (
        f"contract PR #2392 is not in this base: {missing} absent from 22-api-openapi.yaml; "
        "merge #2392 first (contract-first)"
    )
    s = Settings()
    assert (s.audit_query_rate_per_minute, s.audit_query_max_concurrent) == (60, 2)
    assert s.audit_query_timeout_ms == 4000
