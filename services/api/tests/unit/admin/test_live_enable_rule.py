"""The drift check of Semgrep's `cv-admin-no-live-enable` rules (E42-Q06, C5).

The file holds three rules: a server write and a client write that may turn the live gate on,
and an admin read of a posture verdict. The write rules name the live key by the catalogue's
literal and constant, so a renamed key or constant fails here until the rules follow, and each
treats another name for the key as a finding. The server rule leaves out the flag service's named
modules alone, the client rules nothing, and no rule exempts a key. The web app binds the literal
key only as `LIVE_GATE_FLAG`, the one name the client rule knows.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from candleviewer.admin.flags import registry
from candleviewer.admin.flags.catalogue import FLAGS, LIVE_ENABLED

_ROOT = Path(__file__).resolve().parents[5]
_WEB = _ROOT / "apps" / "web" / "src"
_RULE = _ROOT / ".semgrep" / "cv-admin-no-live-enable.yml"
_IDS = (
    "cv-admin-no-live-enable-py",
    "cv-admin-no-live-enable-ts",
    "cv-admin-no-posture-verdict-ts",
)


def _rules() -> dict[str, dict[str, Any]]:
    return {rule["id"]: rule for rule in yaml.safe_load(_RULE.read_text("utf-8"))["rules"]}


def _strings(node: object) -> list[str]:
    """Every string in a rule: its message, patterns and regexes, at any depth."""
    if isinstance(node, dict):
        return [text for value in node.values() for text in _strings(value)]
    if isinstance(node, list):
        return [text for value in node for text in _strings(value)]
    return [node] if isinstance(node, str) else []


def test_the_file_holds_three_error_rules_none_exempting_anything() -> None:
    rules = _rules()
    assert tuple(rules) == _IDS
    languages = [(rule["languages"], rule["severity"]) for rule in rules.values()]
    assert languages == [(["python"], "ERROR")] + [(["typescript"], "ERROR")] * 2
    for rule_id, rule in rules.items():
        assert rule["metadata"]["rule-id"] == rule_id
        assert [key for key in rule["metadata"] if "exempt" in key] == []


def test_the_write_rules_name_the_catalogue_key_and_its_constant() -> None:
    py, ts = (_strings(_rules()[rule_id]) for rule_id in _IDS[:2])
    assert registry.LIVE_ENABLED == LIVE_ENABLED == "trading.live_enabled"
    assert f'$N = "{LIVE_ENABLED}"' in py and f'"{LIVE_ENABLED}"' in ts
    assert f'"=~/{re.escape(LIVE_ENABLED)}/"' in ts  # a URL naming the key
    assert {"$N = LIVE_ENABLED", "from $MODULE import LIVE_ENABLED as $ALIAS"} <= set(py)
    assert "const $ALIAS = <... LIVE_GATE_FLAG ...>" in ts
    others = {spec.key for spec in FLAGS} - {LIVE_ENABLED}
    assert [text for text in py + ts for key in others if key in text] == []


def test_the_server_rule_leaves_out_the_flag_services_named_modules_alone() -> None:
    rules = _rules()
    package = "services/api/candleviewer"
    modules = ("catalogue", "registry", "service", "store", "writes")
    assert rules[_IDS[0]]["paths"] == {
        "include": [f"{package}/**"],
        "exclude": [f"{package}/admin/flags/{module}.py" for module in modules],
    }
    assert all((_ROOT / package / "admin" / "flags" / f"{m}.py").is_file() for m in modules)
    assert rules[_IDS[1]]["paths"] == {"include": ["apps/web/src/**"]}
    assert rules[_IDS[2]]["paths"] == {"include": ["apps/web/src/features/admin/**"]}


def test_the_web_app_binds_the_literal_key_only_as_live_gate_flag() -> None:
    """The client rule knows the key by its literal and by `LIVE_GATE_FLAG`; a constant under any
    other name would be out of its sight, so the literal appears nowhere else in the app."""
    lines = [
        line.strip()
        for path in sorted(_WEB.rglob("*.ts*"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if LIVE_ENABLED in line
    ]
    assert set(lines) <= {f'export const LIVE_GATE_FLAG = "{LIVE_ENABLED}";'}
