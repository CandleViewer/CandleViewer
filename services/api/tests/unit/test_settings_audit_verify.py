"""#2111 nightly audit verify settings (`CV_AUDIT_VERIFY_NIGHTLY_*`, 24 section 15.4): the
accepted defaults and the validated bounds."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from candleviewer.settings import Settings


def _settings(**overrides: float) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg, arg-type]  # pydantic-settings kwarg


def test_nightly_verify_settings_default_to_04_utc_and_1800_s() -> None:
    s = _settings()
    assert (s.audit_verify_nightly_hour_utc, s.audit_verify_nightly_deadline_s) == (4, 1800.0)


def test_nightly_verify_deadline_accepts_its_6_h_maximum() -> None:
    """24 section 15.4: greater than 0 and at most 21600 s."""
    assert _settings(audit_verify_nightly_deadline_s=21600).audit_verify_nightly_deadline_s == 21600


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("audit_verify_nightly_hour_utc", -1), ("audit_verify_nightly_hour_utc", 24),
        ("audit_verify_nightly_deadline_s", 0), ("audit_verify_nightly_deadline_s", -5.0),
        ("audit_verify_nightly_deadline_s", 21600.001),
        ("audit_verify_nightly_deadline_s", math.inf),
        ("audit_verify_nightly_deadline_s", math.nan),
    ],
)  # fmt: skip
def test_nightly_verify_settings_outside_their_bounds_are_refused(name: str, value: float) -> None:
    with pytest.raises(ValidationError) as refused:
        _settings(**{name: value})
    assert refused.value.errors()[0]["type"] != "extra_forbidden"  # a bound, not a missing field
