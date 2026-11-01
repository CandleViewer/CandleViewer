"""`hotkey_profile_refusals_total{code,rule}` (E10-T05, #5211): catalogued, bounded by the closed
label sets the `/settings/hotkeys*` router counts by, and never per user or profile. The router's
counting: tests/hotkey_profiles/test_hotkey_profiles_api.py; the app's wiring, through the real
app: tests/contract/hotkey_profiles/test_hotkey_profiles_contract.py."""

from __future__ import annotations

from candleviewer.api.hotkey_profiles import CONFLICT_RULES, INVALID_RULES, REFUSAL_SERIES
from candleviewer.observability.metrics_catalogue import CATALOGUE


def test_the_refusal_counter_is_catalogued_and_bounded_by_its_closed_label_sets() -> None:
    spec = next(s for s in CATALOGUE if s.name == "hotkey_profile_refusals_total")
    assert (spec.kind, spec.labels, spec.status, spec.owner_epic) == (
        "counter", ("code", "rule"), "planned", "E10")  # fmt: skip
    assert spec.max_series == REFUSAL_SERIES == len(CONFLICT_RULES) + len(INVALID_RULES)


def test_the_two_rule_sets_are_disjoint_and_name_every_rule_22_gives_a_write() -> None:
    """A rule names its code: the `409` rules and the `422` rules never overlap, so the pair
    (code, rule) takes no more series than the rules alone."""
    assert not set(CONFLICT_RULES) & set(INVALID_RULES)
    assert set(CONFLICT_RULES) == {"binding_conflict", "limit_reached", "name_taken",
                                   "profile_active"}  # fmt: skip
    assert {"unknown_action", "duplicate_action", "scope_mismatch", "params_not_allowed",
            "invalid_keys", "shape_mismatch", "bare_letter_dangerous", "reserved_key",
            "locked_command", "invalid_character", "schema"} == set(INVALID_RULES)  # fmt: skip
