"""The catalogue drift check of Semgrep's `cv-admin-no-flag-lookup` (E42-X03, SR-E42-07, AD-F09).

The rule refuses each catalogue key, as an exact string, in the safety modules. Its key list is
exactly `catalogue.FLAGS`, so a flag added there fails here until the rule names it. ADR-0037's
`audit.lane_journal_first` is in it like every other key: the flag reaches `audit/` only as an
injected callable, which the rule's metadata records as decision D3's residual (until #3009).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from candleviewer.admin.flags.catalogue import AUDIT_LANE_JOURNAL_FIRST, FLAGS

_RULE = Path(__file__).resolve().parents[5] / ".semgrep" / "cv-admin-no-flag-lookup.yml"
#: The rule's key pattern: `"=~/^(a\.b|c\.d)$/"`, each key escaped and spelled out whole.
_LITERAL = re.compile(r'"=~/\^\((?P<keys>[^()]+)\)\$/"')
_ESCAPED_KEY = re.compile(r"[a-z0-9_]+(\\\.[a-z0-9_]+)+")


def _rule() -> dict[str, Any]:
    (rule,) = yaml.safe_load(_RULE.read_text(encoding="utf-8"))["rules"]
    assert rule["id"] == _RULE.stem
    return dict(rule)


def _rule_keys(rule: dict[str, Any]) -> list[str]:
    literals = [
        alternative["pattern"]
        for alternative in rule["pattern-either"]
        if str(alternative.get("pattern", "")).startswith('"=~/')
    ]
    assert len(literals) == 1, literals
    found = _LITERAL.fullmatch(literals[0])
    assert found is not None, literals[0]
    escaped = found["keys"].split("|")
    assert all(_ESCAPED_KEY.fullmatch(key) for key in escaped), escaped  # no other regex syntax
    return [key.replace("\\.", ".") for key in escaped]


def test_the_rule_names_every_catalogue_key() -> None:
    rule = _rule()
    keys = _rule_keys(rule)
    assert len(keys) == len(set(keys))
    assert set(keys) == {spec.key for spec in FLAGS}
    assert AUDIT_LANE_JOURNAL_FIRST in keys
    assert "exempt-flag-keys" not in rule["metadata"]  # no key is let through


def test_the_d3_residual_is_recorded_in_the_rule() -> None:
    residual = _rule()["metadata"]["residual"]
    assert AUDIT_LANE_JOURNAL_FIRST in residual and "use_lane_flag" in residual


def test_the_key_pattern_matches_a_key_whole_and_nothing_longer() -> None:
    keys = _rule_keys(_rule())
    pattern = re.compile("^(" + "|".join(re.escape(key) for key in keys) + ")$")
    for spec in FLAGS:
        assert pattern.fullmatch(spec.key)
    assert not pattern.search("maintenance.mode is read by the composition root")
    assert not pattern.search("maintenance.enabled")  # an audit action, not a key
