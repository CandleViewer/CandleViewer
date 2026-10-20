"""The profile cap registry (SR-E28-10): one entry, and one enforcing gate, per stored cap."""

from __future__ import annotations

from candleviewer.accounts.profile_caps import PROFILE_CAPS
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.db import models


def test_every_cap_has_exactly_one_enforcing_gate() -> None:
    """Every `max_*` column of `account_profiles` is a cap: exactly one registry entry each."""
    columns = sorted(c.name for c in models.account_profiles.columns if c.name.startswith("max_"))
    assert sorted(cap.column for cap in PROFILE_CAPS) == columns
    assert all(cap.gate == "E39-S01" for cap in PROFILE_CAPS)


def test_every_cap_names_a_field_of_the_domain_model() -> None:
    fields = {name for name in AccountProfile.model_fields if name.startswith("max_")}
    assert sorted(cap.field for cap in PROFILE_CAPS) == sorted(fields)
