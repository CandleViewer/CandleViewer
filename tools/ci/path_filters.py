"""The `changed-paths` rules of `.github/workflows/pr.yml`, readable as code (#3882).

`dorny/paths-filter` takes them as an inline `filters:` block that cannot import a module, so the
block stays in the workflow and this module is its one reader: the tests that pin the block and the
local gate (tools/ci/pr_gate.py) both load it here. Needs PyYAML.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

PR_YML = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "pr.yml"
FILTER_ACTION = "dorny/paths-filter@"
#: picomatch (`dot: true`) as pr.yml's rules use it: `**/`, `**`, `*` and `?`. A rule with other
#: syntax (`!`, `{a,b}`, `[ab]`) is refused by `load_filters`, never matched wrongly.
_GLOB = {r"\*\*/": "(?:.*/)?", r"\*\*": ".*", r"\*": "[^/]*", r"\?": "[^/]"}
_RULE = re.compile(r"[\w.*?/-]+")


def load_workflow(path: Path = PR_YML) -> dict[str, Any]:
    workflow: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return workflow


def filter_step(workflow: Mapping[str, Any]) -> dict[str, Any]:
    """The one `dorny/paths-filter` step of the `changed-paths` job."""
    steps = workflow["jobs"]["changed-paths"]["steps"]
    found = [s for s in steps if str(s.get("uses", "")).startswith(FILTER_ACTION)]
    if len(found) != 1:
        raise ValueError(
            f"expected one `{FILTER_ACTION}` step in `changed-paths`, found {len(found)}"
        )
    step: dict[str, Any] = found[0]
    return step


def load_filters(workflow: Mapping[str, Any] | None = None) -> dict[str, list[str]]:
    """The rules of the `changed-paths` job by filter name (its `filters:` block is YAML)."""
    step = filter_step(load_workflow() if workflow is None else workflow)
    filters: dict[str, list[str]] = yaml.safe_load(step["with"]["filters"])
    for name, rules in filters.items():
        for rule in rules:
            if not isinstance(rule, str) or not _RULE.fullmatch(rule):
                raise ValueError(f"filter {name!r}: {rule!r} is syntax matches() does not know")
    return filters


def matches(path: str, rule: str) -> bool:
    """Whether `dorny/paths-filter` matches `path` to `rule`."""
    regex = re.sub(r"\\\*\\\*/|\\\*\\\*|\\\*|\\\?", lambda m: _GLOB[m.group(0)], re.escape(rule))
    return re.fullmatch(regex, path) is not None


def select(paths: Iterable[str], filters: Mapping[str, Iterable[str]]) -> dict[str, bool]:
    """The `changed-paths` outputs for a change: filter name -> some path matches a rule of it."""
    changed = list(paths)
    return {
        name: any(matches(path, rule) for rule in rules for path in changed)
        for name, rules in filters.items()
    }
